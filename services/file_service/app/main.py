from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from common.messaging import MessageBus, MessageError, MessageWorker, UserContext, check_rabbitmq, require_user
from fastapi import FastAPI
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from services.file_service.app.config import settings
from services.file_service.app.db.session import SessionLocal, engine
from services.file_service.app.imports.parsers.family_budget_excel_v1 import (
    FamilyBudgetExcelParser,
    ParseIssue,
    SOURCE_TYPE,
)
from services.file_service.app.models import ImportErrorRecord, ImportJob, UploadedFile
from services.file_service.app.storage.client import ObjectStorage

SERVICE_NAME = "file-service"
QUEUE_NAME = "file-service"
FINANCE_QUEUE = "finance-service"

FILE_FIELDS = (
    "id",
    "original_filename",
    "content_type",
    "size_bytes",
    "sha256",
    "status",
    "created_at",
    "updated_at",
)
IMPORT_FIELDS = (
    "id",
    "file_id",
    "status",
    "total_rows",
    "parsed_rows",
    "failed_rows",
    "started_at",
    "finished_at",
    "error_message",
)

app = FastAPI(title=SERVICE_NAME)
parser = FamilyBudgetExcelParser()
bus = MessageBus(settings.rabbitmq_url, SERVICE_NAME)
worker = MessageWorker(
    rabbitmq_url=settings.rabbitmq_url,
    queue_name=QUEUE_NAME,
    service_name=SERVICE_NAME,
    handlers={},
)


@app.on_event("startup")
def startup() -> None:
    worker.handlers.update(
        {
            "files.upload.create": handle_files_upload_create,
            "files.list": handle_files_list,
            "files.get": handle_files_get,
            "files.update": handle_files_update,
            "files.delete": handle_files_delete,
            "files.import.run": handle_files_import_run,
            "files.import.started.v1": handle_import_event,
            "files.import.completed.v1": handle_import_event,
            "files.import.failed.v1": handle_import_event,
            "imports.status.get": handle_imports_status_get,
            "imports.errors.list": handle_imports_errors_list,
        }
    )
    worker.start()


@app.on_event("shutdown")
def shutdown() -> None:
    worker.stop()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, str]:
    with engine.connect() as connection:
        connection.execute(text("select 1"))
    check_rabbitmq(settings.rabbitmq_url)
    return {"status": "ready"}


def handle_files_upload_create(payload: dict, envelope: dict) -> dict:
    user = require_user(envelope)
    source_type = payload.get("source_type") or SOURCE_TYPE
    if source_type != SOURCE_TYPE:
        raise MessageError(422, "Unsupported source_type")

    file_base64 = payload.get("file_base64")
    if not file_base64:
        raise MessageError(400, "Uploaded file is empty")
    try:
        file_bytes = base64.b64decode(str(file_base64), validate=True)
    except Exception as exc:
        raise MessageError(400, "Invalid base64 file payload") from exc
    if not file_bytes:
        raise MessageError(400, "Uploaded file is empty")

    inspection = parser.inspect(file_bytes)
    if inspection.errors:
        first_error = inspection.errors[0]
        raise MessageError(422, {"error_code": first_error.error_code, "message": first_error.message})

    user_uuid = UUID(user.id)
    filename = str(payload.get("filename") or "upload.xlsx")
    content_type = payload.get("content_type")
    sha256 = hashlib.sha256(file_bytes).hexdigest()

    with SessionLocal() as db:
        uploaded = db.scalar(
            select(UploadedFile).where(UploadedFile.user_id == user_uuid, UploadedFile.sha256 == sha256)
        )
        if uploaded is None:
            storage_key = f"{user_uuid}/{sha256}/{filename}"
            ObjectStorage().put_bytes(storage_key, file_bytes, str(content_type) if content_type else None)
            uploaded = UploadedFile(
                user_id=user_uuid,
                original_filename=filename,
                content_type=str(content_type) if content_type else None,
                size_bytes=len(file_bytes),
                sha256=sha256,
                storage_bucket=settings.uploads_bucket,
                storage_key=storage_key,
                status="uploaded",
            )
            db.add(uploaded)
            db.commit()
            db.refresh(uploaded)

        job = ImportJob(user_id=user_uuid, file_id=uploaded.id, source_type=str(source_type), status="queued")
        db.add(job)
        db.commit()
        db.refresh(job)

    bus.publish(QUEUE_NAME, "files.import.run", {"import_id": str(job.id)}, user=user)
    return {"file_id": str(uploaded.id), "import_id": str(job.id), "status": job.status}


