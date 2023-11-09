import hashlib
import pathlib
import yaml
from pydantic import BaseModel, Field
from typing import Dict, Literal, List, Optional


class _ConfigS3Model(BaseModel):
    """
    S3 configuration.
    This is required for uploading source files (usually .vmdk) to a bucket so
    snapshots can be created out of the s3 file
    """

    bucket_name: str = Field(description="The S3 bucket name")
    bucket_region: str = Field(description="The S3 region name")


class _ConfigSourceModel(BaseModel):
    """
    Source configuration.
    This defines the source (usually .vmdk) that is uploaded
    to S3 and then used to create EC2 snapshots in different regions.
    """

    path: pathlib.Path = Field(description="Path to a local .vmdk image")
    architecture: Literal["x86_64", "arm64"] = Field(description="The architecture of the given .vmdk image")


class _ConfigImageModel(BaseModel):
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


class _ConfigModel(BaseModel):
    """
    The base model for the whole configuration
    """

    s3: _ConfigS3Model
    source: _ConfigSourceModel
    images: Dict[str, _ConfigImageModel]
    tags: Optional[Dict[str, str]] = Field(description="Optional Tags to apply to resources")


class Context:
    """
    Context holds the used configuration and some
    automatically calculated values
    """

    def __init__(self, conf_path: pathlib.Path):
        self._conf_path = conf_path
        self._conf = None
        with open(self._conf_path, "r") as f:
            y = yaml.safe_load(f)["awspub"]
            self._conf = _ConfigModel(**y).model_dump()

        # handle relative paths in config files. those are relative to the config file dirname
        if not self.conf["source"]["path"].is_absolute():
            self.conf["source"]["path"] = self._conf_path.parent / self.conf["source"]["path"]

        for image_name, props in self.conf["images"].items():
            if props["uefi_data"] and not self.conf["images"][image_name]["uefi_data"].is_absolute():
                self.conf["images"][image_name]["uefi_data"] = (
                    self._conf_path.parent / self.conf["images"][image_name]["uefi_data"]
                )

        # calculate the sha256 sum of the source file once
        self._source_sha256 = self._sha256sum(self.conf["source"]["path"]).hexdigest()

    @property
    def conf(self):
        return self._conf

    @property
    def source_sha256(self):
        """
        The sha256 sum hexdigest of the source->path value from the given
        configuration. This value is used in different places (eg. to automatically
        upload to S3 with this value as key)
        """
        return self._source_sha256

    @property
    def tags(self):
        """
        Common tags which will be used for all AWS resources
        This includes tags defined in the configuration file
        """
        tags = [
            {"Key": "awspub:source:filename", "Value": self.conf["source"]["path"].name},
            {"Key": "awspub:source:architecture", "Value": self.conf["source"]["architecture"]},
            {"Key": "awspub:source:sha256", "Value": self.source_sha256},
        ]

        tags_extra = self.conf.get("tags", {})
        for name, value in tags_extra.items():
            tags.append({"Key": name, "Value": value})
        return tags

    def _sha256sum(self, file_path: pathlib.Path):
        """
        Calculate a sha256 sum for a given file

        :param file_path: the path to the local file to upload
        :type file_path: pathlib.Path
        :return: a haslib Hash object
        :rtype: _hashlib.HASH
        """
        sha256_hash = hashlib.sha256()
        with open(file_path.resolve(), "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash
