import pathlib
from unittest.mock import patch

import pytest

from awspub import context, exceptions, image

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
    ctx = context.Context(curdir / "fixtures/config1.yaml", None)
    assert ctx.conf["source"]["path"] == curdir / "fixtures/config1.vmdk"
    assert ctx.source_sha256 == "6252475408b9f9ee64452b611d706a078831a99b123db69d144d878a0488a0a8"

    img = image.Image(ctx, imagename)
    assert img.snapshot_name == snapshotname


@pytest.mark.parametrize(
    "imagename,regions_in_partition,regions_expected",
    [
        # test-image-1 has 2 regions defined
        ("test-image-1", ["region1", "region2"], ["region1", "region2"]),
        # test-image-1 has 2 regions defined and there are more regions in the partition
        ("test-image-1", ["region1", "region2", "region3"], ["region1", "region2"]),
        ("test-image-1", ["region1", "region2"], ["region1", "region2"]),
        # test-image-2 has no regions defined, so whatever the ec2 client returns should be valid
        ("test-image-2", ["all-region-1", "all-region-2"], ["all-region-1", "all-region-2"]),
        # test-image-1 has 2 regions defined, but those regions are not in the partition
        ("test-image-1", ["region3", "region4"], []),
        # test-image-1 has 2 regions defined, but those regions are not partially in the partition
        ("test-image-1", ["region2", "region4"], ["region2"]),
        # test-image-2 has no regions defined and the ec2 client doesn't return any regions
        ("test-image-2", [], []),
    ],
)
@patch("awspub.s3.S3.bucket_region", return_value="region1")
def test_image_regions(s3_region_mock, imagename, regions_in_partition, regions_expected):
    """
    Test the regions for a given image
    """
    with patch("boto3.client") as bclient_mock:
        instance = bclient_mock.return_value
        instance.describe_regions.return_value = {"Regions": [{"RegionName": r} for r in regions_in_partition]}
        ctx = context.Context(curdir / "fixtures/config1.yaml", None)
        img = image.Image(ctx, imagename)
        assert sorted(img.image_regions) == sorted(regions_expected)


@pytest.mark.parametrize(
    "imagename,cleanup",
    [
        ("test-image-1", True),
        ("test-image-2", False),
    ],
)
def test_image_cleanup(imagename, cleanup):
    """
    Test the cleanup for a given image
    """
    with patch("boto3.client") as bclient_mock:
        instance = bclient_mock.return_value
        instance.describe_images.return_value = {"Images": [{"Name": imagename, "Public": False, "ImageId": "ami-123"}]}
        instance.describe_regions.return_value = {"Regions": [{"RegionName": "region1"}, {"RegionName": "region2"}]}
        instance.list_buckets.return_value = {"Buckets": [{"Name": "bucket1"}]}
        ctx = context.Context(curdir / "fixtures/config1.yaml", None)
        img = image.Image(ctx, imagename)
        img.cleanup()
        assert instance.deregister_image.called == cleanup


@pytest.mark.parametrize(
    "root_device_name,block_device_mappings,snapshot_id",
    [
        ("", [], None),
        ("/dev/sda1", [], None),
        (
            "/dev/sda1",
            [
                {
                    "DeviceName": "/dev/sda1",
                    "Ebs": {
                        "DeleteOnTermination": True,
                        "SnapshotId": "snap-0be0763f84af34e05",
                        "VolumeSize": 17,
                        "VolumeType": "gp2",
                        "Encrypted": False,
                    },
                },
                {"DeviceName": "/dev/sdb", "VirtualName": "ephemeral0"},
            ],
            "snap-0be0763f84af34e05",
        ),
    ],
)
def test_image___get_root_device_snapshot_id(root_device_name, block_device_mappings, snapshot_id):
    """
    Test the _get_root_device_snapshot_id() method
    """
    i = {"RootDeviceName": root_device_name, "BlockDeviceMappings": block_device_mappings}
    ctx = context.Context(curdir / "fixtures/config1.yaml", None)
    img = image.Image(ctx, "test-image-1")
    assert img._get_root_device_snapshot_id(i) == snapshot_id