def handle_files_list(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    page, page_size = _page(payload)
    with SessionLocal() as db:
        stmt = select(UploadedFile).where(UploadedFile.user_id == user_id)
        total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = db.scalars(
            stmt.order_by(UploadedFile.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        ).all()
        return {"items": [_serialize_file(row) for row in rows], "pagination": {"page": page, "page_size": page_size, "total": total}}


def handle_files_get(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    with SessionLocal() as db:
        uploaded = _get_file(db, user_id, payload.get("file_id") or payload.get("id"))
        return _serialize_file(uploaded)


def handle_files_update(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    with SessionLocal() as db:
        uploaded = _get_file(db, user_id, payload.get("file_id") or payload.get("id"))
        if payload.get("status"):
            uploaded.status = str(payload["status"])
        db.commit()
        db.refresh(uploaded)
        return _serialize_file(uploaded)


def handle_files_delete(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    with SessionLocal() as db:
        uploaded = _get_file(db, user_id, payload.get("file_id") or payload.get("id"))
        uploaded.status = "deleted"
        db.commit()
    return {"status": "deleted"}


def handle_imports_status_get(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    with SessionLocal() as db:
        job = _get_import(db, user_id, payload.get("import_id") or payload.get("id"))
        return _serialize_import(job)


def handle_imports_errors_list(payload: dict, envelope: dict) -> dict:
    user_id = UUID(require_user(envelope).id)
    import_id = UUID(str(payload.get("import_id") or payload.get("id")))
    page, page_size = _page(payload, default_size=100)
    with SessionLocal() as db:
        _get_import(db, user_id, import_id)
        rows = db.scalars(
            select(ImportErrorRecord)
            .where(ImportErrorRecord.import_id == import_id, ImportErrorRecord.user_id == user_id)
            .order_by(ImportErrorRecord.created_at, ImportErrorRecord.row_number)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return {
            "items": [
                {
                    "sheet_name": row.sheet_name,
                    "row_number": row.row_number,
                    "column_name": row.column_name,
                    "raw_value": row.raw_value,
                    "error_code": row.error_code,
                    "message": row.message,
                }
                for row in rows
            ]
        }


def handle_files_import_run(payload: dict, envelope: dict) -> dict:
    import_id = str(payload.get("import_id") or "")
    if not import_id:
        raise MessageError(422, "import_id is required")
    process_import_job(import_id)
    return {"status": "ok"}


def handle_import_event(payload: dict, envelope: dict) -> dict:
    return {"status": "acknowledged"}


def process_import_job(import_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(ImportJob, UUID(import_id))
        if job is None:
            return
        uploaded = db.get(UploadedFile, job.file_id)
        if uploaded is None:
            _fail_job(db, job, "Source file metadata was not found")
            return

        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.error_message = None
        db.commit()
        bus.publish(QUEUE_NAME, "files.import.started.v1", {"import_id": str(job.id)})

        try:
            file_bytes = ObjectStorage().get_bytes(uploaded.storage_key)
            result = parser.parse(file_bytes)
            _store_parse_errors(db, job, result.errors)
            _send_transactions(
                user_id=str(job.user_id),
                import_id=str(job.id),
                file_id=str(uploaded.id),
                transactions=result.transactions,
            )
            job.total_rows = result.total_rows
            job.parsed_rows = len(result.transactions)
            job.failed_rows = result.failed_rows
            if result.errors and result.transactions:
                job.status = "partially_completed"
            elif result.errors:
                job.status = "failed"
                job.error_message = result.errors[0].message
            else:
                job.status = "completed"
            uploaded.status = "parsed" if job.status in {"completed", "partially_completed"} else "failed"
            if job.status in {"completed", "partially_completed"}:
                bus.publish(QUEUE_NAME, "files.import.completed.v1", {"import_id": str(job.id)})
        except Exception as exc:
            job.status = "failed"
            job.error_message = str(exc)
            uploaded.status = "failed"
            bus.publish(QUEUE_NAME, "files.import.failed.v1", {"import_id": str(job.id), "error_message": str(exc)})
        finally:
            job.finished_at = datetime.now(UTC)
            db.commit()
    finally:
        db.close()


def _fail_job(db: Session, job: ImportJob, message: str) -> None:
    job.status = "failed"
    job.error_message = message
    job.finished_at = datetime.now(UTC)
    db.commit()


def _store_parse_errors(db: Session, job: ImportJob, errors: list[ParseIssue]) -> None:
    if not errors:
        return
    db.add_all(
        ImportErrorRecord(
            user_id=job.user_id,
            import_id=job.id,
            sheet_name=error.sheet_name,
            row_number=error.row_number,
            column_name=error.column_name,
            raw_value=error.raw_value,
            error_code=error.error_code,
            message=error.message,
            technical_details=error.technical_details,
        )
        for error in errors
    )
    db.flush()


def _send_transactions(*, user_id: str, import_id: str, file_id: str, transactions) -> int:
    inserted = 0
    user = UserContext(id=user_id)
    for chunk in _chunks(transactions, 500):
        payload = {
            "items": [transaction.to_bulk_item(import_id=import_id, source_file_id=file_id) for transaction in chunk]
        }
        reply = bus.request(FINANCE_QUEUE, "transactions.bulk_create", payload, user=user, timeout_seconds=60.0)
        if not reply.get("ok"):
            raise RuntimeError(str(reply.get("error") or "finance-service rejected transactions.bulk_create"))
        inserted += int((reply.get("payload") or {}).get("inserted", 0))
    return inserted


def _get_file(db: Session, user_id: UUID, file_id: Any) -> UploadedFile:
    if not file_id:
        raise MessageError(422, "file_id is required")
    uploaded = db.scalar(select(UploadedFile).where(UploadedFile.id == UUID(str(file_id)), UploadedFile.user_id == user_id))
    if uploaded is None:
        raise MessageError(404, "File not found")
    return uploaded


def _get_import(db: Session, user_id: UUID, import_id: Any) -> ImportJob:
    if not import_id:
        raise MessageError(422, "import_id is required")
    job = db.scalar(select(ImportJob).where(ImportJob.id == UUID(str(import_id)), ImportJob.user_id == user_id))
    if job is None:
        raise MessageError(404, "Import not found")
    return job


def _serialize_file(row: UploadedFile) -> dict:
    return {field: _serialize_value(getattr(row, field)) for field in FILE_FIELDS}


def _serialize_import(job: ImportJob) -> dict:
    payload = {field: _serialize_value(getattr(job, field)) for field in IMPORT_FIELDS}
    payload["import_id"] = payload.pop("id")
    return payload


def _serialize_value(value: Any) -> Any:
    if isinstance(value, (UUID, datetime)):
        return value.isoformat() if isinstance(value, datetime) else str(value)
    return value


def _page(payload: dict, *, default_size: int = 50) -> tuple[int, int]:
    page = max(int(payload.get("page") or 1), 1)
    page_size = min(max(int(payload.get("page_size") or default_size), 1), 500)
    return page, page_size


def _chunks(items, size: int):
    for index in range(0, len(items), size):
        yield items[index : index + size]
