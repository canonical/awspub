from unittest.mock import patch

import pytest

from awspub.common import _get_regions, _split_partition


@pytest.mark.parametrize(
    "input,expected_output",
    [
        ("123456789123", ("aws", "123456789123")),
        ("aws:123456789123", ("aws", "123456789123")),
        ("aws-cn:123456789123", ("aws-cn", "123456789123")),
        ("aws-us-gov:123456789123", ("aws-us-gov", "123456789123")),
    ],
)
def test_common__split_partition(input, expected_output):
    assert _split_partition(input) == expected_output


@pytest.mark.parametrize(
    "regions_in_partition,configured_regions,expected_output",
    [
        (["region-1", "region-2"], ["region-1", "region-3"], ["region-1"]),
        (["region-1", "region-2", "region-3"], ["region-4", "region-5"], []),
        (["region-1", "region-2"], [], ["region-1", "region-2"]),
    ],
)
def test_common__get_regions(regions_in_partition, configured_regions, expected_output):
    with patch("boto3.client") as bclient_mock:
        instance = bclient_mock.return_value
        instance.describe_regions.return_value = {"Regions": [{"RegionName": r} for r in regions_in_partition]}

        assert _get_regions("", configured_regions) == expected_output