@pytest.mark.parametrize(
    "imagename,partition,called_mod_image,called_mod_snapshot,called_start_change_set,called_put_parameter",
    [
        ("test-image-6", "aws", True, True, False, False),
        ("test-image-7", "aws", False, False, False, False),
        ("test-image-8", "aws", True, True, True, True),
        ("test-image-8", "aws-cn", True, True, False, True),
    ],
)
def test_image_publish(
    imagename, partition, called_mod_image, called_mod_snapshot, called_start_change_set, called_put_parameter
):
    """
    Test the publish() for a given image
    """
    with patch("boto3.client") as bclient_mock:
        instance = bclient_mock.return_value
        instance.meta.partition = partition
        instance.describe_images.return_value = {
            "Images": [
                {
                    "Name": imagename,
                    "ImageId": "ami-abc",
                    "RootDeviceName": "/dev/sda1",
                    "BlockDeviceMappings": [
                        {
                            "DeviceName": "/dev/sda1",
                            "Ebs": {
                                "DeleteOnTermination": True,
                                "SnapshotId": "snap-0be0763f84af34e05",
                            },
                        },
                    ],
                }
            ]
        }
        instance.get_parameters.return_value = {"Parameters": []}
        instance.describe_regions.return_value = {
            "Regions": [{"RegionName": "eu-central-1"}, {"RegionName": "us-east-1"}]
        }
        instance.list_buckets.return_value = {"Buckets": [{"Name": "bucket1"}]}
        ctx = context.Context(curdir / "fixtures/config1.yaml", None)
        img = image.Image(ctx, imagename)
        img.publish()
        assert instance.modify_image_attribute.called == called_mod_image
        assert instance.modify_snapshot_attribute.called == called_mod_snapshot
        assert instance.start_change_set.called == called_start_change_set
        assert instance.put_parameter.called == called_put_parameter


def test_image__get_zero_images():
    """
    Test the Image._get() method with zero matching image
    """
    with patch("boto3.client") as bclient_mock:
        instance = bclient_mock.return_value
        instance.describe_images.return_value = {"Images": []}
        ctx = context.Context(curdir / "fixtures/config1.yaml", None)
        img = image.Image(ctx, "test-image-1")
        assert img._get(instance) is None


def test_image__get_one_images():
    """
    Test the Image._get() method with a single matching image
    """
    with patch("boto3.client") as bclient_mock:
        instance = bclient_mock.return_value
        instance.describe_images.return_value = {
            "Images": [
                {
                    "Name": "test-image-1",
                    "ImageId": "ami-abc",
                    "RootDeviceName": "/dev/sda1",
                    "BlockDeviceMappings": [
                        {
                            "DeviceName": "/dev/sda1",
                            "Ebs": {
                                "DeleteOnTermination": True,
                                "SnapshotId": "snap-abc",
                            },
                        },
                    ],
                }
            ]
        }
        ctx = context.Context(curdir / "fixtures/config1.yaml", None)
        img = image.Image(ctx, "test-image-1")
        assert img._get(instance) == image._ImageInfo("ami-abc", "snap-abc")


def test_image__get_multiple_images():
    """
    Test the Image._get() method with a multiple matching image
    """
    with patch("boto3.client") as bclient_mock:
        instance = bclient_mock.return_value
        instance.describe_images.return_value = {
            "Images": [
                {
                    "Name": "test-image-1",
                    "ImageId": "ami-1,",
                },
                {
                    "Name": "test-image-1",
                    "ImageId": "ami-2,",
                },
            ]
        }
        ctx = context.Context(curdir / "fixtures/config1.yaml", None)
        img = image.Image(ctx, "test-image-1")
        with pytest.raises(exceptions.MultipleImagesException):
            img._get(instance)


