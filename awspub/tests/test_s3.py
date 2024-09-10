import pathlib
from unittest.mock import patch

import pytest

from awspub import context, s3

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
