from __future__ import annotations

import base64
from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID

from common.messaging import MessageBus, UserContext, check_rabbitmq
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Security, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from services.gateway.app.config import settings
from services.gateway.app.schemas import (
    AccountResponse,
    AccountsPageResponse,
    AgentRecommendationsPageResponse,
    AnalyticsAvailableBalanceResponse,
    CategoriesPageResponse,
    CategoryCreateRequest,
    CategoryResponse,
    CategoryUpdateRequest,
    ChangePasswordRequest,
    ChatCreateRequest,
    ChatMessageCreateRequest,
    ChatMessageResponse,
    ChatMessagesPageResponse,
    ChatResponse,
    ChatsPageResponse,
    ChatUpdateRequest,
    ErrorResponse,
    ExpectedExpensesPageResponse,
    ExpectedIncomesPageResponse,
    FileResponse,
    FilesPageResponse,
    FileUpdateRequest,
    GoalCreateRequest,
    GoalResponse,
    GoalUpdateRequest,
    GoalsPageResponse,
    GroupCreateRequest,
    GroupBudgetResponse,
    GroupInvitationResponse,
    GroupInvitationRequest,
    GroupInvitationUpdateRequest,
    GroupInvitationsPageResponse,
    GroupMemberRequest,
    GroupMemberResponse,
    GroupMemberUpdateRequest,
    GroupMembersPageResponse,
    GroupResponse,
    GroupUpdateRequest,
    GroupsPageResponse,
    HealthResponse,
    ImportErrorsResponse,
    ImportStatusResponse,
    LimitCreateRequest,
    LimitResponse,
    LimitUpdateRequest,
    LimitsPageResponse,
    LoginRequest,
    LogoutRequest,
    NotificationDeviceRequest,
    NotificationDeviceResponse,
    NotificationDeliveryResponse,
    NotificationPermissionRequest,
    NotificationPreferenceResponse,
    NotificationTestRequest,
    ProfileUpdateRequest,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    StatusResponse,
    TokenResponse,
    TransactionsPageResponse,
    UploadResponse,
    UserResponse,
)

ACCESS_QUEUE = "access-service"
FILE_QUEUE = "file-service"
FINANCE_QUEUE = "finance-service"
NOTIFICATION_QUEUE = "notification-service"
ANALYTICS_QUEUE = "analytics-service"
GROUP_QUEUE = "group-service"
CHAT_QUEUE = "chat-service"

PROTECTED_RESPONSES = {
    401: {"model": ErrorResponse, "description": "Missing, expired, or invalid Bearer JWT."},
    502: {"model": ErrorResponse, "description": "Internal message bus or service failure."},
    504: {"model": ErrorResponse, "description": "Internal service request timed out."},
}

PUBLIC_RESPONSES = {
    409: {"model": ErrorResponse, "description": "Data conflict, for example an already registered email."},
    422: {"model": ErrorResponse, "description": "Request validation failed."},
    502: {"model": ErrorResponse, "description": "Internal message bus or service failure."},
    504: {"model": ErrorResponse, "description": "Internal service request timed out."},
}

bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="BearerAuth",
    description="JWT from POST /api/v1/auth/login. Send as Authorization: Bearer <token>.",
)

