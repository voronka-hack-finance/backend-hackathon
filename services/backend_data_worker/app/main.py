from __future__ import annotations

from contextlib import asynccontextmanager
import logging

from common.messaging import check_rabbitmq
from fastapi import FastAPI

from services.backend_data_worker.app.config import settings
from services.backend_data_worker.app.consumer import consumer

SERVICE_NAME = "backend-data-worker"

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger = logging.getLogger(__name__)
    logger.info(
        "backend_data_worker_starting data_provider=%s request_queue=%s response_queue=%s finance_queue=%s analytics_queue=%s gateway_base_url=%s",
        settings.data_provider,
        settings.request_queue,
        settings.response_queue,
        settings.finance_service_queue,
        settings.analytics_service_queue,
        settings.gateway_base_url if settings.data_provider == "gateway" else None,
    )
    consumer.start()
    yield
    consumer.stop()


app = FastAPI(title=SERVICE_NAME, lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, str]:
    check_rabbitmq(settings.rabbitmq_url)
    return {"status": "ready", "data_provider": settings.data_provider}
