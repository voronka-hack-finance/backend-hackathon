from __future__ import annotations

import hashlib
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from minio import Minio
from sqlalchemy import Engine, text

from services.access_service.app.security import hash_password
from services.file_service.app.imports.parsers.family_budget_excel_v1 import (
    SOURCE_TYPE,
    FamilyBudgetExcelParser,
)
from services.file_service.app.storage.client import ObjectStorage
from services.finance_service.app.handlers import handle_transactions_bulk_create
from services.migration_service.app.config import settings

logger = logging.getLogger(__name__)

SCRIPT_KEY = "family-budget-excel"
SCRIPT_GROUP = "data-bootstrap"
CHUNK_SIZE = 500
CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_parser = FamilyBudgetExcelParser()


def run_bootstrap(engine: Engine) -> None:
    if not settings.bootstrap_excel_enabled:
        logger.info("Excel bootstrap disabled (BOOTSTRAP_EXCEL_ENABLED=false)")
        return

    path = Path(settings.bootstrap_excel_path)
    if not path.is_file():
        logger.warning("Excel bootstrap skipped: file not found at %s", path)
        return

    file_bytes = path.read_bytes()
    checksum = hashlib.sha256(file_bytes).hexdigest()
    _record_bootstrap(engine, checksum, status="running", error_message=None)
    try:
        inserted = _import_workbook(engine, path, file_bytes)
        _record_bootstrap(engine, checksum, status="completed", error_message=None)
        logger.info(
            "Excel bootstrap completed for %s: %s transactions inserted",
            settings.bootstrap_user_email,
            inserted,
        )
    except Exception as exc:
        _record_bootstrap(engine, checksum, status="failed", error_message=str(exc))
        logger.exception("Excel bootstrap failed")
        raise


def _record_bootstrap(engine: Engine, checksum: str, *, status: str, error_message: str | None) -> None:
    now = datetime.now(UTC)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                insert into bootstrap_runs(script_key, script_group, checksum, status, started_at, finished_at, error_message)
                values (:script_key, :script_group, :checksum, :status, :started_at, :finished_at, :error_message)
                on conflict (script_key) do update set
                  script_group = excluded.script_group,
                  checksum = excluded.checksum,
                  status = excluded.status,
                  started_at = case when excluded.status = 'running' then excluded.started_at else bootstrap_runs.started_at end,
                  finished_at = excluded.finished_at,
                  error_message = excluded.error_message
                """
            ),
            {
                "script_key": SCRIPT_KEY,
                "script_group": SCRIPT_GROUP,
                "checksum": checksum,
                "status": status,
                "started_at": now if status == "running" else None,
                "finished_at": now if status in {"completed", "failed"} else None,
                "error_message": error_message,
            },
        )


def _import_workbook(engine: Engine, path: Path, file_bytes: bytes) -> int:
    user_id = _create_bootstrap_user(engine)
    file_sha256 = hashlib.sha256(file_bytes).hexdigest()

    _wait_for_minio()
    storage = ObjectStorage()
    filename = path.name
    storage_key = f"{user_id}/{file_sha256}/{filename}"
    storage.put_bytes(storage_key, file_bytes, CONTENT_TYPE)

    file_id, import_id = _create_file_and_import(engine, user_id, filename, file_sha256, storage_key, len(file_bytes))

    result = _parser.parse(file_bytes)
    if result.errors and not result.transactions:
        first = result.errors[0]
        raise RuntimeError(first.message or first.error_code or "Excel parse failed")

    envelope = {"user": {"id": str(user_id), "email": settings.bootstrap_user_email}}
    inserted = 0
    for chunk in _chunks(result.transactions, CHUNK_SIZE):
        payload = {
            "items": [
                transaction.to_bulk_item(import_id=str(import_id), source_file_id=str(file_id))
                for transaction in chunk
            ]
        }
        reply = handle_transactions_bulk_create(payload, envelope)
        inserted += int(reply.get("inserted", 0))

    _finalize_import(engine, import_id, file_id, result, inserted)
    return inserted


def _create_bootstrap_user(engine: Engine) -> UUID:
    user_id = uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                insert into users(id, email, password_hash, display_name, created_at, updated_at)
                values (:id, :email, :password_hash, :display_name, now(), now())
                """
            ),
            {
                "id": user_id,
                "email": settings.bootstrap_user_email,
                "password_hash": hash_password(settings.bootstrap_user_password),
                "display_name": settings.bootstrap_user_display_name,
            },
        )
    return user_id


def _create_file_and_import(
    engine: Engine,
    user_id: UUID,
    filename: str,
    sha256: str,
    storage_key: str,
    size_bytes: int,
) -> tuple[UUID, UUID]:
    file_id = uuid4()
    import_id = uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                insert into uploaded_files(
                  id, user_id, original_filename, content_type, size_bytes, sha256,
                  storage_bucket, storage_key, status, created_at, updated_at
                )
                values (
                  :id, :user_id, :filename, :content_type, :size_bytes, :sha256,
                  :bucket, :storage_key, 'uploaded', now(), now()
                )
                """
            ),
            {
                "id": file_id,
                "user_id": user_id,
                "filename": filename,
                "content_type": CONTENT_TYPE,
                "size_bytes": size_bytes,
                "sha256": sha256,
                "bucket": settings.uploads_bucket,
                "storage_key": storage_key,
            },
        )
        conn.execute(
            text(
                """
                insert into import_jobs(
                  id, user_id, file_id, source_type, status, total_rows, parsed_rows, failed_rows,
                  started_at, finished_at, error_message, created_at, updated_at
                )
                values (
                  :id, :user_id, :file_id, :source_type, 'running', 0, 0, 0,
                  now(), null, null, now(), now()
                )
                """
            ),
            {
                "id": import_id,
                "user_id": user_id,
                "file_id": file_id,
                "source_type": SOURCE_TYPE,
            },
        )
    return file_id, import_id


def _finalize_import(engine: Engine, import_id: UUID, file_id: UUID, result, inserted: int) -> None:
    if result.errors and result.transactions:
        job_status = "partially_completed"
        file_status = "parsed"
    elif result.errors:
        job_status = "failed"
        file_status = "failed"
    else:
        job_status = "completed"
        file_status = "parsed"
    error_message = result.errors[0].message if result.errors else None
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                update import_jobs
                set status = :status,
                    total_rows = :total_rows,
                    parsed_rows = :parsed_rows,
                    failed_rows = :failed_rows,
                    error_message = :error_message,
                    finished_at = now(),
                    updated_at = now()
                where id = :id
                """
            ),
            {
                "id": import_id,
                "status": job_status,
                "total_rows": result.total_rows,
                "parsed_rows": inserted,
                "failed_rows": result.failed_rows,
                "error_message": error_message,
            },
        )
        conn.execute(
            text("update uploaded_files set status = :status, updated_at = now() where id = :id"),
            {"id": file_id, "status": file_status},
        )


def _wait_for_minio() -> None:
    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    deadline = time.monotonic() + 90
    while True:
        try:
            client.bucket_exists(settings.uploads_bucket)
            return
        except Exception:
            if time.monotonic() > deadline:
                raise
            time.sleep(2)


def _chunks(items, size: int):
    for index in range(0, len(items), size):
        yield items[index : index + size]
