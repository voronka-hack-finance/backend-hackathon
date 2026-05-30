import json
from pathlib import Path

from common.firebase_config import (
    build_service_account_dict,
    load_service_account_credentials,
    normalize_private_key,
)


def test_normalize_private_key_wraps_raw_body():
    raw = "line1\nline2"
    pem = normalize_private_key(raw)
    assert pem.startswith("-----BEGIN PRIVATE KEY-----")
    assert "line1" in pem
    assert pem.endswith("-----END PRIVATE KEY-----\n")


def test_normalize_private_key_unescapes_env_newlines():
    assert "\\n" not in normalize_private_key("a\\nb").splitlines()[1]


def test_build_service_account_dict_has_required_fields():
    account = build_service_account_dict(
        project_id="proj",
        client_email="svc@proj.iam.gserviceaccount.com",
        private_key="abc",
    )
    assert account["project_id"] == "proj"
    assert account["client_email"] == "svc@proj.iam.gserviceaccount.com"
    assert "BEGIN PRIVATE KEY" in account["private_key"]


def test_load_from_project_id_client_email_private_key():
    account = load_service_account_credentials(
        credentials_json=None,
        credentials_path=None,
        project_id="my-proj",
        client_email="a@b.com",
        private_key="secret",
    )
    assert account is not None
    assert account["project_id"] == "my-proj"


def test_load_from_credentials_json(tmp_path: Path):
    payload = build_service_account_dict(
        project_id="p",
        client_email="e@p.com",
        private_key="k",
    )
    account = load_service_account_credentials(
        credentials_json=json.dumps(payload),
        credentials_path=None,
        project_id=None,
        client_email=None,
        private_key=None,
    )
    assert account["project_id"] == "p"


def test_load_from_credentials_path(tmp_path: Path):
    path = tmp_path / "sa.json"
    path.write_text(
        json.dumps(
            build_service_account_dict(
                project_id="p2",
                client_email="e2@p.com",
                private_key="k2",
            )
        ),
        encoding="utf-8",
    )
    account = load_service_account_credentials(
        credentials_json=None,
        credentials_path=str(path),
        project_id=None,
        client_email=None,
        private_key=None,
    )
    assert account["project_id"] == "p2"


def test_load_returns_none_when_incomplete():
    assert (
        load_service_account_credentials(
            credentials_json=None,
            credentials_path=None,
            project_id="only-id",
            client_email=None,
            private_key=None,
        )
        is None
    )
