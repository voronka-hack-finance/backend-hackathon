from __future__ import annotations

import logging
from typing import Any

from services.backend_data_worker.app.fetcher.rpc import (
    _filters_to_payload,
    _load_category_profiles_reference,
)
from services.backend_data_worker.app.gateway_client import GatewayClient
from services.backend_data_worker.app.schemas import (
    BackendDataRequest,
    Period,
    ResponseError,
    TransactionFilters,
)

logger = logging.getLogger(__name__)


def period_to_gateway_params(period: Period | None) -> dict[str, str]:
    if period is None:
        return {}
    return {
        "date_from": _to_iso_datetime(period.start_date, end_of_day=False),
        "date_to": _to_iso_datetime(period.end_date, end_of_day=True),
    }


def _to_iso_datetime(date_value: str, *, end_of_day: bool) -> str:
    if "T" in date_value:
        return date_value
    suffix = "T23:59:59.999Z" if end_of_day else "T00:00:00.000Z"
    return f"{date_value}{suffix}"


def _filters_to_query_params(filters: TransactionFilters | None) -> dict[str, Any]:
    payload = _filters_to_payload(filters)
    params: dict[str, Any] = {}
    if payload.get("type"):
        params["type"] = payload["type"]
    if payload.get("categories"):
        params["categories"] = payload["categories"]
    if payload.get("mcc"):
        params["mcc"] = payload["mcc"]
    if payload.get("account_id"):
        params["account_id"] = payload["account_id"]
    if payload.get("card_last4"):
        params["card_last4"] = payload["card_last4"]
    return params


class GatewayDataFetcher:
    def __init__(
        self,
        *,
        gateway_client: GatewayClient,
    ) -> None:
        self._client = gateway_client

    def fetch_dataset(self, request: BackendDataRequest) -> tuple[dict[str, Any], list[ResponseError]]:
        dataset: dict[str, Any] = {}
        errors: list[ResponseError] = []
        filter_params = _filters_to_query_params(request.transaction_filters)

        if "transactions" in request.data_types:
            items, total, err = self._fetch_transactions(request, request.period, filter_params)
            dataset["transactions"] = {"items": items}
            self._log_transactions_fetch(
                label="transactions",
                request=request,
                items=items,
                total=total,
                err=err,
                filter_params=filter_params,
            )
            if err:
                errors.append(err)
            elif not items:
                errors.append(_no_transactions_error(request.period, filter_params))

        if "previous_period_transactions" in request.data_types:
            if request.comparison_period is None:
                errors.append(
                    ResponseError(
                        code="MISSING_COMPARISON_PERIOD",
                        message="comparison_period is required for previous_period_transactions",
                    )
                )
                dataset["previous_period_transactions"] = {"items": []}
            else:
                items, total, err = self._fetch_transactions(
                    request,
                    request.comparison_period,
                    filter_params,
                )
                dataset["previous_period_transactions"] = {"items": items}
                self._log_transactions_fetch(
                    label="previous_period_transactions",
                    request=request,
                    items=items,
                    total=total,
                    err=err,
                    filter_params=filter_params,
                    period=request.comparison_period,
                )
                if err:
                    errors.append(err)
                elif not items:
                    errors.append(_no_transactions_error(request.comparison_period, filter_params))

        if "accounts" in request.data_types:
            items, _, err = self._client.get_paginated_items(
                "/api/v1/accounts",
                params={},
                request_user_id=request.user_id,
            )
            dataset["accounts"] = {"items": items}
            if err:
                errors.append(err)

        if "goals" in request.data_types:
            items, _, err = self._client.get_paginated_items(
                "/api/v1/goals",
                params={},
                request_user_id=request.user_id,
            )
            dataset["goals"] = {"items": items}
            if err:
                errors.append(err)

        if "expected_incomes" in request.data_types:
            items, _, err = self._client.get_paginated_items(
                "/api/v1/analytics/expected-incomes",
                params={},
                request_user_id=request.user_id,
            )
            dataset["expected_incomes"] = {"items": items}
            if err:
                errors.append(err)

        if "user_context" in request.data_types:
            dataset["user_context"] = {}
            errors.append(
                ResponseError(
                    code="NOT_IMPLEMENTED_GATEWAY",
                    message="user_context aggregation is not implemented for gateway provider; use rpc provider",
                )
            )

        if "category_profiles" in request.data_types:
            dataset["category_profiles"] = _load_category_profiles_reference()
            errors.append(
                ResponseError(
                    code="CATEGORY_PROFILES_STATIC",
                    message="category_profiles served from static reference mapping until backend endpoint exists",
                )
            )

        if "existing_financial_analysis_result" in request.data_types:
            dataset["existing_financial_analysis_result"] = None

        return dataset, errors

    def _fetch_transactions(
        self,
        request: BackendDataRequest,
        period: Period | None,
        filter_params: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], int | None, ResponseError | None]:
        if period is None:
            return [], None, ResponseError(code="MISSING_PERIOD", message="period is required for transactions fetch")
        params = {**period_to_gateway_params(period), **filter_params}
        return self._client.get_paginated_items(
            "/api/v1/transactions",
            params=params,
            request_user_id=request.user_id,
        )

    def _log_transactions_fetch(
        self,
        *,
        label: str,
        request: BackendDataRequest,
        items: list[dict[str, Any]],
        total: int | None,
        err: ResponseError | None,
        filter_params: dict[str, Any],
        period: Period | None = None,
    ) -> None:
        active_period = period or request.period
        logger.info(
            "gateway_transactions_fetched label=%s user_id=%s period=%s filters=%s gateway_items_len=%s pagination_total=%s gateway_error=%s",
            label,
            request.user_id,
            active_period.model_dump() if active_period else None,
            filter_params or None,
            len(items),
            total,
            err.code if err else None,
        )


def _no_transactions_error(period: Period | None, filter_params: dict[str, Any]) -> ResponseError:
    period_label = f"{period.start_date}..{period.end_date}" if period else "unknown"
    return ResponseError(
        code="NO_TRANSACTIONS",
        message=(
            f"Gateway returned 0 items for period {period_label} with filters {filter_params or {}}"
        ),
    )
