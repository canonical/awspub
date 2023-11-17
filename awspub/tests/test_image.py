from unittest.mock import patch
import pytest
import pathlib

from awspub import context
from awspub import image


curdir = pathlib.Path(__file__).parent.resolve()


@pytest.mark.parametrize(
    "imagename,snapshotname",
    [
        # test-image-1 without any separate snapshot or billing products.
        # so snapshotname should match source sha256sum
        ("test-image-1", "6252475408b9f9ee64452b611d706a078831a99b123db69d144d878a0488a0a8"),
        # test-image-2 with separate snapshot but without billing products.
        # so snapshotname should be the shasum of the concatenated string of:
        # - 6252475408b9f9ee64452b611d706a078831a99b123db69d144d878a0488a0a8
        # - echo -n test-image-2 | sha256sum
        ("test-image-2", "0c274a96fe840cdd9cf65b0bf8e4d755d94fddf00916aa6f26ee3f08e412c88f"),
        # test-image-3 with separate snapshot and billing products
        ("test-image-3", "ef7c5bbbc2816c60acfa4f3954e431c849054f7370bf351055f6d665b60623e7"),
        # test-image-4 without separate snapshot but with billing products
        ("test-image-4", "bf795c602d53ff9c9548cc6305aa1240bd0f3d4429869abe4c96bcef65c4e48d"),
        # test-image-5 without separate snapshot but with multiple billing products
        ("test-image-5", "8171cd4d36d06150a5ff8bb519439c5efd4e91841be62f50736db3b82e4aaedc"),
    ],
)
def test_snapshot_names(imagename, snapshotname):
    """
    Test the snapshot name calculation based on the image properties
    """
    ctx = context.Context(curdir / "fixtures/config1.yaml")
    assert ctx.conf["source"]["path"] == curdir / "fixtures/config1.vmdk"
    assert ctx.source_sha256 == "6252475408b9f9ee64452b611d706a078831a99b123db69d144d878a0488a0a8"

    img = image.Image(ctx, imagename)
    assert img.snapshot_name == snapshotname


@pytest.mark.parametrize(
    "imagename,regions",
    [
        # test-image-1 has 2 regions defined
        ("test-image-1", ["region1", "region2"]),
        # test-image-2 has no regions defined, so whatever the ec2 client returns should be valid
        ("test-image-2", ["all-region-1", "all-region-2"]),
    ],
)
def test_image_regions(imagename, regions):
    """
    Test the regions for a given image
    """
    with patch("boto3.client") as bclient_mock:
        instance = bclient_mock.return_value
        instance.describe_regions.return_value = {
            "Regions": [{"RegionName": "all-region-1"}, {"RegionName": "all-region-2"}]
        }
        ctx = context.Context(curdir / "fixtures/config1.yaml")
        img = image.Image(ctx, imagename)
        assert img.image_regions == regions
