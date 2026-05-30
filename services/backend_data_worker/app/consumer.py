from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from typing import Any

import aio_pika
from aio_pika import DeliveryMode, Message as AioMessage

from services.backend_data_worker.app.config import settings
from services.backend_data_worker.app.processor import process_request_bytes

logger = logging.getLogger(__name__)


async def _close_connection(connection: Any) -> None:
    try:
        if getattr(connection, "is_closed", False):
            return
        await connection.close()
    except Exception:
        pass


class AiBackendDataConsumer:
    def __init__(
        self,
        *,
        rabbitmq_url: str,
        request_queue: str,
        response_queue: str,
    ) -> None:
        self.rabbitmq_url = rabbitmq_url
        self.request_queue = request_queue
        self.response_queue = response_queue
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self._consumer_lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._connection: Any = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stopping.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="backend-data-worker-rabbitmq-consumer",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stopping.set()
        self._request_connection_close(timeout=min(timeout, 5.0))
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def _request_connection_close(self, timeout: float) -> None:
        with self._consumer_lock:
            connection = self._connection
            loop = self._loop
        if connection is None or loop is None:
            return
        try:
            if loop.is_closed():
                return
            future = asyncio.run_coroutine_threadsafe(_close_connection(connection), loop)
            future.result(timeout=timeout)
        except Exception as exc:
            logger.debug("RabbitMQ shutdown close ignored: %s", exc.__class__.__name__)

    def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                asyncio.run(self._consume_forever())
            except Exception:
                if not self._stopping.is_set():
                    logger.exception("AI backend data consumer crashed; retrying in 2s")
                    time.sleep(2)

    async def _consume_forever(self) -> None:
        self._loop = asyncio.get_running_loop()
        connection = await aio_pika.connect_robust(self.rabbitmq_url)
        with self._consumer_lock:
            self._connection = connection
        try:
            async with connection:
                channel = await connection.channel()
                await channel.set_qos(prefetch_count=1)
                queue = await channel.declare_queue(self.request_queue, durable=True)
                await channel.declare_queue(self.response_queue, durable=True)
                logger.info(
                    "ai_backend_data_consumer_connected request_queue=%s response_queue=%s",
                    self.request_queue,
                    self.response_queue,
                )

                async with queue.iterator() as queue_iter:
                    async for message in queue_iter:
                        if self._stopping.is_set():
                            break
                        async with message.process():
                            response = await asyncio.to_thread(process_request_bytes, message.body)
                            publish_payload = response.to_publish_dict()
                            tx_block = (publish_payload.get("data") or {}).get("transactions")
                            mapped_tx_count = (
                                len(tx_block.get("items") or [])
                                if isinstance(tx_block, dict)
                                else 0
                            )
                            body = json.dumps(
                                publish_payload,
                                ensure_ascii=False,
                                default=str,
                            ).encode("utf-8")
                            await channel.default_exchange.publish(
                                AioMessage(
                                    body=body,
                                    content_type="application/json",
                                    delivery_mode=DeliveryMode.PERSISTENT,
                                    correlation_id=response.correlation_id,
                                ),
                                routing_key=self.response_queue,
                            )
                            logger.info(
                                "backend_data_response_published correlation_id=%s status=%s mapped_transactions_count=%s response_queue=%s message_type=%s",
                                response.correlation_id,
                                response.status,
                                mapped_tx_count,
                                self.response_queue,
                                publish_payload.get("message_type"),
                            )
        finally:
            with self._consumer_lock:
                self._connection = None
                self._loop = None


consumer = AiBackendDataConsumer(
    rabbitmq_url=settings.rabbitmq_url,
    request_queue=settings.request_queue,
    response_queue=settings.response_queue,
)
