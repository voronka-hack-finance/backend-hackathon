from __future__ import annotations

import calendar
from datetime import UTC, date, datetime

from services.backend_data_worker.app.schemas import BackendDataRequest, Period, TransactionFilters

TRANSACTION_DATA_TYPES = frozenset({"transactions", "previous_period_transactions"})


def _subtract_months(value: date, months: int) -> date:
    month_index = value.year * 12 + (value.month - 1) - months
    year = month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def default_period(*, end_date: date | None = None, months: int = 6) -> Period:
    end = end_date or datetime.now(UTC).date()
    start = _subtract_months(end, months)
    return Period(start_date=start.isoformat(), end_date=end.isoformat())


def normalize_transaction_filters(filters: TransactionFilters | None) -> TransactionFilters:
    if filters is None:
        return TransactionFilters()

    categories = [category.strip() for category in filters.categories if category and category.strip()]
    mcc = [code.strip() for code in filters.mcc if code and str(code).strip()]
    direction = None if filters.direction == "all" else filters.direction

    return filters.model_copy(
        update={
            "categories": categories,
            "mcc": mcc,
            "direction": direction,
        }
    )


def normalize_request(
    request: BackendDataRequest,
    *,
    default_period_months: int = 6,
) -> tuple[BackendDataRequest, list[str]]:
    notes: list[str] = []
    updates: dict[str, object] = {}

    needs_transactions = any(data_type in TRANSACTION_DATA_TYPES for data_type in request.data_types)
    if needs_transactions and request.period is None:
        updates["period"] = default_period(months=default_period_months)
        notes.append(f"period defaulted to last {default_period_months} months")

    normalized_filters = normalize_transaction_filters(request.transaction_filters)
    if normalized_filters != (request.transaction_filters or TransactionFilters()):
        if request.transaction_filters and request.transaction_filters.categories and not normalized_filters.categories:
            notes.append("category filter removed; fetching all categories")
        updates["transaction_filters"] = normalized_filters
    elif request.transaction_filters is None and needs_transactions:
        updates["transaction_filters"] = normalized_filters

    if not updates:
        return request, notes
    return request.model_copy(update=updates), notes
