import logging
from typing import List, Tuple

import boto3
from mypy_boto3_ec2.client import EC2Client

logger = logging.getLogger(__name__)


def _split_partition(val: str) -> Tuple[str, str]:
    """
    Split a string into partition and resource, separated by a colon. If no partition is given, assume "aws"
    :param val: the string to split
    :type val: str
    :return: the partition and the resource
    :rtype: Tuple[str, str]
    """

    # ARNs encode partition https://docs.aws.amazon.com/IAM/latest/UserGuide/reference-arns.html
    if val.startswith("arn:"):
        arn, partition, resource = val.split(":", maxsplit=2)
        # Return extracted partition, but keep full ARN intact
        return partition, val

    # Partition prefix
    if ":" in val and val.startswith("aws"):
        partition, resource = val.split(":", maxsplit=1)
        return partition, resource

    # if no partition is given, assume default commercial partition "aws"
    return "aws", val


def _get_regions(region_to_query: str, regions_allowlist: List[str]) -> List[str]:
    """
    Get a list of region names querying the `region_to_query` for all regions and
    then filtering by `regions_allowlist`.
    If no `regions_allowlist` is given, all queried regions are returned for the
    current partition.
    If `regions_allowlist` is given, all regions from that list are returned if
    the listed region exist in the current partition.
    Eg. `us-east-1` listed in `regions_allowlist` won't be returned if the current
    partition is `aws-cn`.
    :param region_to_query: region name of current partition
    :type region_to_query: str
    :praram regions_allowlist: list of regions in config file
    :type regions_allowlist: List[str]
    :return: list of regions names
    :rtype: List[str]
    """

    # get all available regions
    ec2client: EC2Client = boto3.client("ec2", region_name=region_to_query)
    resp = ec2client.describe_regions()
    ec2_regions_all = [r["RegionName"] for r in resp["Regions"]]

    if regions_allowlist:
        # filter out regions that are not available in the current partition
        regions_allowlist_set = set(regions_allowlist)
        ec2_regions_all_set = set(ec2_regions_all)
        regions = list(regions_allowlist_set.intersection(ec2_regions_all_set))
        diff = regions_allowlist_set.difference(ec2_regions_all_set)
        if diff:
            logger.warning(
                f"regions {diff} listed in regions allowlist are not available in the current partition."
                " Ignoring those."
            )
    else:
        regions = ec2_regions_all

    return regions
