from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from services.chat_service.app.workflow_outbox import build_workflow_task, user_local_date, utc_now_iso_z
from services.chat_service.app.workflow_producer import publish_workflow_task_bytes
from services.chat_service.app.workflow_schemas import ChatContext, ChatContextMessage, WorkflowTask


def test_workflow_task_rejects_extra_fields():
    with pytest.raises(ValidationError):
        WorkflowTask(
            request_id=str(uuid4()),
            workflow_run_id=str(uuid4()),
            user_id="user-1",
            chat_id="chat-1",
            message_id="msg-1",
            raw_message="Привет",
            current_date="2026-05-31",
            timezone="UTC",
            created_at=utc_now_iso_z(),
            unexpected=True,  # type: ignore[call-arg]
        )


def test_workflow_task_compact_json_without_extra_top_level_keys():
    task = build_workflow_task(
        user_id="550e8400-e29b-41d4-a716-446655440000",
        chat_id="chat_abc",
        message_id="msg_xyz",
        raw_message="Куда уходят деньги?",
        timezone_name="Europe/Moscow",
    )
    payload = task.to_publish_dict()
    assert set(payload.keys()) == {
        "request_id",
        "workflow_run_id",
        "user_id",
        "chat_id",
        "message_id",
        "raw_message",
        "current_date",
        "timezone",
        "created_at",
    }
    assert payload["timezone"] == "Europe/Moscow"
    assert payload["current_date"] == user_local_date("Europe/Moscow")
    body = task.to_publish_bytes().decode("utf-8")
    expected = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    assert body == expected
    parsed = json.loads(body)
    assert parsed["raw_message"] == "Куда уходят деньги?"


def test_workflow_task_with_chat_context_includes_null_legacy_fields():
    task = build_workflow_task(
        user_id="user-1",
        chat_id="chat-1",
        message_id="msg-1",
        raw_message="А за прошлый месяц?",
        timezone_name="Europe/Moscow",
        chat_context=ChatContext(
            last_6_messages=[
                ChatContextMessage(role="user", content="Куда уходят деньги?"),
                ChatContextMessage(role="assistant", content="..."),
            ],
            chat_summary=None,
            active_workflow=None,
        ),
    )
    payload = task.to_publish_dict()
    assert payload["chat_context"]["last_6_messages"][0]["role"] == "user"
    assert payload["chat_context"]["chat_summary"] is None
    assert payload["chat_context"]["active_workflow"] is None
    assert "active_workflow" not in payload


@pytest.mark.asyncio
async def test_publish_workflow_task_declares_durable_queue_and_routes_body():
    published: list[tuple[str, bytes]] = []
    declared: list[tuple[str, bool]] = []

    async def fake_declare_queue(name, durable=False, **kwargs):
        declared.append((name, durable))
        queue = MagicMock()
        return queue

    async def fake_publish(message, routing_key: str):
        published.append((routing_key, message.body))

    channel = MagicMock()
    channel.declare_queue = AsyncMock(side_effect=fake_declare_queue)
    channel.default_exchange.publish = AsyncMock(side_effect=fake_publish)

    connection = MagicMock()
    connection.__aenter__ = AsyncMock(return_value=connection)
    connection.__aexit__ = AsyncMock(return_value=None)
    connection.channel = AsyncMock(return_value=channel)

    body = b'{"request_id":"r1"}'
    with patch("services.chat_service.app.workflow_producer.aio_pika.connect_robust", AsyncMock(return_value=connection)):
        await publish_workflow_task_bytes(
            rabbitmq_url="amqp://guest:guest@localhost:5672/%2F",
            queue_name="ai.workflow.tasks",
            body=body,
        )

    assert declared == [("ai.workflow.tasks", True)]
    assert published == [("ai.workflow.tasks", body)]
