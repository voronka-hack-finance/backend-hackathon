from __future__ import annotations

import json
import logging
import threading
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.engine import Engine

from services.chat_service.app.workflow_producer import publish_workflow_task_bytes_sync
from services.chat_service.app.workflow_schemas import ChatContext, ChatContextMessage, WorkflowTask

from common.agent_debug_log import agent_debug_log

logger = logging.getLogger(__name__)


def utc_now_iso_z() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def user_local_date(timezone_name: str) -> str:
    return datetime.now(ZoneInfo(timezone_name)).date().isoformat()


def build_workflow_task(
    *,
    user_id: str,
    chat_id: str,
    message_id: str,
    raw_message: str,
    timezone_name: str,
    chat_context: ChatContext | None = None,
) -> WorkflowTask:
    return WorkflowTask(
        request_id=str(uuid4()),
        workflow_run_id=str(uuid4()),
        user_id=user_id,
        chat_id=chat_id,
        message_id=message_id,
        raw_message=raw_message,
        current_date=user_local_date(timezone_name),
        timezone=timezone_name,
        created_at=utc_now_iso_z(),
        chat_context=chat_context,
    )


def fetch_chat_context(connection, *, chat_id: UUID, exclude_message_id: UUID, limit: int) -> ChatContext | None:
    rows = connection.execute(
        text(
            """
            select role, content
            from chat_messages
            where chat_id = :chat_id and id != :exclude_message_id
            order by created_at desc
            limit :limit
            """
        ),
        {"chat_id": chat_id, "exclude_message_id": exclude_message_id, "limit": limit},
    ).mappings().all()
    if not rows:
        return None
    messages = [
        ChatContextMessage(role=str(row["role"]), content=str(row["content"]))
        for row in reversed(rows)
    ]
    return ChatContext(last_6_messages=messages, chat_summary=None, active_workflow=None)


def enqueue_workflow_task(connection, *, message_id: UUID, task: WorkflowTask) -> None:
    connection.execute(
        text(
            """
            insert into ai_workflow_task_outbox(message_id, payload)
            values (:message_id, cast(:payload as jsonb))
            on conflict (message_id) do nothing
            """
        ),
        {
            "message_id": message_id,
            "payload": json.dumps(task.to_publish_dict(), ensure_ascii=False, separators=(",", ":")),
        },
    )


def flush_outbox_message(
    engine: Engine,
    *,
    message_id: str,
    rabbitmq_url: str,
    queue_name: str,
    max_attempts: int,
) -> bool:
    with engine.begin() as connection:
        row = connection.execute(
            text(
                """
                select message_id, payload, published_at, attempts
                from ai_workflow_task_outbox
                where message_id = :message_id
                for update
                """
            ),
            {"message_id": UUID(message_id)},
        ).mappings().first()
        # region agent log
        agent_debug_log(
            hypothesis_id="C",
            location="workflow_outbox.py:flush_outbox_message:loaded",
            message="outbox row state before publish",
            data={
                "message_id": message_id,
                "row_found": row is not None,
                "published_at": str(row["published_at"]) if row else None,
                "attempts": int(row["attempts"] or 0) if row else None,
                "queue_name": queue_name,
            },
        )
        # endregion
        if row is None or row["published_at"] is not None:
            return True
        if int(row["attempts"] or 0) >= max_attempts:
            logger.error(
                "ai_workflow_outbox_max_attempts message_id=%s attempts=%s",
                message_id,
                row["attempts"],
            )
            return False
        payload = row["payload"]
        if isinstance(payload, str):
            body = payload.encode("utf-8")
        elif isinstance(payload, dict):
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        else:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        try:
            publish_workflow_task_bytes_sync(
                rabbitmq_url=rabbitmq_url,
                queue_name=queue_name,
                body=body,
            )
            # region agent log
            agent_debug_log(
                hypothesis_id="D",
                location="workflow_outbox.py:flush_outbox_message:published",
                message="rabbitmq publish succeeded",
                data={"message_id": message_id, "queue_name": queue_name, "body_bytes": len(body)},
            )
            # endregion
        except Exception as exc:
            # region agent log
            agent_debug_log(
                hypothesis_id="D",
                location="workflow_outbox.py:flush_outbox_message:publish_failed",
                message="rabbitmq publish failed",
                data={
                    "message_id": message_id,
                    "queue_name": queue_name,
                    "error_type": exc.__class__.__name__,
                    "error": str(exc)[:500],
                },
            )
            # endregion
            connection.execute(
                text(
                    """
                    update ai_workflow_task_outbox
                    set attempts = attempts + 1,
                        last_error = :last_error
                    where message_id = :message_id
                    """
                ),
                {"message_id": UUID(message_id), "last_error": str(exc)[:2000]},
            )
            logger.warning(
                "ai_workflow_outbox_publish_failed message_id=%s error=%s",
                message_id,
                exc.__class__.__name__,
            )
            return False
        connection.execute(
            text(
                """
                update ai_workflow_task_outbox
                set published_at = now(),
                    last_error = null
                where message_id = :message_id
                """
            ),
            {"message_id": UUID(message_id)},
        )
    return True


def flush_pending_outbox(
    engine: Engine,
    *,
    rabbitmq_url: str,
    queue_name: str,
    max_attempts: int,
    batch_size: int = 50,
) -> int:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                select message_id::text as message_id
                from ai_workflow_task_outbox
                where published_at is null and attempts < :max_attempts
                order by created_at
                limit :batch_size
                """
            ),
            {"max_attempts": max_attempts, "batch_size": batch_size},
        ).mappings().all()
    published = 0
    for row in rows:
        if flush_outbox_message(
            engine,
            message_id=row["message_id"],
            rabbitmq_url=rabbitmq_url,
            queue_name=queue_name,
            max_attempts=max_attempts,
        ):
            published += 1
    return published


class WorkflowOutboxFlusher:
    def __init__(
        self,
        *,
        engine: Engine,
        rabbitmq_url: str,
        queue_name: str,
        interval_seconds: float,
        max_attempts: int,
    ) -> None:
        self.engine = engine
        self.rabbitmq_url = rabbitmq_url
        self.queue_name = queue_name
        self.interval_seconds = max(interval_seconds, 1.0)
        self.max_attempts = max(max_attempts, 1)
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stopping.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="chat-service-workflow-outbox-flusher",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stopping.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                count = flush_pending_outbox(
                    self.engine,
                    rabbitmq_url=self.rabbitmq_url,
                    queue_name=self.queue_name,
                    max_attempts=self.max_attempts,
                )
                if count:
                    logger.info("ai_workflow_outbox_flushed count=%s", count)
            except Exception:
                logger.exception("ai_workflow_outbox_flush_loop_failed")
            self._stopping.wait(self.interval_seconds)
