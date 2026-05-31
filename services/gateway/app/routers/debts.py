from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from common.messaging import UserContext
from services.gateway.app.constants import FINANCE_QUEUE, PROTECTED_RESPONSES
from services.gateway.app.dependencies import current_user
from services.gateway.app.openapi_descriptions import DEBTS_CREATE, DEBTS_DELETE, DEBTS_GET, DEBTS_LIST, DEBTS_UPDATE
from services.gateway.app.rpc import model_payload, rpc_call
from services.gateway.app.schemas import DebtCreateRequest, DebtResponse, DebtUpdateRequest, DebtsPageResponse, StatusResponse

router = APIRouter(prefix="/api/v1/debts", tags=["Debts"])


@router.get(
    "",
    summary="List debts",
    description=DEBTS_LIST,
    response_model=DebtsPageResponse,
    responses=PROTECTED_RESPONSES,
)
def debts_list(
    user: UserContext = Depends(current_user),
    status: Literal["active", "closed", "deleted"] = Query(default="active", description="Debt status filter."),
    debt_type: Literal["loan", "credit_card", "other"] | None = Query(default=None, description="Optional debt type filter."),
    page: int = Query(default=1, ge=1, description="Page number."),
    page_size: int = Query(default=50, ge=1, le=500, description="Page size."),
) -> dict:
    return rpc_call(
        FINANCE_QUEUE,
        "debts.list",
        {"status": status, "debt_type": debt_type, "page": page, "page_size": page_size},
        user=user,
    )


@router.post(
    "",
    summary="Create debt",
    description=DEBTS_CREATE,
    response_model=DebtResponse,
    responses=PROTECTED_RESPONSES,
)
def debts_create(payload: DebtCreateRequest, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(FINANCE_QUEUE, "debts.create", model_payload(payload), user=user)


@router.get(
    "/{debt_id}",
    summary="Get debt",
    description=DEBTS_GET,
    response_model=DebtResponse,
    responses=PROTECTED_RESPONSES,
)
def debts_get(debt_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(FINANCE_QUEUE, "debts.get", {"debt_id": str(debt_id)}, user=user)


@router.patch(
    "/{debt_id}",
    summary="Update debt",
    description=DEBTS_UPDATE,
    response_model=DebtResponse,
    responses=PROTECTED_RESPONSES,
)
def debts_update(debt_id: UUID, payload: DebtUpdateRequest, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(FINANCE_QUEUE, "debts.update", {"debt_id": str(debt_id), **model_payload(payload)}, user=user)


@router.delete(
    "/{debt_id}",
    summary="Delete debt",
    description=DEBTS_DELETE,
    response_model=StatusResponse,
    responses=PROTECTED_RESPONSES,
)
def debts_delete(debt_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(FINANCE_QUEUE, "debts.delete", {"debt_id": str(debt_id)}, user=user)
