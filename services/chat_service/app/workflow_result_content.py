from __future__ import annotations

import json
import re
from typing import Any

from services.chat_service.app.workflow_result_schemas import WorkflowResultMessage

_RESPONSE_JSON_KEYS = (
    "response",
    "answer",
    "assistant_message",
    "assistant_text",
    "text",
    "message",
    "content",
    "body",
)
_REQUEST_PREFIX_RE = re.compile(
    r"^(?:Запрос|Request)\s*:\s*.+?(?:\n\s*){1,2}",
    re.IGNORECASE | re.DOTALL,
)


def _extract_from_mapping(payload: dict[str, Any]) -> str | None:
    for key in _RESPONSE_JSON_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    nested = payload.get("data")
    if isinstance(nested, dict):
        return _extract_from_mapping(nested)
    result = payload.get("result")
    if isinstance(result, dict):
        return _extract_from_mapping(result)
    return None


def normalize_assistant_content(*, content: str, metadata: dict[str, Any] | None = None) -> str:
    metadata = metadata or {}
    for source in (metadata,):
        extracted = _extract_from_mapping(source)
        if extracted:
            return _normalize_plain_text(extracted)

    stripped = content.strip()
    if not stripped:
        return stripped

    if stripped.startswith("{") or stripped.startswith("["):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            extracted = _extract_from_mapping(parsed)
            if extracted:
                return _normalize_plain_text(extracted)

    return _normalize_plain_text(stripped)


def _normalize_plain_text(text: str) -> str:
    cleaned = _REQUEST_PREFIX_RE.sub("", text.strip(), count=1).strip()
    return cleaned or text.strip()


def resolve_assistant_content(result: WorkflowResultMessage) -> str:
    return normalize_assistant_content(content=result.content, metadata=result.metadata)
