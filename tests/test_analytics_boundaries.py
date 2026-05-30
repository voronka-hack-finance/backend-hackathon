from pathlib import Path


def test_analytics_does_not_read_finance_owned_tables_directly():
    source = Path("services/analytics_service/app/handlers.py").read_text(encoding="utf-8")

    assert "from transactions" not in source
    assert "from accounts" not in source
    assert '"finance.balance_before_period"' in source
    assert '"finance.income_expected_candidates"' in source
    assert '"finance.expense_pattern_candidates"' in source
