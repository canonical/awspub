import os
import threading
import boto3
from boto3.s3.transfer import TransferConfig
import base64
import logging
import hashlib
from awspub.context import Context


# chunk size is required for calculating the checksums
MULTIPART_CHUNK_SIZE = 8 * 1024 * 1024


logger = logging.getLogger(__name__)


class _UploadFileProgress:
    """
    Helper class to log progress on S3 uploads
    """

    def __init__(self, file_path):
        self._file_path = file_path
        self._file_size = os.path.getsize(self._file_path)
        self._file_size_seen = 0
        self._logged = []
        self._lock = threading.Lock()

    def __call__(self, bytes_seen):
        with self._lock:
            self._file_size_seen += bytes_seen
            percentage = round((self._file_size_seen / self._file_size) * 100, 0)
            if percentage > 0.0 and percentage % 10 == 0 and percentage not in self._logged:
                self._logged.append(percentage)
                logger.info(f"uploaded {percentage} % ({self._file_size_seen} of {self._file_size} bytes)")


class S3:
    """
    Handle S3 API interaction
    """

    def __init__(self, context: Context):
        """
        :param context:
        "type context: awspub.context.Context
        """
        self._ctx: Context = context
        self._s3client = boto3.client("s3", region_name=self.bucket_region)

    @property
    def bucket_region(self):
        return self._ctx.conf["s3"]["bucket_region"]

    @property
    def bucket_name(self):
        return self._ctx.conf["s3"]["bucket_name"]

    def __repr__(self):
        return (
            f"<{self.__class__} bucket:'{self.bucket_name}' "
            f"region:'{self.bucket_region} key:{self._ctx.source_sha256}'>"
        )

    def _multipart_sha256sum(self, file_path: str) -> str:
        """
        Calculate the sha256 checksum like AWS does it (in a multipart upload) per chunk
        See https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity.html#large-object-checksums

        :param file_path: the path to the local file to upload
        :type file_path: str
        """
        sha256_list = []
        count = 0
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(MULTIPART_CHUNK_SIZE), b""):
                sha256_list.append(hashlib.sha256(chunk))
                count += 1

        sha256_list_digest_concatenated = b"".join([s.digest() for s in sha256_list])
        sha256_b64 = base64.b64encode(hashlib.sha256(sha256_list_digest_concatenated).digest())
        return f"{sha256_b64.decode('ascii')}-{count}"

    def _bucket_exists(self) -> bool:
        """
        Check if the S3 bucket from context already exists

        :return: True if the bucket already exists, otherwise False
        :rtype: bool
        """
        resp = self._s3client.list_buckets()
        return self.bucket_name in [b["Name"] for b in resp["Buckets"]]

    def _bucket_create(self):
        """
        Create the S3 bucket from context
        """
        if self._bucket_exists():
            logger.info(f"s3 bucket '{self.bucket_name}' already exists")
            return

        location = {"LocationConstraint": self.bucket_region}
        self._s3client.create_bucket(Bucket=self.bucket_name, CreateBucketConfiguration=location)
        logger.info(f"s3 bucket '{self.bucket_name}' created")

    def _upload_file(self, source_path: str) -> None:
        """
        Upload a given file to the bucket from context. The key name will be the sha256sum hexdigest of the file

        :param source_path: the path to the local file to upload (usually a .vmdk file)
        :type source_path: str
        """
        logger.info(
            f"Starting to upload '{source_path}' in bucket '{self.bucket_name}' as key '{self._ctx.source_sha256}'"
        )

        self._s3client.upload_file(
            source_path,
            self.bucket_name,
            self._ctx.source_sha256,
            ExtraArgs={"ACL": "private", "ChecksumAlgorithm": "SHA256"},
            Callback=_UploadFileProgress(source_path),
            Config=TransferConfig(multipart_chunksize=MULTIPART_CHUNK_SIZE),
        )

        self._s3client.put_object_tagging(
            Bucket=self.bucket_name,
            Key=self._ctx.source_sha256,
            Tagging={
                "TagSet": self._ctx.tags,
            },
        )

        logger.info(
            f"Upload of '{source_path}' to bucket '{self.bucket_name}' " f"as key '{self._ctx.source_sha256}' done"
        )

    def upload_file(self, source_path: str):
        """
        Upload a given file to the bucket from context. The key name will be the sha256sum hexdigest of the file.
        If a file with that name already exist in the given bucket and the calculated sha256sum matches
        the sha256sum from S3, nothing will be uploaded. Instead the existing file will be used.

        :param source_path: the path to the local file to upload (usually a .vmdk file)
        :type source_path: str
        """
        # make sure the bucket exists
        self._bucket_create()

        s3_sha256sum = self._multipart_sha256sum(source_path)

        try:
            # check if the key exists already in the bucket and if so, if the multipart upload
            # sha256sum does match
            head = self._s3client.head_object(
                Bucket=self.bucket_name, Key=self._ctx.source_sha256, ChecksumMode="ENABLED"
            )

            if head["ChecksumSHA256"] == s3_sha256sum:
                logger.info(
                    f"'{self._ctx.source_sha256}' in bucket '{self.bucket_name}' "
                    "already exists and sha256sum matches. nothing to upload to S3"
                )
                return
            else:
                logger.warn(
                    f"'{self._ctx.source_sha256}' in bucket '{self.bucket_name}' "
                    f"already exists but sha256sum does not match. Will be overwritten ..."
                )
        except Exception:
            logging.debug(f"Can not find '{self._ctx.source_sha256}' in bucket '{self.bucket_name}'")

        # do the real upload
        self._upload_file(source_path)
