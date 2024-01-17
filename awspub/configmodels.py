import pathlib
from pydantic import BaseModel, Field
from typing import Dict, Literal, List, Optional


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


class ConfigImageModel(BaseModel):
    """
    Image/AMI configuration.
    """

    desciption: Optional[str] = Field(description="Optional image description", default=None)
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
    share: Optional[List[str]] = Field(
        description="Optional list of account IDs the image and snapshot will be shared with", default=None
    )
    temporary: Optional[bool] = Field(
        description="Optional boolean field indicates that a image is only temporary", default=False
    )
    public: Optional[bool] = Field(
        description="Optional boolean field indicates if the image should be public", default=False
    )


class ConfigModel(BaseModel):
    """
    The base model for the whole configuration
    """

    s3: ConfigS3Model
    source: ConfigSourceModel
    images: Dict[str, ConfigImageModel]
    tags: Optional[Dict[str, str]] = Field(description="Optional Tags to apply to resources", default={})
