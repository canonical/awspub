class MultipleSnapshotsException(Exception):
    pass


class MultipleImportSnapshotTasksException(Exception):
    pass


class MultipleImagesException(Exception):
    pass


class BucketDoesNotExistException(Exception):
    def __init__(self, bucket_name: str, *args, **kwargs):
        msg = f"The bucket named '{bucket_name}' does not exist. You will need to create the bucket before proceeding."
        super().__init__(msg, *args, **kwargs)
