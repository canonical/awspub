from typing import Tuple


def _split_partition(val: str) -> Tuple[str, str]:
    """
    Split a string into partition and resource, separated by a colon. If no partition is given, assume "aws"
    :param val: the string to split
    :type val: str
    :return: the partition and the resource
    :rtype: Tuple[str, str]
    """
    if ":" in val:
        partition, resource = val.split(":")
    else:
        # if no partition is given, assume default commercial partition "aws"
        partition = "aws"
        resource = val
    return partition, resource
