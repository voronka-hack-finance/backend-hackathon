from __future__ import annotations

from typing import Any

from services.backend_data_worker.app.assembler import empty_data_for_types
from services.backend_data_worker.app.schemas import (
    REQUEST_MESSAGE_TYPE,
    SCHEMA_VERSION,
    BackendDataRequest,
    BackendDataResponse,
    ResponseError,
    SUPPORTED_DATA_TYPES,
)


class RequestValidationError(Exception):
    def __init__(self, *, code: str, message: str, correlation_id: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.correlation_id = correlation_id


def parse_request_body(raw: dict[str, Any]) -> BackendDataRequest:
    correlation_id = raw.get("correlation_id")
    if not correlation_id:
        raise RequestValidationError(
            code="MISSING_CORRELATION_ID",
            message="correlation_id is required",
        )
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise RequestValidationError(
            code="INVALID_REQUEST",
            message=f"Unsupported schema_version: {raw.get('schema_version')!r}",
            correlation_id=str(correlation_id),
        )
    if raw.get("message_type") != REQUEST_MESSAGE_TYPE:
        raise RequestValidationError(
            code="INVALID_REQUEST",
            message=f"Unsupported message_type: {raw.get('message_type')!r}",
            correlation_id=str(correlation_id),
        )
    try:
        request = BackendDataRequest.model_validate(raw)
    except Exception as exc:
        raise RequestValidationError(
            code="INVALID_REQUEST",
            message=str(exc),
            correlation_id=str(correlation_id),
        ) from exc
    if not request.user_id:
        raise RequestValidationError(
            code="INVALID_REQUEST",
            message="user_id is required",
            correlation_id=request.correlation_id,
        )
    if not request.data_types:
        raise RequestValidationError(
            code="INVALID_REQUEST",
            message="data_types must not be empty",
            correlation_id=request.correlation_id,
        )
    unknown = [item for item in request.data_types if item not in SUPPORTED_DATA_TYPES]
    if unknown:
        supported_types = [item for item in request.data_types if item in SUPPORTED_DATA_TYPES]
        if not supported_types:
            raise RequestValidationError(
                code="INVALID_REQUEST",
                message=f"Unsupported data_types: {', '.join(unknown)}",
                correlation_id=request.correlation_id,
            )
        request = request.model_copy(update={"data_types": supported_types})
    return request


def _data_types_from_raw(raw: dict[str, Any]) -> list[str]:
    data_types = raw.get("data_types")
    if isinstance(data_types, list):
        return [str(item) for item in data_types]
    return []


def error_response(
    *,
    correlation_id: str,
    code: str,
    message: str,
    data_types: list[str] | None = None,
) -> BackendDataResponse:
    return BackendDataResponse(
        correlation_id=correlation_id,
        status="error",
        data=empty_data_for_types(data_types or []),
        errors=[ResponseError(code=code, message=message)],
    )
