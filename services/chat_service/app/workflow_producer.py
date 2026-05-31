from __future__ import annotations

import asyncio
import logging
from typing import Any

import aio_pika
from aio_pika import DeliveryMode, Message as AioMessage

logger = logging.getLogger(__name__)


def _run_sync(coro, *, timeout: float | None = 30.0) -> Any:
    async def _runner() -> Any:
        if timeout is None:
            return await coro
        return await asyncio.wait_for(coro, timeout=timeout)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_runner())
    raise RuntimeError("Workflow producer must not run on the RabbitMQ consumer event-loop thread")


async def publish_workflow_task_bytes(
    *,
    rabbitmq_url: str,
    queue_name: str,
    body: bytes,
) -> None:
    connection = await aio_pika.connect_robust(rabbitmq_url)
    async with connection:
        channel = await connection.channel()
        await channel.declare_queue(queue_name, durable=True)
        await channel.default_exchange.publish(
            AioMessage(body=body, delivery_mode=DeliveryMode.PERSISTENT),
            routing_key=queue_name,
        )
    logger.info(
        "ai_workflow_task_published queue=%s bytes=%s",
        queue_name,
        len(body),
    )


def publish_workflow_task_bytes_sync(
    *,
    rabbitmq_url: str,
    queue_name: str,
    body: bytes,
    timeout_seconds: float = 10.0,
) -> None:
    _run_sync(
        publish_workflow_task_bytes(
            rabbitmq_url=rabbitmq_url,
            queue_name=queue_name,
            body=body,
        ),
        timeout=timeout_seconds + 2.0,
    )
