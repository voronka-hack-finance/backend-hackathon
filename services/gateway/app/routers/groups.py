from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from common.messaging import UserContext
from services.gateway.app.constants import GROUP_QUEUE, PROTECTED_RESPONSES
from services.gateway.app.dependencies import current_user
from services.gateway.app.openapi_descriptions import (
    GROUP_INVITATION_ACCEPT,
    GROUP_INVITATION_DECLINE,
    GROUP_INVITATIONS_CREATE,
    GROUP_INVITATIONS_DELETE,
    GROUP_INVITATIONS_LIST,
    GROUP_INVITATIONS_UPDATE,
    GROUP_MEMBERS_CREATE,
    GROUP_MEMBERS_DELETE,
    GROUP_MEMBERS_LIST,
    GROUP_MEMBERS_UPDATE,
    GROUPS_BUDGET,
    GROUPS_CREATE,
    GROUPS_DELETE,
    GROUPS_GET,
    GROUPS_LIST,
    GROUPS_UPDATE,
)
from services.gateway.app.rpc import model_payload, rpc_call
from services.gateway.app.schemas import (
    GroupBudgetResponse,
    GroupCreateRequest,
    GroupInvitationRequest,
    GroupInvitationResponse,
    GroupInvitationsPageResponse,
    GroupInvitationUpdateRequest,
    GroupMemberRequest,
    GroupMemberResponse,
    GroupMembersPageResponse,
    GroupMemberUpdateRequest,
    GroupResponse,
    GroupsPageResponse,
    GroupUpdateRequest,
    StatusResponse,
)

router = APIRouter(prefix="/api/v1", tags=["Groups"])


@router.get(
    "/groups",
    summary="Список семейных групп",
    description=GROUPS_LIST,
    response_model=GroupsPageResponse,
    responses=PROTECTED_RESPONSES,
)
def groups_list(
    user: UserContext = Depends(current_user),
    page: int = Query(default=1, ge=1, description="Номер страницы."),
    page_size: int = Query(default=50, ge=1, le=500, description="Размер страницы."),
) -> dict:
    return rpc_call(GROUP_QUEUE, "groups.list", {"page": page, "page_size": page_size}, user=user)


