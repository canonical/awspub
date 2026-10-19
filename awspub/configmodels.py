import pathlib
import re
from enum import Enum
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from awspub.common import _split_partition


class ConfigS3Model(BaseModel):
    """
    S3 configuration.
    Required for import snapshot creation; unused in direct mode.
    """

    model_config = ConfigDict(extra="forbid")

    bucket_name: str = Field(description="The S3 bucket name")
    upload_multipart_concurrency: int = Field(
        default=1,
        ge=1,
        le=32,
        description="The number of parts to upload concurrently during a multipart upload to S3 (1-32)",
    )

    @field_validator("upload_multipart_concurrency", mode="before")
    @classmethod
    def _upload_multipart_concurrency_not_bool(cls, v):
        if isinstance(v, bool):
            raise ValueError("upload_multipart_concurrency must be an int, not a bool")
        return v


class ConfigSourceModel(BaseModel):
    """
    Source configuration.
    This defines the source (usually .vmdk) that is uploaded
    to S3 and then used to create EC2 snapshots in different regions.
    """

    model_config = ConfigDict(extra="forbid")

    path: pathlib.Path = Field(description="Path to a local .vmdk image")
    architecture: Literal["x86_64", "arm64"] = Field(description="The architecture of the given .vmdk image")


class ConfigSnapshotModel(BaseModel):
    """
    Snapshot creation configuration.
    This defines how the EC2 snapshot is created from the source image.
    """

    model_config = ConfigDict(extra="forbid")

    creation: Literal["import", "direct"] = Field(
        description=(
            "How to create the EC2 snapshot from the source image. "
            "'import' (default) uploads the source image to S3 and uses the EC2 VM Import service "
            "(import-snapshot) to create the snapshot - slow (typically several minutes) but needs no "
            "extra IAM permissions beyond S3/EC2. "
            "'direct' creates the snapshot via the EBS direct APIs (StartSnapshot/PutSnapshotBlock/"
            "CompleteSnapshot) by streaming only the non-zero 512 KiB blocks of the source image "
            "(raw or vmdk). This is much faster (no VM Import queue/conversion) but requires the "
            "ebs:StartSnapshot, ebs:PutSnapshotBlock and ebs:CompleteSnapshot IAM permissions"
        ),
        default="import",
    )
    region: Optional[str] = Field(
        default=None,
        min_length=1,
        description=(
            "Region in which to create the initial snapshot. Required for 'direct' creation; "
            "'import' creation always uses the S3 bucket region"
        ),
    )
    block_upload_concurrency: int = Field(
        default=8,
        ge=1,
        le=32,
        description="The number of snapshot blocks to upload concurrently in 'direct' creation mode (1-32)",
    )

    @field_validator("block_upload_concurrency", mode="before")
    @classmethod
    def _block_upload_concurrency_not_bool(cls, v):
        if isinstance(v, bool):
            raise ValueError("block_upload_concurrency must be an int, not a bool")
        return v

    @model_validator(mode="after")
    def check_region(self) -> "ConfigSnapshotModel":
        if self.creation == "direct" and not self.region:
            raise ValueError("snapshot.region is required for direct snapshot creation")
        return self


class ConfigImageMarketplaceSecurityGroupModel(BaseModel):
    """
    Image/AMI Marketplace specific configuration for a security group
    """

    model_config = ConfigDict(extra="forbid")

    from_port: int = Field(description="The source port")
    ip_protocol: Literal["tcp", "udp"] = Field(description="The IP protocol (either 'tcp' or 'udp')")
    ip_ranges: List[str] = Field(description="IP ranges to allow, in CIDR format (eg. '192.0.2.0/24')")
    to_port: int = Field(description="The destination port")


