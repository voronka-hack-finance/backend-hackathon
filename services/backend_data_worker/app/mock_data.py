from __future__ import annotations

from typing import Any

from services.backend_data_worker.app.schemas import (
    MVP_FULL_MOCK_DATA_TYPES,
    MVP_PARTIAL_DATA_TYPES,
    BackendDataRequest,
)


def _mock_transactions() -> dict[str, Any]:
    return {
        "items": [
            {
                "id": "tx_mock_1",
                "operation_amount": "-1294.00",
                "operation_currency": "RUB",
                "type": "expense",
                "description": "Вкусно — и точка",
                "category_name": "Фастфуд",
                "mcc": "5814",
                "operation_at": "2026-05-10T18:25:00+00:00",
            },
            {
                "id": "tx_mock_2",
                "operation_amount": "-450.00",
                "operation_currency": "RUB",
                "type": "expense",
                "description": "Пятёрочка",
                "category_name": "Супермаркеты",
                "mcc": "5411",
                "operation_at": "2026-05-12T09:15:00+00:00",
            },
        ]
    }


def _mock_previous_period_transactions() -> dict[str, Any]:
    return {"items": []}


def _mock_user_context() -> dict[str, Any]:
    return {
        "currentSavings": 45000,
        "stableMonthlyIncome": 85000,
        "hasDebt": False,
        "monthlyDebtPayment": None,
        "debtAmount": "0",
        "financialGoal": "Отпуск",
        "goalAmount": 150000,
        "goalDeadlineMonths": 8,
        "salaryDay": 5,
        "currentBalance": 52000,
        "categoryLimits": [
            {
                "id": "limit_mock_1",
                "account_id": None,
                "category_id": "cat_mock_food",
                "limit_amount": "10000.00",
                "currency": "RUB",
                "period_days": 30,
                "is_active": True,
            },
            {
                "id": "limit_mock_2",
                "account_id": None,
                "category_id": "cat_mock_transport",
                "limit_amount": "5000.00",
                "currency": "RUB",
                "period_days": 30,
                "is_active": True,
            },
        ],
    }


def _mock_category_profiles() -> list[dict[str, Any]]:
    return [
        {
            "category": "Фастфуд",
            "categoryGroup": "food_outside",
            "canOptimize": True,
            "protectedByDefault": False,
            "isRequiredExpense": False,
        },
        {
            "category": "Супермаркеты",
            "categoryGroup": "food_grocery",
            "canOptimize": True,
            "protectedByDefault": False,
            "isRequiredExpense": False,
        },
        {
            "category": "Зарплата",
            "categoryGroup": "essential_fixed",
            "canOptimize": False,
            "protectedByDefault": True,
            "isRequiredExpense": True,
        },
    ]


def _mock_accounts(user_id: str) -> dict[str, Any]:
    return {
        "items": [
            {
                "id": "acc_mock_1",
                "owner_user_id": user_id,
                "name": "Основной счёт",
                "current_balance": "52000.00",
                "currency": "RUB",
            }
        ]
    }


def _mock_goals(user_id: str) -> dict[str, Any]:
    return {
        "items": [
            {
                "id": "goal_mock_1",
                "owner_user_id": user_id,
                "title": "Отпуск",
                "target_amount": "150000.00",
                "current_amount": "45000.00",
                "status": "active",
            }
        ]
    }


def _mock_expected_incomes(user_id: str) -> dict[str, Any]:
    return {
        "items": [
            {
                "id": "income_mock_1",
                "user_id": user_id,
                "title": "Зарплата",
                "expected_amount": "85000.00",
                "currency": "RUB",
            }
        ]
    }


_MOCK_BUILDERS = {
    "transactions": lambda request: _mock_transactions(),
    "previous_period_transactions": lambda request: _mock_previous_period_transactions(),
    "user_context": lambda request: _mock_user_context(),
    "category_profiles": lambda request: _mock_category_profiles(),
    "accounts": lambda request: _mock_accounts(request.user_id),
    "goals": lambda request: _mock_goals(request.user_id),
    "expected_incomes": lambda request: _mock_expected_incomes(request.user_id),
    "existing_financial_analysis_result": lambda request: None,
}


def build_mock_dataset(request: BackendDataRequest) -> dict[str, Any]:
    dataset: dict[str, Any] = {}
    for data_type in request.data_types:
        builder = _MOCK_BUILDERS.get(data_type)
        if builder is not None:
            dataset[data_type] = builder(request)
    return dataset


def partial_data_type_errors(request: BackendDataRequest) -> list[tuple[str, str]]:
    errors: list[tuple[str, str]] = []
    for data_type in request.data_types:
        if data_type in MVP_PARTIAL_DATA_TYPES:
            errors.append(
                (
                    "NOT_IMPLEMENTED_MVP",
                    f"{data_type} returned as minimal mock; real backend fetch not implemented yet",
                )
            )
    return errors


def is_partial_request(request: BackendDataRequest) -> bool:
    return any(item in MVP_PARTIAL_DATA_TYPES for item in request.data_types)


def all_requested_types_supported(request: BackendDataRequest) -> bool:
    return all(item in MVP_FULL_MOCK_DATA_TYPES | MVP_PARTIAL_DATA_TYPES for item in request.data_types)
