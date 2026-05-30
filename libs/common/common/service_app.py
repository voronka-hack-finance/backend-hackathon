from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI

from common.lifespan import worker_lifespan
from common.messaging import MessageWorker
from common.redis_client import check_redis


def create_worker_app(
    *,
    title: str,
    worker: MessageWorker,
    handlers: dict[str, Any],
    ready_check: Callable[[], None],
    check_redis_on_ready: bool = True,
) -> FastAPI:
    app = FastAPI(title=title, lifespan=worker_lifespan(worker, handlers))

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    def ready() -> dict[str, str]:
        ready_check()
        if check_redis_on_ready:
            check_redis()
        return {"status": "ready"}

    return app
