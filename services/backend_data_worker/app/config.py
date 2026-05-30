from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    rabbitmq_url: str = Field(
        default="amqp://guest:guest@localhost:5672/%2F",
        validation_alias="RABBITMQ_URL",
    )
    request_queue: str = Field(
        default="ai.backend.data.requests",
        validation_alias="AI_BACKEND_DATA_REQUEST_QUEUE",
    )
    response_queue: str = Field(
        default="ai.context_builder.backend_data.responses",
        validation_alias="AI_CONTEXT_BUILDER_RESPONSE_QUEUE",
    )
    data_provider: str = Field(default="rpc", validation_alias="BACKEND_DATA_PROVIDER")
    finance_service_queue: str = Field(
        default="finance-service",
        validation_alias="FINANCE_SERVICE_QUEUE",
    )
    analytics_service_queue: str = Field(
        default="analytics-service",
        validation_alias="ANALYTICS_SERVICE_QUEUE",
    )
    rpc_timeout_seconds: float = Field(default=25.0, validation_alias="RPC_TIMEOUT_SECONDS")

    model_config = SettingsConfigDict(extra="ignore")


settings = Settings()
