import pathlib
from unittest.mock import patch

import pytest

from awspub import context, image_marketplace

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


def test_image_marketplace_request_new_version_none_exists():
    """
    Test the request_new_version logic if no version exist already
    """
    with patch("boto3.client") as bclient_mock:
        instance = bclient_mock.return_value
        instance.describe_entity.return_value = {"DetailsDocument": {}}
        ctx = context.Context(curdir / "fixtures/config1.yaml", None)
        img = image_marketplace.ImageMarketplace(ctx, "test-image-8")
        img.request_new_version("ami-123")
        assert instance.start_change_set.called is True


@pytest.mark.parametrize(
    "name,expected",
    [
        ("1.0.0", "1.0.0"),
        ("1.0.0 (testing)", "1.0.0 testing"),
        ("a sentence with spaces", "a sentence with spaces"),
        ("_+=.:@-", "_+=.:@-"),
        ("(parens) [brackets] |pipes|", "parens brackets pipes"),
    ],
)
def test_changeset_name_sanitization(name, expected):
    assert image_marketplace.ImageMarketplace.sanitize_changeset_name(name) == expected
