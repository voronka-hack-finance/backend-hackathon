from common.messaging import UserContext, build_envelope


def test_build_envelope_includes_auth_scopes_when_present():
    envelope = build_envelope(
        message_type="transactions.list",
        source="api-gateway-service",
        payload={},
        user=UserContext(id="00000000-0000-0000-0000-000000000001", email="u@example.com", scopes=("finance.read",)),
    )
    assert envelope["auth"] == {"scopes": ["finance.read"]}


def test_build_envelope_omits_auth_when_no_scopes():
    envelope = build_envelope(
        message_type="transactions.list",
        source="api-gateway-service",
        payload={},
        user=UserContext(id="00000000-0000-0000-0000-000000000001"),
    )
    assert "auth" not in envelope
