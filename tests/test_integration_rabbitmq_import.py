import os
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, text

from common.messaging import MessageBus, UserContext


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DOCKER_SMOKE") != "1",
    reason="requires the docker compose stack running on localhost",
)


BASE_URL = os.getenv("GATEWAY_BASE_URL", "http://localhost:8081")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/%2F")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://app:app@localhost:5432/family_budget")
WORKBOOK = Path("family-bugget.xlsx")


def test_gateway_rabbitmq_import_and_scheduler_smoke():
    email = f"integration-smoke{int(time.time() * 1000)}@example.com"
    password = "secret123"

    with httpx.Client(timeout=120.0) as client:
        registered = client.post(
            f"{BASE_URL}/api/v1/auth/register",
            json={"email": email, "password": password, "display_name": "Integration Smoke"},
        )
        registered.raise_for_status()
        user_id = registered.json()["user_id"]

        login = client.post(f"{BASE_URL}/api/v1/auth/login", json={"email": email, "password": password})
        login.raise_for_status()
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        with WORKBOOK.open("rb") as fh:
            upload = client.post(
                f"{BASE_URL}/api/v1/files",
                headers=headers,
                files={
                    "file": (
                        WORKBOOK.name,
                        fh,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
                data={"source_type": "excel_family_budget_v1"},
            )
        upload.raise_for_status()
        import_id = upload.json()["import_id"]

        status_payload = _wait_import(client, headers, import_id)
        transactions = client.get(f"{BASE_URL}/api/v1/transactions?type=income&page_size=1", headers=headers)
        transactions.raise_for_status()
        group = client.post(f"{BASE_URL}/api/v1/groups", headers=headers, json={"name": "Integration group"})
        group.raise_for_status()
        budget = client.get(f"{BASE_URL}/api/v1/groups/{group.json()['id']}/budget", headers=headers)
        budget.raise_for_status()

    bus = MessageBus(RABBITMQ_URL, "pytest-smoke")
    trusted_user = UserContext(id=user_id, email=email)
    scheduled = bus.request(
        "scheduler-service",
        "notifications.schedule",
        {"scheduled_at": datetime.now(UTC).isoformat(), "notification_type": "integration_smoke"},
        user=trusted_user,
        timeout_seconds=30.0,
    )
    due = bus.request("scheduler-service", "reminders.due.scan", {"user_id": user_id}, timeout_seconds=30.0)

    assert status_payload["status"] == "completed"
    assert status_payload["parsed_rows"] == 2728
    assert transactions.json()["pagination"]["total"] == 340
    assert budget.json()["summary"]["currency"] == "RUB"
    assert scheduled["ok"] is True
    assert due["ok"] is True
    assert _delivery_count(user_id) >= 1


def _wait_import(client: httpx.Client, headers: dict[str, str], import_id: str) -> dict:
    status_payload = {}
    for _ in range(90):
        response = client.get(f"{BASE_URL}/api/v1/imports/{import_id}", headers=headers)
        response.raise_for_status()
        status_payload = response.json()
        if status_payload["status"] not in {"queued", "running"}:
            return status_payload
        time.sleep(1)
    return status_payload


def _delivery_count(user_id: str) -> int:
    engine = create_engine(DATABASE_URL)
    with engine.connect() as connection:
        for _ in range(20):
            count = connection.scalar(
                text("select count(*) from notification_deliveries where user_id = :user_id"),
                {"user_id": user_id},
            )
            if count:
                return int(count)
            time.sleep(0.5)
    return 0
