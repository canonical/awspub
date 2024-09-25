import pathlib
from unittest.mock import patch

import pytest

from awspub import context, s3
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
