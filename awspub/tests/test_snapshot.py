import pathlib
from unittest.mock import ANY, MagicMock, patch

import pytest

from awspub import context, exceptions, snapshot

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


@patch("awspub.snapshot.EBS")
def test_snapshot_create_direct_new_snapshot(ebs_cls_mock):
    """
    In direct creation mode, create() must start a new snapshot via the EBS direct APIs,
    stream its blocks, complete it and never call import_snapshot
    """
    ctx = context.Context(curdir / "fixtures/config-direct.yaml", None)
    s = snapshot.Snapshot(ctx)
    client_mock = MagicMock()
    client_mock.describe_snapshots = MagicMock(return_value={"Snapshots": []})
    client_mock.describe_import_snapshot_tasks = MagicMock(return_value={"ImportSnapshotTasks": []})
    instance = ebs_cls_mock.return_value
    instance.start_snapshot = MagicMock(return_value="snap-direct-1")

    snap_id = s.create(client_mock, "snapshot-name")

    assert snap_id == "snap-direct-1"
    client_mock.import_snapshot.assert_not_called()
    ebs_cls_mock.assert_called_once_with(ctx, client_mock.meta.region_name)
    kwargs = instance.start_snapshot.call_args.kwargs
    # the fixture raw is 1 MiB: volume size must be rounded up to 1 GiB
    assert kwargs["volume_size_gib"] == 1
    assert {"Key": "Name", "Value": "snapshot-name"} in kwargs["tags"]
    instance.write_blocks.assert_called_once_with("snap-direct-1", ANY)
    instance.complete_snapshot.assert_called_once_with("snap-direct-1", changed_blocks_count=ANY)
    client_mock.get_waiter.assert_called_with("snapshot_completed")


@patch("awspub.snapshot.EBS")
def test_snapshot_create_direct_existing_completed(ebs_cls_mock):
    """
    In direct creation mode, a completed snapshot with the given name must be reused as-is
    """
    ctx = context.Context(curdir / "fixtures/config-direct.yaml", None)
    s = snapshot.Snapshot(ctx)
    client_mock = MagicMock()
    client_mock.describe_snapshots = MagicMock(
        return_value={"Snapshots": [{"SnapshotId": "snap-1", "State": "completed"}]}
    )

    snap_id = s.create(client_mock, "snapshot-name")

    assert snap_id == "snap-1"
    ebs_cls_mock.assert_not_called()
    client_mock.import_snapshot.assert_not_called()


@patch("awspub.snapshot.EBS")
def test_snapshot_create_direct_pending_with_import_task_raises(ebs_cls_mock):
    """
    In direct creation mode, a pending snapshot with an active VM import task for the same
    name must raise instead of writing to it concurrently
    """
    ctx = context.Context(curdir / "fixtures/config-direct.yaml", None)
    s = snapshot.Snapshot(ctx)
    client_mock = MagicMock()
    client_mock.describe_snapshots = MagicMock(
        return_value={"Snapshots": [{"SnapshotId": "snap-2", "State": "pending"}]}
    )
    client_mock.describe_import_snapshot_tasks = MagicMock(
        return_value={
            "ImportSnapshotTasks": [
                {
                    "ImportTaskId": "import-snap-1",
                    "SnapshotTaskDetail": {"SnapshotId": "snap-2", "Status": "active"},
                }
            ]
        }
    )

    with pytest.raises(exceptions.ImportSnapshotTaskConflictException):
        s.create(client_mock, "snapshot-name")

    ebs_cls_mock.assert_not_called()


@patch("awspub.snapshot.EBS")
def test_snapshot_create_direct_pending_reused(ebs_cls_mock):
    """
    In direct creation mode, a pending snapshot without an active import task must be
    finished: blocks are written to it and it gets completed without starting a new snapshot
    """
    ctx = context.Context(curdir / "fixtures/config-direct.yaml", None)
    s = snapshot.Snapshot(ctx)
    client_mock = MagicMock()
    client_mock.describe_snapshots = MagicMock(
        return_value={"Snapshots": [{"SnapshotId": "snap-2", "State": "pending"}]}
    )
    client_mock.describe_import_snapshot_tasks = MagicMock(return_value={"ImportSnapshotTasks": []})
    instance = ebs_cls_mock.return_value

    snap_id = s.create(client_mock, "snapshot-name")

    assert snap_id == "snap-2"
    instance.start_snapshot.assert_not_called()
    instance.write_blocks.assert_called_once_with("snap-2", ANY)
    instance.complete_snapshot.assert_called_once_with("snap-2", changed_blocks_count=ANY)


@patch("boto3.client")
def test_snapshot_copy_same_region_uses_known_source_id(bclient_mock):
    """
    copy() for the source region must use the known source snapshot id directly instead of
    a name based lookup - tag based lookups can lag behind directly after a snapshot got
    created (which is the normal case with snapshot creation 'direct')
    """
    ctx = context.Context(curdir / "fixtures/config-direct.yaml", None)
    s = snapshot.Snapshot(ctx)
    instance = bclient_mock.return_value
    instance.describe_snapshots.side_effect = RuntimeError("tag lookup is unavailable")

    snapshot_ids = s.copy("snapshot-name", "us-east-1", ["us-east-1"], source_snapshot_id="snap-42")

    assert snapshot_ids == {"us-east-1": "snap-42"}
    instance.copy_snapshot.assert_not_called()
    instance.get_waiter.assert_called_with("snapshot_completed")
