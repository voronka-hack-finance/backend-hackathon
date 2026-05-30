from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def normalize_private_key(raw: str) -> str:
    """Accept PEM or raw key body; env often stores \\n escapes."""
    value = raw.strip().replace("\\n", "\n")
    if "BEGIN PRIVATE KEY" in value:
        return value
    return f"-----BEGIN PRIVATE KEY-----\n{value}\n-----END PRIVATE KEY-----\n"


def build_service_account_dict(
    *,
    project_id: str,
    client_email: str,
    private_key: str,
    private_key_id: str | None = None,
) -> dict[str, Any]:
    return {
        "type": "service_account",
        "project_id": project_id,
        "private_key_id": private_key_id or "firebase-private-key-id",
        "private_key": normalize_private_key(private_key),
        "client_email": client_email,
        "client_id": "000000000000000000000",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{client_email.replace('@', '%40')}",
        "universe_domain": "googleapis.com",
    }


def load_service_account_credentials(
    *,
    credentials_json: str | None,
    credentials_path: str | None,
    project_id: str | None,
    client_email: str | None,
    private_key: str | None,
    private_key_id: str | None = None,
) -> dict[str, Any] | None:
    if credentials_json:
        return json.loads(credentials_json)
    if credentials_path:
        path = Path(credentials_path)
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    if project_id and client_email and private_key:
        return build_service_account_dict(
            project_id=project_id,
            client_email=client_email,
            private_key=private_key,
            private_key_id=private_key_id,
        )
    return None