@pytest.mark.parametrize(
    "imagename,expected_tags",
    [
        # no image specific tags - assume the common tags
        (
            "test-image-1",
            [
                {"Key": "awspub:source:filename", "Value": "config1.vmdk"},
                {"Key": "awspub:source:architecture", "Value": "x86_64"},
                {
                    "Key": "awspub:source:sha256",
                    "Value": "6252475408b9f9ee64452b611d706a078831a99b123db69d144d878a0488a0a8",
                },
                {"Key": "name", "Value": "foobar"},
            ],
        ),
        # with image specific tag but no override
        (
            "test-image-6",
            [
                {"Key": "awspub:source:filename", "Value": "config1.vmdk"},
                {"Key": "awspub:source:architecture", "Value": "x86_64"},
                {
                    "Key": "awspub:source:sha256",
                    "Value": "6252475408b9f9ee64452b611d706a078831a99b123db69d144d878a0488a0a8",
                },
                {"Key": "name", "Value": "foobar"},
                {"Key": "key1", "Value": "value1"},
            ],
        ),
        # with image specific tag which overrides common tag
        (
            "test-image-7",
            [
                {"Key": "awspub:source:filename", "Value": "config1.vmdk"},
                {"Key": "awspub:source:architecture", "Value": "x86_64"},
                {
                    "Key": "awspub:source:sha256",
                    "Value": "6252475408b9f9ee64452b611d706a078831a99b123db69d144d878a0488a0a8",
                },
                {"Key": "name", "Value": "not-foobar"},
                {"Key": "key2", "Value": "name"},
            ],
        ),
    ],
)
def test_image__tags(imagename, expected_tags):
    """
    Test the Image._tags() method
    """
    ctx = context.Context(curdir / "fixtures/config1.yaml", None)
    img = image.Image(ctx, imagename)
    assert img._tags == expected_tags


@pytest.mark.parametrize(
    "available_images,expected",
    [
        # image available
        ([{"Name": "test-image-6", "ImageId": "ami-123"}], {"eu-central-1": image._ImageInfo("ami-123", None)}),
        # image not available
        ([], {}),
    ],
)
def test_image_list(available_images, expected):
    """
    Test the list for a given image
    """
    with patch("boto3.client") as bclient_mock:
        instance = bclient_mock.return_value
        instance.describe_images.return_value = {"Images": available_images}
        instance.describe_regions.return_value = {
            "Regions": [{"RegionName": "eu-central-1"}, {"RegionName": "us-east-1"}]
        }
        instance.list_buckets.return_value = {"Buckets": [{"Name": "bucket1"}]}
        ctx = context.Context(curdir / "fixtures/config1.yaml", None)
        img = image.Image(ctx, "test-image-6")
        assert img.list() == expected


@patch("awspub.s3.S3.bucket_region", return_value="region1")
def test_image_create_existing(s3_bucket_mock):
    """
    Test the create() method for a given image that already exist
    """
    with patch("boto3.client") as bclient_mock:
        instance = bclient_mock.return_value
        instance.describe_snapshots.return_value = {"Snapshots": [{"SnapshotId": "snap-123"}]}
        instance.describe_images.return_value = {
            "Images": [
                {
                    "Name": "test-image-6",
                    "ImageId": "ami-123",
                    "RootDeviceName": "/dev/sda1",
                    "BlockDeviceMappings": [
                        {
                            "DeviceName": "/dev/sda1",
                            "Ebs": {
                                "DeleteOnTermination": True,
                                "SnapshotId": "snap-123",
                            },
                        },
                    ],
                }
            ]
        }
        instance.describe_regions.return_value = {
            "Regions": [{"RegionName": "eu-central-1"}, {"RegionName": "us-east-1"}]
        }
        instance.list_buckets.return_value = {"Buckets": [{"Name": "bucket1"}]}
        ctx = context.Context(curdir / "fixtures/config1.yaml", None)
        img = image.Image(ctx, "test-image-6")
        assert img.create() == {"eu-central-1": image._ImageInfo(image_id="ami-123", snapshot_id="snap-123")}
        # register and create_tags shouldn't be called given that the image was already there
        assert not instance.register_image.called
        assert not instance.create_tags.called


