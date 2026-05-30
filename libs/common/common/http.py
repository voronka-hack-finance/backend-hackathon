from fastapi import Header, HTTPException, status

INTERNAL_USER_HEADER = "X-User-Id"


def require_internal_user_id(
    x_user_id: str | None = Header(default=None, alias=INTERNAL_USER_HEADER),
) -> str:
    if not x_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing trusted user context",
        )
    return x_user_id
