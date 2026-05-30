from __future__ import annotations

import json
import logging
import time
from typing import Any
from uuid import UUID

from services.backend_data_worker.app.assembler import (
    assemble_response,
    transactions_items_count,
)
from services.backend_data_worker.app.fetcher import get_fetcher
from services.backend_data_worker.app.fetcher.base import DataFetcher
from services.backend_data_worker.app.schemas import BackendDataResponse, ResponseError
from services.backend_data_worker.app.config import settings
from services.backend_data_worker.app.validator import (
    RequestValidationError,
    error_response,
    parse_request_body,
)

logger = logging.getLogger(__name__)


def _data_types_from_raw(raw: dict[str, Any]) -> list[str]:
    data_types = raw.get("data_types")
    if isinstance(data_types, list):
        return [str(item) for item in data_types]
    return []


CRITICAL_ERROR_CODES = frozenset(
    {
        "MISSING_CORRELATION_ID",
        "INVALID_REQUEST",
        "USER_ID_INVALID",
        "MISSING_PERIOD",
        "FINANCE_RPC_ERROR",
        "ANALYTICS_RPC_ERROR",
        "RPC_INVALID_PAYLOAD",
    }
)


def _validate_user_id(user_id: str) -> ResponseError | None:
    try:
        UUID(user_id)
    except ValueError:
        return ResponseError(code="USER_ID_INVALID", message=f"Invalid user_id UUID: {user_id!r}")
    return None


def _validate_period_for_transactions(request_data_types: list[str], period: Any) -> ResponseError | None:
    if "transactions" in request_data_types and period is None:
        return ResponseError(code="MISSING_PERIOD", message="period is required when fetching transactions")
    return None


def _determine_status(
    *,
    dataset: dict[str, Any],
    errors: list[ResponseError],
    data_types: list[str],
) -> str:
    if any(error.code in CRITICAL_ERROR_CODES for error in errors):
        if not _any_data_present(dataset, data_types):
            return "error"
    if errors:
        return "partial"
    return "success"


def _any_data_present(dataset: dict[str, Any], data_types: list[str]) -> bool:
    for data_type in data_types:
        value = dataset.get(data_type)
        if value is None:
            continue
        if data_type in {"transactions", "previous_period_transactions", "accounts", "goals", "expected_incomes"}:
            if isinstance(value, dict) and value.get("items"):
                return True
        elif data_type == "category_profiles" and isinstance(value, list) and value:
            return True
        elif data_type == "user_context" and isinstance(value, dict):
            return True
    return False


def process_request_payload(
    raw: dict[str, Any],
    *,
    fetcher: DataFetcher | None = None,
) -> BackendDataResponse:
    started = time.monotonic()
    data_types_hint = _data_types_from_raw(raw)

    try:
        request = parse_request_body(raw)
    except RequestValidationError as exc:
        correlation_id = exc.correlation_id or raw.get("correlation_id") or "unknown"
        logger.warning(
            "backend_data_request_invalid correlation_id=%s code=%s message=%s raw_user_id=%s data_types=%s",
            correlation_id,
            exc.code,
            exc.message,
            raw.get("user_id"),
            data_types_hint,
        )
        return error_response(
            correlation_id=str(correlation_id),
            code=exc.code,
            message=exc.message,
            data_types=data_types_hint,
        )

    user_error = _validate_user_id(request.user_id)
    if user_error:
        logger.warning(
            "backend_data_request_invalid_user_id correlation_id=%s user_id=%s message=%s",
            request.correlation_id,
            request.user_id,
            user_error.message,
        )
        return error_response(
            correlation_id=request.correlation_id,
            code=user_error.code,
            message=user_error.message,
            data_types=request.data_types,
        )

    period_error = _validate_period_for_transactions(request.data_types, request.period)
    if period_error:
        return error_response(
            correlation_id=request.correlation_id,
            code=period_error.code,
            message=period_error.message,
            data_types=request.data_types,
        )

    logger.info(
        "backend_data_request_received correlation_id=%s request_id=%s user_id=%s chat_id=%s data_types=%s period=%s comparison_period=%s transaction_filters=%s data_provider=%s fetch_path=internal_rpc",
        request.correlation_id,
        request.request_id,
        request.user_id,
        request.chat_id,
        request.data_types,
        request.period.model_dump() if request.period else None,
        request.comparison_period.model_dump() if request.comparison_period else None,
        request.transaction_filters.model_dump() if request.transaction_filters else None,
        (fetcher or get_fetcher()).__class__.__name__ if fetcher else settings.data_provider,
    )

    data_fetcher = fetcher or get_fetcher()
    dataset, errors = data_fetcher.fetch_dataset(request)
    status = _determine_status(dataset=dataset, errors=errors, data_types=request.data_types)
    response = assemble_response(request=request, dataset=dataset, status=status, errors=errors)

    duration_ms = int((time.monotonic() - started) * 1000)
    rpc_errors = [error.code for error in errors]
    mapped_count = transactions_items_count(response.data)
    rpc_count = transactions_items_count(dataset)
    logger.info(
        "backend_data_response_built correlation_id=%s request_id=%s user_id=%s status=%s rpc_transactions_count=%s mapped_transactions_count=%s duration_ms=%s rpc_errors=%s",
        request.correlation_id,
        request.request_id,
        request.user_id,
        response.status,
        rpc_count,
        mapped_count,
        duration_ms,
        rpc_errors,
    )
    return response


def process_request_bytes(body: bytes, *, fetcher: DataFetcher | None = None) -> BackendDataResponse:
    try:
        raw = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return error_response(
            correlation_id="unknown",
            code="INVALID_REQUEST",
            message=f"Invalid JSON: {exc}",
        )
    if not isinstance(raw, dict):
        return error_response(
            correlation_id="unknown",
            code="INVALID_REQUEST",
            message="Request body must be a JSON object",
        )
    return process_request_payload(raw, fetcher=fetcher)
