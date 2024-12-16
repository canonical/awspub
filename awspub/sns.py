"""
Methods used to handle notifications for AWS using SNS
"""

import json
import logging
from typing import Any, Dict, List

import boto3
from botocore.exceptions import ClientError
from mypy_boto3_sns.client import SNSClient
from mypy_boto3_sts.client import STSClient

from awspub.common import _get_regions
from awspub.context import Context
from awspub.exceptions import AWSAuthorizationException, AWSNotificationException
from awspub.s3 import S3

logger = logging.getLogger(__name__)


class SNSNotification(object):
    """
    A data object that contains validation logic and
    structuring rules for SNS notification JSON
    """

    def __init__(self, context: Context, image_name: str):
        """
        Construct a message and verify that it is valid
        """
        self._ctx: Context = context
        self._image_name: str = image_name
        self._s3: S3 = S3(context)

    @property
    def conf(self) -> List[Dict[str, Any]]:
        """
        The sns configuration for the current image (based on "image_name") from context
        """
        return self._ctx.conf["images"][self._image_name]["sns"]

    def _sns_regions(self, topic_config: Dict[Any, Any]) -> List[str]:
        """
        Get the sns regions. Either configured in the sns configuration
        or all available regions.
        If a region is listed that is not available in the currently used partition,
        that region will be ignored (eg. having us-east-1 configured but running in the aws-cn
        partition doesn't include us-east-1 here).
        """

        regions_configured = topic_config["regions"] if "regions" in topic_config else []
        sns_regions = _get_regions(self._s3.bucket_region, regions_configured)

        return sns_regions

    def _get_topic_arn(self, topic_name: str, region_name: str) -> str:
        """
        Calculate topic ARN based on partition, region, account and topic name
        :param topic_name: Name of topic
        :type topic_name: str
        :param region_name: name of region
        :type region_name: str
        :return: return topic ARN
        :rtype: str
        """

        stsclient: STSClient = boto3.client("sts", region_name=region_name)
        resp = stsclient.get_caller_identity()

        account = resp["Account"]
        # resp["Arn"] has string format "arn:partition:iam::accountnumber:user/iam_role"
        partition = resp["Arn"].rsplit(":")[1]

        return f"arn:{partition}:sns:{region_name}:{account}:{topic_name}"

    def publish(self) -> None:
        """
        send notification to subscribers
        """

        for topic in self.conf:
            for topic_name, topic_config in topic.items():
                for region_name in self._sns_regions(topic_config):
                    snsclient: SNSClient = boto3.client("sns", region_name=region_name)
                    try:
                        snsclient.publish(
                            TopicArn=self._get_topic_arn(topic_name, region_name),
                            Subject=topic_config["subject"],
                            Message=json.dumps(topic_config["message"]),
                            MessageStructure="json",
                        )
                    except ClientError as e:
                        exception_code: str = e.response["Error"]["Code"]
                        if exception_code == "AuthorizationError":
                            raise AWSAuthorizationException(
                                "Profile does not have a permission to send the SNS notification."
                                " Please review the policy."
                            )
                        else:
                            raise AWSNotificationException(str(e))
                    logger.info(
                        f"The SNS notification {topic_config['subject']}"
                        f" for the topic {topic_name} in {region_name} has been sent."
                    )
