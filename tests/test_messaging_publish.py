import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from common.messaging import MessageBus, UserContext, build_envelope


@pytest.mark.asyncio
async def test_message_bus_publish_sends_envelope_to_queue():
    bus = MessageBus("amqp://guest:guest@localhost:5672/%2F", "pytest")
    user = UserContext(id="00000000-0000-0000-0000-000000000001", email="u@example.com")

    published: list[tuple[str, bytes]] = []

    async def fake_publish(message, routing_key: str):
        published.append((routing_key, message.body))

    channel = MagicMock()
    channel.default_exchange.publish = AsyncMock(side_effect=fake_publish)

    connection = MagicMock()
    connection.__aenter__ = AsyncMock(return_value=connection)
    connection.__aexit__ = AsyncMock(return_value=None)

    async def channel_factory():
        return channel

    connection.channel = AsyncMock(return_value=channel)

    with patch("common.messaging.aio_pika.connect_robust", AsyncMock(return_value=connection)):
        await bus._publish_async(
            "target-queue",
            "tasks.fire_and_forget",
            {"id": 1},
            user=user,
            correlation_id="corr-123",
        )

    assert len(published) == 1
    routing_key, body = published[0]
    assert routing_key == "target-queue"
    envelope = json.loads(body.decode("utf-8"))
    assert envelope["type"] == "tasks.fire_and_forget"
    assert envelope["source"] == "pytest"
    assert envelope["correlation_id"] == "corr-123"
    assert envelope["payload"] == {"id": 1}
    assert envelope["user"]["id"] == user.id
    expected = build_envelope(
        message_type="tasks.fire_and_forget",
        source="pytest",
        payload={"id": 1},
        correlation_id="corr-123",
        user=user,
    )
    assert envelope["type"] == expected["type"]
    assert envelope["source"] == expected["source"]
    assert envelope["correlation_id"] == expected["correlation_id"]
