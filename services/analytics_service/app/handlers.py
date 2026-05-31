from __future__ import annotations

import random
from decimal import Decimal
from datetime import UTC
from datetime import date
from datetime import datetime
from typing import Any
from uuid import UUID
from sqlalchemy import text
from common.messaging import MessageError, UserContext, require_user
from services.analytics_service.app.runtime import (
    SessionLocal,
    FINANCE_QUEUE,
    bus,
)

def handle_available_balance(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    period_start = _parse_date(payload.get("period_start")) or date.today()
    period_end = _parse_date(payload.get("period_end")) or period_start
    with SessionLocal() as db:
        actual_decimal = _actual_balance_at_period_start(db, user_id, period_start)
        income_decimal = _expected_income_total(db, user_id, period_start, period_end)
        expense_decimal = _expected_expense_total(db, user_id, period_start, period_end)
        available_decimal = actual_decimal + income_decimal - expense_decimal
        calculated_at = datetime.now(UTC)
        db.execute(
            text(
                """
                insert into available_funds_snapshots(
                  user_id, period_start, period_end, actual_balance,
                  expected_income_total, expected_expense_total, available_amount,
                  currency, calculated_at
                )
                values (
                  :user_id, :period_start, :period_end, :actual_balance,
                  :expected_income_total, :expected_expense_total, :available_amount,
                  'RUB', :calculated_at
                )
                """
            ),
            {
                "user_id": user_id,
                "period_start": period_start,
                "period_end": period_end,
                "actual_balance": actual_decimal,
                "expected_income_total": income_decimal,
                "expected_expense_total": expense_decimal,
                "available_amount": available_decimal,
                "calculated_at": calculated_at,
            },
        )
        db.commit()
    return {
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "actual_balance": _decimal_str(actual_decimal),
        "expected_income_total": _decimal_str(income_decimal),
        "expected_expense_total": _decimal_str(expense_decimal),
        "available_amount": _decimal_str(available_decimal),
        "currency": "RUB",
        "calculated_at": calculated_at.isoformat(),
    }


def handle_regular_expenses_detect(payload: dict, envelope: dict) -> dict:
    user = require_user(envelope)
    user_id = UUID(user.id)
    min_occurrences = max(int(payload.get("min_occurrences") or 2), 2)
    limit = min(max(int(payload.get("limit") or 25), 1), 100)
    finance_reply = _finance_request(
        "finance.expense_pattern_candidates",
        {"min_occurrences": min_occurrences, "limit": limit},
        user,
    )
    candidates = (finance_reply.get("payload") or {}).get("items") or []
    created = 0
    with SessionLocal() as db:
        for candidate in candidates:
            exists = db.scalar(
                text(
                    """
                    select 1
                    from regular_expenses
                    where user_id = :user_id
                      and merchant_pattern = :merchant_pattern
                      and status = 'active'
                    """
                ),
                {"user_id": user_id, "merchant_pattern": candidate["merchant_pattern"]},
            )
            if exists:
                continue
            db.execute(
                text(
                    """
                    insert into regular_expenses(
                      user_id, merchant_pattern, average_amount, expected_amount, currency,
                      frequency_days, next_expected_at, confidence, status, source_type
                    )
                    values (
                      :user_id, :merchant_pattern, :average_amount, :average_amount, :currency,
                      30, :next_expected_at, least(0.9500, cast(:occurrences as numeric) / 12.0), 'active', 'detected'
                    )
                    """
                ),
                {
                    "user_id": user_id,
                    "merchant_pattern": candidate["merchant_pattern"],
                    "average_amount": candidate["average_amount"],
                    "currency": candidate["currency"],
                    "next_expected_at": _parse_datetime(candidate["next_expected_at"]),
                    "occurrences": candidate["occurrences"],
                },
            )
            created += 1
        db.commit()
    return {"status": "detected", "candidates": len(candidates), "created": created}


def handle_regular_expenses_due_for_reminders(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    horizon_until = _parse_datetime(payload.get("horizon_until")) or datetime.now(UTC)
    limit = min(max(int(payload.get("limit") or 500), 1), 1000)
    with SessionLocal() as db:
        rows = db.execute(
            text(
                """
                select id, next_expected_at
                from regular_expenses
                where user_id = :user_id
                  and status = 'active'
                  and next_expected_at is not null
                  and next_expected_at <= :horizon_until
                order by next_expected_at
                limit :limit
                """
            ),
            {"user_id": user_id, "horizon_until": horizon_until, "limit": limit},
        ).mappings().all()
    return {"items": [_serialize(row) for row in rows], "pagination": None}


def handle_expected_incomes(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    page, page_size = _page(payload)
    with SessionLocal() as db:
        rows, total = _expected_income_rows(db, user_id, page, page_size)
    return {"items": [_serialize(row) for row in rows], "pagination": {"page": page, "page_size": page_size, "total": total or 0}}


def handle_expected_expenses(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    page, page_size = _page(payload)
    with SessionLocal() as db:
        rows, total = _expected_expense_rows(db, user_id, page, page_size)
    return {"items": [_serialize(row) for row in rows], "pagination": {"page": page, "page_size": page_size, "total": total or 0}}


def handle_regular_expenses_list(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    page, page_size = _page(payload)
    status = payload.get("status")
    params: dict[str, Any] = {"user_id": user_id, "offset": (page - 1) * page_size, "limit": page_size}
    status_sql = "and status <> 'deleted'"
    if status:
        status_sql = "and status = :status"
        params["status"] = str(status)
    with SessionLocal() as db:
        rows = db.execute(
            text(
                f"""
                select id, account_id, category_id, merchant_pattern, average_amount, expected_amount,
                       currency, frequency_days, next_expected_at, confidence,
                       status, source_type, created_at, updated_at
                from regular_expenses
                where user_id = :user_id
                  {status_sql}
                order by next_expected_at nulls last, average_amount desc
                offset :offset limit :limit
                """
            ),
            params,
        ).mappings().all()
        total = db.scalar(
            text(f"select count(*) from regular_expenses where user_id = :user_id {status_sql}"),
            params,
        )
    return {"items": [_serialize(row) for row in rows], "pagination": {"page": page, "page_size": page_size, "total": total or 0}}


def handle_regular_expenses_get(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    regular_expense_id = _required_uuid(payload.get("regular_expense_id") or payload.get("id"), "regular_expense_id")
    with SessionLocal() as db:
        row = _get_regular_expense(db, user_id, regular_expense_id)
    return _serialize(row)


def handle_regular_expenses_create(payload: dict, envelope: dict) -> dict:
    user = require_user(envelope)
    user_id = UUID(user.id)
    merchant_pattern = str(payload.get("merchant_pattern") or "").strip()
    if not merchant_pattern:
        raise MessageError(422, "merchant_pattern is required")
    expected_amount = _parse_decimal(
        payload.get("expected_amount") if payload.get("expected_amount") is not None else payload.get("average_amount")
    )
    if expected_amount is None:
        raise MessageError(422, "expected_amount is required")
    average_amount = _parse_decimal(payload.get("average_amount")) or expected_amount
    account_id = _resolve_regular_expense_account_id(user, payload.get("account_id"))
    category_id = _resolve_regular_expense_category_id(user, payload.get("category_id"))
    source_type = str(payload.get("source_type") or "manual")
    if source_type not in {"detected", "manual", "user_adjusted"}:
        raise MessageError(422, "source_type must be detected, manual, or user_adjusted")
    with SessionLocal() as db:
        row = db.execute(
            text(
                """
                insert into regular_expenses(
                  user_id, account_id, category_id, merchant_pattern, average_amount,
                  expected_amount, currency, frequency_days, next_expected_at,
                  confidence, status, source_type
                )
                values (
                  :user_id, :account_id, :category_id, :merchant_pattern, :average_amount,
                  :expected_amount, :currency, :frequency_days, :next_expected_at,
                  :confidence, :status, :source_type
                )
                returning id, account_id, category_id, merchant_pattern, average_amount,
                          expected_amount, currency, frequency_days, next_expected_at,
                          confidence, status, source_type, created_at, updated_at
                """
            ),
            {
                "user_id": user_id,
                "account_id": account_id,
                "category_id": category_id,
                "merchant_pattern": merchant_pattern,
                "average_amount": average_amount,
                "expected_amount": expected_amount,
                "currency": str(payload.get("currency") or "RUB"),
                "frequency_days": max(int(payload.get("frequency_days") or 30), 1),
                "next_expected_at": _parse_datetime(payload.get("next_expected_at")),
                "confidence": _parse_decimal(payload.get("confidence")) or Decimal("1.0000"),
                "status": str(payload.get("status") or "active"),
                "source_type": source_type,
            },
        ).mappings().one()
        db.commit()
    return _serialize(row)


def handle_regular_expenses_update(payload: dict, envelope: dict) -> dict:
    user = require_user(envelope)
    user_id = UUID(user.id)
    regular_expense_id = _required_uuid(payload.get("regular_expense_id") or payload.get("id"), "regular_expense_id")
    resolved_account_id = _resolve_regular_expense_account_id(user, payload.get("account_id")) if "account_id" in payload else None
    resolved_category_id = _resolve_regular_expense_category_id(user, payload.get("category_id")) if "category_id" in payload else None
    allowed = {
        "account_id",
        "category_id",
        "merchant_pattern",
        "average_amount",
        "expected_amount",
        "currency",
        "frequency_days",
        "next_expected_at",
        "confidence",
        "status",
        "source_type",
    }
    updates = {key: payload[key] for key in allowed if key in payload}
    if not updates:
        raise MessageError(422, "No regular expense fields to update")
    _coerce_regular_expense_updates(updates)
    if "account_id" in payload:
        updates["account_id"] = resolved_account_id
    if "category_id" in payload:
        updates["category_id"] = resolved_category_id
    with SessionLocal() as db:
        existing = _get_regular_expense(db, user_id, regular_expense_id)
        if "source_type" not in updates and existing["source_type"] == "detected":
            updates["source_type"] = "user_adjusted"
        set_sql = ", ".join(f"{field} = :{field}" for field in updates)
        row = db.execute(
            text(
                f"""
                update regular_expenses
                set {set_sql}, updated_at = now()
                where id = :regular_expense_id and user_id = :user_id
                returning id, account_id, category_id, merchant_pattern, average_amount,
                          expected_amount, currency, frequency_days, next_expected_at,
                          confidence, status, source_type, created_at, updated_at
                """
            ),
            {"regular_expense_id": regular_expense_id, "user_id": user_id, **updates},
        ).mappings().one()
        db.commit()
    return _serialize(row)


def handle_regular_expenses_delete(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    regular_expense_id = _required_uuid(payload.get("regular_expense_id") or payload.get("id"), "regular_expense_id")
    with SessionLocal() as db:
        _get_regular_expense(db, user_id, regular_expense_id)
        db.execute(
            text(
                """
                update regular_expenses
                set status = 'deleted',
                    source_type = case when source_type = 'detected' then 'user_adjusted' else source_type end,
                    updated_at = now()
                where id = :regular_expense_id and user_id = :user_id
                """
            ),
            {"regular_expense_id": regular_expense_id, "user_id": user_id},
        )
        db.commit()
    return {"status": "deleted"}


def handle_member_budget(payload: dict, envelope: dict) -> dict:
    return handle_available_balance(payload, envelope)


def handle_member_budget_batch(payload: dict, envelope: dict) -> dict:
    user_ids = payload.get("user_ids") or []
    if not isinstance(user_ids, list):
        raise MessageError(422, "user_ids must be a list")
    analytics_payload = {
        key: value
        for key, value in {
            "period_start": payload.get("period_start"),
            "period_end": payload.get("period_end"),
        }.items()
        if value
    }
    items = []
    for raw_user_id in user_ids:
        user_id = str(raw_user_id)
        budget = handle_available_balance(analytics_payload, {"user": {"id": user_id}})
        items.append({"user_id": user_id, "budget": budget})
    return {"items": items}


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _parse_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _optional_uuid(value: Any, field_name: str) -> UUID | None:
    if value is None or value == "":
        return None
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise MessageError(422, f"{field_name} must be a valid UUID") from exc


def _required_uuid(value: Any, field_name: str) -> UUID:
    parsed = _optional_uuid(value, field_name)
    if parsed is None:
        raise MessageError(422, f"{field_name} is required")
    return parsed


def _resolve_regular_expense_account_id(user: UserContext, value: Any) -> UUID:
    account_id = _optional_uuid(value, "account_id")
    if account_id is not None:
        try:
            _finance_request("accounts.get", {"account_id": str(account_id)}, user)
            return account_id
        except MessageError as exc:
            if exc.status_code == 404:
                raise MessageError(404, "Account not found") from exc
            raise
    reply = _finance_request("accounts.list", {"page": 1, "page_size": 500}, user)
    accounts = (reply.get("payload") or {}).get("items") or []
    if not accounts:
        raise MessageError(422, "account_id is required when the user has no accounts")
    return UUID(str(random.choice(accounts)["id"]))


def _resolve_regular_expense_category_id(user: UserContext, value: Any) -> UUID:
    category_id = _optional_uuid(value, "category_id")
    if category_id is not None:
        try:
            _finance_request("categories.get", {"category_id": str(category_id)}, user)
            return category_id
        except MessageError as exc:
            if exc.status_code == 404:
                raise MessageError(404, "Category not found") from exc
            raise
    reply = _finance_request("categories.list", {"page": 1, "page_size": 500}, user)
    categories = (reply.get("payload") or {}).get("items") or []
    for category in categories:
        if str(category.get("name") or "").casefold() == "другое".casefold():
            return UUID(str(category["id"]))
    created = _finance_request(
        "categories.create",
        {
            "name": "Другое",
            "description": "Категория по умолчанию для регулярных расходов без категории.",
            "icon_key": "more-horizontal",
        },
        user,
    )
    return UUID(str((created.get("payload") or {})["id"]))


def _get_regular_expense(db, user_id: UUID, regular_expense_id: UUID):
    row = db.execute(
        text(
            """
            select id, account_id, category_id, merchant_pattern, average_amount,
                   expected_amount, currency, frequency_days, next_expected_at,
                   confidence, status, source_type, created_at, updated_at
            from regular_expenses
            where id = :regular_expense_id and user_id = :user_id
            """
        ),
        {"regular_expense_id": regular_expense_id, "user_id": user_id},
    ).mappings().first()
    if row is None:
        raise MessageError(404, "Regular expense not found")
    return row


def _coerce_regular_expense_updates(updates: dict[str, Any]) -> None:
    if "merchant_pattern" in updates:
        updates["merchant_pattern"] = str(updates["merchant_pattern"]).strip()
        if not updates["merchant_pattern"]:
            raise MessageError(422, "merchant_pattern cannot be empty")
    for field in ("average_amount", "expected_amount", "confidence"):
        if field in updates:
            parsed = _parse_decimal(updates[field])
            if parsed is None:
                raise MessageError(422, f"{field} cannot be empty")
            updates[field] = parsed
    for field in ("account_id", "category_id"):
        if field in updates:
            updates[field] = _optional_uuid(updates[field], field)
    if "frequency_days" in updates:
        updates["frequency_days"] = max(int(updates["frequency_days"]), 1)
    if "next_expected_at" in updates:
        updates["next_expected_at"] = _parse_datetime(updates["next_expected_at"])
    if "source_type" in updates and updates["source_type"] not in {"detected", "manual", "user_adjusted"}:
        raise MessageError(422, "source_type must be detected, manual, or user_adjusted")


def _page(payload: dict) -> tuple[int, int]:
    page = max(int(payload.get("page") or 1), 1)
    page_size = min(max(int(payload.get("page_size") or 50), 1), 500)
    return page, page_size


def _actual_balance_at_period_start(db, user_id: UUID, period_start: date) -> Decimal:
    reply = _finance_request(
        "finance.balance_before_period",
        {"period_start": period_start.isoformat()},
        UserContext(id=str(user_id)),
    )
    return Decimal(str((reply.get("payload") or {}).get("actual_balance") or "0"))


def _expected_income_total(db, user_id: UUID, period_start: date, period_end: date) -> Decimal:
    stored = db.scalar(
        text(
            """
            select coalesce(sum(expected_amount), 0)
            from expected_incomes
            where user_id = :user_id
              and (expected_at is null or expected_at between :period_start and :period_end)
            """
        ),
        {"user_id": user_id, "period_start": period_start, "period_end": period_end},
    )
    if Decimal(str(stored or "0")) != 0:
        return Decimal(str(stored))
    reply = _finance_request(
        "finance.income_expected_candidates",
        {"period_start": period_start.isoformat(), "period_end": period_end.isoformat(), "page": 1, "page_size": 1000},
        UserContext(id=str(user_id)),
    )
    return sum((Decimal(str(row.get("expected_amount") or "0")) for row in (reply.get("payload") or {}).get("items") or []), Decimal("0"))


def _expected_expense_total(db, user_id: UUID, period_start: date, period_end: date) -> Decimal:
    stored = db.scalar(
        text(
            """
            select coalesce(sum(expected_amount), 0)
            from expected_expenses
            where user_id = :user_id
              and (expected_at is null or expected_at between :period_start and :period_end)
            """
        ),
        {"user_id": user_id, "period_start": period_start, "period_end": period_end},
    )
    if Decimal(str(stored or "0")) != 0:
        return Decimal(str(stored))
    derived = db.scalar(
        text(
            """
            select coalesce(sum(coalesce(expected_amount, average_amount)), 0)
            from regular_expenses
            where user_id = :user_id
              and status = 'active'
              and next_expected_at::date between :period_start and :period_end
            """
        ),
        {"user_id": user_id, "period_start": period_start, "period_end": period_end},
    )
    return Decimal(str(derived or "0"))


def _expected_income_rows(db, user_id: UUID, page: int, page_size: int):
    rows = db.execute(
        text(
            """
            select id, account_id, source_pattern, expected_amount, currency, expected_at,
                   confidence, created_at, updated_at
            from expected_incomes
            where user_id = :user_id
            order by expected_at nulls last, created_at desc
            offset :offset limit :limit
            """
        ),
        {"user_id": user_id, "offset": (page - 1) * page_size, "limit": page_size},
    ).mappings().all()
    total = db.scalar(text("select count(*) from expected_incomes where user_id = :user_id"), {"user_id": user_id})
    if rows or total:
        return rows, total or 0
    reply = _finance_request(
        "finance.income_expected_candidates",
        {"page": page, "page_size": page_size},
        UserContext(id=str(user_id)),
    )
    payload = reply.get("payload") or {}
    return payload.get("items") or [], (payload.get("pagination") or {}).get("total") or 0


def _expected_expense_rows(db, user_id: UUID, page: int, page_size: int):
    rows = db.execute(
        text(
            """
            select id, account_id, regular_expense_id, expected_amount, currency, expected_at,
                   confidence, created_at, updated_at
            from expected_expenses
            where user_id = :user_id
            order by expected_at nulls last, created_at desc
            offset :offset limit :limit
            """
        ),
        {"user_id": user_id, "offset": (page - 1) * page_size, "limit": page_size},
    ).mappings().all()
    total = db.scalar(text("select count(*) from expected_expenses where user_id = :user_id"), {"user_id": user_id})
    if rows or total:
        return rows, total or 0
    rows = db.execute(
        text(
            """
            select id,
                   account_id,
                   id as regular_expense_id,
                   coalesce(expected_amount, average_amount) as expected_amount,
                   currency,
                   next_expected_at::date as expected_at,
                   confidence,
                   created_at,
                   updated_at
            from regular_expenses
            where user_id = :user_id and status = 'active'
            order by next_expected_at nulls last, average_amount desc
            offset :offset limit :limit
            """
        ),
        {"user_id": user_id, "offset": (page - 1) * page_size, "limit": page_size},
    ).mappings().all()
    total = db.scalar(
        text("select count(*) from regular_expenses where user_id = :user_id and status = 'active'"),
        {"user_id": user_id},
    )
    return rows, total or 0


def _serialize(row) -> dict:
    return {key: _serialize_value(value) for key, value in dict(row).items()}


def _serialize_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _decimal_str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def _decimal_str(value: Decimal) -> str:
    return format(value, "f")


def _finance_request(message_type: str, payload: dict, user: UserContext):
    reply = bus.request(FINANCE_QUEUE, message_type, payload, user=user, timeout_seconds=30.0)
    if not reply.get("ok"):
        raise MessageError(int(reply.get("status_code") or 502), reply.get("error") or f"{message_type} failed")
    return reply


MESSAGE_HANDLERS = {
    "analytics.regular_expenses.detect": handle_regular_expenses_detect,
    "analytics.available_balance.get": handle_available_balance,
    "analytics.expected_incomes.list": handle_expected_incomes,
    "analytics.expected_expenses.list": handle_expected_expenses,
    "analytics.regular_expenses.list": handle_regular_expenses_list,
    "analytics.regular_expenses.get": handle_regular_expenses_get,
    "analytics.regular_expenses.create": handle_regular_expenses_create,
    "analytics.regular_expenses.update": handle_regular_expenses_update,
    "analytics.regular_expenses.delete": handle_regular_expenses_delete,
    "analytics.regular_expenses.due_for_reminders": handle_regular_expenses_due_for_reminders,
    "analytics.member_budget.get": handle_member_budget,
    "analytics.member_budget.batch": handle_member_budget_batch,
}
