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

SERVICE_NAME = "chat-service"
QUEUE_NAME = "chat-service"
ANALYTICS_QUEUE = "analytics-service"
FINANCE_QUEUE = "finance-service"

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
            "chat.recommendations.initial.get": handle_recommendations,
            "chats.list": handle_chats_list,
            "chats.create": handle_chats_create,
            "chats.get": handle_chats_get,
            "chats.update": handle_chats_update,
            "chats.delete": handle_chats_delete,
            "chat_messages.list": handle_messages_list,
            "chat_messages.create": handle_messages_create,
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


def handle_recommendations(payload: dict, envelope: dict) -> dict:
    trusted_user = require_user(envelope)
    user_id = UUID(trusted_user.id)
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                select id, chat_id, user_id, agent_key, title, content, confidence, created_at
                from agent_recommendations
                where user_id = :user_id
                order by created_at desc
                limit 20
                """
            ),
            {"user_id": user_id},
        ).mappings().all()
    if rows:
        return {"items": [_serialize(row) for row in rows], "pagination": None}
    context = _recommendation_context(UserContext(id=str(user_id), email=trusted_user.email))
    return {
        "items": [
            {
                "agent_key": "finance-review",
                "title": "Review recent transactions",
                "content": (
                    "Recent period balance is "
                    f"{context['available_amount']} {context['currency']}; "
                    f"income total {context['income_total']}, expense total {context['expense_total']}."
                ),
                "confidence": "0.5000",
            },
            {
                "agent_key": "goals",
                "title": "Plan a savings goal",
                "content": "Estimate monthly progress toward an active savings goal.",
                "confidence": "0.5000",
            },
        ],
        "pagination": None,
    }


def _recommendation_context(user: UserContext) -> dict:
    analytics = bus.request(
        ANALYTICS_QUEUE,
        "analytics.available_balance.get",
        {},
        user=user,
        timeout_seconds=10.0,
    )
    finance = bus.request(
        FINANCE_QUEUE,
        "transactions.sum_by_scope",
        {},
        user=user,
        timeout_seconds=10.0,
    )
    analytics_payload = analytics.get("payload") if analytics.get("ok") else {}
    finance_payload = finance.get("payload") if finance.get("ok") else {}
    return {
        "available_amount": analytics_payload.get("available_amount") or "0",
        "currency": analytics_payload.get("currency") or "RUB",
        "income_total": finance_payload.get("income_total") or "0",
        "expense_total": finance_payload.get("expense_total") or "0",
    }


def handle_chats_list(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    page, page_size = _page(payload)
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                select id, user_id, title, status, created_at, updated_at
                from chats
                where user_id = :user_id
                order by updated_at desc
                offset :offset limit :limit
                """
            ),
            {"user_id": user_id, "offset": (page - 1) * page_size, "limit": page_size},
        ).mappings().all()
        total = connection.scalar(text("select count(*) from chats where user_id = :user_id"), {"user_id": user_id})
    return {"items": [_serialize(row) for row in rows], "pagination": {"page": page, "page_size": page_size, "total": total or 0}}


def handle_chats_create(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    title = str(payload.get("title") or "New chat")
    with engine.begin() as connection:
        row = connection.execute(
            text(
                """
                insert into chats(user_id, title)
                values (:user_id, :title)
                returning id, user_id, title, status, created_at, updated_at
                """
            ),
            {"user_id": user_id, "title": title},
        ).mappings().one()
    return _serialize(row)


def handle_chats_get(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    chat_id = UUID(str(payload.get("chat_id") or payload.get("id")))
    with engine.connect() as connection:
        row = _get_chat(connection, chat_id, user_id)
    return _serialize(row)


def handle_chats_update(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    chat_id = UUID(str(payload.get("chat_id") or payload.get("id")))
    with engine.begin() as connection:
        _get_chat(connection, chat_id, user_id)
        row = connection.execute(
            text(
                """
                update chats
                set title = coalesce(:title, title),
                    status = coalesce(:status, status),
                    updated_at = now()
                where id = :chat_id and user_id = :user_id
                returning id, user_id, title, status, created_at, updated_at
                """
            ),
            {"chat_id": chat_id, "user_id": user_id, "title": payload.get("title"), "status": payload.get("status")},
        ).mappings().one()
    return _serialize(row)


def handle_chats_delete(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    chat_id = UUID(str(payload.get("chat_id") or payload.get("id")))
    with engine.begin() as connection:
        connection.execute(text("delete from chats where id = :chat_id and user_id = :user_id"), {"chat_id": chat_id, "user_id": user_id})
    return {"status": "deleted"}


def handle_messages_list(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    chat_id = UUID(str(payload.get("chat_id")))
    page, page_size = _page(payload)
    with engine.connect() as connection:
        _get_chat(connection, chat_id, user_id)
        rows = connection.execute(
            text(
                """
                select id, chat_id, user_id, role, content, created_at
                from chat_messages
                where chat_id = :chat_id
                order by created_at
                offset :offset limit :limit
                """
            ),
            {"chat_id": chat_id, "offset": (page - 1) * page_size, "limit": page_size},
        ).mappings().all()
        total = connection.scalar(text("select count(*) from chat_messages where chat_id = :chat_id"), {"chat_id": chat_id})
    return {"items": [_serialize(row) for row in rows], "pagination": {"page": page, "page_size": page_size, "total": total or 0}}


def handle_messages_create(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    chat_id = UUID(str(payload.get("chat_id")))
    content = str(payload.get("content") or "").strip()
    if not content:
        raise MessageError(422, "content is required")
    with engine.begin() as connection:
        _get_chat(connection, chat_id, user_id)
        row = connection.execute(
            text(
                """
                insert into chat_messages(chat_id, user_id, role, content)
                values (:chat_id, :user_id, 'user', :content)
                returning id, chat_id, user_id, role, content, created_at
                """
            ),
            {"chat_id": chat_id, "user_id": user_id, "content": content},
        ).mappings().one()
        connection.execute(text("update chats set updated_at = now() where id = :chat_id"), {"chat_id": chat_id})
    return _serialize(row)


def _get_chat(connection, chat_id: UUID, user_id: UUID):
    row = connection.execute(
        text(
            """
            select id, user_id, title, status, created_at, updated_at
            from chats
            where id = :chat_id and user_id = :user_id
            """
        ),
        {"chat_id": chat_id, "user_id": user_id},
    ).mappings().first()
    if row is None:
        raise MessageError(404, "Chat not found")
    return row


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
