from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0006_regular_expenses"
down_revision = "0005_health_score_service"
branch_labels = None
depends_on = None

LEGACY_SQL = Path(__file__).resolve().parents[2] / "migrations" / "070_regular_expenses_manual_crud.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(LEGACY_SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        """
        drop index if exists ix_regular_expenses_user_status_source;
        alter table regular_expenses drop column if exists expected_amount;
        alter table regular_expenses drop column if exists source_type;
        """
    )
