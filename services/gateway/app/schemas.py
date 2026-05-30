from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class ErrorResponse(BaseModel):
    detail: str | dict | list = Field(description="Error details.")


class HealthResponse(BaseModel):
    status: str = Field(description="Current service status.", examples=["ok"])


class RegisterRequest(BaseModel):
    email: EmailStr = Field(description="User email.", examples=["demo@example.com"])
    password: str = Field(min_length=6, max_length=256, description="User password.", examples=["secret123"])
    display_name: str | None = Field(default=None, description="Optional display name.", examples=["Demo User"])


class LoginRequest(BaseModel):
    email: EmailStr = Field(description="User email.", examples=["demo@example.com"])
    password: str = Field(description="User password.", examples=["secret123"])


class RefreshRequest(BaseModel):
    refresh_token: str = Field(description="Opaque refresh token returned by login.")


class LogoutRequest(BaseModel):
    refresh_token: str | None = Field(default=None, description="Refresh token to revoke.")


class ProfileUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, description="New display name.")


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(description="Current password.")
    new_password: str = Field(min_length=6, max_length=256, description="New password.")


class UserResponse(BaseModel):
    user_id: UUID = Field(description="User identifier.")
    id: UUID | None = Field(default=None, description="Alias for user_id.")
    email: EmailStr = Field(description="User email.")
    display_name: str | None = Field(default=None, description="User display name.")
    created_at: datetime | None = Field(default=None, description="Creation timestamp.")
    updated_at: datetime | None = Field(default=None, description="Last update timestamp.")


class RegisterResponse(UserResponse):
    pass


class TokenResponse(BaseModel):
    access_token: str = Field(description="JWT access token for Bearer authentication.")
    refresh_token: str | None = Field(default=None, description="Opaque refresh token.")
    token_type: Literal["bearer"] = Field(default="bearer", description="Token type.")


class StatusResponse(BaseModel):
    status: str = Field(description="Operation status.", examples=["ok"])


class UploadResponse(BaseModel):
    file_id: UUID = Field(description="Stored source file identifier.")
    import_id: UUID = Field(description="Created import job identifier.")
    status: str = Field(description="Current import status.", examples=["queued"])


class FileResponse(BaseModel):
    id: UUID = Field(description="File identifier.")
    original_filename: str = Field(description="Original uploaded filename.")
    content_type: str | None = Field(default=None, description="MIME type.")
    size_bytes: int = Field(description="File size in bytes.")
    sha256: str = Field(description="SHA-256 hash of the original file.")
    status: str = Field(description="File lifecycle status.")
    created_at: datetime = Field(description="Creation timestamp.")
    updated_at: datetime = Field(description="Last update timestamp.")


class FilesPageResponse(BaseModel):
    items: list[FileResponse] = Field(description="Uploaded files owned by the current user.")
    pagination: PaginationResponse


class FileUpdateRequest(BaseModel):
    status: str | None = Field(default=None, description="File status override.")


class ImportStatusResponse(BaseModel):
    import_id: UUID = Field(description="Import job identifier.")
    file_id: UUID = Field(description="Source file identifier.")
    status: Literal["queued", "running", "completed", "failed", "partially_completed"] = Field(
        description="Import processing status."
    )
    total_rows: int = Field(description="Non-empty source rows in matching sheets.")
    parsed_rows: int = Field(description="Successfully parsed rows.")
    failed_rows: int = Field(description="Rows with parser errors.")
    started_at: datetime | None = Field(default=None, description="Processing start timestamp.")
    finished_at: datetime | None = Field(default=None, description="Processing finish timestamp.")
    error_message: str | None = Field(default=None, description="Import-level error message.")


class ImportErrorItem(BaseModel):
    sheet_name: str | None = Field(default=None, description="Excel sheet name.")
    row_number: int | None = Field(default=None, description="Source row number.")
    column_name: str | None = Field(default=None, description="Column with a parsing problem.")
    raw_value: str | None = Field(default=None, description="Original value.")
    error_code: str = Field(description="Machine-readable error code.")
    message: str = Field(description="Human-readable error message.")


class ImportErrorsResponse(BaseModel):
    items: list[ImportErrorItem] = Field(description="Import parser errors.")


