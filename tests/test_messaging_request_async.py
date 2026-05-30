import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from common.messaging import MessageBus, UserContext, ok_reply


@pytest.mark.asyncio
async def test_request_async_sets_future_without_message_process(monkeypatch):
    bus = MessageBus("amqp://guest:guest@localhost:5672/%2F", "pytest")
    captured_callback = None
    published_correlation_id = None

    class FakeQueue:
        def __init__(self) -> None:
            self.name = "amq.gen-test"
            self.cancel = AsyncMock()

        async def consume(self, callback, no_ack: bool = False):
            nonlocal captured_callback
            captured_callback = callback
            assert no_ack is True
            return "consumer-tag-1"

    channel = MagicMock()
    channel.declare_queue = AsyncMock(return_value=FakeQueue())
    async def capture_publish(message, routing_key: str):
        nonlocal published_correlation_id
        published_correlation_id = message.correlation_id

    channel.default_exchange.publish = AsyncMock(side_effect=capture_publish)

    connection = MagicMock()
    connection.__aenter__ = AsyncMock(return_value=connection)
    connection.__aexit__ = AsyncMock(return_value=None)
    connection.channel = AsyncMock(return_value=channel)

    async def fake_connect(_url):
        return connection

    monkeypatch.setattr("common.messaging.aio_pika.connect_robust", fake_connect)

    task = asyncio.create_task(
        bus.request_async(
            "file-service",
            "files.upload.create",
            {"filename": "a.xlsx"},
            user=UserContext(id="00000000-0000-0000-0000-000000000001"),
            timeout_seconds=2.0,
        )
    )
    await asyncio.sleep(0)
    assert captured_callback is not None

    assert published_correlation_id is not None
    response_body = ok_reply(published_correlation_id, {"import_id": "x"})
    fake_message = MagicMock()
    fake_message.correlation_id = published_correlation_id
    fake_message.body = json.dumps(response_body).encode("utf-8")

    await captured_callback(fake_message)
    result = await task

    assert result["ok"] is True
    assert result["payload"]["import_id"] == "x"
