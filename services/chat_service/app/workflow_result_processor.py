from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.engine import Engine

from services.chat_service.app.workflow_result_schemas import WorkflowResultMessage
from services.chat_service.app.workflow_result_content import resolve_assistant_content

from common.agent_debug_log import agent_debug_log

logger = logging.getLogger(__name__)


class WorkflowResultProcessingError(Exception):
    pass


def _serialize_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, UUID):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _serialize_row(row) -> dict[str, Any]:
    return {key: _serialize_value(value) for key, value in dict(row).items()}


def process_workflow_result_bytes(body: bytes, *, engine: Engine) -> dict[str, Any] | None:
    try:
        result = WorkflowResultMessage.parse_bytes(body)
    except (json.JSONDecodeError, ValidationError, UnicodeDecodeError) as exc:
        logger.warning("workflow_result_invalid_payload error=%s", exc.__class__.__name__)
        raise WorkflowResultProcessingError("invalid workflow result payload") from exc

    workflow_run_id = UUID(result.workflow_run_id)
    user_id = UUID(result.user_id)
    chat_id = UUID(result.chat_id)
    message_id = UUID(result.message_id)
    request_id = UUID(result.request_id)

    with engine.begin() as connection:
        existing = connection.execute(
            text(
                """
                select workflow_run_id, assistant_message_id
                from ai_workflow_result_inbox
                where workflow_run_id = :workflow_run_id
                """
            ),
            {"workflow_run_id": workflow_run_id},
        ).mappings().first()
        if existing is not None:
            logger.info(
                "workflow_result_duplicate_skipped workflow_run_id=%s assistant_message_id=%s",
                workflow_run_id,
                existing["assistant_message_id"],
            )
            if existing["assistant_message_id"] is not None:
                row = connection.execute(
                    text(
                        """
                        select id, chat_id, user_id, role, content, created_at
                        from chat_messages
                        where id = :message_id
                        """
                    ),
                    {"message_id": existing["assistant_message_id"]},
                ).mappings().first()
                if row is not None:
                    return _serialize_row(row)
            return None

        chat_row = connection.execute(
            text(
                """
                select id
                from chats
                where id = :chat_id and user_id = :user_id
                """
            ),
            {"chat_id": chat_id, "user_id": user_id},
        ).mappings().first()
        if chat_row is None:
            logger.warning(
                "workflow_result_chat_not_found workflow_run_id=%s chat_id=%s user_id=%s",
                workflow_run_id,
                chat_id,
                user_id,
            )
            raise WorkflowResultProcessingError("chat not found for user")

        trigger_message = connection.execute(
            text(
                """
                select id
                from chat_messages
                where id = :message_id and chat_id = :chat_id
                """
            ),
            {"message_id": message_id, "chat_id": chat_id},
        ).mappings().first()
        if trigger_message is None:
            logger.warning(
                "workflow_result_trigger_message_not_found workflow_run_id=%s message_id=%s chat_id=%s",
                workflow_run_id,
                message_id,
                chat_id,
            )
            raise WorkflowResultProcessingError("trigger message not found in chat")

        assistant_content = resolve_assistant_content(result)
        # region agent log
        agent_debug_log(
            hypothesis_id="F",
            location="workflow_result_processor.py:process_workflow_result_bytes:content",
            message="assistant content normalized",
            data={
                "workflow_run_id": str(workflow_run_id),
                "raw_content_len": len(result.content),
                "normalized_content_len": len(assistant_content),
                "raw_preview": result.content[:120],
                "normalized_preview": assistant_content[:120],
                "metadata_keys": sorted(result.metadata.keys()),
            },
            run_id="post-fix",
        )
        # endregion

        assistant_row = connection.execute(
            text(
                """
                insert into chat_messages(chat_id, user_id, role, content)
                values (:chat_id, :user_id, 'assistant', :content)
                returning id, chat_id, user_id, role, content, created_at
                """
            ),
            {"chat_id": chat_id, "user_id": user_id, "content": assistant_content},
        ).mappings().one()

        connection.execute(
            text("update chats set updated_at = now() where id = :chat_id"),
            {"chat_id": chat_id},
        )

        connection.execute(
            text(
                """
                insert into ai_workflow_result_inbox(
                  workflow_run_id,
                  request_id,
                  user_id,
                  chat_id,
                  message_id,
                  assistant_message_id,
                  status
                )
                values (
                  :workflow_run_id,
                  :request_id,
                  :user_id,
                  :chat_id,
                  :message_id,
                  :assistant_message_id,
                  :status
                )
                """
            ),
            {
                "workflow_run_id": workflow_run_id,
                "request_id": request_id,
                "user_id": user_id,
                "chat_id": chat_id,
                "message_id": message_id,
                "assistant_message_id": assistant_row["id"],
                "status": result.status,
            },
        )

    serialized = _serialize_row(assistant_row)
    logger.info(
        "workflow_result_processed workflow_run_id=%s chat_id=%s message_id=%s assistant_message_id=%s status=%s",
        workflow_run_id,
        chat_id,
        message_id,
        serialized["id"],
        result.status,
    )
    return serialized
