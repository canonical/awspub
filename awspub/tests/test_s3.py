import pathlib
import time
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from awspub import configmodels, context, s3
from awspub.exceptions import BucketDoesNotExistException

curdir = pathlib.Path(__file__).parent.resolve()


@pytest.mark.parametrize(
    "list_multipart_uploads_resp,create_multipart_upload_called",
    [
        # no available uploads - create one
        ([], True),
        # one available upload with non-matching key
        ([{"UploadId": "abc", "Key": "does-not-match"}], True),
        # multiple available upload with non-matching key
        ([{"UploadId": "abc", "Key": "does-not-match"}, {"UploadId": "def", "Key": "does-not-match2"}], True),
        # one available upload with matching key
        ([{"UploadId": "abc", "Key": "6252475408b9f9ee64452b611d706a078831a99b123db69d144d878a0488a0a8"}], False),
        # multiple available upload with one matching key
        (
            [
                {"UploadId": "abc", "Key": "6252475408b9f9ee64452b611d706a078831a99b123db69d144d878a0488a0a8"},
                {"UploadId": "abc", "Key": "does-not-match"},
            ],
            False,
        ),
        # multiple available upload with multiple matching keys
        (
            [
                {"UploadId": "abc", "Key": "6252475408b9f9ee64452b611d706a078831a99b123db69d144d878a0488a0a8"},
                {"UploadId": "def", "Key": "6252475408b9f9ee64452b611d706a078831a99b123db69d144d878a0488a0a8"},
            ],
            False,
        ),
    ],
)
def test_s3__get_multipart_upload_id(list_multipart_uploads_resp, create_multipart_upload_called):
    """
    test the _get_multipart_upload_id() function
    """

    with patch("boto3.client") as bclient_mock:
        instance = bclient_mock.return_value
        instance.list_multipart_uploads.return_value = {"Uploads": list_multipart_uploads_resp}
        ctx = context.Context(curdir / "fixtures/config1.yaml", None)
        sthree = s3.S3(ctx)
        sthree._get_multipart_upload_id()
        assert instance.create_multipart_upload.called == create_multipart_upload_called


@patch("awspub.s3.S3._bucket_exists", return_value=True)
@patch("awspub.s3.boto3")
def test_s3_bucket_region_bucket_exists(boto3_mock, bucket_exists_mock):
    region_name = "sample-region-1"
    head_bucket = {"BucketRegion": region_name}
    boto3_mock.client.return_value.head_bucket.return_value = head_bucket
    ctx = context.Context(curdir / "fixtures/config1.yaml", None)
    sthree = s3.S3(ctx)

    assert sthree.bucket_region == region_name


@patch("awspub.s3.S3._bucket_exists", return_value=False)
@patch("boto3.client")
def test_s3_bucket_region_bucket_not_exists(bclient_mock, bucket_exists_mock):
    ctx = context.Context(curdir / "fixtures/config1.yaml", None)
    sthree = s3.S3(ctx)

    with pytest.raises(BucketDoesNotExistException):
        sthree.bucket_region()


@pytest.mark.parametrize("concurrency", [1, 2, 4, 8])
@patch("boto3.client")
def test_s3__upload_file_multipart_concurrency(bclient_mock, concurrency, monkeypatch):
    """
    test that _upload_file_multipart() uploads all parts and assembles them in ascending
    PartNumber order for the CompleteMultipartUpload call, even when parts finish
    out of order (as can happen with concurrent uploads).
    """
    # config1.vmdk is 65536 bytes, use a small chunk size so we get multiple parts
    monkeypatch.setattr(s3, "MULTIPART_CHUNK_SIZE", 8192)

    ctx = context.Context(curdir / "fixtures/config1.yaml", None)
    ctx.conf["s3"]["upload_multipart_concurrency"] = concurrency
    sthree = s3.S3(ctx)

    instance = bclient_mock.return_value
    instance.list_parts.return_value = {"ChecksumAlgorithm": "SHA256", "Parts": []}

    def _fake_upload_part(**kwargs):
        # force out-of-order completion: earlier part numbers take longer, so later
        # part numbers are more likely to complete first when uploaded concurrently
        part_number = kwargs["PartNumber"]
        time.sleep(0.01 * (9 - part_number))
        return {"ETag": f"etag-{part_number}"}

    instance.upload_part.side_effect = _fake_upload_part

    sthree._upload_file_multipart(str(curdir / "fixtures/config1.vmdk"), "fakesha256sum-8")

    expected_part_count = 8
    assert instance.upload_part.call_count == expected_part_count

    complete_kwargs = instance.complete_multipart_upload.call_args.kwargs
    completed_parts = complete_kwargs["MultipartUpload"]["Parts"]
    assert len(completed_parts) == expected_part_count
    # parts must be sent to S3 in ascending PartNumber order, regardless of completion order
    part_numbers = [p["PartNumber"] for p in completed_parts]
    assert part_numbers == list(range(1, expected_part_count + 1))
    for part in completed_parts:
        assert part["ETag"] == f"etag-{part['PartNumber']}"


@pytest.mark.parametrize(
    "upload_multipart_concurrency,valid",
    [
        (1, True),
        (5, True),
        (32, True),
        (0, False),
        (-1, False),
        (33, False),
        (True, False),
        (False, False),
    ],
)
def test_configmodels_s3_upload_multipart_concurrency(upload_multipart_concurrency, valid):
    """
    test that ConfigS3Model validates upload_multipart_concurrency: only positive
    integers within the allowed range (and not bools) are accepted
    """
    if valid:
        model = configmodels.ConfigS3Model(
            bucket_name="bucket1", upload_multipart_concurrency=upload_multipart_concurrency
        )
        assert model.upload_multipart_concurrency == upload_multipart_concurrency
    else:
        with pytest.raises(ValidationError):
            configmodels.ConfigS3Model(bucket_name="bucket1", upload_multipart_concurrency=upload_multipart_concurrency)


def test_configmodels_s3_upload_multipart_concurrency_default():
    """
    test that the default value for upload_multipart_concurrency is 1 (sequential),
    preserving pre-existing behavior for users who don't set it
    """
    model = configmodels.ConfigS3Model(bucket_name="bucket1")
    assert model.upload_multipart_concurrency == 1
