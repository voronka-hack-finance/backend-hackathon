from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = Field(
        default="postgresql+psycopg://app:app@localhost:5432/family_budget",
        validation_alias="DATABASE_URL",
    )
    rabbitmq_url: str = Field(default="amqp://guest:guest@localhost:5672/%2F", validation_alias="RABBITMQ_URL")
    jwt_secret: str = Field(default="dev-secret-change-me", validation_alias="JWT_SECRET")
    jwt_issuer: str = Field(default="family-budget-backend", validation_alias="JWT_ISSUER")
    access_token_minutes: int = Field(default=1440, validation_alias="ACCESS_TOKEN_MINUTES")
    refresh_token_days: int = Field(default=30, validation_alias="REFRESH_TOKEN_DAYS")

    model_config = SettingsConfigDict(extra="ignore")


settings = Settings()
