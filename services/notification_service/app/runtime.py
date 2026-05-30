from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from common.messaging import MessageWorker, check_rabbitmq, require_user
from common.service_app import create_worker_app
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    database_url: str = Field(
        default="postgresql+psycopg://app:app@localhost:5432/family_budget",
        validation_alias="DATABASE_URL",
    )
    rabbitmq_url: str = Field(default="amqp://guest:guest@localhost:5672/%2F", validation_alias="RABBITMQ_URL")
    firebase_enabled: bool = Field(default=False, validation_alias="FIREBASE_ENABLED")
    firebase_credentials_json: str | None = Field(default=None, validation_alias="FIREBASE_CREDENTIALS_JSON")
    firebase_credentials_path: str | None = Field(default=None, validation_alias="FIREBASE_CREDENTIALS_PATH")

    model_config = SettingsConfigDict(extra="ignore")


settings = Settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)

SERVICE_NAME = "notification-service"
QUEUE_NAME = "notification-service"

worker = MessageWorker(
    rabbitmq_url=settings.rabbitmq_url,
    queue_name=QUEUE_NAME,
    service_name=SERVICE_NAME,
    handlers={},
)

_firebase_app = None
