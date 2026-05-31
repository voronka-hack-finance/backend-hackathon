from __future__ import annotations

from contextlib import asynccontextmanager

from common.messaging import check_rabbitmq
from common.redis_client import check_redis
from fastapi import FastAPI
from sqlalchemy import text

from services.chat_service.app.handlers import MESSAGE_HANDLERS
from services.chat_service.app.runtime import SERVICE_NAME, engine, settings, worker
from services.chat_service.app.workflow_outbox import WorkflowOutboxFlusher
from services.chat_service.app.workflow_result_consumer import workflow_result_consumer


def _ready() -> None:
    with engine.connect() as connection:
        connection.execute(text("select 1"))
    check_rabbitmq(settings.rabbitmq_url)


outbox_flusher = WorkflowOutboxFlusher(
    engine=engine,
    rabbitmq_url=settings.rabbitmq_workflow_url,
    queue_name=settings.rabbitmq_workflow_queue,
    interval_seconds=settings.ai_workflow_outbox_flush_interval_seconds,
    max_attempts=settings.ai_workflow_outbox_max_attempts,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    worker.handlers.update(MESSAGE_HANDLERS)
    worker.start()
    if settings.ai_workflow_publish_enabled:
        outbox_flusher.start()
    if settings.ai_workflow_result_consumer_enabled:
        workflow_result_consumer.start()
    yield
    if settings.ai_workflow_result_consumer_enabled:
        workflow_result_consumer.stop()
    outbox_flusher.stop()
    worker.stop()


app = FastAPI(title=SERVICE_NAME, lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, str]:
    _ready()
    check_redis()
    return {"status": "ready"}
