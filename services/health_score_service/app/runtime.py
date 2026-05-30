from __future__ import annotations

from common.messaging import MessageBus, MessageWorker
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.health_score_service.app.config import settings

SERVICE_NAME = "health-score-service"
QUEUE_NAME = "health-score-service"
FINANCE_QUEUE = "finance-service"
ANALYTICS_QUEUE = "analytics-service"

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

bus = MessageBus(settings.rabbitmq_url, SERVICE_NAME)
worker = MessageWorker(
    rabbitmq_url=settings.rabbitmq_url,
    queue_name=QUEUE_NAME,
    service_name=SERVICE_NAME,
    handlers={},
)
