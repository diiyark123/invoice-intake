import pytest
from botocore.exceptions import ClientError

from app.config import Settings
from app.storage import LocalStorage, S3Storage, get_storage


class FakeS3:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put_object(self, Bucket, Key, Body):
        self.objects[f"{Bucket}/{Key}"] = Body

    def get_object(self, Bucket, Key):
        import io

        return {"Body": io.BytesIO(self.objects[f"{Bucket}/{Key}"])}

    def head_object(self, Bucket, Key):
        if f"{Bucket}/{Key}" not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")


def s3_settings(**kw) -> Settings:
    return Settings(storage_backend="s3", s3_bucket="invoices", **kw)


def test_s3_storage_roundtrip() -> None:
    s = S3Storage(s3_settings(), client=FakeS3())
    assert not s.exists("doc/original/a.pdf")
    s.save(b"%PDF-1.7", "doc/original/a.pdf")
    assert s.exists("doc/original/a.pdf") and s.load("doc/original/a.pdf") == b"%PDF-1.7"


def test_s3_permission_error_is_not_treated_as_missing() -> None:
    class Denied(FakeS3):
        def head_object(self, Bucket, Key):
            raise ClientError({"Error": {"Code": "403"}}, "HeadObject")

    with pytest.raises(ClientError):
        S3Storage(s3_settings(), client=Denied()).exists("x")


def test_s3_needs_a_bucket() -> None:
    with pytest.raises(ValueError, match="S3_BUCKET"):
        S3Storage(Settings(storage_backend="s3", s3_bucket=""), client=FakeS3())


def test_get_storage_picks_backend(tmp_path) -> None:
    assert isinstance(get_storage(Settings(storage_local_path=str(tmp_path))), LocalStorage)
    s3 = get_storage(s3_settings(s3_endpoint_url="https://acc.r2.cloudflarestorage.com"))
    assert isinstance(s3, S3Storage) and s3.client.meta.region_name == "auto"


@pytest.mark.parametrize(
    "url",
    [
        "postgres://u:p@host:5432/invoice",
        "postgresql://u:p@host:5432/invoice",
        "postgresql+psycopg://u:p@host:5432/invoice",
    ],
)
def test_render_style_database_urls_use_psycopg(url: str) -> None:
    assert Settings(database_url=url).database_url == "postgresql+psycopg://u:p@host:5432/invoice"


def test_local_storage_blocks_path_escape(tmp_path) -> None:
    with pytest.raises(ValueError):
        LocalStorage(tmp_path).save(b"x", "../outside.txt")
