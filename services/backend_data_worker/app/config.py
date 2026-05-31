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
    gateway_base_url: str = Field(
        default="http://gateway:8000",
        validation_alias="BACKEND_GATEWAY_BASE_URL",
    )
    gateway_access_token: str = Field(default="", validation_alias="BACKEND_GATEWAY_ACCESS_TOKEN")
    gateway_http_timeout_seconds: float = Field(default=30.0, validation_alias="BACKEND_HTTP_TIMEOUT_SECONDS")
    gateway_page_size: int = Field(default=500, validation_alias="BACKEND_TRANSACTIONS_PAGE_SIZE")
    default_transaction_period_months: int = Field(
        default=6,
        validation_alias="BACKEND_DEFAULT_TRANSACTION_PERIOD_MONTHS",
    )

    model_config = SettingsConfigDict(extra="ignore")


settings = Settings()
