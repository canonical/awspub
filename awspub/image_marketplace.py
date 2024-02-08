from mypy_boto3_marketplace_catalog import MarketplaceCatalogClient
import boto3
import logging
from typing import Dict, Any

from awspub.context import Context


logger = logging.getLogger(__name__)


class ImageMarketplace:
    """
    Handle AWS Marketplace API interaction
    """

    def __init__(self, context: Context, image_name: str):
        self._ctx: Context = context
        self._image_name: str = image_name
        # marketplace-catalog API is only available via us-east-1
        self._mpclient: MarketplaceCatalogClient = boto3.client("marketplace-catalog", region_name="us-east-1")

    @property
    def conf(self) -> Dict[str, Any]:
        """
        The marketplace configuration for the current image (based on "image_name") from context
        """
        return self._ctx.conf["images"][self._image_name]["marketplace"]

    def request_new_version(self, image_id: str):
        """
        Request a new Marketplace version for the given image Id
        :param image_id: an image Id (in the format 'ami-123')
        :type image_id: str
        """
        entity = self._mpclient.describe_entity(Catalog="AWSMarketplace", EntityId=self.conf["entity_id"])
        # check if the version already exists
        for version in entity["DetailsDocument"]["Versions"]:
            if version["VersionTitle"] == self.conf["version_title"]:
                logger.info(f"Marketplace version '{self.conf['version_title']}' already exists. Do nothing")
                return

        # version doesn't exist already - create a new one
        changeset = self._request_new_version_changeset(image_id)
        resp = self._mpclient.start_change_set(
            Catalog="AWSMarketplace",
            ChangeSet=changeset,
            ChangeSetName=f"New version request for {self.conf['version_title']}",
        )
        logger.info(
            f"new version '{self.conf['version_title']}' (image: {image_id}) for entity "
            f"{self.conf['entity_id']} requested (changeset-id: {resp['ChangeSetId']})"
        )

    def _request_new_version_changeset(self, image_id: str):
        """
        Create a changeset structure for a new AmiProduct version
        See https://docs.aws.amazon.com/marketplace-catalog/latest/api-reference/ami-products.html#ami-add-version
        :param image_id: an image Id (in the format 'ami-123')
        :type image_id: str
        :return: A changeset structure to request a new version
        :rtype: List[Dict[str, Any]]
        """
        return [
            {
                "ChangeType": "AddDeliveryOptions",
                "Entity": {
                    "Identifier": self.conf["entity_id"],
                    "Type": "AmiProduct@1.0",
                },
                "DetailsDocument": {
                    "Version": {
                        "VersionTitle": self.conf["version_title"],
                        "ReleaseNotes": self.conf["release_notes"],
                    },
                    "DeliveryOptions": [
                        {
                            "Details": {
                                "AmiDeliveryOptionDetails": {
                                    "AmiSource": {
                                        "AmiId": image_id,
                                        "AccessRoleArn": self.conf["access_role_arn"],
                                        "UserName": self.conf["user_name"],
                                        "OperatingSystemName": self.conf["os_name"],
                                        "OperatingSystemVersion": self.conf["os_version"],
                                    },
                                    "UsageInstructions": self.conf["usage_instructions"],
                                    "RecommendedInstanceType": self.conf["recommended_instance_type"],
                                    "SecurityGroups": [
                                        {
                                            "IpProtocol": sg["ip_protocol"],
                                            "IpRanges": [ipr for ipr in sg["ip_ranges"]],
                                            "FromPort": sg["from_port"],
                                            "ToPort": sg["to_port"],
                                        }
                                        for sg in self.conf["security_groups"]
                                    ],
                                }
                            }
                        }
                    ],
                },
            }
        ]
