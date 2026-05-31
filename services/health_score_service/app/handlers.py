from __future__ import annotations

from calendar import monthrange
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import UUID

from common.messaging import MessageError, UserContext, require_user
from sqlalchemy import text

from services.health_score_service.app.runtime import ANALYTICS_QUEUE, FINANCE_QUEUE, SessionLocal, bus

MONEY_ZERO = Decimal("0")
PERCENT_ZERO = Decimal("0")
OPTIONAL_CATEGORY_MARKERS = ("restaurant", "fastfood", "market", "subscription", "рестор", "фастфуд", "маркет", "подпис")
UNCLEAR_CATEGORY_MARKERS = ("transfer", "cash", "unknown", "перевод", "налич", "проч", "unknown", "")
CREDIT_CATEGORY_MARKERS = ("credit", "loan", "кредит", "займ")
MANDATORY_CATEGORY_MARKERS = ("utility", "rent", "supermarket", "grocery", "жкх", "аренд", "супермаркет", "продукт", "кредит")


def handle_profile_get(payload: dict, envelope: dict) -> dict:
    user = require_user(envelope)
    period = _period(payload.get("period"))
    refresh = bool(payload.get("refresh"))
    if not refresh:
        cached = _load_snapshot(UUID(user.id), period)
        if cached is not None:
            return cached
    return _calculate_and_store(UserContext(id=user.id, email=user.email), period)


def handle_score_get(payload: dict, envelope: dict) -> dict:
    profile = handle_profile_get(payload, envelope)
    return {
        "period": profile["period"],
        "financial_health_score": profile["financial_health_score"],
        "financial_health_status": profile["financial_health_status"],
        "credit_load_index": profile["credit_load_index"],
        "credit_load_zone": profile["credit_load_zone"],
        "credit_load_index_partial": profile["credit_load_index_partial"],
        "top_risk_drivers": profile["top_risk_drivers"],
        "data_gaps": profile["data_gaps"],
        "calculated_at": profile["calculated_at"],
    }


