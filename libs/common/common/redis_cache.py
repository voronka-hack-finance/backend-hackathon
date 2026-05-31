from __future__ import annotations

import hashlib
import json
import logging
import time
from calendar import monthrange
from datetime import UTC, date, datetime
from functools import lru_cache
from typing import Any

from common.redis_client import RedisSettings, get_redis_settings

logger = logging.getLogger(__name__)


def _decode(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode()
    return str(value)


class JsonRedisCache:
    """JSON read-through cache backed by Redis."""

    def __init__(self, client, *, settings: RedisSettings) -> None:
        self._client = client
        self._settings = settings

    def get(self, key: str) -> dict | None:
        try:
            raw = self._client.get(key)
        except Exception:
            logger.warning("Redis cache get failed for %s", key, exc_info=True)
            return None
        if not raw:
            return None
        try:
            return json.loads(_decode(raw))
        except json.JSONDecodeError:
            self._client.delete(key)
            return None

    def set(self, key: str, value: dict, *, ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            return
        try:
            self._client.set(key, json.dumps(value, default=str), ex=ttl_seconds)
        except Exception:
            logger.warning("Redis cache set failed for %s", key, exc_info=True)

    def delete(self, key: str) -> None:
        try:
            self._client.delete(key)
        except Exception:
            logger.warning("Redis cache delete failed for %s", key, exc_info=True)


class UserDataVersion:
    """Monotonic per-user version for cache key suffix invalidation."""

    def __init__(self, client) -> None:
        self._client = client

    @staticmethod
    def key(user_id: str) -> str:
        return f"user:{user_id}:data_version"

    def get(self, user_id: str) -> int:
        try:
            value = self._client.get(self.key(user_id))
        except Exception:
            logger.warning("Redis data_version get failed for user %s", user_id, exc_info=True)
            return 0
        if value is None:
            return 0
        try:
            return int(_decode(value))
        except ValueError:
            return 0

    def bump(self, user_id: str) -> int:
        try:
            return int(self._client.incr(self.key(user_id)))
        except Exception:
            logger.warning("Redis data_version bump failed for user %s", user_id, exc_info=True)
            return self.get(user_id)


class AuthVerifyCache:
    """Short-lived cache for auth.verify_token results (gateway hot path)."""

    def __init__(self, client, *, settings: RedisSettings) -> None:
        self._client = client
        self._settings = settings

    @staticmethod
    def token_hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    @staticmethod
    def verify_key(token: str) -> str:
        return f"auth:verify:{AuthVerifyCache.token_hash(token)}"

    @staticmethod
    def user_tokens_key(user_id: str) -> str:
        return f"auth:user:{user_id}:token_hashes"

    def get(self, token: str) -> dict | None:
        try:
            raw = self._client.get(self.verify_key(token))
        except Exception:
            logger.warning("Auth verify cache get failed", exc_info=True)
            return None
        if not raw:
            return None
        try:
            return json.loads(_decode(raw))
        except json.JSONDecodeError:
            self._client.delete(self.verify_key(token))
            return None

    def set(self, token: str, payload: dict, *, ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            return
        user_id = str((payload.get("user") or {}).get("id") or (payload.get("user") or {}).get("user_id") or "")
        token_digest = self.token_hash(token)
        try:
            pipe = self._client.pipeline()
            pipe.set(self.verify_key(token), json.dumps(payload, default=str), ex=ttl_seconds)
            if user_id:
                user_key = self.user_tokens_key(user_id)
                pipe.sadd(user_key, token_digest)
                pipe.expire(user_key, max(ttl_seconds, self._settings.redis_auth_verify_ttl_max_seconds) + 3600)
            pipe.execute()
        except Exception:
            logger.warning("Auth verify cache set failed", exc_info=True)

    def invalidate_user(self, user_id: str) -> None:
        user_key = self.user_tokens_key(user_id)
        try:
            token_hashes = self._client.smembers(user_key)
        except Exception:
            logger.warning("Auth verify cache invalidate read failed for user %s", user_id, exc_info=True)
            return
        if not token_hashes:
            return
        try:
            pipe = self._client.pipeline()
            for digest in token_hashes:
                pipe.delete(f"auth:verify:{_decode(digest)}")
            pipe.delete(user_key)
            pipe.execute()
        except Exception:
            logger.warning("Auth verify cache invalidate failed for user %s", user_id, exc_info=True)

    def ttl_from_auth(self, auth: dict) -> int:
        exp = auth.get("exp")
        if exp is not None:
            remaining = int(exp) - int(time.time())
            if remaining <= 0:
                return 0
            return max(1, min(remaining, self._settings.redis_auth_verify_ttl_max_seconds))
        return self._settings.redis_auth_verify_ttl_seconds


class ImportLock:
    """Distributed lock for concurrent import job processing."""

    def __init__(self, client, *, ttl_seconds: int) -> None:
        self._client = client
        self._ttl_seconds = ttl_seconds

    @staticmethod
    def key(import_id: str) -> str:
        return f"import:lock:{import_id}"

    def acquire(self, import_id: str) -> bool:
        try:
            return bool(self._client.set(self.key(import_id), "1", nx=True, ex=self._ttl_seconds))
        except Exception:
            logger.warning("Import lock acquire failed for %s", import_id, exc_info=True)
            return True

    def release(self, import_id: str) -> None:
        try:
            self._client.delete(self.key(import_id))
        except Exception:
            logger.warning("Import lock release failed for %s", import_id, exc_info=True)


class DetectDebounce:
    """Lock + cooldown for analytics.regular_expenses.detect."""

    def __init__(self, client, *, lock_ttl_seconds: int, debounce_hours: int) -> None:
        self._client = client
        self._lock_ttl_seconds = lock_ttl_seconds
        self._debounce_seconds = debounce_hours * 3600

    @staticmethod
    def lock_key(user_id: str) -> str:
        return f"detect:lock:{user_id}"

    @staticmethod
    def last_detect_key(user_id: str) -> str:
        return f"last_detect_at:{user_id}"

    def is_debounced(self, user_id: str) -> bool:
        try:
            raw = self._client.get(self.last_detect_key(user_id))
        except Exception:
            logger.warning("Detect debounce read failed for user %s", user_id, exc_info=True)
            return False
        if not raw:
            return False
        try:
            last_at = float(_decode(raw))
        except ValueError:
            return False
        return (time.time() - last_at) < self._debounce_seconds

    def acquire_lock(self, user_id: str) -> bool:
        try:
            return bool(self._client.set(self.lock_key(user_id), "1", nx=True, ex=self._lock_ttl_seconds))
        except Exception:
            logger.warning("Detect lock acquire failed for user %s", user_id, exc_info=True)
            return True

    def release_lock(self, user_id: str) -> None:
        try:
            self._client.delete(self.lock_key(user_id))
        except Exception:
            logger.warning("Detect lock release failed for user %s", user_id, exc_info=True)

    def mark_detected(self, user_id: str) -> None:
        try:
            self._client.set(self.last_detect_key(user_id), str(time.time()), ex=self._debounce_seconds)
        except Exception:
            logger.warning("Detect debounce mark failed for user %s", user_id, exc_info=True)


def health_profile_cache_key(user_id: str, period: str, version: int) -> str:
    return f"health:profile:{user_id}:{period}:{version}"


def analytics_balance_cache_key(user_id: str, period_start: date, period_end: date, version: int) -> str:
    return f"analytics:balance:{user_id}:{period_start.isoformat()}:{period_end.isoformat()}:{version}"


def group_budget_cache_key(
    group_id: str,
    period_start: str,
    period_end: str,
    members_hash: str,
    version: int,
) -> str:
    return f"group:budget:{group_id}:{period_start}:{period_end}:{members_hash}:{version}"


def members_hash(member_user_ids: list[str]) -> str:
    digest = hashlib.sha256(",".join(sorted(member_user_ids)).encode()).hexdigest()
    return digest[:16]


def health_profile_ttl_seconds(settings: RedisSettings, period: str) -> int:
    try:
        year_str, month_str = period.split("-", 1)
        year, month = int(year_str), int(month_str)
        last_day = monthrange(year, month)[1]
        end_of_month = datetime(year, month, last_day, 23, 59, 59, tzinfo=UTC)
        remaining = int(end_of_month.timestamp() - time.time())
        if remaining > 0:
            return min(remaining, settings.redis_health_cache_ttl_seconds)
    except (ValueError, TypeError):
        pass
    return settings.redis_health_cache_ttl_seconds


def bump_user_data_version(user_id: str) -> int:
    version = get_user_data_version()
    if version is None:
        return 0
    return version.bump(str(user_id))


def max_user_data_version(user_ids: list[str]) -> int:
    version = get_user_data_version()
    if version is None or not user_ids:
        return 0
    return max(version.get(str(user_id)) for user_id in user_ids)


@lru_cache
def get_redis_cache_client():
    settings = get_redis_settings()
    if not settings.redis_enabled:
        return None
    try:
        import redis

        client = redis.Redis(host=settings.redis_host, port=settings.redis_port, socket_connect_timeout=2)
        client.ping()
        return client
    except Exception:
        logger.warning("Redis cache disabled: connection failed", exc_info=True)
        return None


@lru_cache
def get_json_cache() -> JsonRedisCache | None:
    client = get_redis_cache_client()
    if client is None:
        return None
    return JsonRedisCache(client, settings=get_redis_settings())


@lru_cache
def get_user_data_version() -> UserDataVersion | None:
    client = get_redis_cache_client()
    if client is None:
        return None
    return UserDataVersion(client)


@lru_cache
def get_auth_verify_cache() -> AuthVerifyCache | None:
    client = get_redis_cache_client()
    if client is None:
        return None
    settings = get_redis_settings()
    return AuthVerifyCache(client, settings=settings)


@lru_cache
def get_import_lock() -> ImportLock | None:
    client = get_redis_cache_client()
    if client is None:
        return None
    settings = get_redis_settings()
    return ImportLock(client, ttl_seconds=settings.redis_import_lock_ttl_seconds)


@lru_cache
def get_detect_debounce() -> DetectDebounce | None:
    client = get_redis_cache_client()
    if client is None:
        return None
    settings = get_redis_settings()
    return DetectDebounce(
        client,
        lock_ttl_seconds=settings.redis_detect_lock_ttl_seconds,
        debounce_hours=settings.redis_detect_debounce_hours,
    )
