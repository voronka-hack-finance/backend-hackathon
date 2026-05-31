from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "1.0"
MESSAGE_TYPE = "ai.workflow.result"
DEFAULT_ERROR_CONTENT = "Не удалось обработать запрос"


class WorkflowResultError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class WorkflowResultMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    message_type: str
    request_id: str
    workflow_run_id: str
    user_id: str
    chat_id: str
    message_id: str
    status: Literal["success", "partial", "error"]
    content: str
    created_at: str
    errors: list[WorkflowResultError] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: str) -> str:
        if value != SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {SCHEMA_VERSION}")
        return value

    @field_validator("message_type")
    @classmethod
    def validate_message_type(cls, value: str) -> str:
        if value != MESSAGE_TYPE:
            raise ValueError(f"message_type must be {MESSAGE_TYPE}")
        return value

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str, info) -> str:
        stripped = value.strip()
        status = info.data.get("status")
        if stripped:
            return stripped
        if status == "error":
            return DEFAULT_ERROR_CONTENT
        raise ValueError("content is required")

    @classmethod
    def parse_bytes(cls, body: bytes) -> WorkflowResultMessage:
        import json

        payload = json.loads(body.decode("utf-8"))
        return cls.model_validate(payload)
