from __future__ import annotations

from typing import Any

from services.backend_data_worker.app.mock_data import build_mock_dataset, partial_data_type_errors
from services.backend_data_worker.app.schemas import BackendDataRequest, ResponseError


class MockDataFetcher:
    def fetch_dataset(self, request: BackendDataRequest) -> tuple[dict[str, Any], list[ResponseError]]:
        dataset = build_mock_dataset(request)
        errors = [
            ResponseError(code=code, message=message) for code, message in partial_data_type_errors(request)
        ]
        return dataset, errors
