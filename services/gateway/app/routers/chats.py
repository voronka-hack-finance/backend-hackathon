from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from common.messaging import UserContext
from services.gateway.app.constants import CHAT_QUEUE, PROTECTED_RESPONSES
from services.gateway.app.dependencies import current_user
from services.gateway.app.openapi_descriptions import (
    CHAT_MESSAGES_CREATE,
    CHAT_MESSAGES_LIST,
    CHATS_CREATE,
    CHATS_DELETE,
    CHATS_GET,
    CHATS_LIST,
    CHATS_RECOMMENDATIONS,
    CHATS_UPDATE,
)
from services.gateway.app.rpc import model_payload, rpc_call
from services.gateway.app.schemas import (
    AgentRecommendationsPageResponse,
    ChatCreateRequest,
    ChatMessageCreateRequest,
    ChatMessageResponse,
    ChatMessagesPageResponse,
    ChatResponse,
    ChatsPageResponse,
    ChatUpdateRequest,
    StatusResponse,
)

router = APIRouter(prefix="/api/v1/chats", tags=["Chats"])


@router.get(
    "/recommendations",
    summary="Стартовые рекомендации агентов",
    description=CHATS_RECOMMENDATIONS,
    response_model=AgentRecommendationsPageResponse,
    responses=PROTECTED_RESPONSES,
)
def chat_recommendations(user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(CHAT_QUEUE, "chat.recommendations.initial.get", {}, user=user)


@router.get(
    "",
    summary="Список чатов",
    description=CHATS_LIST,
    response_model=ChatsPageResponse,
    responses=PROTECTED_RESPONSES,
)
def chats_list(
    user: UserContext = Depends(current_user),
    page: int = Query(default=1, ge=1, description="Номер страницы."),
    page_size: int = Query(default=50, ge=1, le=500, description="Размер страницы."),
) -> dict:
    return rpc_call(CHAT_QUEUE, "chats.list", {"page": page, "page_size": page_size}, user=user)


@router.post(
    "",
    summary="Создание чата",
    description=CHATS_CREATE,
    response_model=ChatResponse,
    responses=PROTECTED_RESPONSES,
)
def chats_create(payload: ChatCreateRequest, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(CHAT_QUEUE, "chats.create", model_payload(payload), user=user)


@router.get(
    "/{chat_id}",
    summary="Чат по идентификатору",
    description=CHATS_GET,
    response_model=ChatResponse,
    responses=PROTECTED_RESPONSES,
)
def chats_get(chat_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(CHAT_QUEUE, "chats.get", {"chat_id": str(chat_id)}, user=user)


@router.patch(
    "/{chat_id}",
    summary="Обновление чата",
    description=CHATS_UPDATE,
    response_model=ChatResponse,
    responses=PROTECTED_RESPONSES,
)
def chats_update(chat_id: UUID, payload: ChatUpdateRequest, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(CHAT_QUEUE, "chats.update", {"chat_id": str(chat_id), **model_payload(payload)}, user=user)


@router.delete(
    "/{chat_id}",
    summary="Удаление чата",
    description=CHATS_DELETE,
    response_model=StatusResponse,
    responses=PROTECTED_RESPONSES,
)
def chats_delete(chat_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(CHAT_QUEUE, "chats.delete", {"chat_id": str(chat_id)}, user=user)


@router.get(
    "/{chat_id}/messages",
    summary="Сообщения чата",
    description=CHAT_MESSAGES_LIST,
    response_model=ChatMessagesPageResponse,
    responses=PROTECTED_RESPONSES,
)
def chat_messages_list(
    chat_id: UUID,
    user: UserContext = Depends(current_user),
    page: int = Query(default=1, ge=1, description="Номер страницы."),
    page_size: int = Query(default=50, ge=1, le=500, description="Размер страницы."),
) -> dict:
    return rpc_call(CHAT_QUEUE, "chat_messages.list", {"chat_id": str(chat_id), "page": page, "page_size": page_size}, user=user)


@router.post(
    "/{chat_id}/messages",
    summary="Новое сообщение в чате",
    description=CHAT_MESSAGES_CREATE,
    response_model=ChatMessageResponse,
    responses=PROTECTED_RESPONSES,
)
def chat_messages_create(chat_id: UUID, payload: ChatMessageCreateRequest, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(CHAT_QUEUE, "chat_messages.create", {"chat_id": str(chat_id), **model_payload(payload)}, user=user)