@router.post(
    "/groups",
    summary="Создание семейной группы",
    description=GROUPS_CREATE,
    response_model=GroupResponse,
    responses=PROTECTED_RESPONSES,
)
def groups_create(payload: GroupCreateRequest, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(GROUP_QUEUE, "groups.create", model_payload(payload), user=user)


@router.get(
    "/groups/{group_id}",
    summary="Группа по идентификатору",
    description=GROUPS_GET,
    response_model=GroupResponse,
    responses=PROTECTED_RESPONSES,
)
def groups_get(group_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(GROUP_QUEUE, "groups.get", {"group_id": str(group_id)}, user=user)


@router.patch(
    "/groups/{group_id}",
    summary="Обновление группы",
    description=GROUPS_UPDATE,
    response_model=GroupResponse,
    responses=PROTECTED_RESPONSES,
)
def groups_update(group_id: UUID, payload: GroupUpdateRequest, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(GROUP_QUEUE, "groups.update", {"group_id": str(group_id), **model_payload(payload)}, user=user)


@router.delete(
    "/groups/{group_id}",
    summary="Удаление группы",
    description=GROUPS_DELETE,
    response_model=StatusResponse,
    responses=PROTECTED_RESPONSES,
)
def groups_delete(group_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(GROUP_QUEUE, "groups.delete", {"group_id": str(group_id)}, user=user)


@router.get(
    "/groups/{group_id}/budget",
    summary="Сводный бюджет группы",
    description=GROUPS_BUDGET,
    response_model=GroupBudgetResponse,
    responses=PROTECTED_RESPONSES,
)
def groups_budget(group_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(GROUP_QUEUE, "groups.family_budget.get", {"group_id": str(group_id)}, user=user)


@router.get(
    "/groups/{group_id}/members",
    summary="Участники группы",
    description=GROUP_MEMBERS_LIST,
    response_model=GroupMembersPageResponse,
    responses=PROTECTED_RESPONSES,
)
def group_members_list(group_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(GROUP_QUEUE, "group_members.list", {"group_id": str(group_id)}, user=user)


@router.post(
    "/groups/{group_id}/members",
    summary="Добавление участника",
    description=GROUP_MEMBERS_CREATE,
    response_model=GroupMemberResponse,
    responses=PROTECTED_RESPONSES,
)
def group_members_create(group_id: UUID, payload: GroupMemberRequest, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(GROUP_QUEUE, "group_members.create", {"group_id": str(group_id), **model_payload(payload)}, user=user)


@router.patch(
    "/groups/{group_id}/members/{member_id}",
    summary="Обновление участника",
    description=GROUP_MEMBERS_UPDATE,
    response_model=GroupMemberResponse,
    responses=PROTECTED_RESPONSES,
)
def group_members_update(
    group_id: UUID,
    member_id: UUID,
    payload: GroupMemberUpdateRequest,
    user: UserContext = Depends(current_user),
) -> dict:
    return rpc_call(
        GROUP_QUEUE,
        "group_members.update",
        {"group_id": str(group_id), "member_id": str(member_id), **model_payload(payload)},
        user=user,
    )


@router.delete(
    "/groups/{group_id}/members/{member_id}",
    summary="Удаление участника",
    description=GROUP_MEMBERS_DELETE,
    response_model=StatusResponse,
    responses=PROTECTED_RESPONSES,
)
def group_members_delete(group_id: UUID, member_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(
        GROUP_QUEUE,
        "group_members.delete",
        {"group_id": str(group_id), "member_id": str(member_id)},
        user=user,
    )


@router.get(
    "/groups/{group_id}/invitations",
    summary="Приглашения в группу",
    description=GROUP_INVITATIONS_LIST,
    response_model=GroupInvitationsPageResponse,
    responses=PROTECTED_RESPONSES,
)
def group_invitations_list(group_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(GROUP_QUEUE, "group_invitations.list", {"group_id": str(group_id)}, user=user)


@router.post(
    "/groups/{group_id}/invitations",
    summary="Создание приглашения",
    description=GROUP_INVITATIONS_CREATE,
    response_model=GroupInvitationResponse,
    responses=PROTECTED_RESPONSES,
)
def group_invitations_create(group_id: UUID, payload: GroupInvitationRequest, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(GROUP_QUEUE, "group_invitations.create", {"group_id": str(group_id), **model_payload(payload)}, user=user)


@router.patch(
    "/groups/{group_id}/invitations/{invitation_id}",
    summary="Обновление приглашения",
    description=GROUP_INVITATIONS_UPDATE,
    response_model=GroupInvitationResponse,
    responses=PROTECTED_RESPONSES,
)
def group_invitations_update(
    group_id: UUID,
    invitation_id: UUID,
    payload: GroupInvitationUpdateRequest,
    user: UserContext = Depends(current_user),
) -> dict:
    return rpc_call(
        GROUP_QUEUE,
        "group_invitations.update",
        {"group_id": str(group_id), "invitation_id": str(invitation_id), **model_payload(payload)},
        user=user,
    )


@router.delete(
    "/groups/{group_id}/invitations/{invitation_id}",
    summary="Удаление приглашения",
    description=GROUP_INVITATIONS_DELETE,
    response_model=StatusResponse,
    responses=PROTECTED_RESPONSES,
)
def group_invitations_delete(group_id: UUID, invitation_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(
        GROUP_QUEUE,
        "group_invitations.delete",
        {"group_id": str(group_id), "invitation_id": str(invitation_id)},
        user=user,
    )


@router.post(
    "/group-invitations/{invitation_id}/accept",
    summary="Принятие приглашения",
    description=GROUP_INVITATION_ACCEPT,
    response_model=GroupInvitationResponse,
    responses=PROTECTED_RESPONSES,
)
def group_invitation_accept(invitation_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(GROUP_QUEUE, "group_invitations.accept", {"invitation_id": str(invitation_id)}, user=user)


@router.post(
    "/group-invitations/{invitation_id}/decline",
    summary="Отклонение приглашения",
    description=GROUP_INVITATION_DECLINE,
    response_model=GroupInvitationResponse,
    responses=PROTECTED_RESPONSES,
)
def group_invitation_decline(invitation_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return rpc_call(GROUP_QUEUE, "group_invitations.decline", {"invitation_id": str(invitation_id)}, user=user)
