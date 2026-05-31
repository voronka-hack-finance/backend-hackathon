from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from common.messaging import MessageBus, MessageError, MessageWorker, UserContext, check_rabbitmq, require_user
from common.service_app import create_worker_app
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine, text


class Settings(BaseSettings):
    database_url: str = Field(
        default="postgresql+psycopg://app:app@localhost:5432/family_budget",
        validation_alias="DATABASE_URL",
    )
    rabbitmq_url: str = Field(default="amqp://guest:guest@localhost:5672/%2F", validation_alias="RABBITMQ_URL")
    rabbitmq_workflow_url: str = Field(
        default="amqp://guest:guest@localhost:5672/%2F",
        validation_alias="RABBITMQ_WORKFLOW_URL",
    )
    rabbitmq_workflow_queue: str = Field(
        default="ai.workflow.tasks",
        validation_alias="RABBITMQ_WORKFLOW_QUEUE",
    )
    ai_workflow_publish_enabled: bool = Field(default=True, validation_alias="AI_WORKFLOW_PUBLISH_ENABLED")
    ai_workflow_default_timezone: str = Field(default="UTC", validation_alias="AI_WORKFLOW_DEFAULT_TIMEZONE")
    ai_workflow_chat_context_messages: int = Field(default=6, validation_alias="AI_WORKFLOW_CHAT_CONTEXT_MESSAGES")
    ai_workflow_outbox_flush_interval_seconds: float = Field(
        default=5.0,
        validation_alias="AI_WORKFLOW_OUTBOX_FLUSH_INTERVAL_SECONDS",
    )
    ai_workflow_outbox_max_attempts: int = Field(default=20, validation_alias="AI_WORKFLOW_OUTBOX_MAX_ATTEMPTS")
    rabbitmq_workflow_result_queue: str = Field(
        default="ai.workflow.results",
        validation_alias="RABBITMQ_WORKFLOW_RESULT_QUEUE",
    )
    ai_workflow_result_consumer_enabled: bool = Field(
        default=True,
        validation_alias="AI_WORKFLOW_RESULT_CONSUMER_ENABLED",
    )

    model_config = SettingsConfigDict(extra="ignore")


settings = Settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)

SERVICE_NAME = "chat-service"
QUEUE_NAME = "chat-service"
ANALYTICS_QUEUE = "analytics-service"
FINANCE_QUEUE = "finance-service"
HEALTH_SCORE_QUEUE = "health-score-service"

bus = MessageBus(settings.rabbitmq_url, SERVICE_NAME)
worker = MessageWorker(
    rabbitmq_url=settings.rabbitmq_url,
    queue_name=QUEUE_NAME,
    service_name=SERVICE_NAME,
    handlers={},
)
