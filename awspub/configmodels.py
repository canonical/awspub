import pathlib
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class ConfigS3Model(BaseModel):
    """
    S3 configuration.
    This is required for uploading source files (usually .vmdk) to a bucket so
    snapshots can be created out of the s3 file
    """

    bucket_name: str = Field(description="The S3 bucket name")
    bucket_region: str = Field(description="The S3 region name")


class ConfigSourceModel(BaseModel):
    """
    Source configuration.
    This defines the source (usually .vmdk) that is uploaded
    to S3 and then used to create EC2 snapshots in different regions.
    """

    path: pathlib.Path = Field(description="Path to a local .vmdk image")
    architecture: Literal["x86_64", "arm64"] = Field(description="The architecture of the given .vmdk image")


class ConfigImageMarketplaceSecurityGroupModel(BaseModel):
    """
    Image/AMI Marketplace specific configuration for a security group
    """

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


class ConfigImageModel(BaseModel):
    """
    Image/AMI configuration.
    """

    description: Optional[str] = Field(description="Optional image description", default=None)
    regions: Optional[List[str]] = Field(
        description="Optional list of regions for this image. If not given, all available regions will be used",
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
        description="Optional list of account IDs the image and snapshot will be shared with", default=None
    )
    temporary: Optional[bool] = Field(
        description="Optional boolean field indicates that a image is only temporary", default=False
    )
    public: Optional[bool] = Field(
        description="Optional boolean field indicates if the image should be public", default=False
    )
    marketplace: Optional[ConfigImageMarketplaceModel] = Field(
        description="Optional structure containing Marketplace related configuration", default=None
    )
    ssm_parameter: Optional[List[ConfigImageSSMParameterModel]] = Field(
        description="Optional list of SSM parameter paths of type `aws:ec2:image` which will "
        "be pushed to the parameter store",
        default=None,
    )
    groups: Optional[List[str]] = Field(description="Optional list of groups this image is part of", default=[])
    tags: Optional[Dict[str, str]] = Field(description="Optional Tags to apply to this image only", default={})


class ConfigModel(BaseModel):
    """
    The base model for the whole configuration
    """

    s3: ConfigS3Model
    source: ConfigSourceModel
    images: Dict[str, ConfigImageModel]
    tags: Optional[Dict[str, str]] = Field(description="Optional Tags to apply to all resources", default={})
