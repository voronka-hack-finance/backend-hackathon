from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from common.messaging import MessageWorker, check_rabbitmq, require_user
from fastapi import FastAPI
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    database_url: str = Field(
        default="postgresql+psycopg://app:app@localhost:5432/family_budget",
        validation_alias="DATABASE_URL",
    )
    rabbitmq_url: str = Field(default="amqp://guest:guest@localhost:5672/%2F", validation_alias="RABBITMQ_URL")
    firebase_enabled: bool = Field(default=False, validation_alias="FIREBASE_ENABLED")
    firebase_credentials_json: str | None = Field(default=None, validation_alias="FIREBASE_CREDENTIALS_JSON")
    firebase_credentials_path: str | None = Field(default=None, validation_alias="FIREBASE_CREDENTIALS_PATH")

    model_config = SettingsConfigDict(extra="ignore")


settings = Settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)

SERVICE_NAME = "notification-service"
QUEUE_NAME = "notification-service"

app = FastAPI(title=SERVICE_NAME)
worker = MessageWorker(
    rabbitmq_url=settings.rabbitmq_url,
    queue_name=QUEUE_NAME,
    service_name=SERVICE_NAME,
    handlers={},
)

_firebase_app = None


@app.on_event("startup")
def startup() -> None:
    worker.handlers.update(
        {
            "notifications.permission.set": handle_permission_set,
            "notifications.devices.save": handle_device_save,
            "notifications.test.send": handle_test_send,
            "notifications.send": handle_send,
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
    return {"status": "ready", "firebase": "enabled" if settings.firebase_enabled else "not_configured"}


def handle_permission_set(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    with engine.begin() as connection:
        row = connection.execute(
            text(
                """
                insert into notification_preferences(user_id, push_enabled, updated_at)
                values (:user_id, :push_enabled, now())
                on conflict (user_id) do update
                set push_enabled = excluded.push_enabled, updated_at = now()
                returning id, user_id, push_enabled, updated_at
                """
            ),
            {"user_id": user_id, "push_enabled": bool(payload.get("push_enabled"))},
        ).mappings().one()
    return _serialize(row)


def handle_device_save(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    with engine.begin() as connection:
        row = connection.execute(
            text(
                """
                insert into notification_devices(user_id, device_id, platform, firebase_token, is_active, updated_at)
                values (:user_id, :device_id, :platform, :firebase_token, true, now())
                on conflict (user_id, device_id) do update
                set platform = excluded.platform,
                    firebase_token = excluded.firebase_token,
                    is_active = true,
                    updated_at = now()
                returning id, user_id, device_id, platform, firebase_token, is_active, created_at, updated_at
                """
            ),
            {
                "user_id": user_id,
                "device_id": str(payload.get("device_id") or ""),
                "platform": payload.get("platform"),
                "firebase_token": payload.get("firebase_token"),
            },
        ).mappings().one()
    return _serialize(row)


def handle_test_send(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    title = str(payload.get("title") or "Test notification")
    body = str(payload.get("body") or "Notification channel is configured.")
    return _deliver_to_user(
        user_id,
        notification_type="test",
        title=title,
        body=body,
        reminder_id=None,
        client_device_id=payload.get("device_id"),
    )


def handle_send(payload: dict, envelope: dict) -> dict:
    user_id = UUID(str(payload.get("user_id") or require_user(envelope).id))
    title = str(payload.get("title") or payload.get("notification_type") or "Reminder")
    body = str(payload.get("body") or payload.get("message") or "")
    return _deliver_to_user(
        user_id,
        notification_type=str(payload.get("notification_type") or "scheduled"),
        title=title,
        body=body,
        reminder_id=payload.get("reminder_id"),
        client_device_id=payload.get("device_id"),
    )


def _deliver_to_user(
    user_id: UUID,
    *,
    notification_type: str,
    title: str,
    body: str,
    reminder_id: Any,
    client_device_id: Any,
) -> dict:
    with engine.begin() as connection:
        preference = connection.execute(
            text("select push_enabled from notification_preferences where user_id = :user_id"),
            {"user_id": user_id},
        ).scalar_one_or_none()
        if preference is False:
            row = _insert_delivery(
                connection,
                user_id=user_id,
                device_pk=None,
                reminder_id=reminder_id,
                notification_type=notification_type,
                status="skipped",
                error_message="push_disabled",
                sent_at=None,
            )
            result = _serialize(row)
            result["status"] = "ok"
            return result

        device = _resolve_device(connection, user_id, client_device_id)
        device_pk = UUID(str(device["id"])) if device else None
        firebase_token = device.get("firebase_token") if device else None

        if not settings.firebase_enabled:
            row = _insert_delivery(
                connection,
                user_id=user_id,
                device_pk=device_pk,
                reminder_id=reminder_id,
                notification_type=notification_type,
                status="skipped",
                error_message="firebase_not_configured",
                sent_at=None,
            )
            result = _serialize(row)
            result["status"] = "ok"
            return result

        if not firebase_token:
            row = _insert_delivery(
                connection,
                user_id=user_id,
                device_pk=device_pk,
                reminder_id=reminder_id,
                notification_type=notification_type,
                status="failed",
                error_message="missing_firebase_token",
                sent_at=None,
            )
            result = _serialize(row)
            result["status"] = "ok"
            return result

        send_status, error_message = _send_firebase_push(firebase_token, title=title, body=body)
        row = _insert_delivery(
            connection,
            user_id=user_id,
            device_pk=device_pk,
            reminder_id=reminder_id,
            notification_type=notification_type,
            status=send_status,
            error_message=error_message,
            sent_at=datetime.now(UTC) if send_status == "sent" else None,
        )
    result = _serialize(row)
    result["status"] = "ok"
    return result


def _resolve_device(connection, user_id: UUID, client_device_id: Any):
    if client_device_id:
        return connection.execute(
            text(
                """
                select id, device_id, firebase_token
                from notification_devices
                where user_id = :user_id and device_id = :device_id and is_active = true
                limit 1
                """
            ),
            {"user_id": user_id, "device_id": str(client_device_id)},
        ).mappings().first()
    return connection.execute(
        text(
            """
            select id, device_id, firebase_token
            from notification_devices
            where user_id = :user_id and is_active = true and firebase_token is not null
            order by updated_at desc
            limit 1
            """
        ),
        {"user_id": user_id},
    ).mappings().first()


def _insert_delivery(
    connection,
    *,
    user_id: UUID,
    device_pk: UUID | None,
    reminder_id: Any,
    notification_type: str,
    status: str,
    error_message: str | None,
    sent_at: datetime | None,
) -> dict:
    return connection.execute(
        text(
            """
            insert into notification_deliveries(
              user_id, device_id, reminder_id, notification_type, status, error_message, sent_at
            )
            values (:user_id, :device_id, :reminder_id, :notification_type, :status, :error_message, :sent_at)
            returning id, user_id, device_id, reminder_id, notification_type, status, error_message, created_at, sent_at
            """
        ),
        {
            "user_id": user_id,
            "device_id": device_pk,
            "reminder_id": UUID(str(reminder_id)) if reminder_id else None,
            "notification_type": notification_type,
            "status": status,
            "error_message": error_message,
            "sent_at": sent_at,
        },
    ).mappings().one()


def _send_firebase_push(token: str, *, title: str, body: str) -> tuple[str, str | None]:
    try:
        from firebase_admin import messaging

        _ensure_firebase_app()
        messaging.send(
            messaging.Message(
                notification=messaging.Notification(title=title, body=body),
                token=token,
            )
        )
        return "sent", None
    except Exception as exc:
        logger.exception("Firebase push failed")
        return "failed", str(exc)


def _ensure_firebase_app():
    global _firebase_app
    if _firebase_app is not None:
        return _firebase_app
    import firebase_admin
    from firebase_admin import credentials

    if settings.firebase_credentials_path:
        cred = credentials.Certificate(settings.firebase_credentials_path)
    elif settings.firebase_credentials_json:
        cred = credentials.Certificate(json.loads(settings.firebase_credentials_json))
    else:
        raise RuntimeError("Firebase enabled but credentials are not configured")
    _firebase_app = firebase_admin.initialize_app(cred)
    return _firebase_app


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
