from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_EXCEL = _REPO_ROOT / "family-bugget.xlsx"


class Settings(BaseSettings):
    database_url: str = Field(
        default="postgresql+psycopg://app:app@localhost:5432/family_budget",
        validation_alias="DATABASE_URL",
    )
    bootstrap_excel_enabled: bool = Field(default=True, validation_alias="BOOTSTRAP_EXCEL_ENABLED")
    bootstrap_excel_path: Path = Field(default=_DEFAULT_EXCEL, validation_alias="BOOTSTRAP_EXCEL_PATH")
    bootstrap_reset_on_start: bool = Field(default=True, validation_alias="BOOTSTRAP_RESET_ON_START")
    bootstrap_user_email: str = Field(default="demo@example.com", validation_alias="BOOTSTRAP_USER_EMAIL")
    bootstrap_user_password: str = Field(default="secret123", validation_alias="BOOTSTRAP_USER_PASSWORD")
    bootstrap_user_display_name: str = Field(default="Иван Иванов", validation_alias="BOOTSTRAP_USER_DISPLAY_NAME")
    minio_endpoint: str = Field(default="localhost:9000", validation_alias="MINIO_ENDPOINT")
    minio_access_key: str = Field(default="minioadmin", validation_alias="MINIO_ACCESS_KEY")
    minio_secret_key: str = Field(default="minioadmin", validation_alias="MINIO_SECRET_KEY")
    minio_secure: bool = Field(default=False, validation_alias="MINIO_SECURE")
    uploads_bucket: str = Field(default="uploaded-files", validation_alias="UPLOADS_BUCKET")

    model_config = SettingsConfigDict(extra="ignore")


settings = Settings()
