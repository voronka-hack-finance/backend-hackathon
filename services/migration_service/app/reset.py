from __future__ import annotations

import logging
import time

from minio import Minio
from minio.deleteobjects import DeleteObject
from sqlalchemy import Engine, text

from services.migration_service.app.config import settings

logger = logging.getLogger(__name__)

PRESERVED_TABLES = frozenset({"alembic_version"})


def reset_application_data(engine: Engine) -> None:
    if not settings.bootstrap_reset_on_start:
        logger.info("Application data reset skipped (BOOTSTRAP_RESET_ON_START=false)")
        return

    _truncate_public_tables(engine)
    _clear_uploads_bucket()
    logger.info("Application data reset completed (database + MinIO uploads)")


def _truncate_public_tables(engine: Engine) -> None:
    excluded = ", ".join(f"'{name}'" for name in PRESERVED_TABLES)
    with engine.connect() as conn:
        tables = conn.scalars(
            text(
                f"""
                select tablename
                from pg_tables
                where schemaname = 'public'
                  and tablename not in ({excluded})
                order by tablename
                """
            )
        ).all()

    if not tables:
        return

    quoted = ", ".join(f'"{name}"' for name in tables)
    with engine.begin() as conn:
        conn.execute(text(f"truncate table {quoted} restart identity cascade"))
    logger.info("Truncated %s public tables", len(tables))


def _clear_uploads_bucket() -> None:
    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    deadline = time.monotonic() + 90
    while True:
        try:
            if not client.bucket_exists(settings.uploads_bucket):
                return
            break
        except Exception:
            if time.monotonic() > deadline:
                raise
            time.sleep(2)

    delete_targets = [
        DeleteObject(obj.object_name)
        for obj in client.list_objects(settings.uploads_bucket, recursive=True)
    ]
    if not delete_targets:
        return

    errors = client.remove_objects(settings.uploads_bucket, delete_targets)
    for error in errors:
        logger.warning("MinIO delete error: %s", error)
    logger.info("Removed %s objects from bucket %s", len(delete_targets), settings.uploads_bucket)
