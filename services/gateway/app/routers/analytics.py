from __future__ import annotations

from datetime import date
from uuid import UUID

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
    RegularExpenseCreateRequest,
    RegularExpenseResponse,
    RegularExpensesPageResponse,
    RegularExpenseUpdateRequest,
    StatusResponse,
)

router = APIRouter(prefix="/api/v1/analytics", tags=["Analytics"])

REGULAR_EXPENSES_DESCRIPTION = (
    "Regular expenses are recurring planned charges such as subscriptions, rent, utilities, or detected recurring "
    "payments. Records are scoped to the authenticated user; manual edits to detected records are preserved as "
    "user_adjusted records so automatic detection does not overwrite user corrections."
)


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


@router.get(
    "/regular-expenses",
    summary="List regular expenses",
    description=REGULAR_EXPENSES_DESCRIPTION,
    response_model=RegularExpensesPageResponse,
    responses=PROTECTED_RESPONSES,
)
def regular_expenses_list(
    user: UserContext = Depends(current_user),
    status: str | None = Query(default=None, description="Optional status filter, for example active or paused."),
    page: int = Query(default=1, ge=1, description="Page number."),
    page_size: int = Query(default=50, ge=1, le=500, description="Page size."),
) -> dict:
    return rpc_call(
        ANALYTICS_QUEUE,
        "analytics.regular_expenses.list",
        {"status": status, "page": page, "page_size": page_size},
        user=user,
    )


@router.post(
    "/regular-expenses",
    summary="Create regular expense",
    description=REGULAR_EXPENSES_DESCRIPTION,
    response_model=RegularExpenseResponse,
    responses=PROTECTED_RESPONSES,
)
def regular_expenses_create(payload: RegularExpenseCreateRequest, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(ANALYTICS_QUEUE, "analytics.regular_expenses.create", payload.model_dump(mode="json", exclude_none=True), user=user)


@router.get(
    "/regular-expenses/{regular_expense_id}",
    summary="Get regular expense",
    description=REGULAR_EXPENSES_DESCRIPTION,
    response_model=RegularExpenseResponse,
    responses=PROTECTED_RESPONSES,
)
def regular_expenses_get(regular_expense_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(ANALYTICS_QUEUE, "analytics.regular_expenses.get", {"regular_expense_id": regular_expense_id}, user=user)


@router.patch(
    "/regular-expenses/{regular_expense_id}",
    summary="Update regular expense",
    description=REGULAR_EXPENSES_DESCRIPTION,
    response_model=RegularExpenseResponse,
    responses=PROTECTED_RESPONSES,
)
def regular_expenses_update(
    regular_expense_id: UUID,
    payload: RegularExpenseUpdateRequest,
    user: UserContext = Depends(current_user),
) -> dict:
    return rpc_call(
        ANALYTICS_QUEUE,
        "analytics.regular_expenses.update",
        {"regular_expense_id": regular_expense_id, **payload.model_dump(mode="json", exclude_unset=True)},
        user=user,
    )


@router.delete(
    "/regular-expenses/{regular_expense_id}",
    summary="Delete regular expense",
    description=(
        REGULAR_EXPENSES_DESCRIPTION
        + " Delete is implemented as a user-scoped soft delete so historical plans and scheduler behavior stay auditable."
    ),
    response_model=StatusResponse,
    responses=PROTECTED_RESPONSES,
)
def regular_expenses_delete(regular_expense_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(ANALYTICS_QUEUE, "analytics.regular_expenses.delete", {"regular_expense_id": regular_expense_id}, user=user)