@pytest.mark.parametrize(
    "imagename,describe_images,get_parameters,get_parameters_called,put_parameter_called",
    [
        # no image, no parameters (this should actually never happen but test it anyway)
        ("test-image-8", [], [], False, False),
        # with image, no parameter, no overwrite
        ("test-image-8", [{"Name": "test-image-8", "ImageId": "ami-123"}], [], True, True),
        # with image, with parameter, no overwrite
        (
            "test-image-8",
            [{"Name": "test-image-8", "ImageId": "ami-123"}],
            [{"Name": "/awspub-test/param1", "Value": "ami-123"}],
            True,
            False,
        ),
        # with image, no parameter, with overwrite
        ("test-image-9", [{"Name": "test-image-8", "ImageId": "ami-123"}], [], False, True),
        # with image, with parameter, with overwrite
        (
            "test-image-9",
            [{"Name": "test-image-8", "ImageId": "ami-123"}],
            [{"Name": "/awspub-test/param1", "Value": "ami-123"}],
            False,
            True,
        ),
    ],
)
def test_image__put_ssm_parameters(
    imagename, describe_images, get_parameters, get_parameters_called, put_parameter_called
):
    """
    Test the _put_ssm_parameters() method
    """
    with patch("boto3.client") as bclient_mock:
        instance = bclient_mock.return_value
        instance.describe_images.return_value = {"Images": describe_images}
        instance.get_parameters.return_value = {"Parameters": get_parameters}
        instance.describe_regions.return_value = {
            "Regions": [{"RegionName": "eu-central-1"}, {"RegionName": "us-east-1"}]
        }
        instance.list_buckets.return_value = {"Buckets": [{"Name": "bucket1"}]}
        ctx = context.Context(curdir / "fixtures/config1.yaml", None)
        img = image.Image(ctx, imagename)
        img._put_ssm_parameters()
        assert instance.get_parameters.called == get_parameters_called
        assert instance.put_parameter.called == put_parameter_called


@pytest.mark.parametrize(
    "image_found,config,config_image_name, expected_problems",
    [
        # image not available
        ([], "fixtures/config1.yaml", "test-image-6", [image.ImageVerificationErrors.NOT_EXIST]),
        # image matches expectations from config
        (
            [
                {
                    "Name": "test-image-6",
                    "State": "available",
                    "ImageId": "ami-123",
                    "RootDeviceName": "/dev/sda1",
                    "RootDeviceType": "ebs",
                    "BootMode": "uefi-preferred",
                    "BlockDeviceMappings": [
                        {
                            "DeviceName": "/dev/sda1",
                            "Ebs": {
                                "DeleteOnTermination": True,
                                "VolumeType": "gp3",
                                "VolumeSize": 8,
                                "SnapshotId": "snap-123",
                            },
                        },
                    ],
                    "Tags": [
                        {"Key": "name", "Value": "foobar"},
                    ],
                }
            ],
            "fixtures/config1.yaml",
            "test-image-6",
            [],
        ),
    ],
)
def test_image__verify(image_found, config, config_image_name, expected_problems):
    """
    Test _verify() for a given image and configuration
    """
    with patch("boto3.client") as bclient_mock:
        instance = bclient_mock.return_value
        instance.describe_images.return_value = {"Images": image_found}
        instance.describe_snapshots.return_value = {"Snapshots": [{"State": "completed"}]}
        ctx = context.Context(curdir / config, None)
        img = image.Image(ctx, config_image_name)
        problems = img._verify("eu-central-1")
        assert problems == expected_problems
