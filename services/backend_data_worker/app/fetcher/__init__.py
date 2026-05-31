from __future__ import annotations

from services.backend_data_worker.app.config import Settings, settings
from services.backend_data_worker.app.fetcher.base import DataFetcher
from services.backend_data_worker.app.fetcher.gateway import GatewayDataFetcher
from services.backend_data_worker.app.fetcher.mock import MockDataFetcher
from services.backend_data_worker.app.fetcher.rpc import RpcDataFetcher
from services.backend_data_worker.app.gateway_client import GatewayClient


def get_fetcher(config: Settings | None = None) -> DataFetcher:
    cfg = config or settings
    if cfg.data_provider == "mock":
        return MockDataFetcher()
    if cfg.data_provider == "gateway":
        if not cfg.gateway_access_token:
            raise RuntimeError("BACKEND_GATEWAY_ACCESS_TOKEN is required when BACKEND_DATA_PROVIDER=gateway")
        return GatewayDataFetcher(
            gateway_client=GatewayClient(
                base_url=cfg.gateway_base_url,
                access_token=cfg.gateway_access_token,
                timeout_seconds=cfg.gateway_http_timeout_seconds,
                page_size=cfg.gateway_page_size,
            ),
        )
    return RpcDataFetcher(
        rabbitmq_url=cfg.rabbitmq_url,
        finance_queue=cfg.finance_service_queue,
        analytics_queue=cfg.analytics_service_queue,
        rpc_timeout_seconds=cfg.rpc_timeout_seconds,
    )
