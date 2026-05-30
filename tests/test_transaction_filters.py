from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from services.finance_service.app.main import _apply_transaction_filters
from services.finance_service.app.models import Transaction


def test_apply_filters_adds_income_expense_type_condition():
    stmt = _apply_transaction_filters(
        select(Transaction),
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        payload={"type": "expense"},
    )

    compiled = stmt.compile(dialect=postgresql.dialect())

    assert "transactions.type" in str(compiled)
    assert "expense" in compiled.params.values()
