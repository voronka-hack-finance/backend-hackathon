from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query

from common.messaging import UserContext
from services.gateway.app.constants import ANALYTICS_QUEUE, PROTECTED_RESPONSES
from services.gateway.app.dependencies import current_user
from services.gateway.app.openapi_descriptions import (
    ANALYTICS_AVAILABLE_BALANCE,
    ANALYTICS_EXPECTED_EXPENSES,
    ANALYTICS_EXPECTED_INCOMES,
)
from services.gateway.app.rpc import date_or_none, rpc_call
from services.gateway.app.schemas import (
    AnalyticsAvailableBalanceResponse,
    ExpectedExpensesPageResponse,
    ExpectedIncomesPageResponse,
)

router = APIRouter(prefix="/api/v1/analytics", tags=["Analytics"])


@router.get(
    "/available-balance",
    summary="Доступный остаток",
    description=ANALYTICS_AVAILABLE_BALANCE,
    response_model=AnalyticsAvailableBalanceResponse,
    responses=PROTECTED_RESPONSES,
)
def analytics_available_balance(
    user: UserContext = Depends(current_user),
    period_start: date | None = Query(default=None, description="Начало периода расчёта (включительно)."),
    period_end: date | None = Query(default=None, description="Конец периода расчёта (включительно)."),
) -> dict:
    return rpc_call(
        ANALYTICS_QUEUE,
        "analytics.available_balance.get",
        {"period_start": date_or_none(period_start), "period_end": date_or_none(period_end)},
        user=user,
    )


@router.get(
    "/expected-incomes",
    summary="Ожидаемые доходы",
    description=ANALYTICS_EXPECTED_INCOMES,
    response_model=ExpectedIncomesPageResponse,
    responses=PROTECTED_RESPONSES,
)
def analytics_expected_incomes(
    user: UserContext = Depends(current_user),
    page: int = Query(default=1, ge=1, description="Номер страницы."),
    page_size: int = Query(default=50, ge=1, le=500, description="Размер страницы."),
) -> dict:
    return rpc_call(ANALYTICS_QUEUE, "analytics.expected_incomes.list", {"page": page, "page_size": page_size}, user=user)


@router.get(
    "/expected-expenses",
    summary="Ожидаемые расходы",
    description=ANALYTICS_EXPECTED_EXPENSES,
    response_model=ExpectedExpensesPageResponse,
    responses=PROTECTED_RESPONSES,
)
def analytics_expected_expenses(
    user: UserContext = Depends(current_user),
    page: int = Query(default=1, ge=1, description="Номер страницы."),
    page_size: int = Query(default=50, ge=1, le=500, description="Размер страницы."),
) -> dict:
    return rpc_call(ANALYTICS_QUEUE, "analytics.expected_expenses.list", {"page": page, "page_size": page_size}, user=user)
