"""File storage behind one small interface: local folder in dev, S3-compatible bucket in prod."""

from pathlib import Path
from typing import Any, Protocol

from app.config import Settings, get_settings


class Storage(Protocol):
    def save(self, data: bytes, key: str) -> None: ...
    def load(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...


class LocalStorage:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError(f"Invalid storage key: {key}")
        return path

    def save(self, data: bytes, key: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def load(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()


class S3Storage:
    """S3-compatible storage (Cloudflare R2 in production; also AWS S3, Backblaze B2)."""

    def __init__(self, settings: Settings, client: Any = None) -> None:
        if not settings.s3_bucket:
            raise ValueError("STORAGE_BACKEND=s3 needs S3_BUCKET")
        self.bucket = settings.s3_bucket
        if client is None:
            import boto3

            client = boto3.client(
                "s3",
                endpoint_url=settings.s3_endpoint_url or None,
                aws_access_key_id=settings.s3_access_key,
                aws_secret_access_key=settings.s3_secret_key,
                region_name=settings.s3_region,
            )
        self.client = client

    def save(self, data: bytes, key: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data)

    def load(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise  # permissions or network problems must not look like "file missing"


def get_storage(settings: Settings | None = None) -> Storage:
    settings = settings or get_settings()
    if settings.storage_backend == "s3":
        return S3Storage(settings)
    return LocalStorage(settings.storage_local_path)
