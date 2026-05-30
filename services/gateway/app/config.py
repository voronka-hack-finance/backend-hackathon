from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    rabbitmq_url: str = Field(default="amqp://guest:guest@localhost:5672/%2F", validation_alias="RABBITMQ_URL")
    rpc_timeout_seconds: float = Field(default=30.0, validation_alias="RPC_TIMEOUT_SECONDS")
    jwt_secret: str = Field(default="dev-secret-change-me", validation_alias="JWT_SECRET")
    jwt_issuer: str = Field(default="family-budget-backend", validation_alias="JWT_ISSUER")

    model_config = SettingsConfigDict(extra="ignore")


settings = Settings()
