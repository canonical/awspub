import logging
from typing import Dict, List, Optional

import boto3
from mypy_boto3_ec2.client import EC2Client

from awspub import exceptions
from awspub.context import Context

logger = logging.getLogger(__name__)


class Snapshot:
    """
    Handle EC2 Snapshot API interaction
    """

    def __init__(self, context: Context):
        self._ctx: Context = context

    def _get(self, ec2client: EC2Client, snapshot_name: str) -> Optional[str]:
        """
        Get the snapshot id for the given name or None

        :param ec2client: EC2 client for a specific region
        :type ec2client: EC2Client
        :param snapshot_name: the Snapshot name
        :type snapshot_name: str
        :return: Either None or a snapshot-id
        :rtype: Optional[str]
        """
        resp = ec2client.describe_snapshots(
            Filters=[
                {
                    "Name": "tag:Name",
                    "Values": [
                        snapshot_name,
                    ],
                },
                {
                    "Name": "status",
                    "Values": [
                        "pending",
                        "completed",
                    ],
                },
            ],
            OwnerIds=["self"],
        )
        if len(resp.get("Snapshots", [])) == 1:
            return resp["Snapshots"][0]["SnapshotId"]
        elif len(resp.get("Snapshots", [])) == 0:
            return None
        else:
            raise exceptions.MultipleSnapshotsException(
                f"Found {len(resp.get('Snapshots', []))} snapshots with "
                f"name '{snapshot_name}' in region {ec2client.meta.region_name}"
            )

    def _get_import_snapshot_task(self, ec2client: EC2Client, snapshot_name: str) -> Optional[str]:
        """
        Get a import snapshot task for the given name

        :param ec2client: EC2 client for a specific region
        :type ec2client: EC2Client
        :param snapshot_name: the Snapshot name
        :type snapshot_name: str
        :return: Either None or a import-snapshot-task-id
        :rtype: Optional[str]
        """
        resp = ec2client.describe_import_snapshot_tasks(
            Filters=[
                {
                    "Name": "tag:Name",
                    "Values": [
                        snapshot_name,
                    ],
                }
            ]
        )
        # API doesn't support filters by status so filter here
        tasks: List = resp.get("ImportSnapshotTasks", [])
        # we already know here that the snapshot does not exist (checked in create() before calling this
        # function). so ignore "deleted" or "completed" tasks here
        # it might happen (for whatever reason) that a task got completed but the snapshot got deleted
        # afterwards. In that case a "completed" task for the given snapshot_name exists but
        # that doesn't help so ignore it
        tasks = [t for t in tasks if t["SnapshotTaskDetail"]["Status"] not in ["deleted", "completed"]]
        if len(tasks) == 1:
            return tasks[0]["ImportTaskId"]
        elif len(tasks) == 0:
            return None
        else:
            raise exceptions.MultipleImportSnapshotTasksException(
                f"Found {len(tasks)} import snapshot tasks with "
                f"name '{snapshot_name}' in region {ec2client.meta.region_name}"
            )

    def create(self, ec2client: EC2Client, snapshot_name: str) -> str:
        """
        Create a EC2 snapshot with the given name
        If the snapshot already exists, just return the snapshot-id for the existing snapshot.

        :param ec2client: EC2 client for a specific region
        :type ec2client: EC2Client
        :param snapshot_name: the Snapshot name
        :type snapshot_name: str
        :return: a snapshot-id
        :rtype: str
        """
        # does a snapshot with the given name already exists?
        snap_id: Optional[str] = self._get(ec2client, snapshot_name)
        if snap_id:
            logger.info(f"snapshot with name '{snapshot_name}' already exists in region {ec2client.meta.region_name}")
            return snap_id

        logger.info(
            f"Create snapshot from bucket '{self._ctx.conf['s3']['bucket_name']}' "
            f"for '{snapshot_name}' in region  {ec2client.meta.region_name}"
        )

        # extend tags
        tags = self._ctx.tags
        tags.append({"Key": "Name", "Value": snapshot_name})

        # does a import snapshot task with the given name already exist?
        import_snapshot_task_id: Optional[str] = self._get_import_snapshot_task(ec2client, snapshot_name)
        if import_snapshot_task_id:
            logger.info(
                f"import snapshot task ({import_snapshot_task_id}) with "
                f"name '{snapshot_name}' exists in region {ec2client.meta.region_name}"
            )
        else:
            resp = ec2client.import_snapshot(
                Description="Import ",
                DiskContainer={
                    "Description": "",
                    "Format": "vmdk",
                    "UserBucket": {
                        "S3Bucket": self._ctx.conf["s3"]["bucket_name"],
                        "S3Key": self._ctx.source_sha256,
                    },
                },
                TagSpecifications=[
                    {"ResourceType": "import-snapshot-task", "Tags": tags},
                ],
            )
            import_snapshot_task_id = resp["ImportTaskId"]

        logger.info(
            f"Waiting for snapshot import task (id: {import_snapshot_task_id}) "
            f"in region {ec2client.meta.region_name} ..."
        )

        waiter_import = ec2client.get_waiter("snapshot_imported")
        waiter_import.wait(ImportTaskIds=[import_snapshot_task_id], WaiterConfig={"Delay": 30, "MaxAttempts": 90})

        task_details = ec2client.describe_import_snapshot_tasks(ImportTaskIds=[import_snapshot_task_id])
        snapshot_id = task_details["ImportSnapshotTasks"][0]["SnapshotTaskDetail"]["SnapshotId"]

        # create tags before waiting for completion so the tags are already there
        ec2client.create_tags(Resources=[snapshot_id], Tags=tags)

        waiter_completed = ec2client.get_waiter("snapshot_completed")
        waiter_completed.wait(SnapshotIds=[snapshot_id], WaiterConfig={"Delay": 30, "MaxAttempts": 60})

        logger.info(f"Snapshot import as '{snapshot_id}' in region {ec2client.meta.region_name} done")
        return snapshot_id

    def _copy(self, snapshot_name: str, source_region: str, destination_region: str) -> str:
        """
        Copy a EC2 snapshot for the given context to the destination region
        NOTE: we don't wait for the snapshot to complete here!

        :param snapshot_name: the Snapshot name to copy
        :type snapshot_name: str
        :param source_region: a region to copy the snapshot from
        :type source_region: str
        :param destination_region: a region to copy the snapshot to
        :type destionation_region: str

        :return: the existing or created snapshot-id
        :rtype: str
        """

        # does the snapshot with that name already exist in the destination region?
        ec2client_dest: EC2Client = boto3.client("ec2", region_name=destination_region)
        snapshot_id: Optional[str] = self._get(ec2client_dest, snapshot_name)
        if snapshot_id:
            logger.info(
                f"snapshot with name '{snapshot_name}' already "
                f"exists ({snapshot_id}) in destination region {ec2client_dest.meta.region_name}"
            )
            return snapshot_id

        ec2client_source: EC2Client = boto3.client("ec2", region_name=source_region)
        source_snapshot_id: Optional[str] = self._get(ec2client_source, snapshot_name)
        if not source_snapshot_id:
            raise ValueError(
                f"Can not find source snapshot with name '{snapshot_name}' "
                f"in region {ec2client_source.meta.region_name}"
            )

        logger.info(f"Copy snapshot {source_snapshot_id} from " f"{source_region} to {destination_region}")
        # extend tags
        tags = self._ctx.tags
        tags.append({"Key": "Name", "Value": snapshot_name})
        resp = ec2client_dest.copy_snapshot(
            SourceRegion=source_region,
            SourceSnapshotId=source_snapshot_id,
            TagSpecifications=[{"ResourceType": "snapshot", "Tags": tags}],
        )

        # note: we don't wait for the snapshot to complete here!
        return resp["SnapshotId"]

    def copy(self, snapshot_name: str, source_region: str, destination_regions: List[str]) -> Dict[str, str]:
        """
        Copy a snapshot to multiple regions

        :param snapshot_name: the Snapshot name to copy
        :type snapshot_name: str
        :param source_region: a region to copy the snapshot from
        :type source_region: str
        :param destination_regions: a list of regions to copy the snaphot to
        :type destionation_regions: List[str]
        :return: a dict with region/snapshot-id mapping for the newly copied snapshots
        :rtype: Dict[str, str] where the key is a region name and the value a snapshot-id
        """
        snapshot_ids: Dict[str, str] = dict()
        for destination_region in destination_regions:
            snapshot_ids[destination_region] = self._copy(snapshot_name, source_region, destination_region)

        logger.info(f"Waiting for {len(snapshot_ids)} snapshots to appear in the destination regions ...")
        for destination_region, snapshot_id in snapshot_ids.items():
            ec2client_dest = boto3.client("ec2", region_name=destination_region)
            waiter = ec2client_dest.get_waiter("snapshot_completed")
            logger.info(f"Waiting for {snapshot_id} in {ec2client_dest.meta.region_name} to complete ...")
            waiter.wait(SnapshotIds=[snapshot_id], WaiterConfig={"Delay": 30, "MaxAttempts": 90})

        return snapshot_ids
