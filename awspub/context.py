import hashlib
import pathlib
import logging
import yaml
from string import Template
from typing import Dict

from awspub.configmodels import ConfigModel


logger = logging.getLogger(__name__)


class Context:
    """
    Context holds the used configuration and some
    automatically calculated values
    """

    def __init__(self, conf_path: pathlib.Path, conf_template_mapping_path: pathlib.Path):
        self._conf_path = conf_path
        self._conf = None
        self._conf_template_mapping_path = conf_template_mapping_path
        self._conf_template_mapping = {}

        # read the config mapping first
        if self._conf_template_mapping_path:
            with open(self._conf_template_mapping_path, "r") as ctm:
                self._conf_template_mapping = yaml.safe_load(ctm)
                logger.debug(f"loaded config template mapping for substitution: {self._conf_template_mapping}")

        # read the config itself
        with open(self._conf_path, "r") as f:
            template = Template(f.read())
            # substitute the values in the config with values from the config template mapping
            ft = template.substitute(**self._conf_template_mapping)
            y = yaml.safe_load(ft)["awspub"]
            self._conf = ConfigModel(**y).model_dump()
            logger.debug(f"config loaded as: {self._conf}")

        # handle relative paths in config files. those are relative to the config file dirname
        if not self.conf["source"]["path"].is_absolute():
            self.conf["source"]["path"] = pathlib.Path(self._conf_path).parent / self.conf["source"]["path"]

        for image_name, props in self.conf["images"].items():
            if props["uefi_data"] and not self.conf["images"][image_name]["uefi_data"].is_absolute():
                self.conf["images"][image_name]["uefi_data"] = (
                    pathlib.Path(self._conf_path).parent / self.conf["images"][image_name]["uefi_data"]
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
    def tags_dict(self) -> Dict[str, str]:
        """
        Common tags which will be used for all AWS resources
        This includes tags defined in the configuration file
        but doesn't include image group specific tags.
        Usually the tags() method should be used.
        """
        tags = dict()
        tags["awspub:source:filename"] = self.conf["source"]["path"].name
        tags["awspub:source:architecture"] = self.conf["source"]["architecture"]
        tags["awspub:source:sha256"] = self.source_sha256
        tags.update(self.conf.get("tags", {}))
        return tags

    @property
    def tags(self):
        """
        Helper to make tags directly usable by the AWS EC2 API
        which requires a list of dicts with "Key" and "Value" defined.
        """
        tags = []
        for name, value in self.tags_dict.items():
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
