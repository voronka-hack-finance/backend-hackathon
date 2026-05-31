from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from services.chat_service.app.workflow_result_consumer import WorkflowResultConsumer
from services.chat_service.app.workflow_result_processor import (
    WorkflowResultProcessingError,
    process_workflow_result_bytes,
)
from services.chat_service.app.workflow_result_schemas import (
    DEFAULT_ERROR_CONTENT,
    MESSAGE_TYPE,
    SCHEMA_VERSION,
    WorkflowResultMessage,
)


def _result_payload(**overrides) -> dict:
    base = {
        "schema_version": SCHEMA_VERSION,
        "message_type": MESSAGE_TYPE,
        "request_id": str(uuid4()),
        "workflow_run_id": str(uuid4()),
        "user_id": str(uuid4()),
        "chat_id": str(uuid4()),
        "message_id": str(uuid4()),
        "status": "success",
        "content": "Ответ ассистента",
        "created_at": "2026-05-31T12:00:00Z",
        "errors": [],
        "metadata": {},
    }
    base.update(overrides)
    return base


def test_workflow_result_message_rejects_extra_fields():
    payload = _result_payload(unexpected=True)
    with pytest.raises(ValidationError):
        WorkflowResultMessage.model_validate(payload)


def test_workflow_result_message_error_status_uses_default_content():
    message = WorkflowResultMessage.model_validate(
        _result_payload(status="error", content="   ")
    )
    assert message.content == DEFAULT_ERROR_CONTENT


def test_workflow_result_message_success_requires_content():
    with pytest.raises(ValidationError):
        WorkflowResultMessage.model_validate(_result_payload(status="success", content=""))


@contextmanager
def _mock_engine(*, existing_inbox=None, chat_exists=True, trigger_exists=True):
    chat_id = uuid4()
    user_id = uuid4()
    message_id = uuid4()
    assistant_id = uuid4()
    assistant_row = {
        "id": assistant_id,
        "chat_id": chat_id,
        "user_id": user_id,
        "role": "assistant",
        "content": "Ответ ассистента",
        "created_at": datetime.now(timezone.utc),
    }

    execute_results: list[list[dict]] = []
    sql_log: list[str] = []

    if existing_inbox is not None:
        execute_results.append([existing_inbox])
    else:
        execute_results.append([])
        execute_results.append([{"id": chat_id}] if chat_exists else [])
        execute_results.append([{"id": message_id}] if chat_exists and trigger_exists else [])
        if chat_exists and trigger_exists:
            execute_results.append([assistant_row])
            execute_results.append([])
            execute_results.append([])

    connection = MagicMock()

    def fake_execute(statement, params=None):
        sql_log.append(str(statement))
        result = MagicMock()
        mappings = MagicMock()
        rows = execute_results.pop(0) if execute_results else []
        mappings.first.return_value = rows[0] if rows else None
        if rows:
            mappings.one.return_value = rows[0]
        result.mappings.return_value = mappings
        return result

    connection.execute.side_effect = fake_execute

    @contextmanager
    def fake_begin():
        yield connection

    engine = MagicMock()
    engine.begin.side_effect = fake_begin
    yield engine, assistant_row, sql_log


def test_process_workflow_result_inserts_assistant_message():
    payload = _result_payload()
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    with _mock_engine() as (engine, assistant_row, _):
        result = process_workflow_result_bytes(body, engine=engine)

    assert result is not None
    assert result["role"] == "assistant"
    assert result["content"] == "Ответ ассистента"
    assert result["id"] == str(assistant_row["id"])


def test_process_workflow_result_idempotent_skip():
    payload = _result_payload()
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    existing = {
        "workflow_run_id": payload["workflow_run_id"],
        "assistant_message_id": None,
    }

    with _mock_engine(existing_inbox=existing) as (engine, _, _):
        assert process_workflow_result_bytes(body, engine=engine) is None

    with _mock_engine(existing_inbox=existing) as (engine, _, _):
        assert process_workflow_result_bytes(body, engine=engine) is None


def test_process_workflow_result_rejects_unknown_chat():
    payload = _result_payload()
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    with _mock_engine(chat_exists=False) as (engine, _, _):
        with pytest.raises(WorkflowResultProcessingError, match="chat not found"):
            process_workflow_result_bytes(body, engine=engine)


def test_process_workflow_result_does_not_touch_outbox():
    payload = _result_payload()
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    with _mock_engine() as (engine, _, sql_log):
        process_workflow_result_bytes(body, engine=engine)
        executed_sql = " ".join(sql_log)
        assert "ai_workflow_task_outbox" not in executed_sql


@pytest.mark.asyncio
async def test_workflow_result_consumer_declares_durable_queue():
    from unittest.mock import AsyncMock, patch

    declared: list[tuple[str, bool]] = []

    async def fake_declare_queue(name, durable=False, **kwargs):
        declared.append((name, durable))
        raise RuntimeError("stop-after-declare")

    channel = MagicMock()
    channel.declare_queue = AsyncMock(side_effect=fake_declare_queue)
    channel.set_qos = AsyncMock()

    connection = MagicMock()
    connection.__aenter__ = AsyncMock(return_value=connection)
    connection.__aexit__ = AsyncMock(return_value=None)
    connection.channel = AsyncMock(return_value=channel)

    consumer = WorkflowResultConsumer(
        rabbitmq_url="amqp://guest:guest@localhost:5672/%2F",
        result_queue="ai.workflow.results",
    )

    with patch(
        "services.chat_service.app.workflow_result_consumer.aio_pika.connect_robust",
        new=AsyncMock(return_value=connection),
    ):
        with pytest.raises(RuntimeError, match="stop-after-declare"):
            await consumer._consume_forever()

    assert declared == [("ai.workflow.results", True)]
