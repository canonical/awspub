import hashlib
import pathlib
import yaml

from awspub.configmodels import ConfigModel


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
            self._conf = ConfigModel(**y).model_dump()

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
