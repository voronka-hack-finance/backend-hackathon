from uuid import UUID

import pytest

from common.messaging import MessageError
from services.finance_service.app.handlers import _validate_owned_references


class FakeSession:
    def __init__(self, exists: bool) -> None:
        self.exists = exists

    def scalar(self, _statement):
        return UUID("00000000-0000-0000-0000-000000000999") if self.exists else None


def test_missing_goal_account_reference_returns_message_error():
    with pytest.raises(MessageError) as exc:
        _validate_owned_references(
            FakeSession(exists=False),
            UUID("00000000-0000-0000-0000-000000000001"),
            {"account_id": "00000000-0000-0000-0000-000000000002"},
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Account not found"


def test_existing_reference_passes_validation():
    _validate_owned_references(
        FakeSession(exists=True),
        UUID("00000000-0000-0000-0000-000000000001"),
        {"account_id": "00000000-0000-0000-0000-000000000002"},
    )
