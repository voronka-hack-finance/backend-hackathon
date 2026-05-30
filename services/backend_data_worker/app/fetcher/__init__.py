from __future__ import annotations

from services.backend_data_worker.app.config import Settings, settings
from services.backend_data_worker.app.fetcher.base import DataFetcher
from services.backend_data_worker.app.fetcher.mock import MockDataFetcher
from services.backend_data_worker.app.fetcher.rpc import RpcDataFetcher


def get_fetcher(config: Settings | None = None) -> DataFetcher:
    cfg = config or settings
    if cfg.data_provider == "mock":
        return MockDataFetcher()
    return RpcDataFetcher(
        rabbitmq_url=cfg.rabbitmq_url,
        finance_queue=cfg.finance_service_queue,
        analytics_queue=cfg.analytics_service_queue,
        rpc_timeout_seconds=cfg.rpc_timeout_seconds,
    )
