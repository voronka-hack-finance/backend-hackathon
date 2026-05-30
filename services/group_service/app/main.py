from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from common.messaging import MessageBus, MessageError, MessageWorker, UserContext, check_rabbitmq, require_user
from fastapi import FastAPI
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine, text


class Settings(BaseSettings):
    database_url: str = Field(
        default="postgresql+psycopg://app:app@localhost:5432/family_budget",
        validation_alias="DATABASE_URL",
    )
    rabbitmq_url: str = Field(default="amqp://guest:guest@localhost:5672/%2F", validation_alias="RABBITMQ_URL")

    model_config = SettingsConfigDict(extra="ignore")


settings = Settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)

SERVICE_NAME = "group-service"
QUEUE_NAME = "group-service"
ANALYTICS_QUEUE = "analytics-service"

app = FastAPI(title=SERVICE_NAME)
bus = MessageBus(settings.rabbitmq_url, SERVICE_NAME)
worker = MessageWorker(
    rabbitmq_url=settings.rabbitmq_url,
    queue_name=QUEUE_NAME,
    service_name=SERVICE_NAME,
    handlers={},
)


@app.on_event("startup")
def startup() -> None:
    worker.handlers.update(
        {
            "groups.list": handle_groups_list,
            "groups.create": handle_groups_create,
            "groups.get": handle_groups_get,
            "groups.update": handle_groups_update,
            "groups.delete": handle_groups_delete,
            "groups.family_budget.get": handle_groups_budget_get,
            "groups.budget.get": handle_groups_budget_get,
            "group_members.list": handle_members_list,
            "group_members.create": handle_members_create,
            "group_members.update": handle_members_update,
            "group_members.delete": handle_members_delete,
            "group_invitations.list": handle_invitations_list,
            "group_invitations.create": handle_invitations_create,
            "group_invitations.update": handle_invitations_update,
            "group_invitations.delete": handle_invitations_delete,
            "group_invitations.accept": handle_invitations_accept,
            "group_invitations.decline": handle_invitations_decline,
        }
    )
    worker.start()


@app.on_event("shutdown")
def shutdown() -> None:
    worker.stop()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, str]:
    with engine.connect() as connection:
        connection.execute(text("select 1"))
    check_rabbitmq(settings.rabbitmq_url)
    return {"status": "ready"}


