import pytest

from awspub.common import _split_partition


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