class TransactionResponse(BaseModel):
    id: UUID = Field(description="Transaction identifier.")
    user_id: UUID | None = Field(default=None, description="Owner user identifier.")
    account_id: UUID | None = Field(default=None, description="Linked account identifier.")
    category_id: UUID | None = Field(default=None, description="Linked category identifier.")
    import_id: UUID = Field(description="Source import identifier.")
    source_file_id: UUID = Field(description="Source file identifier.")
    source_sheet: str = Field(description="Source Excel sheet name.")
    source_row_number: int = Field(description="Source Excel row number.")
    type: Literal["income", "expense"] = Field(description="Transaction direction.")
    operation_at: datetime = Field(description="Operation timestamp.")
    payment_at: datetime | None = Field(default=None, description="Payment timestamp.")
    card_mask: str | None = Field(default=None, description="Source card mask.")
    card_last4: str | None = Field(default=None, description="Card last four digits.")
    status: str | None = Field(default=None, description="Source operation status.")
    operation_amount: str = Field(description="Operation amount as a decimal string.")
    operation_currency: str | None = Field(default=None, description="Operation currency.")
    payment_amount: str | None = Field(default=None, description="Payment amount as a decimal string.")
    payment_currency: str | None = Field(default=None, description="Payment currency.")
    cashback_amount: str | None = Field(default=None, description="Cashback amount as a decimal string.")
    category_name: str | None = Field(default=None, description="Source category name.")
    mcc: str | None = Field(default=None, description="Normalized MCC.")
    description: str | None = Field(default=None, description="Source transaction description.")
    bonus_amount: str | None = Field(default=None, description="Bonus amount as a decimal string.")
    investment_rounding_amount: str | None = Field(default=None, description="Investment rounding amount.")
    rounded_operation_amount: str | None = Field(default=None, description="Rounded operation amount.")
    dedupe_key: str = Field(description="Import dedupe key.")
    raw_payload: dict[str, str | None] = Field(description="All original source columns.")
    created_at: datetime = Field(description="Creation timestamp.")
    updated_at: datetime = Field(description="Last update timestamp.")


class PaginationResponse(BaseModel):
    page: int = Field(ge=1, description="Current page.")
    page_size: int = Field(ge=1, le=500, description="Page size.")
    total: int = Field(ge=0, description="Total item count for filters.")


class TransactionsPageResponse(BaseModel):
    items: list[TransactionResponse] = Field(description="Current user's transactions.")
    pagination: PaginationResponse


class AccountResponse(BaseModel):
    id: UUID
    owner_user_id: UUID
    family_group_id: UUID | None = None
    bank_source: str | None = None
    display_name: str
    account_type: str
    currency: str
    card_last4: str | None = None
    initial_balance: str
    current_balance: str = Field(description="Initial balance plus linked transaction amounts.")
    is_archived: bool
    created_at: datetime
    updated_at: datetime


class AccountCreateRequest(BaseModel):
    display_name: str = Field(description="Account display name.")
    account_type: str = Field(default="card", description="Account type.")
    currency: str = Field(default="RUB", description="Account currency.")
    card_last4: str | None = Field(default=None, description="Card last four digits.")
    bank_source: str | None = Field(default=None, description="Source bank name.")
    initial_balance: str = Field(default="0", description="Initial balance as a decimal string.")


class AccountUpdateRequest(BaseModel):
    display_name: str | None = None
    account_type: str | None = None
    currency: str | None = None
    card_last4: str | None = None
    bank_source: str | None = None
    initial_balance: str | None = None
    is_archived: bool | None = None


class CategoryResponse(BaseModel):
    id: UUID
    account_id: UUID | None = None
    created_by_user_id: UUID
    name: str
    description: str | None = None
    icon_key: str | None = None
    is_archived: bool
    created_at: datetime
    updated_at: datetime


class CategoryCreateRequest(BaseModel):
    name: str = Field(description="Category name.")
    account_id: UUID | None = Field(default=None, description="Optional account scope.")
    description: str | None = None
    icon_key: str | None = None


class CategoryUpdateRequest(BaseModel):
    name: str | None = None
    account_id: UUID | None = None
    description: str | None = None
    icon_key: str | None = None
    is_archived: bool | None = None


