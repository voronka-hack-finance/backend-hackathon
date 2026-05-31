from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"
REQUEST_MESSAGE_TYPE = "ai.backend_data.request"
RESPONSE_MESSAGE_TYPE = "ai.backend_data.response"

SUPPORTED_DATA_TYPES = frozenset(
    {
        "transactions",
        "previous_period_transactions",
        "user_context",
        "category_profiles",
        "accounts",
        "goals",
        "expected_incomes",
        "existing_financial_analysis_result",
    }
)
MVP_FULL_MOCK_DATA_TYPES = frozenset(
    {
        "transactions",
        "previous_period_transactions",
        "user_context",
        "category_profiles",
    }
)
MVP_PARTIAL_DATA_TYPES = frozenset({"accounts", "goals", "expected_incomes"})


class Period(BaseModel):
    start_date: str
    end_date: str


class TransactionFilters(BaseModel):
    direction: Literal["income", "expense", "all"] | None = None
    categories: list[str] = Field(default_factory=list)
    mcc: list[str] = Field(default_factory=list)
    account_id: str | None = None
    card_last4: str | None = None


class BackendDataRequest(BaseModel):
    schema_version: str
    message_type: str
    correlation_id: str
    request_id: str | None = None
    workflow_run_id: str | None = None
    user_id: str
    chat_id: str | None = None
    data_types: list[str] = Field(default_factory=list)
    period: Period | None = None
    comparison_period: Period | None = None
    transaction_filters: TransactionFilters | None = None


class ResponseError(BaseModel):
    code: str
    message: str


class BackendDataResponse(BaseModel):
    schema_version: str = SCHEMA_VERSION
    message_type: str = RESPONSE_MESSAGE_TYPE
    correlation_id: str
    status: Literal["success", "partial", "error"]
    data: dict[str, Any] = Field(default_factory=dict)
    errors: list[ResponseError] = Field(default_factory=list)
    fetch_stats: dict[str, Any] = Field(default_factory=dict)

    def to_publish_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True, exclude={"fetch_stats"})
