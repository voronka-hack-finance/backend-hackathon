from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from common.messaging import MessageBus, UserContext

from services.backend_data_worker.app.schemas import (
    BackendDataRequest,
    Period,
    ResponseError,
    TransactionFilters,
)

logger = logging.getLogger(__name__)

PAGE_SIZE = 500
_REFERENCE_PATH = Path(__file__).resolve().parent.parent / "category_profiles.reference.json"


class RpcDataFetcher:
    def __init__(
        self,
        *,
        rabbitmq_url: str,
        finance_queue: str,
        analytics_queue: str,
        rpc_timeout_seconds: float,
        bus: MessageBus | None = None,
    ) -> None:
        self._finance_queue = finance_queue
        self._analytics_queue = analytics_queue
        self._timeout = rpc_timeout_seconds
        self._bus = bus or MessageBus(rabbitmq_url, "backend-data-worker")

    def fetch_dataset(self, request: BackendDataRequest) -> tuple[dict[str, Any], list[ResponseError]]:
        dataset: dict[str, Any] = {}
        errors: list[ResponseError] = []
        filters_payload = _filters_to_payload(request.transaction_filters)

        if "transactions" in request.data_types:
            items, err, rpc_total = self._fetch_transactions(
                request.user_id,
                request.period,
                filters_payload,
            )
            dataset["transactions"] = {"items": items}
            logger.info(
                "rpc_transactions_fetched user_id=%s period=%s filters=%s rpc_items_len=%s rpc_total=%s rpc_error=%s",
                request.user_id,
                request.period.model_dump() if request.period else None,
                filters_payload or None,
                len(items),
                rpc_total,
                err.code if err else None,
            )
            if err:
                errors.append(err)
            elif not items:
                period_label = (
                    f"{request.period.start_date}..{request.period.end_date}"
                    if request.period
                    else "unknown"
                )
                errors.append(
                    ResponseError(
                        code="NO_TRANSACTIONS",
                        message=(
                            f"Finance RPC returned 0 items for period {period_label} "
                            f"with filters {filters_payload or {}}"
                        ),
                    )
                )

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
                items, err, _rpc_total = self._fetch_transactions(
                    request.user_id,
                    request.comparison_period,
                    filters_payload,
                )
                dataset["previous_period_transactions"] = {"items": items}
                if err:
                    errors.append(err)
                elif not items:
                    period_label = (
                        f"{request.comparison_period.start_date}..{request.comparison_period.end_date}"
                    )
                    errors.append(
                        ResponseError(
                            code="NO_TRANSACTIONS",
                            message=(
                                f"Finance RPC returned 0 items for comparison period {period_label} "
                                f"with filters {filters_payload or {}}"
                            ),
                        )
                    )

        if "accounts" in request.data_types:
            payload, err = self._fetch_paginated(self._finance_queue, "accounts.list", request.user_id, {})
            if err:
                errors.append(err)
                dataset["accounts"] = {"items": []}
            else:
                dataset["accounts"] = {"items": payload.get("items") or []}

        if "goals" in request.data_types:
            payload, err = self._fetch_paginated(self._finance_queue, "goals.list", request.user_id, {})
            if err:
                errors.append(err)
                dataset["goals"] = {"items": []}
            else:
                dataset["goals"] = {"items": payload.get("items") or []}

        if "expected_incomes" in request.data_types:
            payload, err = self._fetch_paginated(
                self._analytics_queue,
                "analytics.expected_incomes.list",
                request.user_id,
                {},
            )
            if err:
                errors.append(err)
                dataset["expected_incomes"] = {"items": []}
            else:
                dataset["expected_incomes"] = {"items": payload.get("items") or []}

        if "user_context" in request.data_types:
            context, context_errors = self._build_user_context(request.user_id)
            dataset["user_context"] = context
            errors.extend(context_errors)

        if "category_profiles" in request.data_types:
            dataset["category_profiles"] = _load_category_profiles_reference()
            errors.append(
                ResponseError(
                    code="CATEGORY_PROFILES_STATIC",
                    message="category_profiles served from static reference mapping until backend RPC exists",
                )
            )

        if "existing_financial_analysis_result" in request.data_types:
            dataset["existing_financial_analysis_result"] = None

        return dataset, errors

    def _fetch_transactions(
        self,
        user_id: str,
        period: Period | None,
        filters_payload: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], ResponseError | None, int | None]:
        if period is None:
            return [], ResponseError(code="MISSING_PERIOD", message="period is required for transactions fetch"), None
        payload = {
            **filters_payload,
            "date_from": period.start_date,
            "date_to": period.end_date,
        }
        result, err = self._fetch_paginated(self._finance_queue, "transactions.list", user_id, payload)
        if err:
            return [], err, None
        items = result.get("items") or []
        pagination = result.get("pagination") or {}
        total = pagination.get("total")
        return items, None, int(total) if total is not None else len(items)

    def _fetch_paginated(
        self,
        queue: str,
        message_type: str,
        user_id: str,
        base_payload: dict[str, Any],
    ) -> tuple[dict[str, Any], ResponseError | None]:
        items: list[dict[str, Any]] = []
        page = 1
        total = 0
        while True:
            payload = {**base_payload, "page": page, "page_size": PAGE_SIZE}
            reply_payload, err = self._rpc(queue, message_type, payload, user_id)
            if err:
                return {"items": items, "pagination": {"page": page, "page_size": PAGE_SIZE, "total": total}}, err
            page_items = reply_payload.get("items") or []
            if not isinstance(page_items, list):
                return {"items": items}, ResponseError(
                    code="RPC_INVALID_PAYLOAD",
                    message=f"{message_type} returned invalid items",
                )
            items.extend(page_items)
            pagination = reply_payload.get("pagination") or {}
            total = int(pagination.get("total") or len(items))
            logger.info(
                "rpc_fetch_page queue=%s message_type=%s user_id=%s page=%s page_items=%s running_total=%s reported_total=%s",
                queue,
                message_type,
                user_id,
                page,
                len(page_items),
                len(items),
                total,
            )
            if page * PAGE_SIZE >= total or not page_items:
                break
            page += 1
        return {"items": items, "pagination": {"page": page, "page_size": PAGE_SIZE, "total": total}}, None

    def _rpc(
        self,
        queue: str,
        message_type: str,
        payload: dict[str, Any],
        user_id: str,
    ) -> tuple[dict[str, Any], ResponseError | None]:
        try:
            reply = self._bus.request(
                queue,
                message_type,
                payload,
                user=UserContext(id=user_id),
                timeout_seconds=self._timeout,
            )
        except Exception as exc:
            logger.warning(
                "rpc_call_failed queue=%s message_type=%s user_id=%s error=%s",
                queue,
                message_type,
                user_id,
                exc.__class__.__name__,
            )
            return {}, ResponseError(
                code=_rpc_error_code(queue),
                message=f"{message_type} failed: {exc}",
            )
        if not reply.get("ok"):
            detail = reply.get("error") or f"{message_type} failed"
            logger.warning(
                "rpc_call_error queue=%s message_type=%s user_id=%s status_code=%s detail=%s",
                queue,
                message_type,
                user_id,
                reply.get("status_code"),
                detail,
            )
            return {}, ResponseError(code=_rpc_error_code(queue), message=str(detail))
        return reply.get("payload") or {}, None

    def _build_user_context(self, user_id: str) -> tuple[dict[str, Any], list[ResponseError]]:
        errors: list[ResponseError] = []
        accounts_items: list[dict[str, Any]] = []
        goals_items: list[dict[str, Any]] = []
        incomes_items: list[dict[str, Any]] = []

        tasks = {
            "accounts": (self._finance_queue, "accounts.list", {}),
            "goals": (self._finance_queue, "goals.list", {}),
            "incomes": (self._analytics_queue, "analytics.expected_incomes.list", {}),
        }

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(self._fetch_paginated, queue, msg_type, user_id, payload): key
                for key, (queue, msg_type, payload) in tasks.items()
            }
            for future in as_completed(futures):
                key = futures[future]
                try:
                    payload, err = future.result()
                except Exception as exc:
                    errors.append(
                        ResponseError(
                            code="USER_CONTEXT_FETCH_FAILED",
                            message=f"Failed to fetch {key} for user_context: {exc}",
                        )
                    )
                    continue
                if err:
                    errors.append(err)
                    continue
                items = payload.get("items") or []
                if key == "accounts":
                    accounts_items = items
                elif key == "goals":
                    goals_items = items
                else:
                    incomes_items = items

        current_balance = _sum_decimal_field(accounts_items, "current_balance")
        stable_income = _max_decimal_field(incomes_items, "expected_amount")
        active_goal = _first_active_goal(goals_items)

        context: dict[str, Any] = {
            "currentSavings": None,
            "stableMonthlyIncome": stable_income,
            "hasDebt": None,
            "monthlyDebtPayment": None,
            "debtAmount": None,
            "financialGoal": active_goal.get("title") if active_goal else None,
            "goalAmount": active_goal.get("target_amount") if active_goal else None,
            "goalDeadlineMonths": _goal_deadline_months(active_goal),
            "salaryDay": None,
            "currentBalance": current_balance,
        }

        if context["currentSavings"] is None and context["salaryDay"] is None and context["hasDebt"] is None:
            errors.append(
                ResponseError(
                    code="USER_CONTEXT_GAPS",
                    message="currentSavings, hasDebt, salaryDay are not available in backend",
                )
            )

        return context, errors


