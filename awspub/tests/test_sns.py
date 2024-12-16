import pathlib
from unittest.mock import patch

import botocore.exceptions
import pytest

from awspub import context, exceptions, sns

curdir = pathlib.Path(__file__).parent.resolve()


@pytest.mark.parametrize(
    "imagename,called_sns_publish, publish_call_count",
    [
        ("test-image-10", True, 1),
        ("test-image-11", True, 2),
        ("test-image-12", True, 2),
    ],
)
def test_sns_publish(imagename, called_sns_publish, publish_call_count):
    """
    Test the send_notification logic
    """
    with patch("boto3.client") as bclient_mock:
        instance = bclient_mock.return_value
        ctx = context.Context(curdir / "fixtures/config1.yaml", None)
        instance.describe_regions.return_value = {
            "Regions": [{"RegionName": "eu-central-1"}, {"RegionName": "us-east-1"}]
        }
        instance.list_buckets.return_value = {"Buckets": [{"Name": "bucket1"}]}

        sns.SNSNotification(ctx, imagename).publish()
        assert instance.publish.called == called_sns_publish
        assert instance.publish.call_count == publish_call_count


@pytest.mark.parametrize(
    "imagename",
    [
        ("test-image-10"),
        ("test-image-11"),
        ("test-image-12"),
    ],
)
def test_sns_publish_fail_with_invalid_topic(imagename):
    """
    Test the send_notification logic
    """
    with patch("boto3.client") as bclient_mock:
        instance = bclient_mock.return_value
        ctx = context.Context(curdir / "fixtures/config1.yaml", None)
        instance.describe_regions.return_value = {
            "Regions": [{"RegionName": "eu-central-1"}, {"RegionName": "us-east-1"}]
        }
        instance.list_buckets.return_value = {"Buckets": [{"Name": "bucket1"}]}

        # topic1 is invalid topic
        def side_effect(*args, **kwargs):
            topic_arn = kwargs.get("TopicArn")
            if "topic1" in topic_arn and "us-east-1" in topic_arn:
                error_reponse = {
                    "Error": {
                        "Code": "NotFoundException",
                        "Message": "An error occurred (NotFound) when calling the Publish operation: "
                        "Topic does not exist.",
                    }
                }
                raise botocore.exceptions.ClientError(error_reponse, "")

        instance.publish.side_effect = side_effect

        with pytest.raises(exceptions.AWSNotificationException):
            sns.SNSNotification(ctx, imagename).publish()


@pytest.mark.parametrize(
    "imagename",
    [
        ("test-image-10"),
        ("test-image-11"),
        ("test-image-12"),
    ],
)
def test_sns_publish_fail_with_unauthorized_user(imagename):
    """
    Test the send_notification logic
    """
    with patch("boto3.client") as bclient_mock:
        instance = bclient_mock.return_value
        ctx = context.Context(curdir / "fixtures/config1.yaml", None)
        instance.describe_regions.return_value = {
            "Regions": [{"RegionName": "eu-central-1"}, {"RegionName": "us-east-1"}]
        }
        instance.list_buckets.return_value = {"Buckets": [{"Name": "bucket1"}]}

        error_reponse = {
            "Error": {
                "Code": "AuthorizationError",
                "Message": "User are not authorized perform SNS Notification service",
            }
        }
        instance.publish.side_effect = botocore.exceptions.ClientError(error_reponse, "")

        with pytest.raises(exceptions.AWSAuthorizationException):
            sns.SNSNotification(ctx, imagename).publish()


@pytest.mark.parametrize(
    "imagename, partition, regions_in_partition, expected",
    [
        (
            "test-image-10",
            "aws-cn",
            ["cn-north1", "cn-northwest-1"],
            [],
        ),
        (
            "test-image-11",
            "aws",
            ["us-east-1", "eu-central-1"],
            [
                "arn:aws:sns:us-east-1:1234:topic1",
                "arn:aws:sns:eu-central-1:1234:topic2",
            ],
        ),
        (
            "test-image-12",
            "aws",
            ["us-east-1", "eu-central-1"],
            [
                "arn:aws:sns:us-east-1:1234:topic1",
                "arn:aws:sns:eu-central-1:1234:topic1",
            ],
        ),
    ],
)
def test_sns__get_topic_arn(imagename, partition, regions_in_partition, expected):
    """
    Test the send_notification logic
    """
    with patch("boto3.client") as bclient_mock:
        instance = bclient_mock.return_value
        ctx = context.Context(curdir / "fixtures/config1.yaml", None)
        sns_conf = ctx.conf["images"][imagename]["sns"]
        instance.describe_regions.return_value = {"Regions": [{"RegionName": r} for r in regions_in_partition]}
        instance.list_buckets.return_value = {"Buckets": [{"Name": "bucket1"}]}

        instance.get_caller_identity.return_value = {"Account": "1234", "Arn": f"arn:{partition}:iam::1234:user/test"}

        topic_arns = []
        for topic in sns_conf:
            for topic_name, topic_conf in topic.items():
                sns_regions = sns.SNSNotification(ctx, imagename)._sns_regions(topic_conf)
                for region in sns_regions:
                    res_arn = sns.SNSNotification(ctx, imagename)._get_topic_arn(topic_name, region)
                    topic_arns.append(res_arn)

        assert topic_arns == expected


@pytest.mark.parametrize(
    "imagename,regions_in_partition,regions_expected",
    [
        ("test-image-10", ["us-east-1", "eu-west-1"], {"topic1": ["us-east-1"]}),
        (
            "test-image-11",
            ["us-east-1", "eu-west-1"],
            {"topic1": ["us-east-1"], "topic2": []},
        ),
        ("test-image-12", ["eu-northwest-1", "ap-southeast-1"], {"topic1": ["eu-northwest-1", "ap-southeast-1"]}),
    ],
)
def test_sns_regions(imagename, regions_in_partition, regions_expected):
    """
    Test the regions for a given image
    """
    with patch("boto3.client") as bclient_mock:
        instance = bclient_mock.return_value
        instance.describe_regions.return_value = {"Regions": [{"RegionName": r} for r in regions_in_partition]}
        ctx = context.Context(curdir / "fixtures/config1.yaml", None)
        sns_conf = ctx.conf["images"][imagename]["sns"]
        instance.list_buckets.return_value = {"Buckets": [{"Name": "bucket1"}]}

        sns_regions = {}
        for topic in sns_conf:
            for topic_name, topic_conf in topic.items():
                sns_regions[topic_name] = sns.SNSNotification(ctx, imagename)._sns_regions(topic_conf)

        assert sns_regions == regions_expected
