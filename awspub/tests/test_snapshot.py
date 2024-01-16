import pathlib
from unittest.mock import MagicMock
import pytest

from awspub import context, snapshot


curdir = pathlib.Path(__file__).parent.resolve()


def test_snapshot__get_none_exist():
    """
    No snapshot exist - should return None
    """
    ctx = context.Context(curdir / "fixtures/config1.yaml", None)
    s = snapshot.Snapshot(ctx)
    client_mock = MagicMock()
    assert s._get(client_mock, "snapshot-name") is None
    client_mock.describe_snapshots.assert_called_with(
        Filters=[
            {"Name": "tag:Name", "Values": ["snapshot-name"]},
            {"Name": "status", "Values": ["pending", "completed"]},
        ]
    )


def test_snapshot__get_one_exist():
    """
    One snapshot exist with the same name - should return the snapshot id
    """
    ctx = context.Context(curdir / "fixtures/config1.yaml", None)
    s = snapshot.Snapshot(ctx)
    client_mock = MagicMock()
    client_mock.describe_snapshots = MagicMock(return_value={"Snapshots": [{"SnapshotId": "snap-1"}]})
    assert s._get(client_mock, "snapshot-name") == "snap-1"
    client_mock.describe_snapshots.assert_called_with(
        Filters=[
            {"Name": "tag:Name", "Values": ["snapshot-name"]},
            {"Name": "status", "Values": ["pending", "completed"]},
        ]
    )


def test_snapshot__get_multiple_exist():
    """
    Multiple snapshots exist - _get() should raise an Exception
    """
    ctx = context.Context(curdir / "fixtures/config1.yaml", None)
    s = snapshot.Snapshot(ctx)
    client_mock = MagicMock()
    client_mock.describe_snapshots = MagicMock(
        return_value={"Snapshots": [{"SnapshotId": "snap-1"}, {"SnapshotId": "snap-2"}]}
    )
    with pytest.raises(Exception):
        s._get(client_mock, "snapshot-name")
    client_mock.describe_snapshots.assert_called_with(
        Filters=[
            {"Name": "tag:Name", "Values": ["snapshot-name"]},
            {"Name": "status", "Values": ["pending", "completed"]},
        ]
    )
