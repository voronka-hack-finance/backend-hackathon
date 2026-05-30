from services.gateway.app.main import _transaction_query_params, app


EXPECTED_PUBLIC_PATHS = {
    "/health",
    "/ready",
    "/api/v1/health",
    "/api/v1/auth/register",
    "/api/v1/auth/login",
    "/api/v1/auth/logout",
    "/api/v1/auth/refresh",
    "/api/v1/auth/me",
    "/api/v1/auth/change-password",
    "/api/v1/files",
    "/api/v1/files/{file_id}",
    "/api/v1/imports/{import_id}",
    "/api/v1/imports/{import_id}/errors",
    "/api/v1/transactions",
    "/api/v1/accounts",
    "/api/v1/goals",
    "/api/v1/goals/{goal_id}",
    "/api/v1/limits",
    "/api/v1/limits/{limit_id}",
    "/api/v1/categories",
    "/api/v1/categories/{category_id}",
    "/api/v1/notifications/permission",
    "/api/v1/notifications/devices",
    "/api/v1/notifications/test",
    "/api/v1/analytics/available-balance",
    "/api/v1/analytics/expected-incomes",
    "/api/v1/analytics/expected-expenses",
    "/api/v1/groups",
    "/api/v1/groups/{group_id}",
    "/api/v1/groups/{group_id}/budget",
    "/api/v1/groups/{group_id}/members",
    "/api/v1/groups/{group_id}/members/{member_id}",
    "/api/v1/groups/{group_id}/invitations",
    "/api/v1/groups/{group_id}/invitations/{invitation_id}",
    "/api/v1/group-invitations/{invitation_id}/accept",
    "/api/v1/group-invitations/{invitation_id}/decline",
    "/api/v1/chats/recommendations",
    "/api/v1/chats",
    "/api/v1/chats/{chat_id}",
    "/api/v1/chats/{chat_id}/messages",
}


PROTECTED_PATHS = EXPECTED_PUBLIC_PATHS - {
    "/health",
    "/ready",
    "/api/v1/health",
    "/api/v1/auth/register",
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
}


def test_transactions_openapi_exposes_type_filter_and_bearer_security():
    schema = app.openapi()
    operation = schema["paths"]["/api/v1/transactions"]["get"]

    assert operation["tags"] == ["Transactions"]
    assert operation["security"] == [{"BearerAuth": []}]

    params = {param["name"]: param for param in operation["parameters"]}
    assert "type" in params
    assert params["type"]["schema"]["anyOf"][0]["enum"] == ["income", "expense"]


def test_openapi_exposes_documented_public_paths():
    schema = app.openapi()

    missing = EXPECTED_PUBLIC_PATHS - set(schema["paths"])

    assert missing == set()


def test_openapi_does_not_expose_undocumented_account_mutations():
    schema = app.openapi()

    assert "/api/v1/accounts/{account_id}" not in schema["paths"]
    assert set(schema["paths"]["/api/v1/accounts"]) == {"get"}


def test_protected_openapi_operations_use_bearer_security():
    schema = app.openapi()

    for path in PROTECTED_PATHS:
        for operation in schema["paths"][path].values():
            assert operation["security"] == [{"BearerAuth": []}], path