app = FastAPI(
    title="Family Budget API Gateway",
    description="Public HTTP API that maps frontend requests to RabbitMQ task messages.",
    version="0.2.0",
    openapi_tags=[
        {"name": "System", "description": "Gateway liveness and readiness endpoints."},
        {"name": "Auth", "description": "Registration, login, refresh tokens, profile, and password changes."},
        {"name": "Files", "description": "Uploaded source files and Excel import jobs."},
        {"name": "Imports", "description": "Import job status and parser errors."},
        {"name": "Transactions", "description": "Normalized financial transaction reads and filters."},
        {"name": "Accounts", "description": "User financial accounts."},
        {"name": "Goals", "description": "Savings goals."},
        {"name": "Limits", "description": "Category spending limits."},
        {"name": "Categories", "description": "User finance categories."},
        {"name": "Notifications", "description": "Push permission, devices, and test sends."},
        {"name": "Analytics", "description": "Available balance, expected incomes, and expected expenses."},
        {"name": "Groups", "description": "Family groups, members, invitations, and group budget."},
        {"name": "Chats", "description": "Agent recommendations, chats, and messages."},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

bus = MessageBus(settings.rabbitmq_url, "api-gateway-service")


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> UserContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Bearer token")
    payload = _rpc(
        ACCESS_QUEUE,
        "auth.verify_token",
        {"token": credentials.credentials},
        timeout_seconds=settings.rpc_timeout_seconds,
    )
    user = payload.get("user") or {}
    user_id = user.get("id") or user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return UserContext(id=str(user_id), email=user.get("email"))


@app.get("/health", tags=["System"], summary="Gateway liveness probe", response_model=HealthResponse)
@app.get("/api/v1/health", tags=["System"], summary="Gateway liveness probe", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/ready", tags=["System"], summary="Gateway readiness probe", response_model=HealthResponse)
def ready() -> HealthResponse:
    check_rabbitmq(settings.rabbitmq_url)
    return HealthResponse(status="ready")


@app.post(
    "/api/v1/auth/register",
    tags=["Auth"],
    summary="Register a user",
    description="Creates a user account through access-service.",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    responses=PUBLIC_RESPONSES,
)
def register(payload: RegisterRequest) -> dict:
    return _rpc(ACCESS_QUEUE, "auth.register", _model_payload(payload))


@app.post(
    "/api/v1/auth/login",
    tags=["Auth"],
    summary="Login and issue tokens",
    description="Validates email/password and returns an access token plus refresh token.",
    response_model=TokenResponse,
    responses={401: {"model": ErrorResponse, "description": "Invalid email or password."}, **PUBLIC_RESPONSES},
)
def login(payload: LoginRequest) -> dict:
    return _rpc(ACCESS_QUEUE, "auth.login", _model_payload(payload))


@app.post(
    "/api/v1/auth/logout",
    tags=["Auth"],
    summary="Logout",
    description="Revokes a refresh token when provided.",
    response_model=StatusResponse,
    responses=PROTECTED_RESPONSES,
)
def logout(payload: LogoutRequest, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(ACCESS_QUEUE, "auth.logout", _model_payload(payload), user=user)


@app.post(
    "/api/v1/auth/refresh",
    tags=["Auth"],
    summary="Refresh access token",
    description="Uses a refresh token to issue a new access token.",
    response_model=TokenResponse,
    responses=PUBLIC_RESPONSES,
)
def refresh(payload: RefreshRequest) -> dict:
    return _rpc(ACCESS_QUEUE, "auth.refresh", _model_payload(payload))


@app.get(
    "/api/v1/auth/me",
    tags=["Auth"],
    summary="Get current user",
    response_model=UserResponse,
    responses=PROTECTED_RESPONSES,
)
def me(user: UserContext = Depends(current_user)) -> dict:
    return _rpc(ACCESS_QUEUE, "auth.me.get", {}, user=user)


@app.patch(
    "/api/v1/auth/me",
    tags=["Auth"],
    summary="Update current user profile",
    response_model=UserResponse,
    responses=PROTECTED_RESPONSES,
)
def update_me(payload: ProfileUpdateRequest, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(ACCESS_QUEUE, "auth.me.patch", _model_payload(payload), user=user)


@app.post(
    "/api/v1/auth/change-password",
    tags=["Auth"],
    summary="Change current user password",
    response_model=StatusResponse,
    responses=PROTECTED_RESPONSES,
)
def change_password(payload: ChangePasswordRequest, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(ACCESS_QUEUE, "auth.change_password", _model_payload(payload), user=user)


@app.post(
    "/api/v1/files",
    tags=["Files"],
    summary="Upload Excel source file",
    description="Stores the original workbook and queues the parser import task.",
    response_model=UploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**PROTECTED_RESPONSES, 400: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def upload_file(
    file: UploadFile = File(..., description="family-budget .xlsx workbook."),
    source_type: str = Form(default="excel_family_budget_v1", description="Parser source type."),
    user: UserContext = Depends(current_user),
) -> dict:
    file_bytes = await file.read()
    return _rpc(
        FILE_QUEUE,
        "files.upload.create",
        {
            "filename": file.filename or "upload.xlsx",
            "content_type": file.content_type,
            "source_type": source_type,
            "file_base64": base64.b64encode(file_bytes).decode("ascii"),
        },
        user=user,
        timeout_seconds=120.0,
    )


@app.get(
    "/api/v1/files",
    tags=["Files"],
    summary="List uploaded files",
    description="Returns uploaded source files owned by the current user.",
    response_model=FilesPageResponse,
    responses=PROTECTED_RESPONSES,
)
def files_list(
    user: UserContext = Depends(current_user),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
) -> dict:
    return _rpc(FILE_QUEUE, "files.list", {"page": page, "page_size": page_size}, user=user)


@app.get("/api/v1/files/{file_id}", tags=["Files"], summary="Get uploaded file", response_model=FileResponse, responses=PROTECTED_RESPONSES)
def files_get(file_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(FILE_QUEUE, "files.get", {"file_id": str(file_id)}, user=user)


@app.patch("/api/v1/files/{file_id}", tags=["Files"], summary="Update file metadata", response_model=FileResponse, responses=PROTECTED_RESPONSES)
def files_update(file_id: UUID, payload: FileUpdateRequest, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(FILE_QUEUE, "files.update", {"file_id": str(file_id), **_model_payload(payload)}, user=user)


@app.delete("/api/v1/files/{file_id}", tags=["Files"], summary="Delete uploaded file", response_model=StatusResponse, responses=PROTECTED_RESPONSES)
def files_delete(file_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(FILE_QUEUE, "files.delete", {"file_id": str(file_id)}, user=user)


@app.get("/api/v1/imports/{import_id}", tags=["Imports"], summary="Get import status", response_model=ImportStatusResponse, responses=PROTECTED_RESPONSES)
def import_status(import_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(FILE_QUEUE, "imports.status.get", {"import_id": str(import_id)}, user=user)


@app.get("/api/v1/imports/{import_id}/errors", tags=["Imports"], summary="List import errors", response_model=ImportErrorsResponse, responses=PROTECTED_RESPONSES)
def import_errors(
    import_id: UUID,
    user: UserContext = Depends(current_user),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
) -> dict:
    return _rpc(FILE_QUEUE, "imports.errors.list", {"import_id": str(import_id), "page": page, "page_size": page_size}, user=user)


@app.get(
    "/api/v1/transactions",
    tags=["Transactions"],
    summary="List transactions",
    description="Returns current user's normalized transactions. Use type=income or type=expense to filter direction.",
    response_model=TransactionsPageResponse,
    responses=PROTECTED_RESPONSES,
)
def transactions(
    user: UserContext = Depends(current_user),
    date_from: date | None = Query(default=None, description="Inclusive operation date from."),
    date_to: date | None = Query(default=None, description="Inclusive operation date to."),
    categories: Annotated[list[str] | None, Query(description="Category names.")] = None,
    mcc: Annotated[list[str] | None, Query(description="MCC values.")] = None,
    transaction_type: Literal["income", "expense"] | None = Query(
        default=None,
        alias="type",
        description="Transaction direction: income or expense.",
    ),
    status_filter: str | None = Query(default=None, alias="status", description="Source operation status."),
    has_cashback: bool | None = Query(default=None, description="Filter by non-zero cashback."),
    card_last4: Annotated[list[str] | None, Query(description="Card last four digits.")] = None,
    account_id: UUID | None = Query(default=None, description="Account identifier."),
    category_id: UUID | None = Query(default=None, description="Category identifier."),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
) -> dict:
    params = _transaction_query_params(
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
    payload = _params_to_payload(params)
    if account_id:
        payload["account_id"] = str(account_id)
    if category_id:
        payload["category_id"] = str(category_id)
    return _rpc(FINANCE_QUEUE, "transactions.list", payload, user=user)


@app.get("/api/v1/accounts", tags=["Accounts"], summary="List accounts", response_model=AccountsPageResponse, responses=PROTECTED_RESPONSES)
def accounts_list(user: UserContext = Depends(current_user), page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=500)) -> dict:
    return _rpc(FINANCE_QUEUE, "accounts.list", {"page": page, "page_size": page_size}, user=user)


@app.get("/api/v1/goals", tags=["Goals"], summary="List goals", response_model=GoalsPageResponse, responses=PROTECTED_RESPONSES)
def goals_list(user: UserContext = Depends(current_user), page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=500)) -> dict:
    return _rpc(FINANCE_QUEUE, "goals.list", {"page": page, "page_size": page_size}, user=user)


@app.post("/api/v1/goals", tags=["Goals"], summary="Create goal", response_model=GoalResponse, responses=PROTECTED_RESPONSES)
def goals_create(payload: GoalCreateRequest, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(FINANCE_QUEUE, "goals.create", _model_payload(payload), user=user)


@app.get("/api/v1/goals/{goal_id}", tags=["Goals"], summary="Get goal", response_model=GoalResponse, responses=PROTECTED_RESPONSES)
def goals_get(goal_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(FINANCE_QUEUE, "goals.get", {"goal_id": str(goal_id)}, user=user)


@app.patch("/api/v1/goals/{goal_id}", tags=["Goals"], summary="Update goal", response_model=GoalResponse, responses=PROTECTED_RESPONSES)
def goals_update(goal_id: UUID, payload: GoalUpdateRequest, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(FINANCE_QUEUE, "goals.update", {"goal_id": str(goal_id), **_model_payload(payload)}, user=user)


@app.delete("/api/v1/goals/{goal_id}", tags=["Goals"], summary="Delete goal", response_model=StatusResponse, responses=PROTECTED_RESPONSES)
def goals_delete(goal_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(FINANCE_QUEUE, "goals.delete", {"goal_id": str(goal_id)}, user=user)


@app.get("/api/v1/limits", tags=["Limits"], summary="List limits", response_model=LimitsPageResponse, responses=PROTECTED_RESPONSES)
def limits_list(user: UserContext = Depends(current_user), page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=500)) -> dict:
    return _rpc(FINANCE_QUEUE, "limits.list", {"page": page, "page_size": page_size}, user=user)


@app.post("/api/v1/limits", tags=["Limits"], summary="Create limit", response_model=LimitResponse, responses=PROTECTED_RESPONSES)
def limits_create(payload: LimitCreateRequest, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(FINANCE_QUEUE, "limits.create", _model_payload(payload), user=user)


@app.get("/api/v1/limits/{limit_id}", tags=["Limits"], summary="Get limit", response_model=LimitResponse, responses=PROTECTED_RESPONSES)
def limits_get(limit_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(FINANCE_QUEUE, "limits.get", {"limit_id": str(limit_id)}, user=user)


@app.patch("/api/v1/limits/{limit_id}", tags=["Limits"], summary="Update limit", response_model=LimitResponse, responses=PROTECTED_RESPONSES)
def limits_update(limit_id: UUID, payload: LimitUpdateRequest, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(FINANCE_QUEUE, "limits.update", {"limit_id": str(limit_id), **_model_payload(payload)}, user=user)


@app.delete("/api/v1/limits/{limit_id}", tags=["Limits"], summary="Delete limit", response_model=StatusResponse, responses=PROTECTED_RESPONSES)
def limits_delete(limit_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(FINANCE_QUEUE, "limits.delete", {"limit_id": str(limit_id)}, user=user)


@app.get("/api/v1/categories", tags=["Categories"], summary="List categories", response_model=CategoriesPageResponse, responses=PROTECTED_RESPONSES)
def categories_list(user: UserContext = Depends(current_user), page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=500)) -> dict:
    return _rpc(FINANCE_QUEUE, "categories.list", {"page": page, "page_size": page_size}, user=user)


@app.post("/api/v1/categories", tags=["Categories"], summary="Create category", response_model=CategoryResponse, responses=PROTECTED_RESPONSES)
def categories_create(payload: CategoryCreateRequest, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(FINANCE_QUEUE, "categories.create", _model_payload(payload), user=user)


@app.get("/api/v1/categories/{category_id}", tags=["Categories"], summary="Get category", response_model=CategoryResponse, responses=PROTECTED_RESPONSES)
def categories_get(category_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(FINANCE_QUEUE, "categories.get", {"category_id": str(category_id)}, user=user)


@app.patch("/api/v1/categories/{category_id}", tags=["Categories"], summary="Update category", response_model=CategoryResponse, responses=PROTECTED_RESPONSES)
def categories_update(category_id: UUID, payload: CategoryUpdateRequest, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(FINANCE_QUEUE, "categories.update", {"category_id": str(category_id), **_model_payload(payload)}, user=user)


@app.delete("/api/v1/categories/{category_id}", tags=["Categories"], summary="Delete category", response_model=StatusResponse, responses=PROTECTED_RESPONSES)
def categories_delete(category_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(FINANCE_QUEUE, "categories.delete", {"category_id": str(category_id)}, user=user)


@app.post(
    "/api/v1/notifications/permission",
    tags=["Notifications"],
    summary="Set notification permission",
    description="Stores the current user's push notification preference.",
    response_model=NotificationPreferenceResponse,
    responses=PROTECTED_RESPONSES,
)
def notification_permission(payload: NotificationPermissionRequest, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(NOTIFICATION_QUEUE, "notifications.permission.set", _model_payload(payload), user=user)


@app.post(
    "/api/v1/notifications/devices",
    tags=["Notifications"],
    summary="Save notification device",
    description="Creates or updates a Firebase-capable device for the current user.",
    response_model=NotificationDeviceResponse,
    responses=PROTECTED_RESPONSES,
)
def notification_device(payload: NotificationDeviceRequest, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(NOTIFICATION_QUEUE, "notifications.devices.save", _model_payload(payload), user=user)


@app.post(
    "/api/v1/notifications/test",
    tags=["Notifications"],
    summary="Send test notification",
    description="Creates a test notification delivery record and sends it when Firebase is configured.",
    response_model=NotificationDeliveryResponse,
    responses=PROTECTED_RESPONSES,
)
def notification_test(payload: NotificationTestRequest, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(NOTIFICATION_QUEUE, "notifications.test.send", _model_payload(payload), user=user)


@app.get(
    "/api/v1/analytics/available-balance",
    tags=["Analytics"],
    summary="Get available balance",
    description="Returns the current user's actual balance plus expected income minus expected expenses for a period.",
    response_model=AnalyticsAvailableBalanceResponse,
    responses=PROTECTED_RESPONSES,
)
def analytics_available_balance(
    user: UserContext = Depends(current_user),
    period_start: date | None = Query(default=None, description="Inclusive period start date."),
    period_end: date | None = Query(default=None, description="Inclusive period end date."),
) -> dict:
    return _rpc(
        ANALYTICS_QUEUE,
        "analytics.available_balance.get",
        {"period_start": _date_or_none(period_start), "period_end": _date_or_none(period_end)},
        user=user,
    )


@app.get(
    "/api/v1/analytics/expected-incomes",
    tags=["Analytics"],
    summary="List expected incomes",
    description="Returns stored expected incomes or derived recurring income candidates for the current user.",
    response_model=ExpectedIncomesPageResponse,
    responses=PROTECTED_RESPONSES,
)
def analytics_expected_incomes(
    user: UserContext = Depends(current_user),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
) -> dict:
    return _rpc(ANALYTICS_QUEUE, "analytics.expected_incomes.list", {"page": page, "page_size": page_size}, user=user)


@app.get(
    "/api/v1/analytics/expected-expenses",
    tags=["Analytics"],
    summary="List expected expenses",
    description="Returns stored expected expenses or active regular expense candidates for the current user.",
    response_model=ExpectedExpensesPageResponse,
    responses=PROTECTED_RESPONSES,
)
def analytics_expected_expenses(
    user: UserContext = Depends(current_user),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
) -> dict:
    return _rpc(ANALYTICS_QUEUE, "analytics.expected_expenses.list", {"page": page, "page_size": page_size}, user=user)


@app.get(
    "/api/v1/groups",
    tags=["Groups"],
    summary="List groups",
    description="Returns family groups owned by or shared with the current user.",
    response_model=GroupsPageResponse,
    responses=PROTECTED_RESPONSES,
)
def groups_list(
    user: UserContext = Depends(current_user),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
) -> dict:
    return _rpc(GROUP_QUEUE, "groups.list", {"page": page, "page_size": page_size}, user=user)


@app.post(
    "/api/v1/groups",
    tags=["Groups"],
    summary="Create group",
    description="Creates a family group and adds the current user as owner.",
    response_model=GroupResponse,
    responses=PROTECTED_RESPONSES,
)
def groups_create(payload: GroupCreateRequest, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(GROUP_QUEUE, "groups.create", _model_payload(payload), user=user)


@app.get(
    "/api/v1/groups/{group_id}",
    tags=["Groups"],
    summary="Get group",
    description="Returns a group visible to the current user.",
    response_model=GroupResponse,
    responses=PROTECTED_RESPONSES,
)
def groups_get(group_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(GROUP_QUEUE, "groups.get", {"group_id": str(group_id)}, user=user)


@app.patch(
    "/api/v1/groups/{group_id}",
    tags=["Groups"],
    summary="Update group",
    description="Updates group metadata. The current user must be the group owner.",
    response_model=GroupResponse,
    responses=PROTECTED_RESPONSES,
)
def groups_update(group_id: UUID, payload: GroupUpdateRequest, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(GROUP_QUEUE, "groups.update", {"group_id": str(group_id), **_model_payload(payload)}, user=user)


@app.delete("/api/v1/groups/{group_id}", tags=["Groups"], summary="Delete group", response_model=StatusResponse, responses=PROTECTED_RESPONSES)
def groups_delete(group_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(GROUP_QUEUE, "groups.delete", {"group_id": str(group_id)}, user=user)


@app.get(
    "/api/v1/groups/{group_id}/budget",
    tags=["Groups"],
    summary="Get group budget",
    description="Aggregates available balance snapshots for active members of a family group.",
    response_model=GroupBudgetResponse,
    responses=PROTECTED_RESPONSES,
)
def groups_budget(group_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(GROUP_QUEUE, "groups.family_budget.get", {"group_id": str(group_id)}, user=user)


@app.get(
    "/api/v1/groups/{group_id}/members",
    tags=["Groups"],
    summary="List group members",
    description="Returns members of a family group visible to the current user.",
    response_model=GroupMembersPageResponse,
    responses=PROTECTED_RESPONSES,
)
def group_members_list(group_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(GROUP_QUEUE, "group_members.list", {"group_id": str(group_id)}, user=user)


@app.post(
    "/api/v1/groups/{group_id}/members",
    tags=["Groups"],
    summary="Add group member",
    description="Adds or reactivates a member. The current user must be the group owner.",
    response_model=GroupMemberResponse,
    responses=PROTECTED_RESPONSES,
)
def group_members_create(group_id: UUID, payload: GroupMemberRequest, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(GROUP_QUEUE, "group_members.create", {"group_id": str(group_id), **_model_payload(payload)}, user=user)


@app.patch(
    "/api/v1/groups/{group_id}/members/{member_id}",
    tags=["Groups"],
    summary="Update group member",
    description="Updates a group member role or status. The current user must be the group owner.",
    response_model=GroupMemberResponse,
    responses=PROTECTED_RESPONSES,
)
def group_members_update(group_id: UUID, member_id: UUID, payload: GroupMemberUpdateRequest, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(GROUP_QUEUE, "group_members.update", {"group_id": str(group_id), "member_id": str(member_id), **_model_payload(payload)}, user=user)


@app.delete("/api/v1/groups/{group_id}/members/{member_id}", tags=["Groups"], summary="Remove group member", response_model=StatusResponse, responses=PROTECTED_RESPONSES)
def group_members_delete(group_id: UUID, member_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(GROUP_QUEUE, "group_members.delete", {"group_id": str(group_id), "member_id": str(member_id)}, user=user)


@app.get(
    "/api/v1/groups/{group_id}/invitations",
    tags=["Groups"],
    summary="List group invitations",
    description="Returns invitations for a family group visible to the current user.",
    response_model=GroupInvitationsPageResponse,
    responses=PROTECTED_RESPONSES,
)
def group_invitations_list(group_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(GROUP_QUEUE, "group_invitations.list", {"group_id": str(group_id)}, user=user)


@app.post(
    "/api/v1/groups/{group_id}/invitations",
    tags=["Groups"],
    summary="Create group invitation",
    description="Creates an invitation for a family group. The current user must be the group owner.",
    response_model=GroupInvitationResponse,
    responses=PROTECTED_RESPONSES,
)
def group_invitations_create(group_id: UUID, payload: GroupInvitationRequest, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(GROUP_QUEUE, "group_invitations.create", {"group_id": str(group_id), **_model_payload(payload)}, user=user)


@app.patch(
    "/api/v1/groups/{group_id}/invitations/{invitation_id}",
    tags=["Groups"],
    summary="Update group invitation",
    description="Updates invitation status, message, or expiration. The current user must be the group owner.",
    response_model=GroupInvitationResponse,
    responses=PROTECTED_RESPONSES,
)
def group_invitations_update(group_id: UUID, invitation_id: UUID, payload: GroupInvitationUpdateRequest, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(GROUP_QUEUE, "group_invitations.update", {"group_id": str(group_id), "invitation_id": str(invitation_id), **_model_payload(payload)}, user=user)


@app.delete("/api/v1/groups/{group_id}/invitations/{invitation_id}", tags=["Groups"], summary="Delete group invitation", response_model=StatusResponse, responses=PROTECTED_RESPONSES)
def group_invitations_delete(group_id: UUID, invitation_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(GROUP_QUEUE, "group_invitations.delete", {"group_id": str(group_id), "invitation_id": str(invitation_id)}, user=user)


@app.post(
    "/api/v1/group-invitations/{invitation_id}/accept",
    tags=["Groups"],
    summary="Accept group invitation",
    description="Accepts an invitation addressed to the current user and adds them to the group.",
    response_model=GroupInvitationResponse,
    responses=PROTECTED_RESPONSES,
)
def group_invitation_accept(invitation_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(GROUP_QUEUE, "group_invitations.accept", {"invitation_id": str(invitation_id)}, user=user)


@app.post(
    "/api/v1/group-invitations/{invitation_id}/decline",
    tags=["Groups"],
    summary="Decline group invitation",
    description="Declines an invitation addressed to the current user.",
    response_model=GroupInvitationResponse,
    responses=PROTECTED_RESPONSES,
)
def group_invitation_decline(invitation_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(GROUP_QUEUE, "group_invitations.decline", {"invitation_id": str(invitation_id)}, user=user)


@app.get(
    "/api/v1/chats/recommendations",
    tags=["Chats"],
    summary="Get initial recommendations",
    description="Returns persisted or derived initial assistant recommendations for the current user.",
    response_model=AgentRecommendationsPageResponse,
    responses=PROTECTED_RESPONSES,
)
def chat_recommendations(user: UserContext = Depends(current_user)) -> dict:
    return _rpc(CHAT_QUEUE, "chat.recommendations.initial.get", {}, user=user)


@app.get(
    "/api/v1/chats",
    tags=["Chats"],
    summary="List chats",
    description="Returns chats owned by the current user.",
    response_model=ChatsPageResponse,
    responses=PROTECTED_RESPONSES,
)
def chats_list(
    user: UserContext = Depends(current_user),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
) -> dict:
    return _rpc(CHAT_QUEUE, "chats.list", {"page": page, "page_size": page_size}, user=user)


@app.post(
    "/api/v1/chats",
    tags=["Chats"],
    summary="Create chat",
    description="Creates a new chat for the current user.",
    response_model=ChatResponse,
    responses=PROTECTED_RESPONSES,
)
def chats_create(payload: ChatCreateRequest, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(CHAT_QUEUE, "chats.create", _model_payload(payload), user=user)


@app.get(
    "/api/v1/chats/{chat_id}",
    tags=["Chats"],
    summary="Get chat",
    description="Returns a chat owned by the current user.",
    response_model=ChatResponse,
    responses=PROTECTED_RESPONSES,
)
def chats_get(chat_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(CHAT_QUEUE, "chats.get", {"chat_id": str(chat_id)}, user=user)


@app.patch(
    "/api/v1/chats/{chat_id}",
    tags=["Chats"],
    summary="Update chat",
    description="Updates a chat owned by the current user.",
    response_model=ChatResponse,
    responses=PROTECTED_RESPONSES,
)
def chats_update(chat_id: UUID, payload: ChatUpdateRequest, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(CHAT_QUEUE, "chats.update", {"chat_id": str(chat_id), **_model_payload(payload)}, user=user)


@app.delete("/api/v1/chats/{chat_id}", tags=["Chats"], summary="Delete chat", response_model=StatusResponse, responses=PROTECTED_RESPONSES)
def chats_delete(chat_id: UUID, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(CHAT_QUEUE, "chats.delete", {"chat_id": str(chat_id)}, user=user)


@app.get(
    "/api/v1/chats/{chat_id}/messages",
    tags=["Chats"],
    summary="List chat messages",
    description="Returns messages for a chat owned by the current user.",
    response_model=ChatMessagesPageResponse,
    responses=PROTECTED_RESPONSES,
)
def chat_messages_list(
    chat_id: UUID,
    user: UserContext = Depends(current_user),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
) -> dict:
    return _rpc(CHAT_QUEUE, "chat_messages.list", {"chat_id": str(chat_id), "page": page, "page_size": page_size}, user=user)


@app.post(
    "/api/v1/chats/{chat_id}/messages",
    tags=["Chats"],
    summary="Create chat message",
    description="Creates a user message in a chat owned by the current user.",
    response_model=ChatMessageResponse,
    responses=PROTECTED_RESPONSES,
)
def chat_messages_create(chat_id: UUID, payload: ChatMessageCreateRequest, user: UserContext = Depends(current_user)) -> dict:
    return _rpc(CHAT_QUEUE, "chat_messages.create", {"chat_id": str(chat_id), **_model_payload(payload)}, user=user)


def _rpc(
    queue_name: str,
    message_type: str,
    payload: dict[str, Any],
    *,
    user: UserContext | None = None,
    timeout_seconds: float | None = None,
    allow_status: set[int] | None = None,
) -> dict:
    reply = bus.request(
        queue_name,
        message_type,
        payload,
        user=user,
        timeout_seconds=timeout_seconds or settings.rpc_timeout_seconds,
    )
    if reply.get("ok"):
        return reply.get("payload") or {}
    status_code = int(reply.get("status_code") or 502)
    if allow_status and status_code in allow_status:
        return {}
    detail = reply.get("error") or "Internal service error"
    if status_code == 504:
        detail = "Internal service timeout"
    elif status_code >= 500:
        detail = "Internal service error"
    raise HTTPException(status_code=status_code, detail=detail)


def _model_payload(model) -> dict[str, Any]:
    return model.model_dump(mode="json", exclude_none=True)


def _date_or_none(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _params_to_payload(params: list[tuple[str, str]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in params:
        if key in payload:
            if not isinstance(payload[key], list):
                payload[key] = [payload[key]]
            payload[key].append(value)
        else:
            payload[key] = value
    return payload


def _transaction_query_params(
    *,
    date_from: date | None,
    date_to: date | None,
    categories: list[str] | None,
    mcc: list[str] | None,
    transaction_type: Literal["income", "expense"] | None,
    status_filter: str | None,
    has_cashback: bool | None,
    card_last4: list[str] | None,
    page: int,
    page_size: int,
) -> list[tuple[str, str]]:
    params: list[tuple[str, str]] = [("page", str(page)), ("page_size", str(page_size))]
    if date_from is not None:
        params.append(("date_from", date_from.isoformat()))
    if date_to is not None:
        params.append(("date_to", date_to.isoformat()))
    if status_filter:
        params.append(("status", status_filter))
    if transaction_type:
        params.append(("type", transaction_type))
    if has_cashback is not None:
        params.append(("has_cashback", str(has_cashback).lower()))
    for value in categories or []:
        params.append(("categories", value))
    for value in mcc or []:
        params.append(("mcc", value))
    for value in card_last4 or []:
        params.append(("card_last4", value))
    return params
