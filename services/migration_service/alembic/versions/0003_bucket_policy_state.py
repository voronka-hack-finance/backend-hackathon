from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0003_bucket_policy_state"
down_revision = "0002_expanded_plan"
branch_labels = None
depends_on = None

LEGACY_SQL = Path(__file__).resolve().parents[2] / "migrations" / "040_bucket_policy_state.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(LEGACY_SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        """
        alter table bucket_bootstrap_runs drop column if exists policy_applied_at;
        alter table bucket_bootstrap_runs drop column if exists policy_name;
        """
    )
