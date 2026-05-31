from __future__ import annotations

import json
import time

import pytest

from common.redis_cache import (
    AuthVerifyCache,
    DetectDebounce,
    ImportLock,
    JsonRedisCache,
    UserDataVersion,
    analytics_balance_cache_key,
    bump_user_data_version,
    health_profile_cache_key,
    members_hash,
)
from common.redis_client import RedisSettings


class FakeRedis:
    def __init__(self) -> None:
        self._values: dict[str, str] = {}
        self._sets: dict[str, set[str]] = {}

    def ping(self) -> bool:
        return True

    def get(self, key: str):
        return self._values.get(key)

    def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool | None:
        if nx and key in self._values:
            return None
        self._values[key] = value
        return True

    def delete(self, key: str) -> None:
        self._values.pop(key, None)
        self._sets.pop(key, None)

    def incr(self, key: str) -> int:
        current = int(self._values.get(key, "0"))
        current += 1
        self._values[key] = str(current)
        return current

    def smembers(self, key: str):
        return self._sets.get(key, set())

    def sadd(self, key: str, value: str) -> None:
        self._sets.setdefault(key, set()).add(value)

    def expire(self, key: str, ttl: int) -> None:
        return None

    def pipeline(self):
        return FakePipeline(self)


class FakePipeline:
    def __init__(self, client: FakeRedis) -> None:
        self._client = client
        self._ops: list[tuple] = []

    def set(self, key: str, value: str, ex: int | None = None):
        self._ops.append(("set", key, value))
        return self

    def sadd(self, key: str, value: str):
        self._ops.append(("sadd", key, value))
        return self

    def delete(self, key: str):
        self._ops.append(("delete", key))
        return self

    def expire(self, key: str, ttl: int):
        self._ops.append(("expire", key, ttl))
        return self

    def execute(self):
        for op in self._ops:
            if op[0] == "set":
                self._client.set(op[1], op[2])
            elif op[0] == "sadd":
                self._client.sadd(op[1], op[2])
            elif op[0] == "delete":
                self._client.delete(op[1])


@pytest.fixture
def redis_settings() -> RedisSettings:
    return RedisSettings(
        REDIS_HOST="localhost",
        REDIS_PORT=6379,
        REDIS_ENABLED=True,
        REDIS_IDEMPOTENCY_TTL_SECONDS=86400,
        REDIS_HEALTH_CACHE_TTL_SECONDS=3600,
        REDIS_ANALYTICS_CACHE_TTL_SECONDS=1800,
        REDIS_AUTH_VERIFY_TTL_SECONDS=60,
        REDIS_AUTH_VERIFY_TTL_MAX_SECONDS=120,
        REDIS_IMPORT_LOCK_TTL_SECONDS=600,
        REDIS_DETECT_LOCK_TTL_SECONDS=300,
        REDIS_DETECT_DEBOUNCE_HOURS=6,
    )


def test_json_cache_roundtrip(redis_settings: RedisSettings):
    client = FakeRedis()
    cache = JsonRedisCache(client, settings=redis_settings)
    payload = {"available_amount": "100.00", "currency": "RUB"}
    cache.set("analytics:balance:u1:2026-05-01:2026-05-31:0", payload, ttl_seconds=60)
    assert cache.get("analytics:balance:u1:2026-05-01:2026-05-31:0") == payload


def test_user_data_version_increments():
    client = FakeRedis()
    version = UserDataVersion(client)
    assert version.get("user-1") == 0
    assert version.bump("user-1") == 1
    assert version.get("user-1") == 1


def test_cache_keys_include_version():
    from datetime import date

    assert health_profile_cache_key("u1", "2026-05", 3) == "health:profile:u1:2026-05:3"
    assert analytics_balance_cache_key("u1", date(2026, 5, 1), date(2026, 5, 31), 2).endswith(":2")
    assert members_hash(["b", "a"]) == members_hash(["a", "b"])


def test_auth_verify_cache_invalidate_user(redis_settings: RedisSettings):
    client = FakeRedis()
    cache = AuthVerifyCache(client, settings=redis_settings)
    token = "sample-token"
    payload = {"user": {"id": "user-1", "email": "a@example.com"}, "auth": {"scopes": [], "exp": int(time.time()) + 300}}
    cache.set(token, payload, ttl_seconds=60)
    assert cache.get(token) == payload
    cache.invalidate_user("user-1")
    assert cache.get(token) is None


def test_import_lock_is_exclusive():
    lock = ImportLock(FakeRedis(), ttl_seconds=60)
    assert lock.acquire("import-1") is True
    assert lock.acquire("import-1") is False
    lock.release("import-1")
    assert lock.acquire("import-1") is True


def test_detect_debounce_blocks_repeat_runs():
    debounce = DetectDebounce(FakeRedis(), lock_ttl_seconds=60, debounce_hours=1)
    assert debounce.acquire_lock("user-1") is True
    debounce.mark_detected("user-1")
    debounce.release_lock("user-1")
    assert debounce.is_debounced("user-1") is True


def test_bump_user_data_version_noop_when_disabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("common.redis_cache.get_user_data_version", lambda: None)
    assert bump_user_data_version("user-1") == 0
