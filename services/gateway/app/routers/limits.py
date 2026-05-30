from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from common.messaging import UserContext
from services.gateway.app.constants import FINANCE_QUEUE, PROTECTED_RESPONSES
from services.gateway.app.dependencies import current_user
from services.gateway.app.openapi_descriptions import (
    LIMITS_CREATE,
    LIMITS_DELETE,
    LIMITS_GET,
    LIMITS_LIST,
    LIMITS_UPDATE,
)
from services.gateway.app.rpc import model_payload, rpc_call
from services.gateway.app.schemas import LimitCreateRequest, LimitResponse, LimitsPageResponse, LimitUpdateRequest, StatusResponse

router = APIRouter(prefix="/api/v1/limits", tags=["Limits"])


@router.get(
    "",
    summary="Список лимитов",
    description=LIMITS_LIST,
    response_model=LimitsPageResponse,
    responses=PROTECTED_RESPONSES,
)
def limits_list(
    user: UserContext = Depends(current_user),
    page: int = Query(default=1, ge=1, description="Номер страницы."),
    page_size: int = Query(default=50, ge=1, le=500, description="Размер страницы."),
) -> dict:
    return rpc_call(FINANCE_QUEUE, "limits.list", {"page": page, "page_size": page_size}, user=user)


@router.post(
    "",
    summary="Создание лимита",
    description=LIMITS_CREATE,
    response_model=LimitResponse,
    responses=PROTECTED_RESPONSES,
)
def limits_create(payload: LimitCreateRequest, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(FINANCE_QUEUE, "limits.create", model_payload(payload), user=user)


@router.get(
    "/{limit_id}",
    summary="Лимит по идентификатору",
    description=LIMITS_GET,
    response_model=LimitResponse,
    responses=PROTECTED_RESPONSES,
)
def limits_get(limit_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(FINANCE_QUEUE, "limits.get", {"limit_id": str(limit_id)}, user=user)


@router.patch(
    "/{limit_id}",
    summary="Обновление лимита",
    description=LIMITS_UPDATE,
    response_model=LimitResponse,
    responses=PROTECTED_RESPONSES,
)
def limits_update(limit_id: UUID, payload: LimitUpdateRequest, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(FINANCE_QUEUE, "limits.update", {"limit_id": str(limit_id), **model_payload(payload)}, user=user)


@router.delete(
    "/{limit_id}",
    summary="Удаление лимита",
    description=LIMITS_DELETE,
    response_model=StatusResponse,
    responses=PROTECTED_RESPONSES,
)
def limits_delete(limit_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(FINANCE_QUEUE, "limits.delete", {"limit_id": str(limit_id)}, user=user)
