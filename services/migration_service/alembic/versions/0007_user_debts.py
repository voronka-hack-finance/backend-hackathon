from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0007_user_debts"
down_revision = "0006_regular_expenses"
branch_labels = None
depends_on = None

LEGACY_SQL = Path(__file__).resolve().parents[2] / "migrations" / "080_user_debts.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(LEGACY_SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql("drop table if exists user_debts cascade;")
