from io import BytesIO
from pathlib import Path

from minio import Minio

from services.file_service.app.config import settings


class ObjectStorage:
    def __init__(self) -> None:
        self.backend = settings.storage_backend
        self.bucket = settings.uploads_bucket
        if self.backend == "minio":
            self.client = Minio(
                settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure,
            )
        else:
            self.client = None

    def ensure_bucket(self) -> None:
        if self.backend == "minio":
            assert self.client is not None
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
            return
        Path(settings.local_storage_path, self.bucket).mkdir(parents=True, exist_ok=True)

    def put_bytes(self, key: str, data: bytes, content_type: str | None) -> None:
        self.ensure_bucket()
        if self.backend == "minio":
            assert self.client is not None
            self.client.put_object(
                self.bucket,
                key,
                BytesIO(data),
                length=len(data),
                content_type=content_type or "application/octet-stream",
            )
            return
        path = Path(settings.local_storage_path, self.bucket, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get_bytes(self, key: str) -> bytes:
        if self.backend == "minio":
            assert self.client is not None
            response = self.client.get_object(self.bucket, key)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()
        return Path(settings.local_storage_path, self.bucket, key).read_bytes()
