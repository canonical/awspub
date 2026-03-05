import pathlib
from unittest.mock import MagicMock, patch

import botocore.exceptions
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


def test_snapshot_copy_success():
    """
    copy() succeeds for all destination regions — returns region→snapshot_id mapping
    """
    ctx = context.Context(curdir / "fixtures/config1.yaml", None)
    s = snapshot.Snapshot(ctx)

    waiter_mock = MagicMock()
    ec2client_mock = MagicMock()
    ec2client_mock.get_waiter.return_value = waiter_mock

    with patch.object(s, "_copy", return_value="snap-abc") as copy_mock, patch(
        "boto3.client", return_value=ec2client_mock
    ):
        result = s.copy("snap-name", "us-east-1", ["eu-west-1", "ap-southeast-1"])

    assert result == {"eu-west-1": "snap-abc", "ap-southeast-1": "snap-abc"}
    assert copy_mock.call_count == 2
    waiter_mock.wait.assert_called()


def test_snapshot_copy_region_error_raises():
    """
    copy() with allow_partial_region=False raises when _copy() fails for a region
    """
    ctx = context.Context(curdir / "fixtures/config1.yaml", None)
    s = snapshot.Snapshot(ctx)

    exc = botocore.exceptions.ClientError(
        {"Error": {"Code": "RequestLimitExceeded", "Message": "throttled"}}, "CopySnapshot"
    )

    with patch.object(s, "_copy", side_effect=exc), patch("boto3.client", return_value=MagicMock()):
        with pytest.raises(botocore.exceptions.ClientError):
            s.copy("snap-name", "us-east-1", ["eu-west-1"], allow_partial_region=False)


def test_snapshot_copy_region_error_partial_allowed():
    """
    copy() with allow_partial_region=True skips failed regions and returns only successful ones
    """
    ctx = context.Context(curdir / "fixtures/config1.yaml", None)
    s = snapshot.Snapshot(ctx)

    exc = botocore.exceptions.ClientError(
        {"Error": {"Code": "RequestLimitExceeded", "Message": "throttled"}}, "CopySnapshot"
    )

    def copy_side_effect(snap_name, src, dst):
        if dst == "me-central-1":
            raise exc
        return "snap-abc"

    waiter_mock = MagicMock()
    ec2client_mock = MagicMock()
    ec2client_mock.get_waiter.return_value = waiter_mock

    with patch.object(s, "_copy", side_effect=copy_side_effect), patch("boto3.client", return_value=ec2client_mock):
        result = s.copy("snap-name", "us-east-1", ["eu-west-1", "me-central-1"], allow_partial_region=True)

    assert result == {"eu-west-1": "snap-abc"}


def test_snapshot_copy_waiter_error_partial_allowed():
    """
    copy() with allow_partial_region=True skips regions where the waiter fails
    """
    ctx = context.Context(curdir / "fixtures/config1.yaml", None)
    s = snapshot.Snapshot(ctx)

    exc = botocore.exceptions.WaiterError("snapshot_completed", "failed", None)

    waiter_mock = MagicMock()
    waiter_mock.wait.side_effect = exc
    ec2client_mock = MagicMock()
    ec2client_mock.get_waiter.return_value = waiter_mock

    with patch.object(s, "_copy", return_value="snap-abc"), patch("boto3.client", return_value=ec2client_mock):
        result = s.copy("snap-name", "us-east-1", ["eu-west-1"], allow_partial_region=True)

    assert result == {}
