from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from common.messaging import UserContext
from services.gateway.app.constants import FINANCE_QUEUE, PROTECTED_RESPONSES
from services.gateway.app.dependencies import current_user
from services.gateway.app.openapi_descriptions import (
    CATEGORIES_CREATE,
    CATEGORIES_DELETE,
    CATEGORIES_GET,
    CATEGORIES_LIST,
    CATEGORIES_UPDATE,
)
from services.gateway.app.rpc import model_payload, rpc_call
from services.gateway.app.schemas import (
    CategoriesPageResponse,
    CategoryCreateRequest,
    CategoryResponse,
    CategoryUpdateRequest,
    StatusResponse,
)

router = APIRouter(prefix="/api/v1/categories", tags=["Categories"])


@router.get(
    "",
    summary="Список категорий",
    description=CATEGORIES_LIST,
    response_model=CategoriesPageResponse,
    responses=PROTECTED_RESPONSES,
)
def categories_list(
    user: UserContext = Depends(current_user),
    page: int = Query(default=1, ge=1, description="Номер страницы."),
    page_size: int = Query(default=50, ge=1, le=500, description="Размер страницы."),
) -> dict:
    return rpc_call(FINANCE_QUEUE, "categories.list", {"page": page, "page_size": page_size}, user=user)


@router.post(
    "",
    summary="Создание категории",
    description=CATEGORIES_CREATE,
    response_model=CategoryResponse,
    responses=PROTECTED_RESPONSES,
)
def categories_create(payload: CategoryCreateRequest, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(FINANCE_QUEUE, "categories.create", model_payload(payload), user=user)


@router.get(
    "/{category_id}",
    summary="Категория по идентификатору",
    description=CATEGORIES_GET,
    response_model=CategoryResponse,
    responses=PROTECTED_RESPONSES,
)
def categories_get(category_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(FINANCE_QUEUE, "categories.get", {"category_id": str(category_id)}, user=user)


@router.patch(
    "/{category_id}",
    summary="Обновление категории",
    description=CATEGORIES_UPDATE,
    response_model=CategoryResponse,
    responses=PROTECTED_RESPONSES,
)
def categories_update(category_id: UUID, payload: CategoryUpdateRequest, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(FINANCE_QUEUE, "categories.update", {"category_id": str(category_id), **model_payload(payload)}, user=user)


@router.delete(
    "/{category_id}",
    summary="Удаление категории",
    description=CATEGORIES_DELETE,
    response_model=StatusResponse,
    responses=PROTECTED_RESPONSES,
)
def categories_delete(category_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(FINANCE_QUEUE, "categories.delete", {"category_id": str(category_id)}, user=user)
