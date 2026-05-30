from __future__ import annotations

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from common.messaging import UserContext
from services.gateway.app.constants import FINANCE_QUEUE, PROTECTED_RESPONSES
from services.gateway.app.dependencies import current_user
from services.gateway.app.openapi_descriptions import TRANSACTIONS_LIST
from services.gateway.app.rpc import params_to_payload, rpc_call, transaction_query_params
from services.gateway.app.schemas import TransactionsPageResponse

router = APIRouter(prefix="/api/v1/transactions", tags=["Transactions"])


@router.get(
    "",
    summary="Список транзакций",
    description=TRANSACTIONS_LIST,
    response_model=TransactionsPageResponse,
    responses=PROTECTED_RESPONSES,
)
def transactions(
    user: UserContext = Depends(current_user),
    date_from: date | None = Query(default=None, description="Начало периода операции (включительно)."),
    date_to: date | None = Query(default=None, description="Конец периода операции (включительно)."),
    categories: Annotated[list[str] | None, Query(description="Фильтр по названиям категорий.")] = None,
    mcc: Annotated[list[str] | None, Query(description="Фильтр по кодам MCC.")] = None,
    transaction_type: Literal["income", "expense"] | None = Query(
        default=None,
        alias="type",
        description="Направление: income (доход) или expense (расход).",
    ),
    status_filter: str | None = Query(default=None, alias="status", description="Статус операции в источнике."),
    has_cashback: bool | None = Query(default=None, description="Только операции с ненулевым кэшбэком."),
    card_last4: Annotated[list[str] | None, Query(description="Последние 4 цифры карты.")] = None,
    account_id: UUID | None = Query(default=None, description="Идентификатор счёта."),
    category_id: UUID | None = Query(default=None, description="Идентификатор категории."),
    page: int = Query(default=1, ge=1, description="Номер страницы."),
    page_size: int = Query(default=50, ge=1, le=500, description="Размер страницы."),
) -> dict:
    params = transaction_query_params(
        date_from=date_from,
        date_to=date_to,
        categories=categories,
        mcc=mcc,
        transaction_type=transaction_type,
        status_filter=status_filter,
        has_cashback=has_cashback,
        card_last4=card_last4,
        page=page,
        page_size=page_size,
    )
    payload = params_to_payload(params)
    if account_id:
        payload["account_id"] = str(account_id)
    if category_id:
        payload["category_id"] = str(category_id)
    return rpc_call(FINANCE_QUEUE, "transactions.list", payload, user=user)
