from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from common.messaging import UserContext
from services.gateway.app.constants import FINANCE_QUEUE, PROTECTED_RESPONSES
from services.gateway.app.dependencies import current_user
from services.gateway.app.openapi_descriptions import (
    GOALS_CREATE,
    GOALS_DELETE,
    GOALS_GET,
    GOALS_LIST,
    GOALS_UPDATE,
)
from services.gateway.app.rpc import model_payload, rpc_call
from services.gateway.app.schemas import GoalCreateRequest, GoalResponse, GoalUpdateRequest, GoalsPageResponse, StatusResponse

router = APIRouter(prefix="/api/v1/goals", tags=["Goals"])


@router.get(
    "",
    summary="Список целей",
    description=GOALS_LIST,
    response_model=GoalsPageResponse,
    responses=PROTECTED_RESPONSES,
)
def goals_list(
    user: UserContext = Depends(current_user),
    page: int = Query(default=1, ge=1, description="Номер страницы."),
    page_size: int = Query(default=50, ge=1, le=500, description="Размер страницы."),
) -> dict:
    return rpc_call(FINANCE_QUEUE, "goals.list", {"page": page, "page_size": page_size}, user=user)


@router.post(
    "",
    summary="Создание цели",
    description=GOALS_CREATE,
    response_model=GoalResponse,
    responses=PROTECTED_RESPONSES,
)
def goals_create(payload: GoalCreateRequest, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(FINANCE_QUEUE, "goals.create", model_payload(payload), user=user)


@router.get(
    "/{goal_id}",
    summary="Цель по идентификатору",
    description=GOALS_GET,
    response_model=GoalResponse,
    responses=PROTECTED_RESPONSES,
)
def goals_get(goal_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(FINANCE_QUEUE, "goals.get", {"goal_id": str(goal_id)}, user=user)


@router.patch(
    "/{goal_id}",
    summary="Обновление цели",
    description=GOALS_UPDATE,
    response_model=GoalResponse,
    responses=PROTECTED_RESPONSES,
)
def goals_update(goal_id: UUID, payload: GoalUpdateRequest, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(FINANCE_QUEUE, "goals.update", {"goal_id": str(goal_id), **model_payload(payload)}, user=user)


@router.delete(
    "/{goal_id}",
    summary="Удаление цели",
    description=GOALS_DELETE,
    response_model=StatusResponse,
    responses=PROTECTED_RESPONSES,
)
def goals_delete(goal_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(FINANCE_QUEUE, "goals.delete", {"goal_id": str(goal_id)}, user=user)
