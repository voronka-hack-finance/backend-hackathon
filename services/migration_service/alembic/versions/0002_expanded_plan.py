from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0002_expanded_plan"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None

LEGACY_SQL = Path(__file__).resolve().parents[2] / "migrations" / "030_expanded_plan.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(LEGACY_SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        """
        drop table if exists agent_recommendations cascade;
        drop table if exists chat_messages cascade;
        drop table if exists chats cascade;
        drop table if exists family_invitations cascade;
        drop table if exists family_members cascade;
        drop table if exists family_groups cascade;
        drop table if exists notification_deliveries cascade;
        drop table if exists notification_preferences cascade;
        drop table if exists notification_devices cascade;
        drop table if exists scheduled_reminders cascade;
        drop table if exists available_funds_snapshots cascade;
        drop table if exists expected_expenses cascade;
        drop table if exists expected_incomes cascade;
        drop table if exists regular_expenses cascade;
        drop table if exists savings_goals cascade;
        drop table if exists category_limits cascade;
        drop table if exists account_categories cascade;
        drop table if exists accounts cascade;
        drop table if exists bucket_bootstrap_runs cascade;
        alter table transactions drop column if exists category_id;
        alter table transactions drop column if exists account_id;
        alter table users drop column if exists display_name;
        """
    )
