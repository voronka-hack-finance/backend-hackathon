from __future__ import annotations

import logging
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class RedisSettings(BaseSettings):
    redis_host: str = Field(default="localhost", validation_alias="REDIS_HOST")
    redis_port: int = Field(default=6379, validation_alias="REDIS_PORT")
    redis_enabled: bool = Field(default=True, validation_alias="REDIS_ENABLED")
    redis_idempotency_ttl_seconds: int = Field(default=86400, validation_alias="REDIS_IDEMPOTENCY_TTL_SECONDS")

    model_config = SettingsConfigDict(extra="ignore")


@lru_cache
def get_redis_settings() -> RedisSettings:
    return RedisSettings()


def check_redis(*, host: str | None = None, port: int | None = None) -> None:
    settings = get_redis_settings()
    if not settings.redis_enabled:
        return
    import redis

    client = redis.Redis(
        host=host or settings.redis_host,
        port=port or settings.redis_port,
        socket_connect_timeout=2,
    )
    client.ping()


class MessageIdempotencyGuard:
    """Deduplicate RabbitMQ command handling by message_id (plan: optional idempotency)."""

    def __init__(self, client, *, ttl_seconds: int) -> None:
        self._client = client
        self._ttl_seconds = ttl_seconds

    def claim(self, message_id: str) -> bool:
        key = f"family-budget:msg:{message_id}"
        return bool(self._client.set(key, "1", nx=True, ex=self._ttl_seconds))


@lru_cache
def get_idempotency_guard() -> MessageIdempotencyGuard | None:
    settings = get_redis_settings()
    if not settings.redis_enabled:
        return None
    try:
        import redis

        client = redis.Redis(host=settings.redis_host, port=settings.redis_port, socket_connect_timeout=2)
        client.ping()
        return MessageIdempotencyGuard(client, ttl_seconds=settings.redis_idempotency_ttl_seconds)
    except Exception:
        logger.warning("Redis idempotency disabled: connection failed", exc_info=True)
        return None
