from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from common.messaging import UserContext
from services.gateway.app.constants import FINANCE_QUEUE, PROTECTED_RESPONSES
from services.gateway.app.dependencies import current_user
from services.gateway.app.openapi_descriptions import ACCOUNTS_LIST
from services.gateway.app.rpc import rpc_call
from services.gateway.app.schemas import AccountsPageResponse

router = APIRouter(prefix="/api/v1/accounts", tags=["Accounts"])


@router.get(
    "",
    summary="Список счетов",
    description=ACCOUNTS_LIST,
    response_model=AccountsPageResponse,
    responses=PROTECTED_RESPONSES,
)
def accounts_list(
    user: UserContext = Depends(current_user),
    page: int = Query(default=1, ge=1, description="Номер страницы."),
    page_size: int = Query(default=50, ge=1, le=500, description="Размер страницы."),
) -> dict:
    return rpc_call(FINANCE_QUEUE, "accounts.list", {"page": page, "page_size": page_size}, user=user)
