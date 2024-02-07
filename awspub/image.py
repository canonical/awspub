from mypy_boto3_ec2.client import EC2Client
import hashlib
import boto3
import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from awspub.context import Context
from awspub.snapshot import Snapshot
from awspub.s3 import S3
from awspub import exceptions


logger = logging.getLogger(__name__)


@dataclass
class _ImageInfo:
    """
    Information about a image from EC2
    """

    image_id: str
    snapshot_id: Optional[str]


class Image:
    """
    Handle EC2 Image/AMI API interaction
    """

    def __init__(self, context: Context, image_name: str):
        self._ctx: Context = context
        self._image_name: str = image_name
        self._image_regions: List[str] = []

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
        or all available regions
        """
        if not self._image_regions:
            if self.conf["regions"]:
                self._image_regions = self.conf["regions"]
            else:
                ec2client: EC2Client = boto3.client("ec2", region_name=self._s3.bucket_region)
                resp = ec2client.describe_regions()
                self._image_regions = [r["RegionName"] for r in resp["Regions"]]
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

    def _share(self, images: Dict[str, str], snapshots: Dict[str, str]):
        """
        Share images with accounts

        :param images: a dict of images with key=region and value=image-id
        :type images: Dict[str, str]
        :param snapshots: a dict of snapshots with key=region and value=snapshot-id
        :type snapshots: Dict[str, str]
        """
        if not self.conf["share"]:
            return

        share_list = [{"UserId": user_id} for user_id in self.conf["share"]]

        for region, image_id in images.items():
            ec2client_image: EC2Client = boto3.client("ec2", region_name=region)
            ec2client_image.modify_image_attribute(
                Attribute="LaunchPermission",
                ImageId=image_id,
                LaunchPermission={"Add": share_list},  # type: ignore
            )
        for region, snapshot_id in snapshots.items():
            ec2client_snapshot: EC2Client = boto3.client("ec2", region_name=region)
            ec2client_snapshot.modify_snapshot_attribute(
                Attribute="createVolumePermission",
                SnapshotId=snapshot_id,
                CreateVolumePermission={"Add": share_list},  # type: ignore
            )
        logger.info(f"shared images & snapshots with '{self.conf['share']}'")

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

    def list(self) -> Dict[str, Optional[str]]:
        """
        Get image based on the available configuration
        This doesn't change anything - it just tries to get the available image
        for the different configured regions
        :return: a Dict with region names as keys and optional image/AMI Ids as values
        :rtype: Dict[str, Optional[str]]
        """
        image_ids: Dict[str, Optional[str]] = dict()
        for region in self.image_regions:
            ec2client_region: EC2Client = boto3.client("ec2", region_name=region)
            image_info: Optional[_ImageInfo] = self._get(ec2client_region)
            if image_info:
                image_ids[region] = image_info.image_id
            else:
                image_ids[region] = None
        return image_ids

    def create(self) -> Dict[str, str]:
        """
        Get or create a image based on the available configuration

        :return: a Dict with region names as keys and image/AMI Ids as values
        :rtype: Dict[str, str]
        """
        # this **must** be the region that is used for S3
        ec2client: EC2Client = boto3.client("ec2", region_name=self._s3.bucket_region)

        # make sure the initial snapshot exists
        self._snapshot.create(ec2client, self.snapshot_name)

        # make sure the snapshot exist in all required regions
        snapshot_ids: Dict[str, str] = self._snapshot.copy(
            self.snapshot_name, self._s3.bucket_region, self.image_regions
        )

        image_ids: Dict[str, str] = dict()
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
                image_ids[region] = image_info.image_id
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
                        {"VirtualName": "ephemeral0", "DeviceName": "/dev/sdb"},
                    ],
                    EnaSupport=True,
                    SriovNetSupport="simple",
                    VirtualizationType="hvm",
                    BootMode=self.conf["boot_mode"],
                )

                if self.conf["tpm_support"]:
                    register_image_kwargs["TpmSupport"] = self.conf["tpm_support"]

                if self.conf["uefi_data"]:
                    with open(self.conf["uefi_data"], "r") as f:
                        uefi_data = f.read()
                    register_image_kwargs["UefiData"] = uefi_data

                if self.conf["billing_products"]:
                    register_image_kwargs["BillingProducts"] = self.conf["billing_products"]

                resp = ec2client_region.register_image(**register_image_kwargs)
                ec2client_region.create_tags(Resources=[resp["ImageId"]], Tags=self._tags)
                image_ids[region] = resp["ImageId"]

        # wait for the images
        logger.info(f"Waiting for {len(image_ids)} images to be ready the regions ...")
        for region, image_id in image_ids.items():
            ec2client_region_wait: EC2Client = boto3.client("ec2", region_name=region)
            logger.info(f"Waiting for {image_id} in {ec2client_region_wait.meta.region_name} to exist/be available ...")
            waiter_exists = ec2client_region_wait.get_waiter("image_exists")
            waiter_exists.wait(ImageIds=[image_id])
            waiter_available = ec2client_region_wait.get_waiter("image_available")
            waiter_available.wait(ImageIds=[image_id])
        logger.info(f"{len(image_ids)} images are ready")

        # share
        self._share(image_ids, snapshot_ids)

        return image_ids

    def public(self) -> None:
        """
        Make an image and the underlying snapshot public if the public flag is set in the config
        Note: if public and temporary are both set, the image will **not** be made public
        Note: this command doesn't unpublish anything!
        """
        if not self.conf["public"]:
            logger.info(f"image {self.image_name} not marked as public. do not publish")
            return

        # never publish temporary images
        if self.conf["temporary"]:
            logger.warning(f"image {self.image_name} marked as temporary. do not publish")
            return

        # do the publication
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

    def verify(self) -> Dict[str, List[str]]:
        """
        Verify (but don't modify or create anything) that the image configuration
        matches what is on AWS
        """
        logger.info(f"Verifying image {self.image_name} ...")
        problems: Dict[str, List[str]] = dict()
        for region in self.image_regions:
            problems[region] = []
            ec2client_region: EC2Client = boto3.client("ec2", region_name=region)
            image_info: Optional[_ImageInfo] = self._get(ec2client_region)

            if not image_info:
                problems[region].append("image not available")
                logger.error(f"  {self.image_name} / {region}: not available in region")
                continue

            image_aws = ec2client_region.describe_images(ImageIds=[image_info.image_id])["Images"][0]
            # verify state
            if image_aws["State"] != "available":
                problems[region].append(f"State {image_aws['State']} != available")

            # verify RootDeviceType
            if image_aws["RootDeviceType"] != "ebs":
                problems[region].append(f"RootDeviceType {image_aws['RootDeviceType']} != ebs")

            # verify BootMode
            if image_aws["BootMode"] != self.conf["boot_mode"]:
                problems[region].append(f"BootMode {image_aws['BootMode']} != {self.conf['boot_mode']}")

            # verify RootDeviceVolumeType, RootDeviceVolumeSize and Snapshot
            for bdm in image_aws["BlockDeviceMappings"]:
                if bdm.get("DeviceName") and bdm["DeviceName"] == image_aws["RootDeviceName"]:
                    # here's the root device
                    if bdm["Ebs"]["VolumeType"] != self.conf["root_device_volume_type"]:
                        problems[region].append(
                            f"RootDeviceVolumeType {bdm['Ebs']['VolumeType']} != "
                            f"{self.conf['root_device_volume_type']}"
                        )
                    if bdm["Ebs"]["VolumeSize"] != self.conf["root_device_volume_size"]:
                        problems[region].append(
                            f"RootDeviceVolumeSize {bdm['Ebs']['VolumeSize']} != "
                            f"{self.conf['root_device_volume_size']}"
                        )
                    # verify snapshot
                    snapshot_aws = ec2client_region.describe_snapshots(SnapshotIds=[bdm["Ebs"]["SnapshotId"]])[
                        "Snapshots"
                    ][0]
                    if snapshot_aws["State"] != "completed":
                        problems[region].append(f"Snapshot state for  {snapshot_aws['SnapshotId']} != completed")
                    for tag in snapshot_aws["Tags"]:
                        if tag["Key"] == "Name" and tag["Value"] != self.snapshot_name:
                            problems[region].append(f"Snapshot name {tag['Value']} != {self.snapshot_name}")
        return problems
