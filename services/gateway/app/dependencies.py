from __future__ import annotations

from common.messaging import UserContext, check_rabbitmq
from common.redis_cache import get_auth_verify_cache
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
    token = credentials.credentials
    auth_cache = get_auth_verify_cache()
    if auth_cache is not None:
        cached = auth_cache.get(token)
        if cached is not None:
            return _user_context_from_verify_payload(cached)
    payload = rpc_call(
        ACCESS_QUEUE,
        "auth.verify_token",
        {"token": token},
        timeout_seconds=settings.rpc_timeout_seconds,
    )
    if auth_cache is not None:
        auth = payload.get("auth") or {}
        ttl = auth_cache.ttl_from_auth(auth)
        if ttl > 0:
            auth_cache.set(token, payload, ttl_seconds=ttl)
    return _user_context_from_verify_payload(payload)


def _user_context_from_verify_payload(payload: dict) -> UserContext:
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
