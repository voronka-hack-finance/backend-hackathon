from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    rabbitmq_url: str = Field(default="amqp://guest:guest@localhost:5672/%2F", validation_alias="RABBITMQ_URL")
    rpc_timeout_seconds: float = Field(default=30.0, validation_alias="RPC_TIMEOUT_SECONDS")
    cors_origins: str = Field(default="*", validation_alias="CORS_ORIGINS")
    public_base_url: str = Field(
        default="http://localhost:8081",
        validation_alias="GATEWAY_PUBLIC_URL",
        description="Public gateway URL for OpenAPI servers and Swagger when the browser has no http(s) origin.",
    )

    model_config = SettingsConfigDict(extra="ignore")

    def cors_origin_list(self) -> list[str]:
        value = self.cors_origins.strip()
        if not value or value == "*":
            return ["*"]
        return [origin.strip() for origin in value.split(",") if origin.strip()]


settings = Settings()
