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
        ("test-image-11", True, 4),
    ],
)
def test_sns_publish(imagename, called_sns_publish, publish_call_count):
    """
    Test the send_notification logic
    """
    with patch("boto3.client") as bclient_mock:
        instance = bclient_mock.return_value
        ctx = context.Context(curdir / "fixtures/config1.yaml", None)
        image_conf = ctx.conf["images"][imagename]

        for region in image_conf["regions"]:
            sns.SNSNotification(ctx, imagename, region).publish()

        assert instance.publish.called == called_sns_publish
        assert instance.publish.call_count == publish_call_count


@pytest.mark.parametrize(
    "imagename",
    [
        ("test-image-10"),
        ("test-image-11"),
    ],
)
def test_sns_publish_fail_with_invalid_topic(imagename):
    """
    Test the send_notification logic
    """
    with patch("boto3.client") as bclient_mock:
        instance = bclient_mock.return_value
        ctx = context.Context(curdir / "fixtures/config1.yaml", None)
        image_conf = ctx.conf["images"][imagename]

        # topic1 is invalid topic
        def side_effect(*args, **kwargs):
            topic_arn = kwargs.get("TopicArn")
            if "topic1" in topic_arn:
                error_reponse = {
                    "Error": {
                        "Code": "NotFoundException",
                        "Message": "An error occurred (NotFound) when calling the Publish operation: "
                        "Topic does not exist.",
                    }
                }
                raise botocore.exceptions.ClientError(error_reponse, "")

        instance.publish.side_effect = side_effect

        for region in image_conf["regions"]:
            with pytest.raises(exceptions.AWSNotificationException):
                sns.SNSNotification(ctx, imagename, region).publish()


@pytest.mark.parametrize(
    "imagename",
    [
        ("test-image-10"),
        ("test-image-11"),
    ],
)
def test_sns_publish_fail_with_unauthorized_user(imagename):
    """
    Test the send_notification logic
    """
    with patch("boto3.client") as bclient_mock:
        instance = bclient_mock.return_value
        ctx = context.Context(curdir / "fixtures/config1.yaml", None)
        image_conf = ctx.conf["images"][imagename]

        error_reponse = {
            "Error": {
                "Code": "AuthorizationError",
                "Message": "User are not authorized perform SNS Notification service",
            }
        }
        instance.publish.side_effect = botocore.exceptions.ClientError(error_reponse, "")

        for region in image_conf["regions"]:
            with pytest.raises(exceptions.AWSAuthorizationException):
                sns.SNSNotification(ctx, imagename, region).publish()


@pytest.mark.parametrize(
    "imagename, partition, expected",
    [
        (
            "test-image-10",
            "aws-cn",
            [
                "arn:aws-cn:sns:us-east-1:1234:topic1",
            ],
        ),
        (
            "test-image-11",
            "aws",
            [
                "arn:aws:sns:us-east-1:1234:topic1",
                "arn:aws:sns:us-east-1:1234:topic2",
                "arn:aws:sns:eu-central-1:1234:topic1",
                "arn:aws:sns:eu-central-1:1234:topic2",
            ],
        ),
    ],
)
def test_sns__get_topic_arn(imagename, partition, expected):
    """
    Test the send_notification logic
    """
    with patch("boto3.client") as bclient_mock:
        instance = bclient_mock.return_value
        ctx = context.Context(curdir / "fixtures/config1.yaml", None)
        image_conf = ctx.conf["images"][imagename]

        instance.get_caller_identity.return_value = {"Account": "1234", "Arn": f"arn:{partition}:iam::1234:user/test"}

        topic_arns = []
        for region in image_conf["regions"]:
            for topic in image_conf["sns"]:
                topic_name = next(iter(topic))
                res_arn = sns.SNSNotification(ctx, imagename, region)._get_topic_arn(topic_name)
                topic_arns.append(res_arn)

        assert topic_arns == expected