class LimitResponse(BaseModel):
    id: UUID
    account_id: UUID | None = None
    category_id: UUID | None = None
    owner_user_id: UUID
    limit_amount: str
    currency: str
    period_days: int
    period_started_at: datetime
    is_active: bool
    created_at: datetime
    updated_at: datetime


class LimitCreateRequest(BaseModel):
    limit_amount: str = Field(description="Limit amount as a decimal string.")
    account_id: UUID | None = None
    category_id: UUID | None = None
    currency: str = "RUB"
    period_days: int = Field(default=30, ge=1)
    period_started_at: datetime | None = None


class LimitUpdateRequest(BaseModel):
    limit_amount: str | None = None
    account_id: UUID | None = None
    category_id: UUID | None = None
    currency: str | None = None
    period_days: int | None = Field(default=None, ge=1)
    period_started_at: datetime | None = None
    is_active: bool | None = None


class GoalResponse(BaseModel):
    id: UUID
    account_id: UUID | None = None
    owner_user_id: UUID
    title: str
    description: str | None = None
    target_amount: str
    current_amount: str
    currency: str
    target_date: date | None = None
    status: str
    created_at: datetime
    updated_at: datetime


class GoalCreateRequest(BaseModel):
    title: str
    target_amount: str = Field(description="Target amount as a decimal string.")
    account_id: UUID | None = None
    description: str | None = None
    current_amount: str = "0"
    currency: str = "RUB"
    target_date: date | None = None


class GoalUpdateRequest(BaseModel):
    title: str | None = None
    target_amount: str | None = None
    account_id: UUID | None = None
    description: str | None = None
    current_amount: str | None = None
    currency: str | None = None
    target_date: date | None = None
    status: str | None = None


class AccountsPageResponse(BaseModel):
    items: list[AccountResponse]
    pagination: PaginationResponse


class CategoriesPageResponse(BaseModel):
    items: list[CategoryResponse]
    pagination: PaginationResponse


class LimitsPageResponse(BaseModel):
    items: list[LimitResponse]
    pagination: PaginationResponse


class GoalsPageResponse(BaseModel):
    items: list[GoalResponse]
    pagination: PaginationResponse


class NotificationPermissionRequest(BaseModel):
    push_enabled: bool = Field(description="Whether push notifications are enabled.")


class NotificationDeviceRequest(BaseModel):
    device_id: str = Field(description="Client device identifier.")
    platform: str | None = Field(default=None, description="Device platform.")
    firebase_token: str | None = Field(default=None, description="Firebase token.")


class NotificationTestRequest(BaseModel):
    title: str = Field(default="Test notification")
    body: str = Field(default="Notification channel is configured.")


class NotificationPreferenceResponse(BaseModel):
    id: UUID = Field(description="Notification preference identifier.")
    user_id: UUID = Field(description="Owner user identifier.")
    push_enabled: bool = Field(description="Whether push notifications are enabled.")
    updated_at: datetime = Field(description="Last preference update timestamp.")


class NotificationDeviceResponse(BaseModel):
    id: UUID = Field(description="Notification device identifier.")
    user_id: UUID = Field(description="Owner user identifier.")
    device_id: str = Field(description="Client device identifier.")
    platform: str | None = Field(default=None, description="Device platform.")
    firebase_token: str | None = Field(default=None, description="Stored Firebase token.")
    is_active: bool = Field(description="Whether the device is active for sends.")
    created_at: datetime = Field(description="Creation timestamp.")
    updated_at: datetime = Field(description="Last update timestamp.")


class NotificationDevicesPageResponse(BaseModel):
    items: list[NotificationDeviceResponse]
    pagination: PaginationResponse


class NotificationDeliveryResponse(BaseModel):
    id: UUID = Field(description="Notification delivery identifier.")
    user_id: UUID = Field(description="Recipient user identifier.")
    reminder_id: UUID | None = Field(default=None, description="Linked reminder identifier.")
    notification_type: str = Field(description="Notification type.")
    status: str = Field(description="Gateway-level result status.")
    error_message: str | None = Field(default=None, description="Delivery error message.")
    created_at: datetime = Field(description="Creation timestamp.")
    sent_at: datetime | None = Field(default=None, description="Send timestamp when delivered.")


