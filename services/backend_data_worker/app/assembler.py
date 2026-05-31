from __future__ import annotations

from typing import Any

from services.backend_data_worker.app.schemas import (
    BackendDataRequest,
    BackendDataResponse,
    ResponseError,
)

LIST_DATA_TYPES = frozenset(
    {
        "transactions",
        "previous_period_transactions",
        "accounts",
        "goals",
        "expected_incomes",
    }
)


def empty_data_for_types(data_types: list[str]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for data_type in data_types:
        if data_type in LIST_DATA_TYPES:
            data[data_type] = {"items": []}
        elif data_type == "category_profiles":
            data[data_type] = []
        elif data_type == "user_context":
            data[data_type] = {}
        elif data_type == "existing_financial_analysis_result":
            data[data_type] = None
    return data


def assemble_response(
    *,
    request: BackendDataRequest,
    dataset: dict[str, Any],
    status: str,
    errors: list[ResponseError],
) -> BackendDataResponse:
    filtered_data = {key: dataset[key] for key in request.data_types if key in dataset}
    return BackendDataResponse(
        correlation_id=request.correlation_id,
        status=status,  # type: ignore[arg-type]
        data=filtered_data,
        errors=errors,
    )


def transactions_items_count(data: dict[str, Any], data_type: str = "transactions") -> int:
    block = data.get(data_type)
    if not isinstance(block, dict):
        return 0
    items = block.get("items")
    if not isinstance(items, list):
        return 0
    return len(items)
