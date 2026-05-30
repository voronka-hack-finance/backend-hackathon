from __future__ import annotations

from datetime import date
from typing import Any, Literal

from common.messaging import MessageBus, UserContext
from fastapi import HTTPException

from services.gateway.app.config import settings

bus = MessageBus(settings.rabbitmq_url, "api-gateway-service")


def rpc_call(
    queue_name: str,
    message_type: str,
    payload: dict[str, Any],
    *,
    user: UserContext | None = None,
    timeout_seconds: float | None = None,
    allow_status: set[int] | None = None,
) -> dict:
    reply = bus.request(
        queue_name,
        message_type,
        payload,
        user=user,
        timeout_seconds=timeout_seconds or settings.rpc_timeout_seconds,
    )
    if reply.get("ok"):
        return reply.get("payload") or {}
    status_code = int(reply.get("status_code") or 502)
    if allow_status and status_code in allow_status:
        return {}
    detail = reply.get("error") or "Internal service error"
    if status_code == 504:
        detail = "Internal service timeout"
    elif status_code >= 500:
        detail = "Internal service error"
    raise HTTPException(status_code=status_code, detail=detail)


def model_payload(model) -> dict[str, Any]:
    return model.model_dump(mode="json", exclude_none=True)


def date_or_none(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def params_to_payload(params: list[tuple[str, str]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in params:
        if key in payload:
            if not isinstance(payload[key], list):
                payload[key] = [payload[key]]
            payload[key].append(value)
        else:
            payload[key] = value
    return payload


def transaction_query_params(
    *,
    date_from: date | None,
    date_to: date | None,
    categories: list[str] | None,
    mcc: list[str] | None,
    transaction_type: Literal["income", "expense"] | None,
    status_filter: str | None,
    has_cashback: bool | None,
    card_last4: list[str] | None,
    page: int,
    page_size: int,
) -> list[tuple[str, str]]:
    params: list[tuple[str, str]] = [("page", str(page)), ("page_size", str(page_size))]
    if date_from is not None:
        params.append(("date_from", date_from.isoformat()))
    if date_to is not None:
        params.append(("date_to", date_to.isoformat()))
    if status_filter:
        params.append(("status", status_filter))
    if transaction_type:
        params.append(("type", transaction_type))
    if has_cashback is not None:
        params.append(("has_cashback", str(has_cashback).lower()))
    for value in categories or []:
        params.append(("categories", value))
    for value in mcc or []:
        params.append(("mcc", value))
    for value in card_last4 or []:
        params.append(("card_last4", value))
    return params
