import asyncio
from unittest.mock import AsyncMock

import pytest

from common.messaging import MessageBus, MessageWorker, ok_reply


@pytest.mark.asyncio
async def test_publish_from_handler_thread_uses_asyncio_run(monkeypatch):
    bus = MessageBus("amqp://guest:guest@localhost:5672/%2F", "pytest")
    published = []

    async def fake_publish_async(*args, **kwargs):
        published.append(args)

    monkeypatch.setattr(bus, "_publish_async", fake_publish_async)

    await asyncio.to_thread(
        bus.publish,
        "file-service",
        "files.import.run",
        {"import_id": "1"},
    )

    assert len(published) == 1


@pytest.mark.asyncio
async def test_worker_runs_handler_in_thread_pool(monkeypatch):
    worker = MessageWorker(
        rabbitmq_url="amqp://guest:guest@localhost:5672/%2F",
        queue_name="file-service",
        service_name="file-service",
        handlers={"ping": lambda _p, _e: {"thread": "worker"}},
        idempotency_guard=None,
    )
    to_thread_calls: list = []
    real_to_thread = asyncio.to_thread

    async def track_to_thread(func, *args, **kwargs):
        to_thread_calls.append(func.__name__)
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", track_to_thread)

    body = b'{"type":"ping","payload":{},"message_id":"m1"}'
    message = AsyncMock()
    message.correlation_id = "c1"
    message.reply_to = "reply-q"
    message.body = body
    message.process.return_value.__aenter__ = AsyncMock(return_value=None)
    message.process.return_value.__aexit__ = AsyncMock(return_value=None)

    reply = await real_to_thread(worker._handle_message, message)

    assert reply["ok"] is True
    assert reply["payload"]["thread"] == "worker"
