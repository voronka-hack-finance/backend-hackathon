from __future__ import annotations

from common.messaging import MessageWorker, check_rabbitmq
from common.service_app import create_worker_app
from sqlalchemy import text

from services.finance_service.app.config import settings
from services.finance_service.app.db import engine
from services.finance_service.app.handlers import MESSAGE_HANDLERS

SERVICE_NAME = "finance-service"
QUEUE_NAME = "finance-service"

worker = MessageWorker(
    rabbitmq_url=settings.rabbitmq_url,
    queue_name=QUEUE_NAME,
    service_name=SERVICE_NAME,
    handlers={},
)


def _ready() -> None:
    with engine.connect() as connection:
        connection.execute(text("select 1"))
    check_rabbitmq(settings.rabbitmq_url)


app = create_worker_app(title=SERVICE_NAME, worker=worker, handlers=MESSAGE_HANDLERS, ready_check=_ready)
