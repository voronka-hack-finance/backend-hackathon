from __future__ import annotations

from typing import Any, Protocol

from services.backend_data_worker.app.schemas import BackendDataRequest, ResponseError


class DataFetcher(Protocol):
    def fetch_dataset(self, request: BackendDataRequest) -> tuple[dict[str, Any], list[ResponseError]]: ...
