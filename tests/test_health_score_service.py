from datetime import date
from decimal import Decimal
from pathlib import Path

from services.health_score_service.app.handlers import _build_profile


def test_health_profile_calculates_scores_and_reports_mvp_credit_gaps():
    profile = _build_profile(
        period="2026-05",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        transactions=[
            {"type": "income", "operation_at": "2026-05-05T10:00:00+00:00", "operation_amount": "100000", "category_name": "Salary"},
            {"type": "expense", "operation_at": "2026-05-06T10:00:00+00:00", "operation_amount": "-30000", "category_name": "Супермаркеты"},
            {"type": "expense", "operation_at": "2026-05-07T10:00:00+00:00", "operation_amount": "-10000", "category_name": "Кредиты"},
            {"type": "expense", "operation_at": "2026-05-08T10:00:00+00:00", "operation_amount": "-5000", "category_name": "Рестораны"},
        ],
        previous_transactions=[
            {"type": "income", "operation_at": "2026-04-05T10:00:00+00:00", "operation_amount": "100000", "category_name": "Salary"},
            {"type": "income", "operation_at": "2026-03-05T10:00:00+00:00", "operation_amount": "100000", "category_name": "Salary"},
        ],
        sums={"income_total": "100000", "expense_total": "-45000"},
        accounts=[{"current_balance": "150000"}],
        limits=[],
        goals=[{"status": "active", "target_amount": "200000", "current_amount": "50000", "target_date": "2026-12-31"}],
        balance_before={"actual_balance": "100000"},
        available={"available_amount": "55000"},
        expected_incomes=[],
        expected_expenses=[],
        regular_expenses=[{"status": "active", "average_amount": "10000"}],
    )

    assert profile["period"] == "2026-05"
    assert Decimal(profile["financial_health_score"]) >= 0
    assert profile["credit_load_index_partial"] is True
    assert profile["monthly_credit_payments"] == "10000.00"
    assert any(gap["field"] == "credit_card_utilization" for gap in profile["data_gaps"])


def test_health_score_service_does_not_query_foreign_tables_directly():
    source = Path("services/health_score_service/app/handlers.py").read_text(encoding="utf-8")

    forbidden = [
        "from transactions",
        "from accounts",
        "from category_limits",
        "from savings_goals",
        "from regular_expenses",
        "from expected_incomes",
        "from expected_expenses",
    ]
    assert not any(token in source for token in forbidden)
    assert "from health_score_snapshots" in source