class AnalyticsAvailableBalanceResponse(BaseModel):
    period_start: date
    period_end: date
    actual_balance: str
    expected_income_total: str
    expected_expense_total: str
    available_amount: str
    currency: str
    calculated_at: datetime | None = None


class ExpectedIncomeResponse(BaseModel):
    id: UUID | None = Field(default=None, description="Expected income identifier, null for derived rows.")
    account_id: UUID | None = Field(default=None, description="Linked account identifier.")
    source_pattern: str = Field(description="Detected or configured income source pattern.")
    expected_amount: str = Field(description="Expected amount as a decimal string.")
    currency: str = Field(description="Expected income currency.")
    expected_at: date | None = Field(default=None, description="Expected income date.")
    confidence: str | None = Field(default=None, description="Confidence score as a decimal string.")
    created_at: datetime | None = Field(default=None, description="Creation timestamp.")
    updated_at: datetime | None = Field(default=None, description="Last update timestamp.")


class ExpectedExpenseResponse(BaseModel):
    id: UUID | None = Field(default=None, description="Expected expense identifier, null for derived rows.")
    account_id: UUID | None = Field(default=None, description="Linked account identifier.")
    regular_expense_id: UUID | None = Field(default=None, description="Linked regular expense identifier.")
    expected_amount: str = Field(description="Expected amount as a decimal string.")
    currency: str = Field(description="Expected expense currency.")
    expected_at: date | None = Field(default=None, description="Expected expense date.")
    confidence: str | None = Field(default=None, description="Confidence score as a decimal string.")
    created_at: datetime | None = Field(default=None, description="Creation timestamp.")
    updated_at: datetime | None = Field(default=None, description="Last update timestamp.")


class ExpectedIncomesPageResponse(BaseModel):
    items: list[ExpectedIncomeResponse] = Field(description="Expected or derived incomes.")
    pagination: PaginationResponse


class ExpectedExpensesPageResponse(BaseModel):
    items: list[ExpectedExpenseResponse] = Field(description="Expected or derived expenses.")
    pagination: PaginationResponse


class HealthDataGapResponse(BaseModel):
    field: str = Field(description="Metric that could not be calculated exactly.")
    reason: str = Field(description="Human-readable reason for the missing or partial value.")


class FinancialHealthProfileResponse(BaseModel):
    period: str = Field(description="Calendar month in YYYY-MM format.", examples=["2026-05"])
    period_start: date = Field(description="First day of the calculated period.")
    period_end: date = Field(description="Last day of the calculated period.")
    financial_health_score: str = Field(description="Financial health score from 0 to 100 as a decimal string.")
    financial_health_status: str = Field(description="Financial health status label.")
    credit_load_index: str = Field(description="Credit load index from 0 to 100 as a decimal string.")
    credit_load_zone: str = Field(description="Credit load zone: green, yellow, orange, or red.")
    credit_load_index_partial: bool = Field(description="True when credit scoring is calculated with MVP proxy data.")
    total_income: str = Field(description="Income total for the period as a decimal string.")
    total_expenses: str = Field(description="Expense total for the period as a decimal string.")
    net_cashflow: str = Field(description="Income minus expenses as a decimal string.")
    expense_to_income_ratio: str | None = Field(default=None, description="Expense-to-income percentage as a decimal string.")
    savings_rate: str | None = Field(default=None, description="Savings rate percentage as a decimal string.")
    score_components: dict[str, str | None] = Field(description="Normalized component scores used in the final score.")
    weights_applied: dict[str, str] = Field(description="Renormalized component weights actually applied.")
    data_gaps: list[HealthDataGapResponse] = Field(description="Unavailable or partially supported metrics.")
    top_risk_drivers: list[str] = Field(description="Lowest-scoring drivers that need attention.")
    calculated_at: datetime = Field(description="Snapshot calculation timestamp.")

    model_config = {"extra": "allow"}


