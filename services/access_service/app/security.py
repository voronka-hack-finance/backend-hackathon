import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 390_000
SALT_BYTES = 16
KEY_BYTES = 32


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS, dklen=KEY_BYTES)
    return "$".join(
        [
            ALGORITHM,
            str(ITERATIONS),
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(digest).decode("ascii"),
        ]
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, digest_text = password_hash.split("$", 3)
        if algorithm != ALGORITHM:
            return False
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            int(iterations_text),
            dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def refresh_expires(days: int) -> datetime:
    return datetime.now(UTC) + timedelta(days=days)
