from __future__ import annotations

from datetime import UTC, timedelta
from datetime import datetime
from typing import Any
from uuid import UUID
from sqlalchemy import text
from common.messaging import require_user
from services.scheduler_service.app.runtime import (
    engine,
    NOTIFICATION_QUEUE,
    ANALYTICS_QUEUE,
    FINANCE_QUEUE,
    bus,
)

def handle_plan_regular_expenses(payload: dict, envelope: dict) -> dict:
    user = require_user(envelope)
    user_id = UUID(user.id)
    horizon_until = datetime.now(UTC) + timedelta(days=int(payload.get("horizon_days") or 45))
    candidates = bus.request(
        ANALYTICS_QUEUE,
        "analytics.regular_expenses.due_for_reminders",
        {"horizon_until": horizon_until.isoformat(), "limit": payload.get("limit") or 500},
        user=user,
        timeout_seconds=30.0,
    )
    if not candidates.get("ok"):
        return {
            "status": "failed",
            "user_id": str(user_id),
            "created": 0,
            "error": candidates.get("error") or "analytics-service error",
        }
    created = 0
    with engine.begin() as connection:
        rows = (candidates.get("payload") or {}).get("items") or []
        for row in rows:
            scheduled_at = _parse_datetime(row.get("next_expected_at"))
            if scheduled_at is None:
                continue
            created += _insert_reminder_once(
                connection,
                user_id=user_id,
                regular_expense_id=UUID(str(row["id"])),
                category_limit_id=None,
                reminder_type="regular_expense",
                scheduled_at=scheduled_at,
            )
    return {"status": "planned", "user_id": str(user_id), "created": created}


def handle_plan_limit_warnings(payload: dict, envelope: dict) -> dict:
    user = require_user(envelope)
    user_id = UUID(user.id)
    horizon_until = datetime.now(UTC) + timedelta(days=int(payload.get("horizon_days") or 45))
    candidates = bus.request(
        FINANCE_QUEUE,
        "limits.due_warnings",
        {"horizon_until": horizon_until.isoformat(), "limit": payload.get("limit") or 500},
        user=user,
        timeout_seconds=30.0,
    )
    if not candidates.get("ok"):
        return {
            "status": "failed",
            "user_id": str(user_id),
            "created": 0,
            "error": candidates.get("error") or "finance-service error",
        }
    created = 0
    with engine.begin() as connection:
        rows = (candidates.get("payload") or {}).get("items") or []
        for row in rows:
            scheduled_at = _parse_datetime(row.get("scheduled_at"))
            if scheduled_at is None:
                continue
            created += _insert_reminder_once(
                connection,
                user_id=user_id,
                regular_expense_id=None,
                category_limit_id=UUID(str(row["id"])),
                reminder_type="category_limit_warning",
                scheduled_at=scheduled_at,
            )
    return {"status": "planned", "user_id": str(user_id), "created": created}


def handle_due_scan(payload: dict, envelope: dict) -> dict:
    limit = min(max(int(payload.get("limit") or 100), 1), 1000)
    user_id = _optional_user_id(payload, envelope)
    filters = "and user_id = :user_id" if user_id else ""
    params: dict[str, Any] = {"now": datetime.now(UTC), "limit": limit}
    if user_id:
        params["user_id"] = user_id
    queued = 0
    with engine.begin() as connection:
        rows = connection.execute(
            text(
                f"""
                select id, user_id, reminder_type
                from scheduled_reminders
                where status = 'planned'
                  and scheduled_at <= :now
                  {filters}
                order by scheduled_at
                limit :limit
                """
            ),
            params,
        ).mappings().all()
        for row in rows:
            bus.publish(
                NOTIFICATION_QUEUE,
                "notifications.send",
                {
                    "user_id": str(row["user_id"]),
                    "reminder_id": str(row["id"]),
                    "notification_type": row["reminder_type"],
                },
            )
            connection.execute(
                text("update scheduled_reminders set status = 'queued', updated_at = now() where id = :id"),
                {"id": row["id"]},
            )
            queued += 1
    return {"status": "scanned", "queued": queued}


def handle_notifications_schedule(payload: dict, envelope: dict) -> dict:
    user_id = _optional_user_id(payload, envelope) or UUID(require_user(envelope).id)
    scheduled_at = _parse_datetime(payload.get("scheduled_at")) or datetime.now(UTC)
    reminder_type = str(payload.get("reminder_type") or payload.get("notification_type") or "manual")
    with engine.begin() as connection:
        row = connection.execute(
            text(
                """
                insert into scheduled_reminders(
                  user_id, regular_expense_id, category_limit_id, reminder_type, status, scheduled_at
                )
                values (:user_id, :regular_expense_id, :category_limit_id, :reminder_type, 'planned', :scheduled_at)
                returning id, user_id, regular_expense_id, category_limit_id, reminder_type,
                          status, scheduled_at, sent_at, created_at, updated_at
                """
            ),
            {
                "user_id": user_id,
                "regular_expense_id": _optional_uuid(payload.get("regular_expense_id")),
                "category_limit_id": _optional_uuid(payload.get("category_limit_id")),
                "reminder_type": reminder_type,
                "scheduled_at": scheduled_at,
            },
        ).mappings().one()
    return {key: _serialize_value(value) for key, value in dict(row).items()}


def _insert_reminder_once(
    connection,
    *,
    user_id: UUID,
    regular_expense_id: UUID | None,
    category_limit_id: UUID | None,
    reminder_type: str,
    scheduled_at: datetime,
) -> int:
    exists = connection.scalar(
        text(
            """
            select 1
            from scheduled_reminders
            where user_id = :user_id
              and reminder_type = :reminder_type
              and scheduled_at = :scheduled_at
              and status in ('planned', 'queued')
              and regular_expense_id is not distinct from :regular_expense_id
              and category_limit_id is not distinct from :category_limit_id
            """
        ),
        {
            "user_id": user_id,
            "regular_expense_id": regular_expense_id,
            "category_limit_id": category_limit_id,
            "reminder_type": reminder_type,
            "scheduled_at": scheduled_at,
        },
    )
    if exists:
        return 0
    connection.execute(
        text(
            """
            insert into scheduled_reminders(
              user_id, regular_expense_id, category_limit_id, reminder_type, status, scheduled_at
            )
            values (:user_id, :regular_expense_id, :category_limit_id, :reminder_type, 'planned', :scheduled_at)
            """
        ),
        {
            "user_id": user_id,
            "regular_expense_id": regular_expense_id,
            "category_limit_id": category_limit_id,
            "reminder_type": reminder_type,
            "scheduled_at": scheduled_at,
        },
    )
    return 1


def _optional_user_id(payload: dict, envelope: dict) -> UUID | None:
    if payload.get("user_id"):
        return UUID(str(payload["user_id"]))
    user = envelope.get("user") or {}
    if user.get("id"):
        return UUID(str(user["id"]))
    return None


def _optional_uuid(value: Any) -> UUID | None:
    return UUID(str(value)) if value else None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _serialize_value(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


MESSAGE_HANDLERS = {
    "reminders.plan_regular_expenses": handle_plan_regular_expenses,
    "reminders.plan_limit_warning": handle_plan_limit_warnings,
    "reminders.limit_warnings.plan": handle_plan_limit_warnings,
    "reminders.due.scan": handle_due_scan,
    "notifications.schedule": handle_notifications_schedule,
}
