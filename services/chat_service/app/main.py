from __future__ import annotations

from common.messaging import check_rabbitmq
from common.service_app import create_worker_app
from sqlalchemy import text

from services.chat_service.app.handlers import MESSAGE_HANDLERS
from services.chat_service.app.runtime import SERVICE_NAME, engine, settings, worker


def _ready() -> None:
    with engine.connect() as connection:
        connection.execute(text("select 1"))
    check_rabbitmq(settings.rabbitmq_url)


app = create_worker_app(title=SERVICE_NAME, worker=worker, handlers=MESSAGE_HANDLERS, ready_check=_ready)
