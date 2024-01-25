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
        ],
        OwnerIds=["self"],
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
        ],
        OwnerIds=["self"],
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
        ],
        OwnerIds=["self"],
    )


def test_snapshot__get_import_snapshot_task_completed():
    """
    Test the Snapshot._get_import_snapshot_task() method
    """
    ctx = context.Context(curdir / "fixtures/config1.yaml", None)
    s = snapshot.Snapshot(ctx)
    client_mock = MagicMock()
    client_mock.describe_import_snapshot_tasks = MagicMock(
        return_value={
            "ImportSnapshotTasks": [
                {
                    "ImportTaskId": "import-snap-08b79d7b5d382d56b",
                    "SnapshotTaskDetail": {
                        "SnapshotId": "snap-0e0f3407a1b541c40",
                        "Status": "completed",
                    },
                    "Tags": [
                        {"Key": "Name", "Value": "021abb3f2338b5e57b5d870816565429659bc70769d71c486234ad60fe6aec67"},
                    ],
                }
            ],
        }
    )
    assert (
        s._get_import_snapshot_task(client_mock, "021abb3f2338b5e57b5d870816565429659bc70769d71c486234ad60fe6aec67")
        is None
    )


def test_snapshot__get_import_snapshot_task_active():
    """
    Test the Snapshot._get_import_snapshot_task() method
    """
    ctx = context.Context(curdir / "fixtures/config1.yaml", None)
    s = snapshot.Snapshot(ctx)
    client_mock = MagicMock()
    client_mock.describe_import_snapshot_tasks = MagicMock(
        return_value={
            "ImportSnapshotTasks": [
                {
                    "ImportTaskId": "import-snap-08b79d7b5d382d56b",
                    "SnapshotTaskDetail": {
                        "SnapshotId": "snap-0e0f3407a1b541c40",
                        "Status": "active",
                    },
                    "Tags": [
                        {"Key": "Name", "Value": "021abb3f2338b5e57b5d870816565429659bc70769d71c486234ad60fe6aec67"},
                    ],
                }
            ],
        }
    )
    assert (
        s._get_import_snapshot_task(client_mock, "021abb3f2338b5e57b5d870816565429659bc70769d71c486234ad60fe6aec67")
        == "import-snap-08b79d7b5d382d56b"
    )
