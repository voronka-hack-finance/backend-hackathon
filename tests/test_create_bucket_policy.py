import json

import pytest

from services.create_bucket_service.app.main import _apply_bucket_policy, _readonly_policy


class FakeMinio:
    def __init__(self) -> None:
        self.deleted = []
        self.policies = []

    def delete_bucket_policy(self, bucket_name: str) -> None:
        self.deleted.append(bucket_name)

    def set_bucket_policy(self, bucket_name: str, policy: str) -> None:
        self.policies.append((bucket_name, json.loads(policy)))


def test_private_policy_removes_anonymous_bucket_policy():
    client = FakeMinio()

    _apply_bucket_policy(client, "uploaded-files", "private")

    assert client.deleted == ["uploaded-files"]
    assert client.policies == []


def test_readonly_policy_allows_only_get_object_for_bucket_objects():
    client = FakeMinio()

    _apply_bucket_policy(client, "uploaded-files", "readonly")

    assert client.deleted == []
    assert len(client.policies) == 1
    bucket_name, policy = client.policies[0]
    assert bucket_name == "uploaded-files"
    assert policy == json.loads(_readonly_policy("uploaded-files"))
    assert policy["Statement"][0]["Action"] == ["s3:GetObject"]
    assert policy["Statement"][0]["Resource"] == ["arn:aws:s3:::uploaded-files/*"]


def test_unknown_bucket_policy_is_rejected():
    with pytest.raises(ValueError, match="UPLOADS_BUCKET_POLICY"):
        _apply_bucket_policy(FakeMinio(), "uploaded-files", "public-write")
