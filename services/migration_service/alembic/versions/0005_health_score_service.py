from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0005_health_score_service"
down_revision = "0004_transaction_dedupe"
branch_labels = None
depends_on = None

LEGACY_SQL = Path(__file__).resolve().parents[2] / "migrations" / "060_health_score_service.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(LEGACY_SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql("drop table if exists health_score_snapshots cascade;")
