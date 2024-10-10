import hashlib
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

import boto3
from mypy_boto3_ec2.client import EC2Client
from mypy_boto3_ssm import SSMClient

from awspub import exceptions
from awspub.common import _split_partition
from awspub.context import Context
from awspub.image_marketplace import ImageMarketplace
from awspub.s3 import S3
from awspub.snapshot import Snapshot

logger = logging.getLogger(__name__)


@dataclass
class _ImageInfo:
    """
    Information about a image from EC2
    """

    image_id: str
    snapshot_id: Optional[str]


class ImageVerificationErrors(str, Enum):
    """
    Possible errors for image verification
    """

    NOT_EXIST = "image does not exist"
    STATE_NOT_AVAILABLE = "image not available"
    ROOT_DEVICE_TYPE = "root device type mismatch"
    ROOT_DEVICE_VOLUME_TYPE = "root device volume type mismatch"
    ROOT_DEVICE_VOLUME_SIZE = "root device volume size mismatch"
    ROOT_DEVICE_SNAPSHOT_NOT_COMPLETE = "root device snapshot not complete"
    BOOT_MODE = "boot mode mismatch"
    TAGS = "tags mismatch"
    TPM_SUPPORT = "tpm support mismatch"
    IMDS_SUPPORT = "imds support mismatch"
    BILLING_PRODUCTS = "billing products mismatch"