def _filters_to_payload(filters: TransactionFilters | None) -> dict[str, Any]:
    if filters is None:
        return {}
    payload: dict[str, Any] = {}
    direction = filters.direction
    if direction == "expense":
        payload["type"] = "expense"
    elif direction == "income":
        payload["type"] = "income"
    if filters.categories:
        payload["categories"] = filters.categories
    if filters.mcc:
        payload["mcc"] = filters.mcc
    if filters.account_id:
        payload["account_id"] = filters.account_id
    if filters.card_last4:
        payload["card_last4"] = [filters.card_last4]
    return payload


def _rpc_error_code(queue: str) -> str:
    if "analytics" in queue:
        return "ANALYTICS_RPC_ERROR"
    return "FINANCE_RPC_ERROR"


def _load_category_profiles_reference() -> list[dict[str, Any]]:
    with _REFERENCE_PATH.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, list):
        return data
    return []


def _parse_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _sum_decimal_field(items: list[dict[str, Any]], field: str) -> str | None:
    total = Decimal("0")
    found = False
    for item in items:
        parsed = _parse_decimal(item.get(field))
        if parsed is not None:
            total += parsed
            found = True
    if not found:
        return None
    return format(total, "f")


def _max_decimal_field(items: list[dict[str, Any]], field: str) -> str | None:
    values = [_parse_decimal(item.get(field)) for item in items]
    decimals = [value for value in values if value is not None]
    if not decimals:
        return None
    return format(max(decimals), "f")


def _first_active_goal(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in items:
        if item.get("status") == "active":
            return item
    return items[0] if items else None


def _goal_deadline_months(goal: dict[str, Any] | None) -> int | None:
    if not goal:
        return None
    target_date_raw = goal.get("target_date")
    if not target_date_raw:
        return None
    try:
        if isinstance(target_date_raw, str):
            target_date = datetime.fromisoformat(target_date_raw.replace("Z", "+00:00")).date()
        elif isinstance(target_date_raw, date):
            target_date = target_date_raw
        else:
            return None
    except ValueError:
        return None
    today = datetime.now(UTC).date()
    months = (target_date.year - today.year) * 12 + (target_date.month - today.month)
    return max(months, 0)
