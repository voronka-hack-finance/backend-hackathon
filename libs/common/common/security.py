from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from fastapi import HTTPException, status


def create_access_token(
    *,
    user_id: UUID | str,
    secret: str,
    issuer: str,
    expires_minutes: int,
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "user_id": str(user_id),
        "iss": issuer,
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


class TokenDecodeError(Exception):
    """Raised when a JWT cannot be decoded or validated."""


def decode_access_token(*, token: str, secret: str, issuer: str) -> dict:
    try:
        return jwt.decode(token, secret, algorithms=["HS256"], issuer=issuer)
    except jwt.PyJWTError as exc:
        raise TokenDecodeError("Invalid or expired token") from exc


def user_id_from_bearer(*, authorization: str | None, secret: str, issuer: str) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )
    token = authorization.split(" ", 1)[1].strip()
    try:
        claims = decode_access_token(token=token, secret=secret, issuer=issuer)
    except TokenDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    user_id = claims.get("user_id") or claims.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token does not contain user id",
        )
    return str(user_id)
