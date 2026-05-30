from __future__ import annotations

import json
import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pika

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
        correlation_id = str(uuid4())
        reply_queue = f"reply.{self.source}.{correlation_id}"
        connection = _connect(self.rabbitmq_url)
        channel = connection.channel()
        channel.queue_declare(queue=queue_name, durable=True)
        channel.queue_declare(queue=reply_queue, exclusive=True, auto_delete=True)
        response_queue: queue.Queue[JsonDict] = queue.Queue(maxsize=1)

        def on_response(_channel, method, properties, body):
            if properties.correlation_id == correlation_id:
                response_queue.put(json.loads(body.decode("utf-8")))
                _channel.basic_ack(method.delivery_tag)

        channel.basic_consume(queue=reply_queue, on_message_callback=on_response)
        envelope = build_envelope(
            message_type=message_type,
            source=self.source,
            payload=payload or {},
            correlation_id=correlation_id,
            reply_to=reply_queue,
            user=user,
        )
        channel.basic_publish(
            exchange="",
            routing_key=queue_name,
            properties=pika.BasicProperties(
                correlation_id=correlation_id,
                reply_to=reply_queue,
                content_type="application/json",
                delivery_mode=2,
            ),
            body=json.dumps(envelope, ensure_ascii=False, default=str).encode("utf-8"),
        )
        try:
            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline:
                connection.process_data_events(time_limit=0.2)
                try:
                    return response_queue.get_nowait()
                except queue.Empty:
                    continue
            return error_reply(correlation_id, 504, f"Timed out waiting for {message_type}")
        finally:
            if connection.is_open:
                connection.close()

    def publish(
        self,
        queue_name: str,
        message_type: str,
        payload: JsonDict | None = None,
        *,
        user: UserContext | None = None,
        correlation_id: str | None = None,
    ) -> None:
        connection = _connect(self.rabbitmq_url)
        channel = connection.channel()
        channel.queue_declare(queue=queue_name, durable=True)
        envelope = build_envelope(
            message_type=message_type,
            source=self.source,
            payload=payload or {},
            correlation_id=correlation_id or str(uuid4()),
            user=user,
        )
        channel.basic_publish(
            exchange="",
            routing_key=queue_name,
            properties=pika.BasicProperties(content_type="application/json", delivery_mode=2),
            body=json.dumps(envelope, ensure_ascii=False, default=str).encode("utf-8"),
        )
        connection.close()


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
    ) -> None:
        self.rabbitmq_url = rabbitmq_url
        self.queue_name = queue_name
        self.service_name = service_name
        self.handlers = handlers
        self.max_retries = max(max_retries, 0)
        self.retry_delay_ms = max(retry_delay_ms, 0)
        self._thread: threading.Thread | None = None
        self._connection = None
        self._stopping = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stopping.clear()
        self._thread = threading.Thread(target=self._run, name=f"{self.service_name}-rabbitmq-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        if self._connection and self._connection.is_open:
            try:
                self._connection.close()
            except Exception:
                logger.exception("Failed to close RabbitMQ connection for %s", self.service_name)

    def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                self._connection = _connect(self.rabbitmq_url)
                channel = self._connection.channel()
                channel.queue_declare(queue=self.queue_name, durable=True)
                self._declare_retry_and_dead_queues(channel)
                channel.basic_qos(prefetch_count=1)

                def on_message(_channel, method, properties, body):
                    reply = self._handle_message(properties, body)
                    if properties.reply_to:
                        _channel.basic_publish(
                            exchange="",
                            routing_key=properties.reply_to,
                            properties=pika.BasicProperties(
                                correlation_id=properties.correlation_id,
                                content_type="application/json",
                            ),
                            body=json.dumps(reply, ensure_ascii=False, default=str).encode("utf-8"),
                        )
                    elif not reply.get("ok"):
                        self._retry_or_dead_letter(_channel, body, reply)
                    _channel.basic_ack(method.delivery_tag)

                channel.basic_consume(queue=self.queue_name, on_message_callback=on_message)
                channel.start_consuming()
            except Exception:
                if not self._stopping.is_set():
                    logger.exception("RabbitMQ worker %s crashed; retrying", self.service_name)
                    time.sleep(2)

    def _handle_message(self, properties, body) -> JsonDict:
        correlation_id = properties.correlation_id or str(uuid4())
        try:
            envelope = json.loads(body.decode("utf-8"))
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

    def _publish_dead_letter(self, channel, original_body, reply: JsonDict) -> None:
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
            properties=pika.BasicProperties(content_type="application/json", delivery_mode=2),
            body=json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"),
        )

    def _retry_or_dead_letter(self, channel, original_body, reply: JsonDict) -> None:
        envelope = json.loads(original_body.decode("utf-8"))
        retry_meta = envelope.get("retry") or {}
        attempts = int(retry_meta.get("attempts") or 0)
        if attempts >= self.max_retries:
            self._publish_dead_letter(channel, original_body, reply)
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
            properties=pika.BasicProperties(content_type="application/json", delivery_mode=2),
            body=json.dumps(envelope, ensure_ascii=False, default=str).encode("utf-8"),
        )

    def _declare_retry_and_dead_queues(self, channel) -> None:
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
    return UserContext(id=str(user_id), email=user.get("email"))


def check_rabbitmq(rabbitmq_url: str) -> None:
    connection = _connect(rabbitmq_url)
    try:
        connection.channel()
    finally:
        if connection.is_open:
            connection.close()


def _connect(rabbitmq_url: str):
    params = pika.URLParameters(rabbitmq_url)
    deadline = time.monotonic() + 60
    while True:
        try:
            return pika.BlockingConnection(params)
        except pika.exceptions.AMQPConnectionError:
            if time.monotonic() > deadline:
                raise
            time.sleep(1)