class FinancialHealthScoreResponse(BaseModel):
    period: str = Field(description="Calendar month in YYYY-MM format.", examples=["2026-05"])
    financial_health_score: str = Field(description="Financial health score from 0 to 100 as a decimal string.")
    financial_health_status: str = Field(description="Financial health status label.")
    credit_load_index: str = Field(description="Credit load index from 0 to 100 as a decimal string.")
    credit_load_zone: str = Field(description="Credit load zone: green, yellow, orange, or red.")
    credit_load_index_partial: bool = Field(description="True when credit scoring is calculated with MVP proxy data.")
    top_risk_drivers: list[str] = Field(description="Lowest-scoring drivers that need attention.")
    data_gaps: list[HealthDataGapResponse] = Field(description="Unavailable or partially supported metrics.")
    calculated_at: datetime = Field(description="Snapshot calculation timestamp.")


class FinancialHealthHistoryItem(BaseModel):
    period: str = Field(description="Calendar month in YYYY-MM format.")
    financial_health_score: str | None = Field(default=None, description="Financial health score as a decimal string.")
    financial_health_status: str = Field(description="Financial health status label.")
    credit_load_index: str | None = Field(default=None, description="Credit load index as a decimal string.")
    credit_load_zone: str = Field(description="Credit load zone label.")
    calculated_at: datetime = Field(description="Snapshot calculation timestamp.")


class FinancialHealthHistoryPageResponse(BaseModel):
    items: list[FinancialHealthHistoryItem] = Field(description="Historical financial health snapshots.")
    pagination: PaginationResponse


class GroupCreateRequest(BaseModel):
    name: str = Field(description="Group display name.")
    description: str | None = Field(default=None, description="Optional group description.")


class GroupUpdateRequest(BaseModel):
    name: str | None = Field(default=None, description="Group display name.")
    description: str | None = Field(default=None, description="Optional group description.")


class GroupMemberRequest(BaseModel):
    user_id: UUID = Field(description="User to add to the group.")
    role: str = Field(default="member", description="Member role.")


class GroupMemberUpdateRequest(BaseModel):
    role: str | None = Field(default=None, description="New member role.")
    status: str | None = Field(default=None, description="New membership status.")


class GroupInvitationRequest(BaseModel):
    invited_email: EmailStr = Field(description="Email address to invite.")
    message: str | None = Field(default=None, description="Optional invitation message.")
    expires_at: datetime | None = Field(default=None, description="Optional expiration timestamp.")


class GroupInvitationUpdateRequest(BaseModel):
    status: str | None = Field(default=None, description="Invitation status.")
    message: str | None = Field(default=None, description="Invitation message.")
    expires_at: datetime | None = Field(default=None, description="Invitation expiration timestamp.")


class GroupResponse(BaseModel):
    id: UUID = Field(description="Group identifier.")
    created_by_user_id: UUID = Field(description="Owner user identifier.")
    name: str = Field(description="Group display name.")
    description: str | None = Field(default=None, description="Group description.")
    created_at: datetime = Field(description="Creation timestamp.")
    updated_at: datetime = Field(description="Last update timestamp.")


class GroupsPageResponse(BaseModel):
    items: list[GroupResponse] = Field(description="Groups visible to the current user.")
    pagination: PaginationResponse


class GroupMemberResponse(BaseModel):
    id: UUID = Field(description="Membership identifier.")
    family_group_id: UUID = Field(description="Group identifier.")
    user_id: UUID = Field(description="Member user identifier.")
    role: str = Field(description="Member role.")
    status: str = Field(description="Membership status.")
    joined_at: datetime | None = Field(default=None, description="Join timestamp.")
    created_at: datetime = Field(description="Creation timestamp.")
    updated_at: datetime = Field(description="Last update timestamp.")


class GroupMembersPageResponse(BaseModel):
    items: list[GroupMemberResponse] = Field(description="Group members.")
    pagination: PaginationResponse | None = Field(default=None, description="Pagination information when available.")