def test_new_public_groups_have_specific_response_models_and_descriptions():
    schema = app.openapi()
    expected_models = {
        ("/api/v1/files", "get"): "FilesPageResponse",
        ("/api/v1/notifications/permission", "post"): "NotificationPreferenceResponse",
        ("/api/v1/notifications/devices", "post"): "NotificationDeviceResponse",
        ("/api/v1/notifications/test", "post"): "NotificationDeliveryResponse",
        ("/api/v1/analytics/expected-incomes", "get"): "ExpectedIncomesPageResponse",
        ("/api/v1/analytics/expected-expenses", "get"): "ExpectedExpensesPageResponse",
        ("/api/v1/groups", "get"): "GroupsPageResponse",
        ("/api/v1/groups", "post"): "GroupResponse",
        ("/api/v1/groups/{group_id}", "get"): "GroupResponse",
        ("/api/v1/groups/{group_id}", "patch"): "GroupResponse",
        ("/api/v1/groups/{group_id}/budget", "get"): "GroupBudgetResponse",
        ("/api/v1/groups/{group_id}/members", "get"): "GroupMembersPageResponse",
        ("/api/v1/groups/{group_id}/members", "post"): "GroupMemberResponse",
        ("/api/v1/groups/{group_id}/members/{member_id}", "patch"): "GroupMemberResponse",
        ("/api/v1/groups/{group_id}/invitations", "get"): "GroupInvitationsPageResponse",
        ("/api/v1/groups/{group_id}/invitations", "post"): "GroupInvitationResponse",
        ("/api/v1/groups/{group_id}/invitations/{invitation_id}", "patch"): "GroupInvitationResponse",
        ("/api/v1/group-invitations/{invitation_id}/accept", "post"): "GroupInvitationResponse",
        ("/api/v1/group-invitations/{invitation_id}/decline", "post"): "GroupInvitationResponse",
        ("/api/v1/chats/recommendations", "get"): "AgentRecommendationsPageResponse",
        ("/api/v1/chats", "get"): "ChatsPageResponse",
        ("/api/v1/chats", "post"): "ChatResponse",
        ("/api/v1/chats/{chat_id}", "get"): "ChatResponse",
        ("/api/v1/chats/{chat_id}", "patch"): "ChatResponse",
        ("/api/v1/chats/{chat_id}/messages", "get"): "ChatMessagesPageResponse",
        ("/api/v1/chats/{chat_id}/messages", "post"): "ChatMessageResponse",
    }

    for (path, method), model_name in expected_models.items():
        operation = schema["paths"][path][method]
        assert operation.get("description"), f"{method.upper()} {path}"
        assert _response_ref(operation) == f"#/components/schemas/{model_name}", f"{method.upper()} {path}"


def test_mutation_endpoints_have_specific_request_models():
    schema = app.openapi()
    expected_models = {
        ("/api/v1/notifications/permission", "post"): "NotificationPermissionRequest",
        ("/api/v1/notifications/devices", "post"): "NotificationDeviceRequest",
        ("/api/v1/notifications/test", "post"): "NotificationTestRequest",
        ("/api/v1/groups", "post"): "GroupCreateRequest",
        ("/api/v1/groups/{group_id}", "patch"): "GroupUpdateRequest",
        ("/api/v1/groups/{group_id}/members", "post"): "GroupMemberRequest",
        ("/api/v1/groups/{group_id}/members/{member_id}", "patch"): "GroupMemberUpdateRequest",
        ("/api/v1/groups/{group_id}/invitations", "post"): "GroupInvitationRequest",
        ("/api/v1/groups/{group_id}/invitations/{invitation_id}", "patch"): "GroupInvitationUpdateRequest",
        ("/api/v1/chats", "post"): "ChatCreateRequest",
        ("/api/v1/chats/{chat_id}", "patch"): "ChatUpdateRequest",
        ("/api/v1/chats/{chat_id}/messages", "post"): "ChatMessageCreateRequest",
    }

    for (path, method), model_name in expected_models.items():
        operation = schema["paths"][path][method]
        assert _request_ref(operation) == f"#/components/schemas/{model_name}", f"{method.upper()} {path}"


def test_transaction_query_params_forwards_type_alias():
    params = _transaction_query_params(
        date_from=None,
        date_to=None,
        categories=None,
        mcc=None,
        transaction_type="income",
        status_filter=None,
        has_cashback=None,
        card_last4=None,
        page=1,
        page_size=50,
    )

    assert ("type", "income") in params


def _response_ref(operation: dict) -> str:
    return operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]


def _request_ref(operation: dict) -> str:
    return operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