def handle_groups_list(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    page, page_size = _page(payload)
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                select distinct g.id, g.created_by_user_id, g.name, g.description, g.created_at, g.updated_at
                from family_groups g
                left join family_members m on m.family_group_id = g.id and m.status = 'active'
                where g.created_by_user_id = :user_id or m.user_id = :user_id
                order by g.updated_at desc
                offset :offset limit :limit
                """
            ),
            {"user_id": user_id, "offset": (page - 1) * page_size, "limit": page_size},
        ).mappings().all()
        total = connection.scalar(
            text(
                """
                select count(distinct g.id)
                from family_groups g
                left join family_members m on m.family_group_id = g.id and m.status = 'active'
                where g.created_by_user_id = :user_id or m.user_id = :user_id
                """
            ),
            {"user_id": user_id},
        )
    return {"items": [_serialize(row) for row in rows], "pagination": {"page": page, "page_size": page_size, "total": total or 0}}


def handle_groups_create(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    name = str(payload.get("name") or "").strip()
    if not name:
        raise MessageError(422, "name is required")
    with engine.begin() as connection:
        group = connection.execute(
            text(
                """
                insert into family_groups(created_by_user_id, name, description)
                values (:user_id, :name, :description)
                returning id, created_by_user_id, name, description, created_at, updated_at
                """
            ),
            {"user_id": user_id, "name": name, "description": payload.get("description")},
        ).mappings().one()
        connection.execute(
            text(
                """
                insert into family_members(family_group_id, user_id, role, status, joined_at)
                values (:group_id, :user_id, 'owner', 'active', now())
                on conflict (family_group_id, user_id) do nothing
                """
            ),
            {"group_id": group["id"], "user_id": user_id},
        )
    return _serialize(group)


def handle_groups_get(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    group_id = UUID(str(payload.get("group_id") or payload.get("id")))
    with engine.connect() as connection:
        group = _get_group(connection, group_id, user_id)
    return _serialize(group)


def handle_groups_update(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    group_id = UUID(str(payload.get("group_id") or payload.get("id")))
    with engine.begin() as connection:
        _require_group_owner(connection, group_id, user_id)
        group = connection.execute(
            text(
                """
                update family_groups
                set name = coalesce(:name, name),
                    description = coalesce(:description, description),
                    updated_at = now()
                where id = :group_id
                returning id, created_by_user_id, name, description, created_at, updated_at
                """
            ),
            {"group_id": group_id, "name": payload.get("name"), "description": payload.get("description")},
        ).mappings().one()
    return _serialize(group)


def handle_groups_delete(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    group_id = UUID(str(payload.get("group_id") or payload.get("id")))
    with engine.begin() as connection:
        _require_group_owner(connection, group_id, user_id)
        connection.execute(text("delete from family_groups where id = :group_id"), {"group_id": group_id})
    return {"status": "deleted"}


def handle_groups_budget_get(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    group_id = UUID(str(payload.get("group_id") or payload.get("id")))
    with engine.connect() as connection:
        group = _get_group(connection, group_id, user_id)
        members = connection.execute(
            text(
                """
                select id, family_group_id, user_id, role, status, joined_at, created_at, updated_at
                from family_members
                where family_group_id = :group_id and status = 'active'
                order by created_at
                """
            ),
            {"group_id": group_id},
        ).mappings().all()

    member_payloads = []
    totals = {
        "actual_balance": Decimal("0"),
        "expected_income_total": Decimal("0"),
        "expected_expense_total": Decimal("0"),
        "available_amount": Decimal("0"),
    }
    analytics_payload = {
        key: value
        for key, value in {
            "period_start": payload.get("period_start"),
            "period_end": payload.get("period_end"),
        }.items()
        if value
    }
    member_user_ids = [str(row["user_id"]) for row in members]
    budgets_by_user: dict[str, dict] = {}
    if member_user_ids:
        reply = bus.request(
            ANALYTICS_QUEUE,
            "analytics.member_budget.batch",
            {**analytics_payload, "user_ids": member_user_ids},
            user=UserContext(id=str(user_id)),
            timeout_seconds=30.0,
        )
        if reply.get("ok"):
            for item in (reply.get("payload") or {}).get("items") or []:
                budgets_by_user[str(item.get("user_id"))] = item.get("budget") or {}
        else:
            for member_row in members:
                member_reply = bus.request(
                    ANALYTICS_QUEUE,
                    "analytics.member_budget.get",
                    analytics_payload,
                    user=UserContext(id=str(member_row["user_id"])),
                    timeout_seconds=15.0,
                )
                if member_reply.get("ok"):
                    budgets_by_user[str(member_row["user_id"])] = member_reply.get("payload") or {}

    for row in members:
        member = _serialize(row)
        budget = budgets_by_user.get(str(row["user_id"]))
        if budget is not None:
            for key in totals:
                totals[key] += Decimal(str(budget.get(key) or "0"))
            member["budget"] = budget
        else:
            member["budget_error"] = "analytics-service error"
        member_payloads.append(member)

    return {
        "group": _serialize(group),
        "members": member_payloads,
        "summary": {
            "currency": "RUB",
            "actual_balance": format(totals["actual_balance"], "f"),
            "expected_income_total": format(totals["expected_income_total"], "f"),
            "expected_expense_total": format(totals["expected_expense_total"], "f"),
            "available_amount": format(totals["available_amount"], "f"),
        },
    }


def handle_members_list(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    group_id = UUID(str(payload.get("group_id")))
    with engine.connect() as connection:
        _get_group(connection, group_id, user_id)
        rows = connection.execute(
            text(
                """
                select id, family_group_id, user_id, role, status, joined_at, created_at, updated_at
                from family_members
                where family_group_id = :group_id
                order by created_at
                """
            ),
            {"group_id": group_id},
        ).mappings().all()
    return {"items": [_serialize(row) for row in rows], "pagination": None}


def handle_members_create(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    group_id = UUID(str(payload.get("group_id")))
    member_user_id = UUID(str(payload.get("user_id")))
    with engine.begin() as connection:
        _require_group_owner(connection, group_id, user_id)
        row = connection.execute(
            text(
                """
                insert into family_members(family_group_id, user_id, role, status, joined_at)
                values (:group_id, :member_user_id, :role, 'active', now())
                on conflict (family_group_id, user_id) do update
                set role = excluded.role, status = 'active', updated_at = now()
                returning id, family_group_id, user_id, role, status, joined_at, created_at, updated_at
                """
            ),
            {"group_id": group_id, "member_user_id": member_user_id, "role": payload.get("role") or "member"},
        ).mappings().one()
    return _serialize(row)


def handle_members_update(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    group_id = UUID(str(payload.get("group_id")))
    member_id = UUID(str(payload.get("member_id")))
    with engine.begin() as connection:
        _require_group_owner(connection, group_id, user_id)
        row = connection.execute(
            text(
                """
                update family_members
                set role = coalesce(:role, role), status = coalesce(:status, status), updated_at = now()
                where id = :member_id and family_group_id = :group_id
                returning id, family_group_id, user_id, role, status, joined_at, created_at, updated_at
                """
            ),
            {"group_id": group_id, "member_id": member_id, "role": payload.get("role"), "status": payload.get("status")},
        ).mappings().first()
    if row is None:
        raise MessageError(404, "Member not found")
    return _serialize(row)


def handle_members_delete(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    group_id = UUID(str(payload.get("group_id")))
    member_id = UUID(str(payload.get("member_id")))
    with engine.begin() as connection:
        _require_group_owner(connection, group_id, user_id)
        connection.execute(
            text("delete from family_members where id = :member_id and family_group_id = :group_id"),
            {"group_id": group_id, "member_id": member_id},
        )
    return {"status": "deleted"}


def handle_invitations_list(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    group_id = UUID(str(payload.get("group_id")))
    with engine.connect() as connection:
        _get_group(connection, group_id, user_id)
        rows = connection.execute(
            text(
                """
                select id, family_group_id, invited_by_user_id, invited_user_id, invited_email,
                       status, message, expires_at, created_at, updated_at
                from family_invitations
                where family_group_id = :group_id
                order by created_at desc
                """
            ),
            {"group_id": group_id},
        ).mappings().all()
    return {"items": [_serialize(row) for row in rows], "pagination": None}


def handle_invitations_create(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    group_id = UUID(str(payload.get("group_id")))
    invited_email = str(payload.get("invited_email") or "").strip().lower()
    if not invited_email:
        raise MessageError(422, "invited_email is required")
    with engine.begin() as connection:
        _require_group_owner(connection, group_id, user_id)
        row = connection.execute(
            text(
                """
                insert into family_invitations(family_group_id, invited_by_user_id, invited_email, message, expires_at)
                values (:group_id, :user_id, :invited_email, :message, :expires_at)
                returning id, family_group_id, invited_by_user_id, invited_user_id, invited_email,
                          status, message, expires_at, created_at, updated_at
                """
            ),
            {
                "group_id": group_id,
                "user_id": user_id,
                "invited_email": invited_email,
                "message": payload.get("message"),
                "expires_at": payload.get("expires_at"),
            },
        ).mappings().one()
    return _serialize(row)


def handle_invitations_update(payload: dict, envelope: dict) -> dict:
    return _update_invitation(payload, envelope)


def handle_invitations_delete(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    group_id = UUID(str(payload.get("group_id")))
    invitation_id = UUID(str(payload.get("invitation_id")))
    with engine.begin() as connection:
        _require_group_owner(connection, group_id, user_id)
        connection.execute(
            text("delete from family_invitations where id = :invitation_id and family_group_id = :group_id"),
            {"group_id": group_id, "invitation_id": invitation_id},
        )
    return {"status": "deleted"}


def handle_invitations_accept(payload: dict, envelope: dict) -> dict:
    user = require_user(envelope)
    user_id = UUID(user.id)
    invitation_id = UUID(str(payload.get("invitation_id")))
    with engine.begin() as connection:
        invitation = connection.execute(
            text(
                """
                select *
                from family_invitations
                where id = :invitation_id and status = 'pending'
                """
            ),
            {"invitation_id": invitation_id},
        ).mappings().first()
        if invitation is None:
            raise MessageError(404, "Invitation not found")
        if invitation["invited_user_id"] and invitation["invited_user_id"] != user_id:
            raise MessageError(403, "Invitation belongs to another user")
        if not invitation["invited_user_id"] and user.email:
            if str(invitation["invited_email"]).lower() != user.email.lower():
                raise MessageError(403, "Invitation email does not match current user")
        row = connection.execute(
            text(
                """
                update family_invitations
                set status = 'accepted', invited_user_id = :user_id, updated_at = now()
                where id = :invitation_id
                returning id, family_group_id, invited_by_user_id, invited_user_id, invited_email,
                          status, message, expires_at, created_at, updated_at
                """
            ),
            {"invitation_id": invitation_id, "user_id": user_id},
        ).mappings().one()
        connection.execute(
            text(
                """
                insert into family_members(family_group_id, user_id, role, status, joined_at)
                values (:group_id, :user_id, 'member', 'active', now())
                on conflict (family_group_id, user_id) do update
                set status = 'active', updated_at = now()
                """
            ),
            {"group_id": row["family_group_id"], "user_id": user_id},
        )
    return _serialize(row)


def handle_invitations_decline(payload: dict, envelope: dict) -> dict:
    return _update_invitation({**payload, "status": "declined"}, envelope)


def _update_invitation(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    invitation_id = UUID(str(payload.get("invitation_id")))
    group_id = UUID(str(payload.get("group_id"))) if payload.get("group_id") else None
    with engine.begin() as connection:
        if group_id:
            _require_group_owner(connection, group_id, user_id)
        row = connection.execute(
            text(
                """
                update family_invitations
                set status = coalesce(:status, status),
                    message = coalesce(:message, message),
                    expires_at = coalesce(:expires_at, expires_at),
                    updated_at = now()
                where id = :invitation_id
                returning id, family_group_id, invited_by_user_id, invited_user_id, invited_email,
                          status, message, expires_at, created_at, updated_at
                """
            ),
            {
                "invitation_id": invitation_id,
                "status": payload.get("status"),
                "message": payload.get("message"),
                "expires_at": payload.get("expires_at"),
            },
        ).mappings().first()
    if row is None:
        raise MessageError(404, "Invitation not found")
    return _serialize(row)


def _get_group(connection, group_id: UUID, user_id: UUID):
    group = connection.execute(
        text(
            """
            select distinct g.id, g.created_by_user_id, g.name, g.description, g.created_at, g.updated_at
            from family_groups g
            left join family_members m on m.family_group_id = g.id and m.status = 'active'
            where g.id = :group_id and (g.created_by_user_id = :user_id or m.user_id = :user_id)
            """
        ),
        {"group_id": group_id, "user_id": user_id},
    ).mappings().first()
    if group is None:
        raise MessageError(404, "Group not found")
    return group


def _require_group_owner(connection, group_id: UUID, user_id: UUID) -> None:
    exists = connection.scalar(
        text("select 1 from family_groups where id = :group_id and created_by_user_id = :user_id"),
        {"group_id": group_id, "user_id": user_id},
    )
    if not exists:
        raise MessageError(403, "Group owner permission required")


def _page(payload: dict) -> tuple[int, int]:
    page = max(int(payload.get("page") or 1), 1)
    page_size = min(max(int(payload.get("page_size") or 50), 1), 500)
    return page, page_size


def _serialize(row) -> dict:
    return {key: _serialize_value(value) for key, value in dict(row).items()}


def _serialize_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, UUID):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
