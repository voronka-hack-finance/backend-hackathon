from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0004_transaction_dedupe"
down_revision = "0003_bucket_policy_state"
branch_labels = None
depends_on = None

LEGACY_SQL = Path(__file__).resolve().parents[2] / "migrations" / "050_transaction_dedupe.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(LEGACY_SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        """
        drop index if exists uq_transactions_user_dedupe_key;
        drop index if exists ix_refresh_sessions_refresh_token_hash;
        """
    )
