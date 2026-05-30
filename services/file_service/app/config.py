from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = Field(
        default="postgresql+psycopg://app:app@localhost:5432/family_budget",
        validation_alias="DATABASE_URL",
    )
    rabbitmq_url: str = Field(default="amqp://guest:guest@localhost:5672/%2F", validation_alias="RABBITMQ_URL")
    minio_endpoint: str = Field(default="localhost:9000", validation_alias="MINIO_ENDPOINT")
    minio_access_key: str = Field(default="minioadmin", validation_alias="MINIO_ACCESS_KEY")
    minio_secret_key: str = Field(default="minioadmin", validation_alias="MINIO_SECRET_KEY")
    minio_secure: bool = Field(default=False, validation_alias="MINIO_SECURE")
    uploads_bucket: str = Field(default="uploaded-files", validation_alias="UPLOADS_BUCKET")
    storage_backend: str = Field(default="minio", validation_alias="STORAGE_BACKEND")
    local_storage_path: Path = Field(default=Path(".local-object-store"), validation_alias="LOCAL_STORAGE_PATH")

    model_config = SettingsConfigDict(extra="ignore")


settings = Settings()