class GroupInvitationResponse(BaseModel):
    id: UUID = Field(description="Invitation identifier.")
    family_group_id: UUID = Field(description="Group identifier.")
    invited_by_user_id: UUID = Field(description="Inviting user identifier.")
    invited_user_id: UUID | None = Field(default=None, description="Resolved invited user identifier.")
    invited_email: EmailStr = Field(description="Invited email address.")
    status: str = Field(description="Invitation status.")
    message: str | None = Field(default=None, description="Invitation message.")
    expires_at: datetime | None = Field(default=None, description="Expiration timestamp.")
    created_at: datetime = Field(description="Creation timestamp.")
    updated_at: datetime = Field(description="Last update timestamp.")


class GroupInvitationsPageResponse(BaseModel):
    items: list[GroupInvitationResponse] = Field(description="Group invitations.")
    pagination: PaginationResponse | None = Field(default=None, description="Pagination information when available.")


class MemberBudgetResponse(BaseModel):
    id: UUID = Field(description="Membership identifier.")
    family_group_id: UUID = Field(description="Group identifier.")
    user_id: UUID = Field(description="Member user identifier.")
    role: str = Field(description="Member role.")
    status: str = Field(description="Membership status.")
    joined_at: datetime | None = Field(default=None, description="Join timestamp.")
    created_at: datetime = Field(description="Creation timestamp.")
    updated_at: datetime = Field(description="Last update timestamp.")
    budget: AnalyticsAvailableBalanceResponse | None = Field(default=None, description="Member budget snapshot.")
    budget_error: str | None = Field(default=None, description="Analytics error for this member.")


class GroupBudgetSummaryResponse(BaseModel):
    currency: str = Field(description="Summary currency.")
    actual_balance: str = Field(description="Aggregated actual balance as a decimal string.")
    expected_income_total: str = Field(description="Aggregated expected income as a decimal string.")
    expected_expense_total: str = Field(description="Aggregated expected expense as a decimal string.")
    available_amount: str = Field(description="Aggregated available amount as a decimal string.")


class GroupBudgetResponse(BaseModel):
    group: GroupResponse = Field(description="Group metadata.")
    members: list[MemberBudgetResponse] = Field(description="Member budget rows.")
    summary: GroupBudgetSummaryResponse = Field(description="Aggregated group budget summary.")


class ChatCreateRequest(BaseModel):
    title: str = Field(default="New chat", description="Chat title.")


class ChatUpdateRequest(BaseModel):
    title: str | None = Field(default=None, description="Chat title.")
    status: str | None = Field(default=None, description="Chat status.")


class ChatMessageCreateRequest(BaseModel):
    content: str = Field(description="User message content.")


class ChatResponse(BaseModel):
    id: UUID = Field(description="Chat identifier.")
    user_id: UUID = Field(description="Owner user identifier.")
    title: str = Field(description="Chat title.")
    status: str = Field(description="Chat status.")
    created_at: datetime = Field(description="Creation timestamp.")
    updated_at: datetime = Field(description="Last update timestamp.")


class ChatsPageResponse(BaseModel):
    items: list[ChatResponse] = Field(description="Current user's chats.")
    pagination: PaginationResponse


class ChatMessageResponse(BaseModel):
    id: UUID = Field(description="Message identifier.")
    chat_id: UUID = Field(description="Chat identifier.")
    user_id: UUID = Field(description="Author user identifier.")
    role: str = Field(description="Message role.")
    content: str = Field(description="Message content.")
    created_at: datetime = Field(description="Creation timestamp.")


class ChatMessagesPageResponse(BaseModel):
    items: list[ChatMessageResponse] = Field(description="Chat messages.")
    pagination: PaginationResponse


class AgentRecommendationResponse(BaseModel):
    id: UUID | None = Field(default=None, description="Recommendation identifier when persisted.")
    chat_id: UUID | None = Field(default=None, description="Linked chat identifier.")
    user_id: UUID | None = Field(default=None, description="Owner user identifier.")
    agent_key: str = Field(description="Recommendation agent key.")
    title: str = Field(description="Recommendation title.")
    content: str = Field(description="Recommendation content.")
    confidence: str | None = Field(default=None, description="Confidence score as a decimal string.")
    created_at: datetime | None = Field(default=None, description="Creation timestamp.")


class AgentRecommendationsPageResponse(BaseModel):
    items: list[AgentRecommendationResponse] = Field(description="Initial agent recommendations.")
    pagination: PaginationResponse | None = Field(default=None, description="Pagination information when available.")
