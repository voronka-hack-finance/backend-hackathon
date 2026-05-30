from __future__ import annotations

from common.messaging import UserContext, check_rabbitmq
from common.redis_client import check_redis
from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from services.gateway.app.config import settings
from services.gateway.app.constants import ACCESS_QUEUE
from services.gateway.app.rpc import rpc_call

bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="BearerAuth",
    description="JWT from POST /api/v1/auth/login. Send as Authorization: Bearer <token>.",
)


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> UserContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Bearer token")
    payload = rpc_call(
        ACCESS_QUEUE,
        "auth.verify_token",
        {"token": credentials.credentials},
        timeout_seconds=settings.rpc_timeout_seconds,
    )
    user = payload.get("user") or {}
    user_id = user.get("id") or user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    auth = payload.get("auth") or {}
    raw_scopes = auth.get("scopes")
    scopes = tuple(str(scope) for scope in raw_scopes) if raw_scopes else None
    return UserContext(id=str(user_id), email=user.get("email"), scopes=scopes)


def check_gateway_ready() -> None:
    check_rabbitmq(settings.rabbitmq_url)
    check_redis()
