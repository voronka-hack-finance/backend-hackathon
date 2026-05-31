from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChatContextMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str
    content: str


class ChatContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    last_6_messages: list[ChatContextMessage] = Field(default_factory=list)
    chat_summary: str | None = None
    active_workflow: str | dict[str, Any] | None = None


class WorkflowTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    workflow_run_id: str
    user_id: str
    chat_id: str
    message_id: str
    raw_message: str
    current_date: str
    timezone: str
    created_at: str
    chat_context: ChatContext | None = None
    active_workflow: str | dict[str, Any] | None = None

    def to_publish_dict(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json", exclude_none=True)
        if self.chat_context is not None:
            payload["chat_context"] = self.chat_context.model_dump(mode="json")
        return payload

    def to_publish_bytes(self) -> bytes:
        return json.dumps(self.to_publish_dict(), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