def handle_history_list(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    page, page_size = _page(payload)
    with SessionLocal() as db:
        rows = db.execute(
            text(
                """
                select period, financial_health_score, financial_health_status,
                       credit_load_index, credit_load_zone, calculated_at
                from health_score_snapshots
                where user_id = :user_id
                order by period desc
                offset :offset limit :limit
                """
            ),
            {"user_id": user_id, "offset": (page - 1) * page_size, "limit": page_size},
        ).mappings().all()
        total = db.scalar(
            text("select count(*) from health_score_snapshots where user_id = :user_id"),
            {"user_id": user_id},
        )
    return {
        "items": [_serialize_row(row) for row in rows],
        "pagination": {"page": page, "page_size": page_size, "total": total or 0},
    }


def _calculate_and_store(user: UserContext, period: str) -> dict:
    period_start, period_end = _period_bounds(period)
    transactions = _list_all_transactions(user, period_start, period_end)
    previous_transactions = _list_all_transactions(user, period_start - timedelta(days=92), period_start - timedelta(days=1))
    sums = _rpc(FINANCE_QUEUE, "transactions.sum_by_scope", _period_payload(period_start, period_end), user)
    accounts = _items(_rpc(FINANCE_QUEUE, "accounts.list", {"page": 1, "page_size": 500}, user))
    limits = _items(_rpc(FINANCE_QUEUE, "limits.list", {"page": 1, "page_size": 500}, user))
    goals = _items(_rpc(FINANCE_QUEUE, "goals.list", {"page": 1, "page_size": 500}, user))
    balance_before = _rpc(FINANCE_QUEUE, "finance.balance_before_period", {"period_start": period_start.isoformat()}, user)
    available = _safe_rpc(
        ANALYTICS_QUEUE,
        "analytics.available_balance.get",
        {"period_start": period_start.isoformat(), "period_end": period_end.isoformat()},
        user,
    )
    expected_incomes = _items(_safe_rpc(ANALYTICS_QUEUE, "analytics.expected_incomes.list", {"page": 1, "page_size": 500}, user))
    expected_expenses = _items(_safe_rpc(ANALYTICS_QUEUE, "analytics.expected_expenses.list", {"page": 1, "page_size": 500}, user))
    regular_expenses = _items(_safe_rpc(ANALYTICS_QUEUE, "analytics.regular_expenses.list", {"page": 1, "page_size": 500}, user))

    profile = _build_profile(
        period=period,
        period_start=period_start,
        period_end=period_end,
        transactions=transactions,
        previous_transactions=previous_transactions,
        sums=sums,
        accounts=accounts,
        limits=limits,
        goals=goals,
        balance_before=balance_before,
        available=available,
        expected_incomes=expected_incomes,
        expected_expenses=expected_expenses,
        regular_expenses=regular_expenses,
    )
    _store_snapshot(UUID(user.id), period, profile)
    return profile


def _build_profile(
    *,
    period: str,
    period_start: date,
    period_end: date,
    transactions: list[dict],
    previous_transactions: list[dict],
    sums: dict,
    accounts: list[dict],
    limits: list[dict],
    goals: list[dict],
    balance_before: dict,
    available: dict,
    expected_incomes: list[dict],
    expected_expenses: list[dict],
    regular_expenses: list[dict],
) -> dict:
    data_gaps: list[dict[str, str]] = []
    total_income = _money(sums.get("income_total"))
    total_expenses = abs(_money(sums.get("expense_total")))
    if total_income == 0:
        data_gaps.append({"field": "expense_to_income_ratio", "reason": "No income transactions for the period."})

    category_expenses = _category_expenses(transactions)
    category_limits = _category_limits(category_expenses, limits)
    optional_expenses = _sum_by_markers(category_expenses, OPTIONAL_CATEGORY_MARKERS)
    unclear_expenses = _sum_by_markers(category_expenses, UNCLEAR_CATEGORY_MARKERS)
    credit_payments = _sum_by_markers(category_expenses, CREDIT_CATEGORY_MARKERS)
    fixed_expenses = sum(
        (
            _money(row.get("expected_amount") if row.get("expected_amount") is not None else row.get("average_amount"))
            for row in regular_expenses
            if row.get("status") in {None, "active"}
        ),
        MONEY_ZERO,
    )
    variable_expenses = max(total_expenses - fixed_expenses, MONEY_ZERO)
    mandatory_expenses = fixed_expenses + _sum_by_markers(category_expenses, MANDATORY_CATEGORY_MARKERS)
    net_cashflow = total_income - total_expenses
    expense_to_income_ratio = _percent(total_expenses, total_income)
    savings_rate = _percent(net_cashflow, total_income)
    elapsed_days = _elapsed_days(period_start, period_end)
    days_in_period = monthrange(period_start.year, period_start.month)[1]
    days_remaining = max(days_in_period - elapsed_days, 1)
    average_daily_expense = total_expenses / Decimal(elapsed_days)
    forecast_expenses = average_daily_expense * Decimal(days_in_period)
    actual_balance = _money(balance_before.get("actual_balance"))
    forecast_balance = actual_balance + total_income - forecast_expenses
    available_amount = _money(available.get("available_amount")) if available else forecast_balance
    safe_daily_budget = max(available_amount / Decimal(days_remaining), MONEY_ZERO)
    reserve_base = mandatory_expenses if mandatory_expenses > 0 else total_expenses
    current_balance = sum((_money(row.get("current_balance")) for row in accounts), MONEY_ZERO)
    reserve_months = (current_balance / reserve_base) if reserve_base > 0 else None

    clarity_score = Decimal("100") - _percent(unclear_expenses, total_expenses, default=PERCENT_ZERO)
    budget_score = _budget_score(category_limits, data_gaps)
    goal_metrics, goal_score = _goal_metrics(goals, net_cashflow, data_gaps)
    income_stability_score = _income_stability(transactions + previous_transactions, data_gaps)
    debt_to_income_ratio = _percent(credit_payments, total_income)
    active_credits_count = _active_credit_count(transactions + previous_transactions)
    credit_load_index = _credit_load_index(debt_to_income_ratio, net_cashflow, credit_payments, active_credits_count)

    components = {
        "cashflow_score": _cashflow_score(net_cashflow, total_income, data_gaps),
        "debt_score": _debt_score(debt_to_income_ratio, data_gaps),
        "reserve_score": _reserve_score(reserve_months, data_gaps),
        "budget_score": budget_score,
        "clarity_score": _clamp(clarity_score),
        "goal_score": goal_score,
        "income_stability_score": income_stability_score,
    }
    weights = {
        "cashflow_score": Decimal("0.25"),
        "debt_score": Decimal("0.20"),
        "reserve_score": Decimal("0.15"),
        "budget_score": Decimal("0.15"),
        "clarity_score": Decimal("0.10"),
        "goal_score": Decimal("0.10"),
        "income_stability_score": Decimal("0.05"),
    }
    financial_score, weights_applied = _weighted_score(components, weights)
    if financial_score is None:
        financial_score = Decimal("0")

    profile = {
        "period": period,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "total_income": _decimal_str(total_income),
        "total_expenses": _decimal_str(total_expenses),
        "net_cashflow": _decimal_str(net_cashflow),
        "expense_to_income_ratio": _optional_decimal(expense_to_income_ratio),
        "savings_rate": _optional_decimal(savings_rate),
        "expense_progress": _optional_decimal(_clamp(expense_to_income_ratio) if expense_to_income_ratio is not None else None),
        "category_expenses": [{"category_name": name, "amount": _decimal_str(amount)} for name, amount in category_expenses.items()],
        "category_shares": _category_shares(category_expenses, total_expenses),
        "category_overspend": category_limits,
        "unclear_expenses": _decimal_str(unclear_expenses),
        "clarity_score": _decimal_str(_clamp(clarity_score)),
        "optional_expenses": _decimal_str(optional_expenses),
        "fixed_expenses": _decimal_str(fixed_expenses),
        "variable_expenses": _decimal_str(variable_expenses),
        "saving_potential_soft": _decimal_str(optional_expenses * Decimal("0.10")),
        "saving_potential_normal": _decimal_str(optional_expenses * Decimal("0.20")),
        "saving_potential_hard": _decimal_str(optional_expenses * Decimal("0.30")),
        "average_daily_expense": _decimal_str(average_daily_expense),
        "forecast_expenses": _decimal_str(forecast_expenses),
        "forecast_balance": _decimal_str(forecast_balance),
        "safe_daily_budget": _decimal_str(safe_daily_budget),
        "goal_progress": goal_metrics.get("goal_progress"),
        "required_monthly_saving": goal_metrics.get("required_monthly_saving"),
        "goal_affordability": goal_metrics.get("goal_affordability"),
        "reserve_months": _optional_decimal(reserve_months),
        "income_stability_score": _optional_decimal(income_stability_score),
        "monthly_credit_payments": _decimal_str(credit_payments),
        "debt_to_income_ratio": _optional_decimal(debt_to_income_ratio),
        "active_credits_count": active_credits_count,
        "credit_load_index": _decimal_str(credit_load_index),
        "credit_load_zone": _credit_zone(credit_load_index),
        "credit_load_index_partial": True,
        "financial_health_score": _decimal_str(financial_score),
        "financial_health_status": _health_status(financial_score),
        "score_components": {key: _optional_decimal(value) for key, value in components.items()},
        "weights_applied": {key: _decimal_str(value) for key, value in weights_applied.items()},
        "expected_incomes": expected_incomes,
        "expected_expenses": expected_expenses,
        "data_gaps": data_gaps + [
            {"field": "credit_card_utilization", "reason": "No credit-card limit and balance source is available in MVP."},
            {"field": "overdue_days", "reason": "No overdue debt data source is available in MVP."},
            {"field": "overdue_score", "reason": "No overdue debt data source is available in MVP."},
            {"field": "credit_card_utilization_score", "reason": "No credit-card utilization source is available in MVP."},
        ],
        "top_risk_drivers": _risk_drivers(components, credit_load_index),
        "calculated_at": datetime.now(UTC).isoformat(),
    }
    return profile


def _list_all_transactions(user: UserContext, period_start: date, period_end: date) -> list[dict]:
    page = 1
    items: list[dict] = []
    while True:
        payload = {**_period_payload(period_start, period_end), "page": page, "page_size": 500}
        reply = _rpc(FINANCE_QUEUE, "transactions.list", payload, user)
        batch = reply.get("items") or []
        items.extend(batch)
        pagination = reply.get("pagination") or {}
        if page * int(pagination.get("page_size") or 500) >= int(pagination.get("total") or len(items)):
            return items
        page += 1


def _load_snapshot(user_id: UUID, period: str) -> dict | None:
    with SessionLocal() as db:
        row = db.execute(
            text(
                """
                select profile_json
                from health_score_snapshots
                where user_id = :user_id and period = :period
                """
            ),
            {"user_id": user_id, "period": period},
        ).mappings().first()
    return dict(row["profile_json"]) if row else None


def _store_snapshot(user_id: UUID, period: str, profile: dict) -> None:
    with SessionLocal() as db:
        db.execute(
            text(
                """
                insert into health_score_snapshots(
                  user_id, period, financial_health_score, credit_load_index,
                  financial_health_status, credit_load_zone, profile_json,
                  score_components, calculated_at
                )
                values (
                  :user_id, :period, :financial_health_score, :credit_load_index,
                  :financial_health_status, :credit_load_zone, cast(:profile_json as jsonb),
                  cast(:score_components as jsonb), :calculated_at
                )
                on conflict (user_id, period) do update set
                  financial_health_score = excluded.financial_health_score,
                  credit_load_index = excluded.credit_load_index,
                  financial_health_status = excluded.financial_health_status,
                  credit_load_zone = excluded.credit_load_zone,
                  profile_json = excluded.profile_json,
                  score_components = excluded.score_components,
                  calculated_at = excluded.calculated_at
                """
            ),
            {
                "user_id": user_id,
                "period": period,
                "financial_health_score": Decimal(profile["financial_health_score"]),
                "credit_load_index": Decimal(profile["credit_load_index"]),
                "financial_health_status": profile["financial_health_status"],
                "credit_load_zone": profile["credit_load_zone"],
                "profile_json": _json(profile),
                "score_components": _json(profile["score_components"]),
                "calculated_at": _parse_datetime(profile["calculated_at"]),
            },
        )
        db.commit()


def _rpc(queue: str, message_type: str, payload: dict, user: UserContext) -> dict:
    reply = bus.request(queue, message_type, payload, user=user, timeout_seconds=30.0)
    if not reply.get("ok"):
        raise MessageError(int(reply.get("status_code") or 502), reply.get("error") or f"{message_type} failed")
    return reply.get("payload") or {}


def _safe_rpc(queue: str, message_type: str, payload: dict, user: UserContext) -> dict:
    reply = bus.request(queue, message_type, payload, user=user, timeout_seconds=20.0)
    return reply.get("payload") or {} if reply.get("ok") else {}


def _period(raw: Any) -> str:
    if raw is None or raw == "":
        today = datetime.now(UTC).date()
        return f"{today.year:04d}-{today.month:02d}"
    value = str(raw)
    if len(value) != 7 or value[4] != "-":
        raise MessageError(422, "period must use YYYY-MM format")
    year, month = int(value[:4]), int(value[5:])
    if month < 1 or month > 12:
        raise MessageError(422, "period month must be between 01 and 12")
    return f"{year:04d}-{month:02d}"


def _period_bounds(period: str) -> tuple[date, date]:
    year, month = int(period[:4]), int(period[5:])
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def _period_payload(period_start: date, period_end: date) -> dict:
    return {"date_from": period_start.isoformat(), "date_to": period_end.isoformat()}


def _page(payload: dict) -> tuple[int, int]:
    page = max(int(payload.get("page") or 1), 1)
    page_size = min(max(int(payload.get("page_size") or 50), 1), 500)
    return page, page_size


def _items(payload: dict) -> list[dict]:
    return list(payload.get("items") or [])


def _money(value: Any) -> Decimal:
    if value is None or value == "":
        return MONEY_ZERO
    return Decimal(str(value))


def _percent(numerator: Decimal, denominator: Decimal, *, default: Decimal | None = None) -> Decimal | None:
    if denominator == 0:
        return default
    return (numerator / denominator) * Decimal("100")


def _category_expenses(transactions: list[dict]) -> dict[str, Decimal]:
    result: dict[str, Decimal] = {}
    for transaction in transactions:
        if transaction.get("type") != "expense":
            continue
        name = str(transaction.get("category_name") or "Unclear")
        result[name] = result.get(name, MONEY_ZERO) + abs(_money(transaction.get("operation_amount")))
    return dict(sorted(result.items(), key=lambda item: item[1], reverse=True))


def _category_limits(category_expenses: dict[str, Decimal], limits: list[dict]) -> list[dict]:
    result: list[dict] = []
    if not limits:
        return result
    category_id_limits = {str(row.get("category_id")): _money(row.get("limit_amount")) for row in limits if row.get("category_id")}
    if not category_id_limits:
        return result
    return result


def _category_shares(category_expenses: dict[str, Decimal], total_expenses: Decimal) -> list[dict]:
    return [
        {"category_name": name, "share": _optional_decimal(_percent(amount, total_expenses, default=PERCENT_ZERO))}
        for name, amount in category_expenses.items()
    ]


def _sum_by_markers(category_expenses: dict[str, Decimal], markers: tuple[str, ...]) -> Decimal:
    total = MONEY_ZERO
    for name, amount in category_expenses.items():
        lower = name.lower()
        if any(marker in lower for marker in markers):
            total += amount
    return total


def _budget_score(category_limits: list[dict], data_gaps: list[dict[str, str]]) -> Decimal | None:
    if not category_limits:
        data_gaps.append({"field": "budget_score", "reason": "No active category limits are available for the period."})
        return None
    over_ratio = sum((Decimal(str(row.get("overspend_ratio") or "0")) for row in category_limits), PERCENT_ZERO)
    return _clamp(Decimal("100") - over_ratio)


def _goal_metrics(goals: list[dict], net_cashflow: Decimal, data_gaps: list[dict[str, str]]) -> tuple[dict[str, str | None], Decimal | None]:
    active_goals = [goal for goal in goals if goal.get("status") in {None, "active"}]
    if not active_goals:
        data_gaps.append({"field": "goal_score", "reason": "No active savings goals are available."})
        return {"goal_progress": None, "required_monthly_saving": None, "goal_affordability": None}, None
    goal = active_goals[0]
    target = _money(goal.get("target_amount"))
    current = _money(goal.get("current_amount"))
    remaining = max(target - current, MONEY_ZERO)
    progress = _percent(current, target, default=Decimal("100"))
    required = remaining
    if goal.get("target_date"):
        target_date = date.fromisoformat(str(goal["target_date"]))
        months = max(((target_date.year - date.today().year) * 12 + target_date.month - date.today().month), 1)
        required = remaining / Decimal(months)
    affordability = _percent(net_cashflow, required, default=Decimal("100")) if required > 0 else Decimal("100")
    score = (_clamp(progress or PERCENT_ZERO) * Decimal("0.60")) + (_clamp(affordability or PERCENT_ZERO) * Decimal("0.40"))
    return {
        "goal_progress": _optional_decimal(progress),
        "required_monthly_saving": _decimal_str(required),
        "goal_affordability": _optional_decimal(affordability),
    }, _clamp(score)


def _income_stability(transactions: list[dict], data_gaps: list[dict[str, str]]) -> Decimal | None:
    monthly: dict[str, Decimal] = {}
    for transaction in transactions:
        if transaction.get("type") != "income":
            continue
        operation_at = _parse_datetime(str(transaction.get("operation_at")))
        key = f"{operation_at.year:04d}-{operation_at.month:02d}"
        monthly[key] = monthly.get(key, MONEY_ZERO) + abs(_money(transaction.get("operation_amount")))
    values = [value for value in monthly.values() if value > 0]
    if len(values) < 2:
        data_gaps.append({"field": "income_stability_score", "reason": "At least two income months are required."})
        return None
    average = sum(values, MONEY_ZERO) / Decimal(len(values))
    variance = sum(((value - average) ** 2 for value in values), MONEY_ZERO) / Decimal(len(values))
    coefficient = (variance.sqrt() / average) if average > 0 else Decimal("1")
    return _clamp(((Decimal("0.50") - coefficient) / Decimal("0.50")) * Decimal("100"))


def _cashflow_score(net_cashflow: Decimal, total_income: Decimal, data_gaps: list[dict[str, str]]) -> Decimal | None:
    if total_income == 0:
        data_gaps.append({"field": "cashflow_score", "reason": "No income transactions for the period."})
        return None
    ratio = net_cashflow / total_income
    return _clamp(((ratio + Decimal("0.10")) / Decimal("0.30")) * Decimal("100"))


def _debt_score(debt_to_income_ratio: Decimal | None, data_gaps: list[dict[str, str]]) -> Decimal | None:
    if debt_to_income_ratio is None:
        data_gaps.append({"field": "debt_score", "reason": "No income is available to calculate debt-to-income ratio."})
        return None
    return _clamp(Decimal("100") - ((debt_to_income_ratio - Decimal("10")) / Decimal("40") * Decimal("100")))


def _reserve_score(reserve_months: Decimal | None, data_gaps: list[dict[str, str]]) -> Decimal | None:
    if reserve_months is None:
        data_gaps.append({"field": "reserve_score", "reason": "No expense base is available to calculate reserve months."})
        return None
    return _clamp((reserve_months / Decimal("3")) * Decimal("100"))


def _weighted_score(components: dict[str, Decimal | None], weights: dict[str, Decimal]) -> tuple[Decimal | None, dict[str, Decimal]]:
    available = {key: value for key, value in components.items() if value is not None}
    total_weight = sum((weights[key] for key in available), PERCENT_ZERO)
    if total_weight == 0:
        return None, {}
    applied: dict[str, Decimal] = {}
    score = PERCENT_ZERO
    for key, value in available.items():
        weight = weights[key] / total_weight
        applied[key] = weight
        score += value * weight
    return _clamp(score), applied


def _credit_load_index(
    debt_to_income_ratio: Decimal | None,
    net_cashflow: Decimal,
    credit_payments: Decimal,
    active_credits_count: int,
) -> Decimal:
    components: list[tuple[Decimal, Decimal]] = []
    if debt_to_income_ratio is not None:
        components.append((Decimal("0.55"), _clamp((debt_to_income_ratio / Decimal("50")) * Decimal("100"))))
    free_after_debt = net_cashflow - credit_payments
    if credit_payments > 0:
        components.append((Decimal("0.10"), Decimal("100") if free_after_debt < 0 else Decimal("25")))
    components.append((Decimal("0.05"), _clamp(Decimal(active_credits_count) * Decimal("25"))))
    total_weight = sum((weight for weight, _ in components), PERCENT_ZERO)
    return _clamp(sum((score * (weight / total_weight) for weight, score in components), PERCENT_ZERO))


def _active_credit_count(transactions: list[dict]) -> int:
    names = {
        str(transaction.get("description") or transaction.get("category_name") or "credit").lower()
        for transaction in transactions
        if transaction.get("type") == "expense"
        and any(marker in str(transaction.get("category_name") or "").lower() for marker in CREDIT_CATEGORY_MARKERS)
    }
    return len(names)


def _risk_drivers(components: dict[str, Decimal | None], credit_load_index: Decimal) -> list[str]:
    drivers = [key for key, value in sorted(components.items(), key=lambda item: item[1] if item[1] is not None else Decimal("999")) if value is not None and value < 60]
    if credit_load_index > 50:
        drivers.append("credit_load_index")
    return drivers[:5]


def _health_status(score: Decimal) -> str:
    if score >= 80:
        return "good"
    if score >= 60:
        return "stable_with_growth_areas"
    if score >= 40:
        return "needs_control"
    if score >= 20:
        return "survival_mode"
    return "alert"


def _credit_zone(score: Decimal) -> str:
    if score <= 25:
        return "green"
    if score <= 50:
        return "yellow"
    if score <= 75:
        return "orange"
    return "red"


def _elapsed_days(period_start: date, period_end: date) -> int:
    today = datetime.now(UTC).date()
    effective_end = min(max(today, period_start), period_end)
    return max((effective_end - period_start).days + 1, 1)


def _clamp(value: Decimal | None, low: Decimal = Decimal("0"), high: Decimal = Decimal("100")) -> Decimal:
    if value is None:
        return low
    return min(max(value, low), high)


def _optional_decimal(value: Decimal | None) -> str | None:
    return None if value is None else _decimal_str(value)


def _decimal_str(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _serialize_row(row: Any) -> dict:
    result: dict[str, Any] = {}
    for key, value in dict(row).items():
        if isinstance(value, Decimal):
            result[key] = _decimal_str(value)
        elif isinstance(value, UUID):
            result[key] = str(value)
        elif hasattr(value, "isoformat"):
            result[key] = value.isoformat()
        else:
            result[key] = value
    return result


def _json(payload: dict) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False, default=str)


MESSAGE_HANDLERS = {
    "health.profile.get": handle_profile_get,
    "health.score.get": handle_score_get,
    "health.history.list": handle_history_list,
    "health.profile.recalculate": handle_profile_get,
}
