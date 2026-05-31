from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any

import aio_pika

from services.chat_service.app.runtime import engine, settings
from services.chat_service.app.workflow_result_processor import (
    WorkflowResultProcessingError,
    process_workflow_result_bytes,
)

logger = logging.getLogger(__name__)


async def _close_connection(connection: Any) -> None:
    try:
        if getattr(connection, "is_closed", False):
            return
        await connection.close()
    except Exception:
        pass


class WorkflowResultConsumer:
    def __init__(
        self,
        *,
        rabbitmq_url: str,
        result_queue: str,
    ) -> None:
        self.rabbitmq_url = rabbitmq_url
        self.result_queue = result_queue
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
            name="chat-service-workflow-result-consumer",
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
                    logger.exception("Workflow result consumer crashed; retrying in 2s")
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
                queue = await channel.declare_queue(self.result_queue, durable=True)
                logger.info(
                    "workflow_result_consumer_connected queue=%s",
                    self.result_queue,
                )

                async with queue.iterator() as queue_iter:
                    async for message in queue_iter:
                        if self._stopping.is_set():
                            break
                        async with message.process():
                            try:
                                await asyncio.to_thread(
                                    process_workflow_result_bytes,
                                    message.body,
                                    engine=engine,
                                )
                            except WorkflowResultProcessingError:
                                logger.warning(
                                    "workflow_result_processing_rejected queue=%s",
                                    self.result_queue,
                                )
                            except Exception:
                                logger.exception(
                                    "workflow_result_processing_failed queue=%s",
                                    self.result_queue,
                                )
                                raise
        finally:
            with self._consumer_lock:
                self._connection = None
                self._loop = None


workflow_result_consumer = WorkflowResultConsumer(
    rabbitmq_url=settings.rabbitmq_workflow_url,
    result_queue=settings.rabbitmq_workflow_result_queue,
)
