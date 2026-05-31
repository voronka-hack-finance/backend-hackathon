from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None

LEGACY_DIR = Path(__file__).resolve().parents[2] / "migrations"


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        """
        create extension if not exists pgcrypto;

        create table if not exists bootstrap_runs (
          id uuid primary key default gen_random_uuid(),
          script_key text not null unique,
          script_group text not null,
          checksum text not null,
          status text not null,
          started_at timestamptz,
          finished_at timestamptz,
          error_message text
        );
        """
    )
    for name in ("005_auth_service.sql", "010_file_service.sql", "020_transaction_service.sql"):
        bind.exec_driver_sql((LEGACY_DIR / name).read_text(encoding="utf-8"))


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        """
        drop table if exists transactions cascade;
        drop table if exists import_errors cascade;
        drop table if exists import_jobs cascade;
        drop table if exists uploaded_files cascade;
        drop table if exists refresh_sessions cascade;
        drop table if exists bootstrap_runs cascade;
        drop table if exists users cascade;
        """
    )
