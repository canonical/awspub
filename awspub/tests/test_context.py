import glob
import os
import pathlib

import pytest
from pydantic import ValidationError
from ruamel.yaml.constructor import DuplicateKeyError

from awspub import context

curdir = pathlib.Path(__file__).parent.resolve()


def test_context_create():
    """
    Create a Context object from a given configuration
    """
    ctx = context.Context(curdir / "fixtures/config1.yaml", None)
    assert ctx.conf["source"]["path"] == curdir / "fixtures/config1.vmdk"
    assert ctx.source_sha256 == "6252475408b9f9ee64452b611d706a078831a99b123db69d144d878a0488a0a8"
    assert ctx.conf["source"]["architecture"] == "x86_64"
    assert ctx.conf["s3"]["bucket_name"] == "bucket1"


def test_context_create_minimal():
    """
    Create a Context object from a given minimal configuration
    """
    ctx = context.Context(curdir / "fixtures/config-minimal.yaml", None)
    assert ctx.conf["source"]["path"] == curdir / "fixtures/config1.vmdk"
    assert ctx.source_sha256 == "6252475408b9f9ee64452b611d706a078831a99b123db69d144d878a0488a0a8"
    assert ctx.conf["source"]["architecture"] == "x86_64"
    assert ctx.conf["s3"]["bucket_name"] == "bucket1"


def test_context_create_with_mapping():
    """
    Create a Context object from a given configuration
    """
    ctx = context.Context(curdir / "fixtures/config2.yaml", curdir / "fixtures/config2-mapping.yaml")
    assert ctx.conf["source"]["path"] == curdir / "fixtures/config1.vmdk"
    assert ctx.source_sha256 == "6252475408b9f9ee64452b611d706a078831a99b123db69d144d878a0488a0a8"
    assert ctx.conf["images"].get("test-image-value1")
    assert ctx.conf["images"].get("test-image-value$2")


def test_context_with_docs_config_samples():
    """
    Create a Context object with the sample config files used for documentation
    """
    config_samples_dir = curdir.parents[1] / "docs" / "config-samples"
    for f in glob.glob(f"{config_samples_dir}/*.yaml"):
        mapping_file = f + ".mapping"
        if os.path.exists(mapping_file):
            mapping = mapping_file
        else:
            mapping = None
        context.Context(os.path.join(config_samples_dir, f), mapping)


def test_context_with_duplicate_image_name():
    """
    Create a context with a configuration file that contains a duplicate image name key
    """
    with pytest.raises(DuplicateKeyError):
        context.Context(curdir / "fixtures/config3-duplicate-keys.yaml", None)


@pytest.mark.parametrize(
    "config_file",
    ["fixtures/config-minimal.yaml", "fixtures/config-valid-nonawspub.yaml"],
)
def test_valid_configuration(config_file):
    """
    Test with a valid configuration file (no extra fields)
    """
    ctx = context.Context(curdir / config_file, None)
    assert ctx.conf is not None
    assert ctx.conf["s3"]["bucket_name"] == "bucket1"
    assert ctx.conf["source"]["architecture"] == "x86_64"


def test_invalid_configuration_extra_field():
    """
    Test with an invalid configuration file that includes an extra field
    """
    with pytest.raises(ValidationError):
        context.Context(curdir / "fixtures/config-invalid-s3-extra.yaml", None)
