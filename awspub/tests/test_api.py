import pathlib

import pytest

from awspub import api, context

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