class ConfigImageMarketplaceModel(BaseModel):
    """
    Image/AMI Marketplace specific configuration to request new Marketplace versions
    See https://docs.aws.amazon.com/marketplace-catalog/latest/api-reference/ami-products.html
    for further information
    """

    model_config = ConfigDict(extra="forbid")

    entity_id: str = Field(description="The entity ID (product ID)")
    # see https://docs.aws.amazon.com/marketplace/latest/userguide/ami-single-ami-products.html#single-ami-marketplace-ami-access  # noqa:E501
    access_role_arn: str = Field(
        description="IAM role Amazon Resource Name (ARN) used by AWS Marketplace to access the provided AMI"
    )
    version_title: str = Field(description="The version title. Must be unique across the product")
    release_notes: str = Field(description="The release notes")
    user_name: str = Field(description="The login username to access the operating system")
    scanning_port: int = Field(description="Port to access the operating system (default: 22)", default=22)
    os_name: str = Field(description="Operating system name displayed to Marketplace buyers")
    os_version: str = Field(description="Operating system version displayed to Marketplace buyers")
    usage_instructions: str = Field(
        description=" Instructions for using the AMI, or a link to more information about the AMI"
    )
    recommended_instance_type: str = Field(
        description="The instance type that is recommended to run the service with the AMI and is the "
        "default for 1-click installs of your service"
    )
    security_groups: Optional[List[ConfigImageMarketplaceSecurityGroupModel]]


