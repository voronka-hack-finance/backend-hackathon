from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest

from common.security import TokenDecodeError, create_access_token, decode_access_token


def test_jwt_round_trip_contains_user_id():
    user_id = uuid4()
    token = create_access_token(
        user_id=user_id,
        secret="test-secret",
        issuer="family-budget-backend",
        expires_minutes=5,
    )

    claims = decode_access_token(
        token=token,
        secret="test-secret",
        issuer="family-budget-backend",
    )

    assert claims["sub"] == str(user_id)
    assert claims["user_id"] == str(user_id)


def test_jwt_rejects_expired_token():
    user_id = uuid4()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "user_id": str(user_id),
        "iss": "family-budget-backend",
        "iat": now - timedelta(minutes=10),
        "exp": now - timedelta(minutes=1),
    }
    token = jwt.encode(payload, "test-secret", algorithm="HS256")

    with pytest.raises(TokenDecodeError):
        decode_access_token(token=token, secret="test-secret", issuer="family-budget-backend")


def test_jwt_rejects_wrong_secret():
    token = create_access_token(
        user_id=uuid4(),
        secret="secret-a",
        issuer="family-budget-backend",
        expires_minutes=5,
    )

    with pytest.raises(TokenDecodeError):
        decode_access_token(token=token, secret="secret-b", issuer="family-budget-backend")


def test_jwt_rejects_wrong_issuer():
    token = create_access_token(
        user_id=uuid4(),
        secret="test-secret",
        issuer="other-issuer",
        expires_minutes=5,
    )

    with pytest.raises(TokenDecodeError):
        decode_access_token(token=token, secret="test-secret", issuer="family-budget-backend")
