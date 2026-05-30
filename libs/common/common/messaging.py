from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import aio_pika
from aio_pika import DeliveryMode, Message as AioMessage
from aio_pika.abc import AbstractChannel, AbstractIncomingMessage

from common.redis_client import MessageIdempotencyGuard, get_idempotency_guard

logger = logging.getLogger(__name__)

JsonDict = dict[str, Any]
MessageHandler = Callable[[JsonDict, JsonDict], JsonDict | None]


@dataclass(frozen=True)
class UserContext:
    id: str
    email: str | None = None
    scopes: tuple[str, ...] | None = None

    def as_metadata(self) -> JsonDict:
        payload: JsonDict = {"id": self.id}
        if self.email:
            payload["email"] = self.email
        return payload


def _run_sync(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    raise RuntimeError("MessageBus synchronous API cannot be used inside a running event loop")


class MessageBus:
    def __init__(self, rabbitmq_url: str, source: str) -> None:
        self.rabbitmq_url = rabbitmq_url
        self.source = source

    def request(
        self,
        queue_name: str,
        message_type: str,
        payload: JsonDict | None = None,
        *,
        user: UserContext | None = None,
        timeout_seconds: float = 30.0,
    ) -> JsonDict:
        return _run_sync(
            self._request_async(
                queue_name,
                message_type,
                payload,
                user=user,
                timeout_seconds=timeout_seconds,
            )
        )

    async def _request_async(
        self,
        queue_name: str,
        message_type: str,
        payload: JsonDict | None,
        *,
        user: UserContext | None,
        timeout_seconds: float,
    ) -> JsonDict:
        correlation_id = str(uuid4())
        connection = await aio_pika.connect_robust(self.rabbitmq_url)
        async with connection:
            channel = await connection.channel()
            callback_queue = await channel.declare_queue(exclusive=True, auto_delete=True)
            loop = asyncio.get_running_loop()
            future: asyncio.Future[JsonDict] = loop.create_future()

            async def on_response(message: AbstractIncomingMessage) -> None:
                async with message.process():
                    if message.correlation_id == correlation_id and not future.done():
                        future.set_result(json.loads(message.body.decode("utf-8")))

            await callback_queue.consume(on_response, no_ack=True)
            envelope = build_envelope(
                message_type=message_type,
                source=self.source,
                payload=payload or {},
                correlation_id=correlation_id,
                reply_to=callback_queue.name,
                user=user,
            )
            await channel.default_exchange.publish(
                AioMessage(
                    body=json.dumps(envelope, ensure_ascii=False, default=str).encode("utf-8"),
                    correlation_id=correlation_id,
                    reply_to=callback_queue.name,
                    content_type="application/json",
                    delivery_mode=DeliveryMode.PERSISTENT,
                ),
                routing_key=queue_name,
            )
            try:
                return await asyncio.wait_for(future, timeout=timeout_seconds)
            except asyncio.TimeoutError:
                return error_reply(correlation_id, 504, f"Timed out waiting for {message_type}")

    def publish(
        self,
        queue_name: str,
        message_type: str,
        payload: JsonDict | None = None,
        *,
        user: UserContext | None = None,
        correlation_id: str | None = None,
    ) -> None:
        _run_sync(
            self._publish_async(
                queue_name,
                message_type,
                payload,
                user=user,
                correlation_id=correlation_id,
            )
        )

    async def _publish_async(
        self,
        queue_name: str,
        message_type: str,
        payload: JsonDict | None,
        *,
        user: UserContext | None,
        correlation_id: str | None,
    ) -> None:
        connection = await aio_pika.connect_robust(self.rabbitmq_url)
        async with connection:
            channel = await connection.channel()
            envelope = build_envelope(
                message_type=message_type,
                source=self.source,
                payload=payload or {},
                correlation_id=correlation_id or str(uuid4()),
                user=user,
            )
            await channel.default_exchange.publish(
                AioMessage(
                    body=json.dumps(envelope, ensure_ascii=False, default=str).encode("utf-8"),
                    content_type="application/json",
                    delivery_mode=DeliveryMode.PERSISTENT,
                ),
                routing_key=queue_name,
            )


class MessageWorker:
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_RETRY_DELAY_MS = 1000

    def __init__(
        self,
        *,
        rabbitmq_url: str,
        queue_name: str,
        service_name: str,
        handlers: dict[str, MessageHandler],
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay_ms: int = DEFAULT_RETRY_DELAY_MS,
        idempotency_guard: MessageIdempotencyGuard | None | object = ...,
    ) -> None:
        self.rabbitmq_url = rabbitmq_url
        self.queue_name = queue_name
        self.service_name = service_name
        self.handlers = handlers
        self.max_retries = max(max_retries, 0)
        self.retry_delay_ms = max(retry_delay_ms, 0)
        if idempotency_guard is ...:
            self._idempotency = get_idempotency_guard()
        else:
            self._idempotency = idempotency_guard
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stopping.clear()
        self._thread = threading.Thread(target=self._run, name=f"{self.service_name}-rabbitmq-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()

    def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                asyncio.run(self._consume_forever())
            except Exception:
                if not self._stopping.is_set():
                    logger.exception("RabbitMQ worker %s crashed; retrying", self.service_name)
                    time.sleep(2)

    async def _consume_forever(self) -> None:
        connection = await aio_pika.connect_robust(self.rabbitmq_url)
        async with connection:
            channel = await connection.channel()
            await channel.set_qos(prefetch_count=1)
            await self._declare_retry_and_dead_queues(channel)
            queue = await channel.declare_queue(self.queue_name, durable=True)

            async with queue.iterator() as queue_iter:
                async for message in queue_iter:
                    if self._stopping.is_set():
                        break
                    async with message.process():
                        reply = self._handle_message(message)
                        if message.reply_to:
                            await channel.default_exchange.publish(
                                AioMessage(
                                    body=json.dumps(reply, ensure_ascii=False, default=str).encode("utf-8"),
                                    correlation_id=message.correlation_id,
                                    content_type="application/json",
                                ),
                                routing_key=message.reply_to,
                            )
                        elif not reply.get("ok"):
                            await self._retry_or_dead_letter(channel, message.body, reply)

    def _handle_message(self, message: AbstractIncomingMessage) -> JsonDict:
        correlation_id = message.correlation_id or str(uuid4())
        try:
            envelope = json.loads(message.body.decode("utf-8"))
            message_id = envelope.get("message_id")
            if self._idempotency and message_id and not self._idempotency.claim(str(message_id)):
                return ok_reply(correlation_id, {"status": "duplicate_skipped"})
            message_type = envelope.get("type")
            handler = self.handlers.get(message_type)
            if handler is None:
                return error_reply(correlation_id, 404, f"Unsupported message type: {message_type}")
            payload = handler(envelope.get("payload") or {}, envelope)
            return ok_reply(correlation_id, payload or {})
        except MessageError as exc:
            return error_reply(correlation_id, exc.status_code, exc.detail)
        except Exception as exc:
            logger.exception("Message handler failed in %s", self.service_name)
            return error_reply(correlation_id, 500, str(exc))

    async def _publish_dead_letter(self, channel: AbstractChannel, original_body: bytes, reply: JsonDict) -> None:
        dead_queue = f"{self.queue_name}.dead"
        await channel.declare_queue(dead_queue, durable=True)
        payload = {
            "service": self.service_name,
            "queue": self.queue_name,
            "error": reply,
            "original": json.loads(original_body.decode("utf-8")),
            "created_at": datetime.now(UTC).isoformat(),
        }
        await channel.default_exchange.publish(
            AioMessage(
                body=json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"),
                content_type="application/json",
                delivery_mode=DeliveryMode.PERSISTENT,
            ),
            routing_key=dead_queue,
        )

    async def _retry_or_dead_letter(self, channel: AbstractChannel, original_body: bytes, reply: JsonDict) -> None:
        envelope = json.loads(original_body.decode("utf-8"))
        retry_meta = envelope.get("retry") or {}
        attempts = int(retry_meta.get("attempts") or 0)
        if attempts >= self.max_retries:
            await self._publish_dead_letter(channel, original_body, reply)
            return

        errors = list(retry_meta.get("errors") or [])
        errors.append(
            {
                "status_code": reply.get("status_code"),
                "error": reply.get("error"),
                "failed_at": datetime.now(UTC).isoformat(),
            }
        )
        envelope["retry"] = {
            "attempts": attempts + 1,
            "max_attempts": self.max_retries,
            "delay_ms": self.retry_delay_ms,
            "errors": errors[-10:],
        }
        retry_queue = f"{self.queue_name}.retry"
        await channel.default_exchange.publish(
            AioMessage(
                body=json.dumps(envelope, ensure_ascii=False, default=str).encode("utf-8"),
                content_type="application/json",
                delivery_mode=DeliveryMode.PERSISTENT,
            ),
            routing_key=retry_queue,
        )

    async def _declare_retry_and_dead_queues(self, channel: AbstractChannel) -> None:
        await channel.declare_queue(f"{self.queue_name}.dead", durable=True)
        await channel.declare_queue(
            f"{self.queue_name}.retry",
            durable=True,
            arguments={
                "x-message-ttl": self.retry_delay_ms,
                "x-dead-letter-exchange": "",
                "x-dead-letter-routing-key": self.queue_name,
            },
        )

    # Sync helpers used by unit tests (channel duck-typing).
    def _declare_retry_and_dead_queues_sync(self, channel) -> None:
        channel.queue_declare(queue=f"{self.queue_name}.dead", durable=True)
        channel.queue_declare(
            queue=f"{self.queue_name}.retry",
            durable=True,
            arguments={
                "x-message-ttl": self.retry_delay_ms,
                "x-dead-letter-exchange": "",
                "x-dead-letter-routing-key": self.queue_name,
            },
        )

    def _retry_or_dead_letter_sync(self, channel, original_body: bytes, reply: JsonDict) -> None:
        envelope = json.loads(original_body.decode("utf-8"))
        retry_meta = envelope.get("retry") or {}
        attempts = int(retry_meta.get("attempts") or 0)
        if attempts >= self.max_retries:
            dead_queue = f"{self.queue_name}.dead"
            channel.queue_declare(queue=dead_queue, durable=True)
            payload = {
                "service": self.service_name,
                "queue": self.queue_name,
                "error": reply,
                "original": json.loads(original_body.decode("utf-8")),
                "created_at": datetime.now(UTC).isoformat(),
            }
            channel.basic_publish(
                exchange="",
                routing_key=dead_queue,
                body=json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"),
            )
            return

        errors = list(retry_meta.get("errors") or [])
        errors.append(
            {
                "status_code": reply.get("status_code"),
                "error": reply.get("error"),
                "failed_at": datetime.now(UTC).isoformat(),
            }
        )
        envelope["retry"] = {
            "attempts": attempts + 1,
            "max_attempts": self.max_retries,
            "delay_ms": self.retry_delay_ms,
            "errors": errors[-10:],
        }
        retry_queue = f"{self.queue_name}.retry"
        channel.basic_publish(
            exchange="",
            routing_key=retry_queue,
            body=json.dumps(envelope, ensure_ascii=False, default=str).encode("utf-8"),
        )


class MessageError(Exception):
    def __init__(self, status_code: int, detail: str | JsonDict | list[Any]) -> None:
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


def build_envelope(
    *,
    message_type: str,
    source: str,
    payload: JsonDict,
    correlation_id: str | None = None,
    reply_to: str | None = None,
    user: UserContext | None = None,
) -> JsonDict:
    envelope: JsonDict = {
        "message_id": str(uuid4()),
        "correlation_id": correlation_id or str(uuid4()),
        "type": message_type,
        "source": source,
        "created_at": datetime.now(UTC).isoformat(),
        "payload": payload,
    }
    if reply_to:
        envelope["reply_to"] = reply_to
    if user:
        envelope["user"] = user.as_metadata()
        if user.scopes:
            envelope["auth"] = {"scopes": list(user.scopes)}
    return envelope


def ok_reply(correlation_id: str, payload: JsonDict) -> JsonDict:
    return {
        "correlation_id": correlation_id,
        "ok": True,
        "status_code": 200,
        "payload": payload,
        "created_at": datetime.now(UTC).isoformat(),
    }


def error_reply(correlation_id: str, status_code: int, detail: str | JsonDict | list[Any]) -> JsonDict:
    return {
        "correlation_id": correlation_id,
        "ok": False,
        "status_code": status_code,
        "error": detail,
        "created_at": datetime.now(UTC).isoformat(),
    }


def require_user(envelope: JsonDict) -> UserContext:
    user = envelope.get("user") or {}
    user_id = user.get("id")
    if not user_id:
        raise MessageError(401, "Missing trusted user metadata")
    auth = envelope.get("auth") or {}
    raw_scopes = auth.get("scopes")
    scopes = tuple(str(scope) for scope in raw_scopes) if raw_scopes else None
    return UserContext(id=str(user_id), email=user.get("email"), scopes=scopes)


def check_rabbitmq(rabbitmq_url: str) -> None:
    async def _ping() -> None:
        connection = await aio_pika.connect_robust(rabbitmq_url)
        await connection.close()

    _run_sync(_ping())
