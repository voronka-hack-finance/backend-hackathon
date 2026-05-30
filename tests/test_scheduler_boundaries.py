from pathlib import Path


def test_scheduler_does_not_read_analytics_or_finance_owned_tables_directly():
    source = Path("services/scheduler_service/app/main.py").read_text(encoding="utf-8")

    assert "from regular_expenses" not in source
    assert "from category_limits" not in source
    assert '"analytics.regular_expenses.due_for_reminders"' in source
    assert '"limits.due_warnings"' in source