class ConfigImageSSMParameterModel(BaseModel):
    """
    Image/AMI SSM specific configuration to push parameters of type `aws:ec2:image` to the parameter store
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        description="The fully qualified name of the parameter that you want to add to the system. "
        "A parameter name must be unique within an Amazon Web Services Region"
    )
    description: Optional[str] = Field(
        description="Information about the parameter that you want to add to the system", default=None
    )
    allow_overwrite: Optional[bool] = Field(
        description="allow to overwrite an existing parameter. Useful for keep a 'latest' parameter (default: false)",
        default=False,
    )


class SNSNotificationProtocol(str, Enum):
    DEFAULT = "default"
    EMAIL = "email"


class ConfigImageSNSNotificationModel(BaseModel):
    """
    Image/AMI SNS Notification specific configuration to notify subscribers about new images availability
    """

    model_config = ConfigDict(extra="forbid")

    subject: str = Field(description="The subject of SNS Notification", min_length=1, max_length=99)
    message: Dict[SNSNotificationProtocol, str] = Field(
        description="The body of the message to be sent to subscribers.",
        default={SNSNotificationProtocol.DEFAULT: ""},
    )
    regions: Optional[List[str]] = Field(
        description="Optional list of regions for sending notification. If not given, regions where the image "
        "registered will be used from the currently used parition. If a region doesn't exist in the currently "
        "used partition, it will be ignored.",
        default=None,
    )
    regions_denylist: Optional[List[str]] = Field(
        description="Optional list of regions to exclude from sending notifications. "
        "A region listed in both 'regions' and 'regions_denylist' will raise a validation error.",
        default=None,
    )

    @field_validator("message")
    def check_message(cls, value):
        # Check message protocols have default key
        # Message should contain at least a top-level JSON key of "default"
        # with a value that is a string
        if SNSNotificationProtocol.DEFAULT not in value:
            raise ValueError(f"{SNSNotificationProtocol.DEFAULT.value} key is required to send SNS notification")
        return value

    @model_validator(mode="after")
    def check_regions_denylist(self):
        if self.regions and self.regions_denylist:
            overlap = set(self.regions) & set(self.regions_denylist)
            if overlap:
                raise ValueError(
                    f"Regions {sorted(overlap)} appear in both 'regions' and 'regions_denylist'. "
                    "A region cannot be both included and excluded."
                )
        return self


class ConfigImageModel(BaseModel):
    """
    Image/AMI configuration.
    """

    model_config = ConfigDict(extra="forbid")

    description: Optional[str] = Field(description="Optional image description", default=None)
    regions: Optional[List[str]] = Field(
        description="Optional list of regions for this image. If not given, all available regions will"
        "be used from the currently used partition. If a region doesn't exist in the currently used partition,"
        " it will be ignored.",
        default=None,
    )
    regions_denylist: Optional[List[str]] = Field(
        description="Optional list of regions to exclude from publication for this image. "
        "A region listed in both 'regions' and 'regions_denylist' will raise a validation error.",
        default=None,
    )
    separate_snapshot: bool = Field(description="Use a separate snapshot for this image?", default=False)
    billing_products: Optional[List[str]] = Field(description="Optional list of billing codes", default=None)
    boot_mode: Literal["legacy-bios", "uefi", "uefi-preferred"] = Field(
        description="The boot mode. For arm64, this needs to be 'uefi'"
    )
    root_device_name: Optional[str] = Field(description="The root device name", default="/dev/sda1")
    root_device_volume_type: Optional[Literal["gp2", "gp3"]] = Field(
        description="The root device volume type", default="gp3"
    )
    root_device_volume_size: Optional[int] = Field(description="The root device volume size (in GB)", default=8)
    uefi_data: Optional[pathlib.Path] = Field(
        description="Optional path to a non-volatile UEFI variable store (must be already base64 encoded)", default=None
    )
    tpm_support: Optional[Literal["v2.0"]] = Field(
        description="Optional TPM support. If this is set, 'boot_mode' must be 'uefi'", default=None
    )
    imds_support: Optional[Literal["v2.0"]] = Field(description="Optional IMDS support", default=None)
    share: Optional[List[str]] = Field(
        description="Optional list of account IDs, organization ARN, OU ARN the image and snapshot will be shared with."
        " The account ID can be prefixed with the partition and separated by ':'. Eg 'aws-cn:123456789123'",
        default=None,
    )
    temporary: Optional[bool] = Field(
        description="Optional boolean field indicates that a image is only temporary", default=False
    )
    public: Optional[bool] = Field(
        description="Optional boolean field indicates if the image should be public", default=False
    )
    marketplace: Optional[ConfigImageMarketplaceModel] = Field(
        description="Optional structure containing Marketplace related configuration for the commercial "
        "'aws' partition",
        default=None,
    )
    ssm_parameter: Optional[List[ConfigImageSSMParameterModel]] = Field(
        description="Optional list of SSM parameter paths of type `aws:ec2:image` which will "
        "be pushed to the parameter store",
        default=None,
    )
    groups: Optional[List[str]] = Field(description="Optional list of groups this image is part of", default=[])
    tags: Optional[Dict[str, str]] = Field(description="Optional Tags to apply to this image only", default={})
    sns: Optional[List[Dict[str, ConfigImageSNSNotificationModel]]] = Field(
        description="Optional list of SNS Notification related configuration", default=None
    )

    @field_validator("share")
    @classmethod
    def check_share(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        """
        Make sure the account IDs are valid and if given the partition is correct
        """
        patterns = [
            # https://docs.aws.amazon.com/organizations/latest/APIReference/API_Account.html
            r"\d{12}",
            # Adjusted for partitions
            # https://docs.aws.amazon.com/organizations/latest/APIReference/API_Organization.html
            r"arn:aws(?:-cn)?(?:-us-gov)?:organizations::\d{12}:organization\/o-[a-z0-9]{10,32}",
            # https://docs.aws.amazon.com/organizations/latest/APIReference/API_OrganizationalUnit.html
            r"arn:aws(?:-cn)?(?:-us-gov)?:organizations::\d{12}:ou\/o-[a-z0-9]{10,32}\/ou-[0-9a-z]{4,32}-[0-9a-z]{8,32}",  # noqa:E501
        ]
        if v is not None:
            for val in v:
                partition, account_id_or_arn = _split_partition(val)
                valid = False
                for pattern in patterns:
                    if re.fullmatch(pattern, account_id_or_arn):
                        valid = True
                        break
                if not valid:
                    raise ValueError("Account ID must be 12 digits long or an ARN for Organization or OU")
                if partition not in ["aws", "aws-cn", "aws-us-gov"]:
                    raise ValueError("Partition must be one of 'aws', 'aws-cn', 'aws-us-gov'")
        return v

    @model_validator(mode="after")
    def check_regions_denylist(self):
        if self.regions and self.regions_denylist:
            overlap = set(self.regions) & set(self.regions_denylist)
            if overlap:
                raise ValueError(
                    f"Regions {sorted(overlap)} appear in both 'regions' and 'regions_denylist'. "
                    "A region cannot be both included and excluded."
                )
        return self


class ConfigModel(BaseModel):
    """
    The base model for the whole configuration
    """

    model_config = ConfigDict(extra="forbid")

    s3: Optional[ConfigS3Model] = Field(
        default=None,
        description="S3 configuration, required for import snapshot creation and unused in direct mode",
    )
    source: ConfigSourceModel
    snapshot: ConfigSnapshotModel = Field(
        description="Optional snapshot creation configuration (how the snapshot is created from the source image)",
        default_factory=ConfigSnapshotModel,
    )
    images: Dict[str, ConfigImageModel]
    tags: Optional[Dict[str, str]] = Field(description="Optional Tags to apply to all resources", default={})

    @model_validator(mode="after")
    def check_s3(self) -> "ConfigModel":
        if self.snapshot.creation == "import" and self.s3 is None:
            raise ValueError("s3 is required for import snapshot creation")
        return self
