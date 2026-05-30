from uuid import uuid4

from common.security import create_access_token, decode_access_token


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
