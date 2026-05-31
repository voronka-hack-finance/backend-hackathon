from __future__ import annotations

import json

from services.chat_service.app.workflow_result_content import normalize_assistant_content, resolve_assistant_content
from services.chat_service.app.workflow_result_schemas import WorkflowResultMessage


def test_normalize_strips_zapros_prefix():
    raw = "Запрос: проанализируй расходы за последние 6 месяцев\n\nОсновные расходы сосредоточены на переводах."
    assert normalize_assistant_content(content=raw) == "Основные расходы сосредоточены на переводах."


def test_normalize_extracts_json_response_field():
    raw = json.dumps(
        {
            "query": "проанализируй расходы",
            "response": "Основные расходы сосредоточены на переводах.",
        },
        ensure_ascii=False,
    )
    assert normalize_assistant_content(content=raw) == "Основные расходы сосредоточены на переводах."


def test_normalize_prefers_metadata_response():
    content = "Запрос: fallback\n\nignored"
    metadata = {"response": "Ответ из metadata"}
    assert normalize_assistant_content(content=content, metadata=metadata) == "Ответ из metadata"


def test_resolve_assistant_content_from_workflow_result_message():
    message = WorkflowResultMessage.model_validate(
        {
            "schema_version": "1.0",
            "message_type": "ai.workflow.result",
            "request_id": "550e8400-e29b-41d4-a716-446655440000",
            "workflow_run_id": "660e8400-e29b-41d4-a716-446655440001",
            "user_id": "770e8400-e29b-41d4-a716-446655440002",
            "chat_id": "880e8400-e29b-41d4-a716-446655440003",
            "message_id": "990e8400-e29b-41d4-a716-446655440004",
            "status": "success",
            "content": "Запрос: test\n\nЧистый ответ.",
            "created_at": "2026-05-31T05:13:48Z",
        }
    )
    assert resolve_assistant_content(message) == "Чистый ответ."
