import base64
import hashlib
import logging
import os
from typing import Dict

import boto3
from mypy_boto3_s3.type_defs import CompletedPartTypeDef

from awspub.context import Context
from awspub.exceptions import BucketDoesNotExistException

# chunk size is required for calculating the checksums
MULTIPART_CHUNK_SIZE = 8 * 1024 * 1024


logger = logging.getLogger(__name__)


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
        self._s3client = boto3.client("s3")
        self._bucket_region = None

    @property
    def bucket_region(self):
        if not self._bucket_region:
            if not self._bucket_exists():
                raise BucketDoesNotExistException(self.bucket_name)
            self._bucket_region = self._s3client.head_bucket(Bucket=self.bucket_name)["BucketRegion"]

        return self._bucket_region

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
        Check if the S3 bucket from context exists

        :return: True if the bucket exists, otherwise False
        :rtype: bool
        """
        resp = self._s3client.list_buckets()
        return self.bucket_name in [b["Name"] for b in resp["Buckets"]]

    def upload_file(self, source_path: str):
        """
        Upload a given file to the bucket from context. The key name will be the sha256sum hexdigest of the file.
        If a file with that name already exist in the given bucket and the calculated sha256sum matches
        the sha256sum from S3, nothing will be uploaded. Instead the existing file will be used.
        This method does use a multipart upload internally so an upload can be retriggered in case
        of errors and the previously uploaded content will be reused.
        Note: be aware that failed multipart uploads are not deleted. So it's recommended to setup
        a bucket lifecycle rule to delete incomplete multipart uploads.
        See https://docs.aws.amazon.com/AmazonS3/latest/userguide//mpu-abort-incomplete-mpu-lifecycle-config.html

        :param source_path: the path to the local file to upload (usually a .vmdk file)
        :type source_path: str
        """
        # make sure the bucket exists
        if not self._bucket_exists():
            raise BucketDoesNotExistException(self.bucket_name)

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
        self._upload_file_multipart(source_path, s3_sha256sum)

    def _get_multipart_upload_id(self) -> str:
        """
        Get an existing or create a multipart upload id

        :return: a multipart upload id
        :rtype: str
        """
        resp = self._s3client.list_multipart_uploads(Bucket=self.bucket_name)
        multipart_uploads = [
            upload["UploadId"] for upload in resp.get("Uploads", []) if upload["Key"] == self._ctx.source_sha256
        ]
        if len(multipart_uploads) == 1:
            logger.info(f"found existing multipart upload '{multipart_uploads[0]}' for key '{self._ctx.source_sha256}'")
            return multipart_uploads[0]
        elif len(multipart_uploads) == 0:
            # create a new multipart upload
            resp_create = self._s3client.create_multipart_upload(
                Bucket=self.bucket_name,
                Key=self._ctx.source_sha256,
                ChecksumAlgorithm="SHA256",
                ACL="private",
            )
            upload_id = resp_create["UploadId"]
            logger.info(
                f"new multipart upload (upload id: '{upload_id})' started in bucket "
                f"{self.bucket_name} for key {self._ctx.source_sha256}"
            )
            # if there's an expire rule configured for that bucket, inform about it
            if resp_create.get("AbortDate"):
                logger.info(
                    f"multipart upload '{upload_id}' will expire at "
                    f"{resp_create['AbortDate']} (rule: {resp_create.get('AbortRuleId')})"
                )
            else:
                logger.warning("there is no matching expire/lifecycle rule configured for incomplete multipart uploads")
            return upload_id
        else:
            # multiple multipart uploads for the same key available
            logger.warning(
                f"there are multiple ({len(multipart_uploads)}) multipart uploads ongoing in "
                f"bucket {self.bucket_name} for key {self._ctx.source_sha256}"
            )
            logger.warning("using the first found multipart upload but you should delete pending multipart uploads")
            return multipart_uploads[0]

    def _upload_file_multipart(self, source_path: str, s3_sha256sum: str) -> None:
        """
        Upload a given file to the bucket from context. The key name will be the sha256sum hexdigest of the file

        :param source_path: the path to the local file to upload (usually a .vmdk file)
        :type source_path: str
        :param s3_sha256sum: the sha256sum how S3 calculates it
        :type s3_sha256sum: str
        """
        upload_id = self._get_multipart_upload_id()

        logger.info(f"using upload id '{upload_id}' for multipart upload of '{source_path}' ...")
        resp_list_parts = self._s3client.list_parts(
            Bucket=self.bucket_name, Key=self._ctx.source_sha256, UploadId=upload_id
        )

        # sanity check for the used checksum algorithm
        if resp_list_parts["ChecksumAlgorithm"] != "SHA256":
            logger.error(f"available ongoing multipart upload '{upload_id}' does not use SHA256 as checksum algorithm")

        # already available parts
        parts_available = {p["PartNumber"]: p for p in resp_list_parts.get("Parts", [])}
        # keep a list of parts (either already available or created) required to complete the multipart upload
        parts: Dict[int, CompletedPartTypeDef] = {}
        parts_size_done: int = 0
        source_path_size: int = os.path.getsize(source_path)
        with open(source_path, "rb") as f:
            # parts start at 1 (not 0)
            for part_number, chunk in enumerate(iter(lambda: f.read(MULTIPART_CHUNK_SIZE), b""), start=1):
                # the sha256sum of the current part
                sha256_part = base64.b64encode(hashlib.sha256(chunk).digest()).decode("ascii")
                # do nothing if that part number already exist and the sha256sum matches
                if parts_available.get(part_number):
                    if parts_available[part_number]["ChecksumSHA256"] == sha256_part:
                        logger.info(f"part {part_number} already exists and sha256sum matches. continue")
                        parts[part_number] = dict(
                            PartNumber=part_number,
                            ETag=parts_available[part_number]["ETag"],
                            ChecksumSHA256=parts_available[part_number]["ChecksumSHA256"],
                        )
                        parts_size_done += len(chunk)
                        continue
                    else:
                        logger.info(f"part {part_number} already exists but will be overwritten")

                # upload a new part
                resp_upload_part = self._s3client.upload_part(
                    Body=chunk,
                    Bucket=self.bucket_name,
                    ContentLength=len(chunk),
                    ChecksumAlgorithm="SHA256",
                    ChecksumSHA256=sha256_part,
                    Key=self._ctx.source_sha256,
                    PartNumber=part_number,
                    UploadId=upload_id,
                )
                parts_size_done += len(chunk)
                # add new part to the dict of parts
                parts[part_number] = dict(
                    PartNumber=part_number,
                    ETag=resp_upload_part["ETag"],
                    ChecksumSHA256=sha256_part,
                )
                logger.info(
                    f"part {part_number} uploaded ({round(parts_size_done/source_path_size * 100, 2)}% "
                    f"; {parts_size_done} / {source_path_size} bytes)"
                )

        logger.info(
            f"finishing the multipart upload for key '{self._ctx.source_sha256}' in bucket {self.bucket_name} now ..."
        )
        # finish the multipart upload
        self._s3client.complete_multipart_upload(
            Bucket=self.bucket_name,
            Key=self._ctx.source_sha256,
            UploadId=upload_id,
            ChecksumSHA256=s3_sha256sum,
            MultipartUpload={"Parts": [value for key, value in parts.items()]},
        )
        logger.info(
            f"multipart upload finished and key '{self._ctx.source_sha256}' now "
            f"available in bucket '{self.bucket_name}'"
        )

        # add tagging to the final s3 object
        self._s3client.put_object_tagging(
            Bucket=self.bucket_name,
            Key=self._ctx.source_sha256,
            Tagging={
                "TagSet": self._ctx.tags,
            },
        )
