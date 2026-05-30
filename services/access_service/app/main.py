from datetime import UTC, datetime
from uuid import UUID

from common.messaging import MessageBus, MessageError, MessageWorker, check_rabbitmq
from common.security import TokenDecodeError, create_access_token, decode_access_token
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from services.access_service.app.config import settings
from services.access_service.app.db import SessionLocal
from services.access_service.app.models import RefreshSession, User
from services.access_service.app.security import (
    hash_password,
    new_refresh_token,
    refresh_expires,
    token_hash,
    verify_password,
)

SERVICE_NAME = "access-service"
QUEUE_NAME = "access-service"

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
            "auth.register": handle_register,
            "auth.login": handle_login,
            "auth.logout": handle_logout,
            "auth.refresh": handle_refresh,
            "auth.me.get": handle_me_get,
            "auth.me.patch": handle_me_patch,
            "auth.change_password": handle_change_password,
            "auth.verify_token": handle_verify_token,
            "users.get": handle_users_get,
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
    with SessionLocal() as db:
        db.execute(select(User.id).limit(1))
    check_rabbitmq(settings.rabbitmq_url)
    return {"status": "ready"}


def handle_register(payload: dict, envelope: dict) -> dict:
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    display_name = payload.get("display_name")
    if not email or not password or len(password) < 6:
        raise MessageError(422, "email and password with at least 6 chars are required")
    with SessionLocal() as db:
        user = User(email=email, password_hash=hash_password(password), display_name=display_name)
        db.add(user)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise MessageError(409, "Email already registered") from exc
        db.refresh(user)
        return _user_payload(user)


def handle_login(payload: dict, envelope: dict) -> dict:
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        if user is None or not verify_password(password, user.password_hash):
            raise MessageError(401, "Invalid credentials")
        refresh_token = new_refresh_token()
        session = RefreshSession(
            user_id=user.id,
            refresh_token_hash=token_hash(refresh_token),
            expires_at=refresh_expires(settings.refresh_token_days),
        )
        db.add(session)
        db.commit()
        return {
            "access_token": _access_token(user.id),
            "refresh_token": refresh_token,
            "token_type": "bearer",
        }


def handle_logout(payload: dict, envelope: dict) -> dict:
    refresh_token = payload.get("refresh_token")
    if not refresh_token:
        return {"status": "ok"}
    with SessionLocal() as db:
        session = db.scalar(
            select(RefreshSession).where(
                RefreshSession.refresh_token_hash == token_hash(str(refresh_token)),
                RefreshSession.status == "active",
            )
        )
        if session:
            session.status = "revoked"
            session.revoked_at = datetime.now(UTC)
            db.commit()
    return {"status": "ok"}


def handle_refresh(payload: dict, envelope: dict) -> dict:
    refresh_token = str(payload.get("refresh_token", ""))
    with SessionLocal() as db:
        session = db.scalar(
            select(RefreshSession).where(
                RefreshSession.refresh_token_hash == token_hash(refresh_token),
                RefreshSession.status == "active",
            )
        )
        if session is None or session.expires_at < datetime.now(UTC):
            raise MessageError(401, "Invalid refresh token")
        user = db.get(User, session.user_id)
        if user is None:
            raise MessageError(401, "Invalid refresh token")
        session.status = "revoked"
        session.revoked_at = datetime.now(UTC)
        rotated_refresh_token = new_refresh_token()
        db.add(
            RefreshSession(
                user_id=user.id,
                refresh_token_hash=token_hash(rotated_refresh_token),
                expires_at=refresh_expires(settings.refresh_token_days),
            )
        )
        db.commit()
        return {
            "access_token": _access_token(user.id),
            "refresh_token": rotated_refresh_token,
            "token_type": "bearer",
        }


def handle_me_get(payload: dict, envelope: dict) -> dict:
    user_id = UUID((envelope.get("user") or {}).get("id"))
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user is None:
            raise MessageError(404, "User not found")
        return _user_payload(user)


def handle_me_patch(payload: dict, envelope: dict) -> dict:
    user_id = UUID((envelope.get("user") or {}).get("id"))
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user is None:
            raise MessageError(404, "User not found")
        if "display_name" in payload:
            user.display_name = payload.get("display_name")
        db.commit()
        db.refresh(user)
        return _user_payload(user)


def handle_change_password(payload: dict, envelope: dict) -> dict:
    user_id = UUID((envelope.get("user") or {}).get("id"))
    current_password = str(payload.get("current_password", ""))
    new_password = str(payload.get("new_password", ""))
    if len(new_password) < 6:
        raise MessageError(422, "new_password must contain at least 6 chars")
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user is None or not verify_password(current_password, user.password_hash):
            raise MessageError(401, "Invalid current password")
        user.password_hash = hash_password(new_password)
        db.execute(
            update(RefreshSession)
            .where(
                RefreshSession.user_id == user.id,
                RefreshSession.status == "active",
            )
            .values(status="revoked", revoked_at=datetime.now(UTC))
        )
        db.commit()
        return {"status": "ok"}


def handle_verify_token(payload: dict, envelope: dict) -> dict:
    token = str(payload.get("token", ""))
    try:
        claims = decode_access_token(token=token, secret=settings.jwt_secret, issuer=settings.jwt_issuer)
    except TokenDecodeError as exc:
        raise MessageError(401, "Invalid or expired token") from exc
    user_id = UUID(claims.get("user_id") or claims.get("sub"))
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user is None:
            raise MessageError(401, "User not found")
        return {"user": _user_payload(user)}


def handle_users_get(payload: dict, envelope: dict) -> dict:
    user_id = UUID(str(payload.get("user_id")))
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user is None:
            raise MessageError(404, "User not found")
        return _user_payload(user)


def _access_token(user_id: UUID) -> str:
    return create_access_token(
        user_id=user_id,
        secret=settings.jwt_secret,
        issuer=settings.jwt_issuer,
        expires_minutes=settings.access_token_minutes,
    )


def _user_payload(user: User) -> dict:
    return {
        "user_id": str(user.id),
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
    }
