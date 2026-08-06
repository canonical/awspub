import pathlib
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from awspub import api, context, image

curdir = pathlib.Path(__file__).parent.resolve()


@pytest.mark.parametrize(
    "group,expected_image_names",
    [
        # without any group, all images should be processed
        (
            None,
            [
                "test-image-1",
                "test-image-2",
                "test-image-3",
                "test-image-4",
                "test-image-5",
                "test-image-6",
                "test-image-7",
                "test-image-8",
                "test-image-9",
                "test-image-10",
                "test-image-11",
                "test-image-12",
            ],
        ),
        # with a group that no image as, no image should be processed
        (
            "group-not-used",
            [],
        ),
        # with a group that an image has
        (
            "group2",
            ["test-image-1"],
        ),
        # with a group that multiple images have
        (
            "group1",
            ["test-image-1", "test-image-2"],
        ),
    ],
)
def test_api__images_filtered(group, expected_image_names):
    """
    Test the _images_filtered() function
    """
    ctx = context.Context(curdir / "fixtures/config1.yaml", None)

    image_names = [i[0] for i in api._images_filtered(ctx, group)]
    assert image_names == expected_image_names


@pytest.mark.parametrize(
    "group,expected",
    [
        # without any group, all images should be processed
        (
            None,
            (
                {"test-image-1": {"eu-central-1": "ami-123", "eu-central-2": "ami-456"}},
                {
                    "group1": {"test-image-1": {"eu-central-1": "ami-123", "eu-central-2": "ami-456"}},
                    "group2": {"test-image-1": {"eu-central-1": "ami-123", "eu-central-2": "ami-456"}},
                },
            ),
        ),
        # with a group that no image as, image should be there but nothing in the group
        ("group-not-used", ({"test-image-1": {"eu-central-1": "ami-123", "eu-central-2": "ami-456"}}, {})),
    ],
)
def test_api__images_grouped(group, expected):
    """
    Test the _images_grouped() function
    """
    ctx = context.Context(curdir / "fixtures/config1.yaml", None)
    images = [
        (
            "test-image-1",
            image.Image(ctx, "test-image-1"),
            {"eu-central-1": image._ImageInfo("ami-123", None), "eu-central-2": image._ImageInfo("ami-456", None)},
        )
    ]
    grouped = api._images_grouped(images, group)
    assert grouped == expected


@patch("awspub.api.Image")
@patch("awspub.api.S3")
def test_api_create_upload_multipart_concurrency_override(s3_mock, image_mock):
    """
    test that create() overrides s3.upload_multipart_concurrency in the context
    when explicitly given
    """
    api.create(curdir / "fixtures/config1.yaml", None, None, upload_multipart_concurrency=6)
    ctx_used = s3_mock.call_args.args[0]
    assert ctx_used.conf["s3"]["upload_multipart_concurrency"] == 6


@patch("awspub.api.Image")
@patch("awspub.api.S3")
def test_api_create_upload_multipart_concurrency_not_overridden(s3_mock, image_mock):
    """
    test that create() leaves the config default in place when no override is given
    """
    api.create(curdir / "fixtures/config1.yaml", None, None)
    ctx_used = s3_mock.call_args.args[0]
    assert ctx_used.conf["s3"]["upload_multipart_concurrency"] == 1


@pytest.mark.parametrize("upload_multipart_concurrency", [0, -1, 33, True, False])
def test_api_create_upload_multipart_concurrency_override_invalid(upload_multipart_concurrency):
    """
    test that create() rejects invalid multipart-upload concurrency overrides
    """
    with pytest.raises(ValidationError):
        api.create(
            curdir / "fixtures/config1.yaml",
            None,
            None,
            upload_multipart_concurrency=upload_multipart_concurrency,
        )
