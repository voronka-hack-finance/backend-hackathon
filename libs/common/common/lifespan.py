from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from common.messaging import MessageWorker


def worker_lifespan(worker: MessageWorker, handlers: dict[str, Any]):
    """FastAPI lifespan that starts/stops a RabbitMQ MessageWorker."""

    @asynccontextmanager
    async def lifespan(_app):
        worker.handlers.update(handlers)
        worker.start()
        yield
        worker.stop()

    return lifespan
