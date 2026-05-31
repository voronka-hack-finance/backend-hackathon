from __future__ import annotations

import base64
import json
import logging
from typing import Any

import httpx

from services.backend_data_worker.app.schemas import ResponseError

logger = logging.getLogger(__name__)


def decode_jwt_user_id(token: str) -> str | None:
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        payload = parts[1]
        padding = "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload + padding)
        claims = json.loads(decoded)
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    user_id = claims.get("user_id") or claims.get("sub")
    return str(user_id) if user_id else None


class GatewayClient:
    def __init__(
        self,
        *,
        base_url: str,
        access_token: str,
        timeout_seconds: float,
        page_size: int = 500,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._access_token = access_token
        self._timeout = timeout_seconds
        self._page_size = min(max(page_size, 1), 500)

    def warn_user_id_mismatch(self, *, request_user_id: str) -> None:
        token_user_id = decode_jwt_user_id(self._access_token)
        if token_user_id and token_user_id != request_user_id:
            logger.warning(
                "gateway_jwt_user_id_mismatch request_user_id=%s token_user_id=%s",
                request_user_id,
                token_user_id,
            )

    def get_paginated_items(
        self,
        path: str,
        *,
        params: dict[str, Any],
        request_user_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], int | None, ResponseError | None]:
        if request_user_id:
            self.warn_user_id_mismatch(request_user_id=request_user_id)

        items: list[dict[str, Any]] = []
        page = 1
        reported_total: int | None = None

        with httpx.Client(base_url=self._base_url, timeout=self._timeout) as client:
            while True:
                page_params = {**params, "page": page, "page_size": self._page_size}
                try:
                    response = client.get(
                        path,
                        params=page_params,
                        headers={"Authorization": f"Bearer {self._access_token}"},
                    )
                except httpx.HTTPError as exc:
                    logger.warning(
                        "gateway_request_failed path=%s page=%s user_id=%s error=%s",
                        path,
                        page,
                        request_user_id,
                        exc.__class__.__name__,
                    )
                    return items, reported_total, ResponseError(
                        code="GATEWAY_HTTP_ERROR",
                        message=f"Gateway request failed for {path}: {exc}",
                    )

                logger.info(
                    "gateway_response_received path=%s gateway_status=%s page=%s user_id=%s",
                    path,
                    response.status_code,
                    page,
                    request_user_id,
                )

                if response.status_code >= 400:
                    return items, reported_total, ResponseError(
                        code="GATEWAY_HTTP_ERROR",
                        message=f"Gateway {path} returned HTTP {response.status_code}: {response.text[:200]}",
                    )

                try:
                    body = response.json()
                except json.JSONDecodeError as exc:
                    return items, reported_total, ResponseError(
                        code="GATEWAY_INVALID_PAYLOAD",
                        message=f"Gateway {path} returned invalid JSON: {exc}",
                    )

                if not isinstance(body, dict):
                    return items, reported_total, ResponseError(
                        code="GATEWAY_INVALID_PAYLOAD",
                        message=f"Gateway {path} response must be a JSON object",
                    )

                page_items = body.get("items") or []
                if not isinstance(page_items, list):
                    return items, reported_total, ResponseError(
                        code="GATEWAY_INVALID_PAYLOAD",
                        message=f"Gateway {path} returned invalid items",
                    )

                pagination = body.get("pagination") or {}
                if isinstance(pagination, dict) and pagination.get("total") is not None:
                    reported_total = int(pagination["total"])

                logger.info(
                    "gateway_page_fetched path=%s page=%s gateway_items_len=%s pagination_total=%s running_total=%s",
                    path,
                    page,
                    len(page_items),
                    reported_total,
                    len(items) + len(page_items),
                )

                items.extend(page_items)
                if reported_total is not None and len(items) >= reported_total:
                    break
                if not page_items:
                    break
                page += 1

        return items, reported_total, None