class Image:
    """
    Handle EC2 Image/AMI API interaction
    """

    def __init__(self, context: Context, image_name: str):
        self._ctx: Context = context
        self._image_name: str = image_name
        self._image_regions: List[str] = []
        self._image_regions_cached: bool = False

        if self._image_name not in self._ctx.conf["images"].keys():
            raise ValueError(f"image '{self._image_name}' not found in context configuration")

        self._snapshot: Snapshot = Snapshot(context)
        self._s3: S3 = S3(context)

    def __repr__(self):
        return f"<{self.__class__} :'{self.image_name}' (snapshot name: {self.snapshot_name})"

    @property
    def conf(self) -> Dict[str, Any]:
        """
        The configuration for the current image (based on "image_name") from context
        """
        return self._ctx.conf["images"][self._image_name]

    @property
    def image_name(self) -> str:
        """
        Get the image name
        """
        return self._image_name

    @property
    def snapshot_name(self) -> str:
        """
        Get the snapshot name which is a sha256 hexdigest

        The snapshot name is the sha256 hexdigest of the source file given in the source->path
        configuration option.

        if the "separate_snapshot" config option is set to True, the snapshot name is
        sha256 hexdigest of the source file given in the source->path conf option and then
        the sha256 hexdigest of the image-name appended and then the sha256 hexdigest
        calculated of this concatenated string.

        if the "billing_products" config option is set, the snapshot name is
        sha256 hexdigest of the source file given in the source->path conf option and then
        the sha256 hexdigest of each entry in the billing_products appended and then the sha256 hexdigest
        calculated of this concatenated string.

        Note that both options ("separate_snapshot" and "billing_products") can be combined
        and the snapshot calculation steps would be combined, too.
        """
        s_name = self._ctx.source_sha256
        if self.conf["separate_snapshot"] is True:
            s_name += hashlib.sha256(self.image_name.encode("utf-8")).hexdigest()

        if self.conf["billing_products"]:
            for bp in self.conf["billing_products"]:
                s_name += hashlib.sha256(bp.encode("utf-8")).hexdigest()

        # in the separate_snapshot and billing_products had no effect, don't do another sha256 of
        # the source_sha256 to simplify things
        if s_name == self._ctx.source_sha256:
            return s_name

        # do a sha256 of the concatenated string
        return hashlib.sha256(s_name.encode("utf-8")).hexdigest()

    @property
    def image_regions(self) -> List[str]:
        """
        Get the image regions. Either configured in the image configuration
        or all available regions.
        If a region is listed that is not available in the currently used partition,
        that region will be ignored (eg. having us-east-1 configured but running in the aws-cn
        partition doesn't include us-east-1 here).
        """
        if not self._image_regions_cached:
            # get all available regions
            ec2client: EC2Client = boto3.client("ec2", region_name=self._s3.bucket_region)
            resp = ec2client.describe_regions()
            image_regions_all = [r["RegionName"] for r in resp["Regions"]]

            if self.conf["regions"]:
                # filter out regions that are not available in the current partition
                image_regions_configured_set = set(self.conf["regions"])
                image_regions_all_set = set(image_regions_all)
                self._image_regions = list(image_regions_configured_set.intersection(image_regions_all_set))
                diff = image_regions_configured_set.difference(image_regions_all_set)
                if diff:
                    logger.warning(f"configured regions {diff} not available in the current partition. Ignoring those.")
            else:
                self._image_regions = image_regions_all
            self._image_regions_cached = True
        return self._image_regions

    @property
    def _tags(self):
        """
        Get the tags for this image (common tags + image specific tags)
        image specific tags override common tags
        """
        tags = []
        # the common tags
        tags_dict = self._ctx.tags_dict
        # the image specific tags
        tags_dict.update(self.conf.get("tags", {}))
        for name, value in tags_dict.items():
            tags.append({"Key": name, "Value": value})
        return tags

    def _share_list_filtered(self, share_conf: List[str]) -> List[Dict[str, str]]:
        """
        Get a filtered list of share configurations based on the current partition
        :param share_conf: the share configuration
        :type share_conf: List[str]
        :return: a List of share configurations that is usable by modify_image_attribute()
        :rtype: List[Dict[str, str]]
        """
        # the current partition
        partition_current = boto3.client("ec2").meta.partition

        share_list: List[Dict[str, str]] = []
        for share in share_conf:
            partition, account_id = _split_partition(share)
            if partition == partition_current:
                share_list.append({"UserId": account_id})
        return share_list

    def _share(self, share_conf: List[str], images: Dict[str, _ImageInfo]):
        """
        Share images with accounts

        :param share_conf: the share configuration containing list
        :type share_conf: List[str]
        :param images: a Dict with region names as keys and _ImageInfo objects as values
        :type images: Dict[str, _ImageInfo]
        """
        share_list = self._share_list_filtered(share_conf)

        if not share_list:
            logger.info("no valid accounts found for sharing in this partition, skipping")
            return

        for region, image_info in images.items():
            ec2client: EC2Client = boto3.client("ec2", region_name=region)
            # modify image permissions
            ec2client.modify_image_attribute(
                Attribute="LaunchPermission",
                ImageId=image_info.image_id,
                LaunchPermission={"Add": share_list},  # type: ignore
            )

            # modify snapshot permissions
            if image_info.snapshot_id:
                ec2client.modify_snapshot_attribute(
                    Attribute="createVolumePermission",
                    SnapshotId=image_info.snapshot_id,
                    CreateVolumePermission={"Add": share_list},  # type: ignore
                )

        logger.info(f"shared images & snapshots with '{share_conf}'")

    def _get_root_device_snapshot_id(self, image):
        """
        Get the root device snapshot id for a given image
        :param image: a image structure returned by eg. describe_images()["Images"][0]
        :type image: dict
        :return: Either None or a snapshot-id
        :rtype: Optional[str]
        """
        root_device_name = image.get("RootDeviceName")
        if not root_device_name:
            logger.debug(f"can not get RootDeviceName for image {image}")
            return None
        for bdm in image["BlockDeviceMappings"]:
            if bdm["DeviceName"] == root_device_name:
                ebs = bdm.get("Ebs")
                if not ebs:
                    logger.debug(
                        f"can not get RootDeviceName. root device {root_device_name} doesn't have a Ebs section"
                    )
                    return None
                logger.debug(f"found Ebs for root device {root_device_name}: {bdm['Ebs']}")
                return bdm["Ebs"]["SnapshotId"]

    def _get(self, ec2client: EC2Client) -> Optional[_ImageInfo]:
        """
        Get the a _ImageInfo for the current image which contains the ami id and
        root device snapshot id.
        This relies on the image name to be unique and will raise a MultipleImagesException
        if multiple images are found.

        :param ec2client: EC2Client
        :type ec2client: EC2Client
        :return: Either None or a _ImageInfo
        :rtype: Optional[_ImageInfo]
        """
        resp = ec2client.describe_images(
            Filters=[
                {"Name": "name", "Values": [self.image_name]},
            ],
            Owners=["self"],
        )

        if len(resp.get("Images", [])) == 1:
            root_device_snapshot_id = self._get_root_device_snapshot_id(resp["Images"][0])
            return _ImageInfo(resp["Images"][0]["ImageId"], root_device_snapshot_id)
        elif len(resp.get("Images", [])) == 0:
            return None
        else:
            images = [i["ImageId"] for i in resp.get("Images", [])]
            raise exceptions.MultipleImagesException(
                f"Found {len(images)} images ({', '.join(images)}) with "
                f"name {self.image_name} in region {ec2client.meta.region_name}. There should be only 1."
            )

    def _put_ssm_parameters(self) -> None:
        """
        Push the configured SSM parameters to the parameter store
        """
        logger.info(f"Pushing SSM parameters for image {self.image_name} in {len(self.image_regions)} regions ...")
        for region in self.image_regions:
            ec2client_region: EC2Client = boto3.client("ec2", region_name=region)
            image_info: Optional[_ImageInfo] = self._get(ec2client_region)

            # image in region not found
            if not image_info:
                logger.error(f"image {self.image_name} not available in region {region}. can not push SSM parameter")
                continue

            ssmclient_region: SSMClient = boto3.client("ssm", region_name=region)
            # iterate over all defined parameters
            for parameter in self.conf["ssm_parameter"]:
                # if overwrite is not allowed, check if the parameter is already there and if so, do nothing
                if not parameter["allow_overwrite"]:
                    resp = ssmclient_region.get_parameters(Names=[parameter["name"]])
                    if len(resp["Parameters"]) >= 1:
                        # sanity check if the available parameter matches the value we would (but don't) push
                        if resp["Parameters"][0]["Value"] != image_info.image_id:
                            logger.warning(
                                f"SSM parameter {parameter['name']} exists but value does not match "
                                f"(found {resp['Parameters'][0]['Value']}; expected: {image_info.image_id}"
                            )
                        # parameter exists already and overwrite is not allowed so continue
                        continue
                # push parameter to store
                ssmclient_region.put_parameter(
                    Name=parameter["name"],
                    Description=parameter.get("description", ""),
                    Value=image_info.image_id,
                    Type="String",
                    Overwrite=parameter["allow_overwrite"],
                    DataType="aws:ec2:image",
                    # TODO: tags can't be used together with overwrite
                    # Tags=self._ctx.tags,
                )

                logger.info(
                    f"pushed SSM parameter {parameter['name']} with value {image_info.image_id} in region {region}"
                )

    def _public(self) -> None:
        """
        Make image and underlying root device snapshot public
        """
        logger.info(f"Make image {self.image_name} in {len(self.image_regions)} regions public ...")

        for region in self.image_regions:
            ec2client_region: EC2Client = boto3.client("ec2", region_name=region)
            image_info: Optional[_ImageInfo] = self._get(ec2client_region)
            if image_info:
                ec2client_region.modify_image_attribute(
                    ImageId=image_info.image_id,
                    LaunchPermission={
                        "Add": [
                            {
                                "Group": "all",
                            },
                        ],
                    },
                )
                logger.info(f"image {image_info.image_id} in region {region} public now")

                if image_info.snapshot_id:
                    ec2client_region.modify_snapshot_attribute(
                        SnapshotId=image_info.snapshot_id,
                        Attribute="createVolumePermission",
                        GroupNames=[
                            "all",
                        ],
                        OperationType="add",
                    )
                    logger.info(
                        f"snapshot {image_info.snapshot_id} ({image_info.image_id}) in region {region} public now"
                    )
                else:
                    logger.error(
                        f"snapshot for image {self.image_name} ({image_info.image_id}) not available "
                        f"in region {region}. can not make public"
                    )
            else:
                logger.error(f"image {self.image_name} not available in region {region}. can not make public")

    def cleanup(self) -> None:
        """
        Cleanup/delete the temporary images

        If an image is marked as "temporary" in the configuration, do
        delete that image in all regions.
        Note: if a temporary image is public, it won't be deleted. A temporary
        image should never be public
        Note: the underlying snapshot is currently not deleted. That might change in
        the future
        """
        if not self.conf["temporary"]:
            logger.info(f"image {self.image_name} not marked as temporary. no cleanup")
            return

        # do the cleanup - the image is marked as temporary
        logger.info(f"Cleanup image {self.image_name} ...")
        for region in self.image_regions:
            ec2client_region: EC2Client = boto3.client("ec2", region_name=region)
            image_info: Optional[_ImageInfo] = self._get(ec2client_region)

            if image_info:
                resp = ec2client_region.describe_images(
                    Filters=[
                        {"Name": "image-id", "Values": [image_info.image_id]},
                    ]
                )
                if resp["Images"][0]["Public"] is True:
                    # this shouldn't happen because the image is marked as temporary in the config
                    # so how can it be public?
                    logger.error(
                        f"no cleanup for {self.image_name} in {region} because ({image_info.image_id}) image is public"
                    )
                else:
                    ec2client_region.deregister_image(ImageId=image_info.image_id)
                    logger.info(f"{self.image_name} in {region} ({image_info.image_id}) deleted")

    def list(self) -> Dict[str, _ImageInfo]:
        """
        Get image based on the available configuration
        This doesn't change anything - it just tries to get the available image
        for the different configured regions
        :return: a Dict with region names as keys and _ImageInfo objects as values
        :rtype: Dict[str, _ImageInfo]
        """
        images: Dict[str, _ImageInfo] = dict()
        for region in self.image_regions:
            ec2client_region: EC2Client = boto3.client("ec2", region_name=region)
            image_info: Optional[_ImageInfo] = self._get(ec2client_region)
            if image_info:
                images[region] = image_info
            else:
                logger.warning(f"image {self.image_name} not available in region {region}")
        return images

    def create(self) -> Dict[str, _ImageInfo]:
        """
        Get or create a image based on the available configuration

        :return: a Dict with region names as keys and _ImageInfo objects as values
        :rtype: Dict[str, _ImageInfo]
        """
        # this **must** be the region that is used for S3
        ec2client: EC2Client = boto3.client("ec2", region_name=self._s3.bucket_region)

        # make sure the initial snapshot exists
        self._snapshot.create(ec2client, self.snapshot_name)

        # make sure the snapshot exist in all required regions
        snapshot_ids: Dict[str, str] = self._snapshot.copy(
            self.snapshot_name, self._s3.bucket_region, self.image_regions
        )

        images: Dict[str, _ImageInfo] = dict()
        for region in self.image_regions:
            ec2client_region: EC2Client = boto3.client("ec2", region_name=region)
            image_info: Optional[_ImageInfo] = self._get(ec2client_region)
            if image_info:
                if image_info.snapshot_id != snapshot_ids[region]:
                    logger.warning(
                        f"image with name '{self.image_name}' already exists ({image_info.image_id}) "
                        f"in region {ec2client_region.meta.region_name} but the root device "
                        f"snapshot id is unexpected (got {image_info.snapshot_id} but expected {snapshot_ids[region]})"
                    )
                else:
                    logger.info(
                        f"image with name '{self.image_name}' already exists ({image_info.image_id}) "
                        f"in region {ec2client_region.meta.region_name}"
                    )
                images[region] = image_info
            else:
                logger.info(
                    f"creating image with name '{self.image_name}' in "
                    f"region {ec2client_region.meta.region_name} ..."
                )

                register_image_kwargs = dict(
                    Name=self.image_name,
                    Description=self.conf.get("description", ""),
                    Architecture=self._ctx.conf["source"]["architecture"],
                    RootDeviceName=self.conf["root_device_name"],
                    BlockDeviceMappings=[
                        {
                            "Ebs": {
                                "SnapshotId": snapshot_ids[region],
                                "VolumeType": self.conf["root_device_volume_type"],
                                "VolumeSize": self.conf["root_device_volume_size"],
                            },
                            "DeviceName": self.conf["root_device_name"],
                        },
                        # TODO: make those ephemeral block device mappings configurable
                        {"VirtualName": "ephemeral0", "DeviceName": "/dev/sdb"},
                        {"VirtualName": "ephemeral1", "DeviceName": "/dev/sdc"},
                    ],
                    EnaSupport=True,
                    SriovNetSupport="simple",
                    VirtualizationType="hvm",
                    BootMode=self.conf["boot_mode"],
                )

                if self.conf["tpm_support"]:
                    register_image_kwargs["TpmSupport"] = self.conf["tpm_support"]

                if self.conf["imds_support"]:
                    register_image_kwargs["ImdsSupport"] = self.conf["imds_support"]

                if self.conf["uefi_data"]:
                    with open(self.conf["uefi_data"], "r") as f:
                        uefi_data = f.read()
                    register_image_kwargs["UefiData"] = uefi_data

                if self.conf["billing_products"]:
                    register_image_kwargs["BillingProducts"] = self.conf["billing_products"]

                resp = ec2client_region.register_image(**register_image_kwargs)
                ec2client_region.create_tags(Resources=[resp["ImageId"]], Tags=self._tags)
                images[region] = _ImageInfo(resp["ImageId"], snapshot_ids[region])

        # wait for the images
        logger.info(f"Waiting for {len(images)} images to be ready the regions ...")
        for region, image_info in images.items():
            ec2client_region_wait: EC2Client = boto3.client("ec2", region_name=region)
            logger.info(
                f"Waiting for {image_info.image_id} in {ec2client_region_wait.meta.region_name} "
                "to exist/be available ..."
            )
            waiter_exists = ec2client_region_wait.get_waiter("image_exists")
            waiter_exists.wait(ImageIds=[image_info.image_id])
            waiter_available = ec2client_region_wait.get_waiter("image_available")
            waiter_available.wait(ImageIds=[image_info.image_id])
        logger.info(f"{len(images)} images are ready")

        # share
        if self.conf["share"]:
            self._share(self.conf["share"], images)

        return images

    def publish(self) -> None:
        """
        Handle all publication steps
        - make image and underlying root device snapshot public if the public flag is set
        - request a new marketplace version for the image in us-east-1 if the marketplace config is present
        Note: if the temporary flag is set in the image, this method will do nothing
        Note: this command doesn't unpublish anything!
        """
        # never publish temporary images
        if self.conf["temporary"]:
            logger.warning(f"image {self.image_name} marked as temporary. do not publish")
            return

        # make snapshot and image public if requested in the image
        if self.conf["public"]:
            self._public()
        else:
            logger.info(f"image {self.image_name} not marked as public. do not publish")

        # handle SSM parameter store
        if self.conf["ssm_parameter"]:
            self._put_ssm_parameters()

        # handle marketplace publication
        if self.conf["marketplace"]:
            # the "marketplace" configuration is only valid in the "aws" partition
            partition = boto3.client("ec2").meta.partition
            if partition == "aws":
                logger.info(f"marketplace version request for {self.image_name}")
                # image needs to be in us-east-1
                ec2client: EC2Client = boto3.client("ec2", region_name="us-east-1")
                image_info: Optional[_ImageInfo] = self._get(ec2client)
                if image_info:
                    im = ImageMarketplace(self._ctx, self.image_name)
                    im.request_new_version(image_info.image_id)
                else:
                    logger.error(
                        f"can not request marketplace version for {self.image_name} because no image found in us-east-1"
                    )
            else:
                logger.info(
                    f"found marketplace config for {self.image_name} and partition 'aws' but "
                    f"currently using partition {partition}. Ignoring marketplace config."
                )

    def _verify(self, region: str) -> List[ImageVerificationErrors]:
        """
        Verify (but don't modify or create anything) the image in a single region
        """
        problems: List[ImageVerificationErrors] = []
        ec2client_region: EC2Client = boto3.client("ec2", region_name=region)
        image_info: Optional[_ImageInfo] = self._get(ec2client_region)

        if not image_info:
            problems.append(ImageVerificationErrors.NOT_EXIST)
            return problems

        image_aws = ec2client_region.describe_images(ImageIds=[image_info.image_id])["Images"][0]

        # verify state
        if image_aws["State"] != "available":
            problems.append(ImageVerificationErrors.STATE_NOT_AVAILABLE)

        # verify RootDeviceType
        if image_aws["RootDeviceType"] != "ebs":
            problems.append(ImageVerificationErrors.ROOT_DEVICE_TYPE)

        # verify BootMode
        if image_aws["BootMode"] != self.conf["boot_mode"]:
            problems.append(ImageVerificationErrors.BOOT_MODE)

        # verify RootDeviceVolumeType, RootDeviceVolumeSize and Snapshot
        for bdm in image_aws["BlockDeviceMappings"]:
            if bdm.get("DeviceName") and bdm["DeviceName"] == image_aws["RootDeviceName"]:
                # here's the root device
                if bdm["Ebs"]["VolumeType"] != self.conf["root_device_volume_type"]:
                    problems.append(ImageVerificationErrors.ROOT_DEVICE_VOLUME_TYPE)
                if bdm["Ebs"]["VolumeSize"] != self.conf["root_device_volume_size"]:
                    problems.append(ImageVerificationErrors.ROOT_DEVICE_VOLUME_SIZE)

                # verify snapshot
                snapshot_aws = ec2client_region.describe_snapshots(SnapshotIds=[bdm["Ebs"]["SnapshotId"]])["Snapshots"][
                    0
                ]
                if snapshot_aws["State"] != "completed":
                    problems.append(ImageVerificationErrors.ROOT_DEVICE_SNAPSHOT_NOT_COMPLETE)

        # verify tpm support
        if self.conf["tpm_support"] and image_aws.get("TpmSupport") != self.conf["tpm_support"]:
            problems.append(ImageVerificationErrors.TPM_SUPPORT)

        # verify imds support
        if self.conf["imds_support"] and image_aws.get("ImdsSupport") != self.conf["imds_support"]:
            problems.append(ImageVerificationErrors.IMDS_SUPPORT)

        # billing products
        if self.conf["billing_products"] and image_aws.get("BillingProducts") != self.conf["billing_products"]:
            problems.append(ImageVerificationErrors.BILLING_PRODUCTS)

        # verify tags
        for tag in image_aws["Tags"]:
            if tag["Key"] == "Name" and tag["Value"] != self.snapshot_name:
                problems.append(ImageVerificationErrors.TAGS)

        return problems

    def verify(self) -> Dict[str, List[ImageVerificationErrors]]:
        """
        Verify (but don't modify or create anything) that the image configuration
        matches what is on AWS
        """
        logger.info(f"Verifying image {self.image_name} ...")
        problems: Dict[str, List[ImageVerificationErrors]] = dict()
        for region in self.image_regions:
            problems[region] = self._verify(region)

        return problems
