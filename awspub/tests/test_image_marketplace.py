from unittest.mock import patch
import pytest
import pathlib

from awspub import context
from awspub import image_marketplace


curdir = pathlib.Path(__file__).parent.resolve()


@pytest.mark.parametrize(
    "imagename,new_version,called_start_change_set",
    [
        # same version that already exists
        ("test-image-8", "1.0.0", False),
        # new version
        ("test-image-8", "2.0.0", True),
    ],
)
def test_image_marketplace_request_new_version(imagename, new_version, called_start_change_set):
    """
    Test the request_new_version logic
    """
    with patch("boto3.client") as bclient_mock:
        instance = bclient_mock.return_value
        instance.describe_entity.return_value = {"DetailsDocument": {"Versions": [{"VersionTitle": new_version}]}}
        ctx = context.Context(curdir / "fixtures/config1.yaml", None)
        img = image_marketplace.ImageMarketplace(ctx, imagename)
        img.request_new_version("ami-123")
        assert instance.start_change_set.called == called_start_change_set
