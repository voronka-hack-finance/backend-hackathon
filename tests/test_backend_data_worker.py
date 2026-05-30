from __future__ import annotations

import asyncio
import json
import socket
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from services.backend_data_worker.app.assembler import assemble_response, transactions_items_count
from services.backend_data_worker.app.fetcher.mock import MockDataFetcher
from services.backend_data_worker.app.fetcher.rpc import RpcDataFetcher
from services.backend_data_worker.app.mock_data import build_mock_dataset
from services.backend_data_worker.app.processor import process_request_payload
from services.backend_data_worker.app.schemas import BackendDataRequest, RESPONSE_MESSAGE_TYPE
from services.backend_data_worker.app.validator import RequestValidationError, parse_request_body


def _valid_request(**overrides) -> dict:
    payload = {
        "schema_version": "1.0",
        "message_type": "ai.backend_data.request",
        "correlation_id": str(uuid4()),
        "request_id": "req-1",
        "workflow_run_id": "wf-1",
        "user_id": "550e8400-e29b-41d4-a716-446655440000",
        "chat_id": "chat-1",
        "data_types": ["transactions", "user_context", "category_profiles"],
        "period": {"start_date": "2026-05-01", "end_date": "2026-05-31"},
        "comparison_period": {"start_date": "2026-04-01", "end_date": "2026-04-30"},
        "transaction_filters": {
            "direction": "expense",
            "categories": ["Фастфуд"],
            "mcc": [],
            "account_id": None,
            "card_last4": None,
        },
    }
    payload.update(overrides)
    return payload


def test_parse_request_ok():
    raw = _valid_request()
    request = parse_request_body(raw)
    assert request.correlation_id == raw["correlation_id"]
    assert request.user_id == raw["user_id"]
    assert request.data_types == raw["data_types"]


def test_parse_request_rejects_bad_message_type():
    raw = _valid_request(message_type="wrong.type")
    with pytest.raises(RequestValidationError) as exc:
        parse_request_body(raw)
    assert exc.value.code == "INVALID_REQUEST"
    assert exc.value.correlation_id == raw["correlation_id"]


def test_parse_request_rejects_missing_correlation_id():
    raw = _valid_request()
    raw.pop("correlation_id")
    with pytest.raises(RequestValidationError) as exc:
        parse_request_body(raw)
    assert exc.value.code == "MISSING_CORRELATION_ID"


def test_assembler_filters_data_types():
    request = BackendDataRequest.model_validate(_valid_request(data_types=["transactions"]))
    dataset = build_mock_dataset(request)
    response = assemble_response(
        request=request,
        dataset=dataset,
        status="success",
        errors=[],
    )
    assert set(response.data.keys()) == {"transactions"}
    assert isinstance(response.data["transactions"], dict)
    assert isinstance(response.data["transactions"]["items"], list)


def test_process_request_preserves_correlation_id():
    raw = _valid_request(data_types=["transactions"])
    response = process_request_payload(raw, fetcher=MockDataFetcher())
    assert response.correlation_id == raw["correlation_id"]
    assert response.message_type == RESPONSE_MESSAGE_TYPE
    assert response.status == "success"
    assert "transactions" in response.data
    assert transactions_items_count(response.data) >= 1


def test_process_request_error_response_is_publishable():
    response = process_request_payload({"message_type": "broken"})
    assert response.status == "error"
    assert response.correlation_id == "unknown"
    assert response.errors[0].code == "MISSING_CORRELATION_ID"
    json.dumps(response.to_publish_dict())


def test_process_request_partial_for_optional_data_types():
    raw = _valid_request(data_types=["accounts", "transactions"])
    response = process_request_payload(raw, fetcher=MockDataFetcher())
    assert response.status == "partial"
    assert "accounts" in response.data
    assert "transactions" in response.data
    assert any(error.code == "NOT_IMPLEMENTED_MVP" for error in response.errors)


def test_processor_invalid_user_id_error():
    raw = _valid_request(user_id="user_123", data_types=["transactions"])
    response = process_request_payload(raw, fetcher=MockDataFetcher())
    assert response.status == "error"
    assert response.errors[0].code == "USER_ID_INVALID"
    assert response.data["transactions"] == {"items": []}


def test_processor_rpc_transactions_pagination_and_filters():
    captured: list[dict[str, Any]] = []

    def handler(queue: str, message_type: str, payload: dict, *, user=None, timeout_seconds=30.0) -> dict:
        captured.append({"queue": queue, "message_type": message_type, "payload": payload, "user_id": user.id})
        page = payload.get("page", 1)
        if page == 1:
            return {
                "ok": True,
                "payload": {
                    "items": [{"id": "tx-1", "type": "expense", "category_name": "Фастфуд"}],
                    "pagination": {"page": 1, "page_size": 500, "total": 1},
                },
            }
        return {"ok": True, "payload": {"items": [], "pagination": {"page": page, "page_size": 500, "total": 1}}}

    bus = MagicMock()
    bus.request.side_effect = handler
    fetcher = RpcDataFetcher(
        rabbitmq_url="amqp://guest:guest@localhost:5672/%2F",
        finance_queue="finance-service",
        analytics_queue="analytics-service",
        rpc_timeout_seconds=5,
        bus=bus,
    )
    raw = _valid_request(data_types=["transactions"])
    response = process_request_payload(raw, fetcher=fetcher)

    assert response.status == "success"
    assert response.data["transactions"]["items"][0]["id"] == "tx-1"
    assert len(captured) == 1
    tx_call = captured[0]
    assert tx_call["queue"] == "finance-service"
    assert tx_call["message_type"] == "transactions.list"
    assert tx_call["payload"]["type"] == "expense"
    assert tx_call["payload"]["categories"] == ["Фастфуд"]
    assert tx_call["payload"]["date_from"] == "2026-05-01"
    assert tx_call["payload"]["date_to"] == "2026-05-31"
    assert tx_call["user_id"] == raw["user_id"]


def test_processor_empty_transactions_partial():
    bus = MagicMock()
    bus.request.return_value = {
        "ok": True,
        "payload": {"items": [], "pagination": {"page": 1, "page_size": 500, "total": 0}},
    }
    fetcher = RpcDataFetcher(
        rabbitmq_url="amqp://guest:guest@localhost:5672/%2F",
        finance_queue="finance-service",
        analytics_queue="analytics-service",
        rpc_timeout_seconds=5,
        bus=bus,
    )
    raw = _valid_request(data_types=["transactions"])
    response = process_request_payload(raw, fetcher=fetcher)

    assert response.status == "partial"
    assert response.data["transactions"]["items"] == []
    assert any(error.code == "TRANSACTIONS_EMPTY" for error in response.errors)


def test_processor_rpc_failure_error():
    bus = MagicMock()
    bus.request.return_value = {"ok": False, "status_code": 502, "error": "finance unavailable"}
    fetcher = RpcDataFetcher(
        rabbitmq_url="amqp://guest:guest@localhost:5672/%2F",
        finance_queue="finance-service",
        analytics_queue="analytics-service",
        rpc_timeout_seconds=5,
        bus=bus,
    )
    raw = _valid_request(data_types=["transactions"])
    response = process_request_payload(raw, fetcher=fetcher)

    assert response.status == "error"
    assert response.data["transactions"]["items"] == []
    assert any(error.code == "FINANCE_RPC_ERROR" for error in response.errors)


def _rabbitmq_available(host: str = "localhost", port: int = 5673) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


@pytest.mark.asyncio
@pytest.mark.skipif(not _rabbitmq_available(), reason="RabbitMQ is not available on localhost:5673")
async def test_integration_request_reply_roundtrip(monkeypatch):
    aio_pika = pytest.importorskip("aio_pika")
    from aio_pika import DeliveryMode, Message as AioMessage

    from services.backend_data_worker.app.consumer import AiBackendDataConsumer

    monkeypatch.setattr(
        "services.backend_data_worker.app.processor.get_fetcher",
        lambda: MockDataFetcher(),
    )

    suffix = uuid4().hex[:8]
    request_queue = f"test.ai.backend.data.requests.{suffix}"
    response_queue = f"test.ai.context_builder.backend_data.responses.{suffix}"

    worker = AiBackendDataConsumer(
        rabbitmq_url="amqp://guest:guest@localhost:5673/",
        request_queue=request_queue,
        response_queue=response_queue,
    )
    worker.start()
    try:
        await asyncio.sleep(1)
        correlation_id = str(uuid4())
        request_body = _valid_request(correlation_id=correlation_id, data_types=["transactions"])
        connection = await aio_pika.connect_robust("amqp://guest:guest@localhost:5673/")
        async with connection:
            channel = await connection.channel()
            response_queue_obj = await channel.declare_queue(response_queue, durable=True)
            await channel.declare_queue(request_queue, durable=True)
            await channel.default_exchange.publish(
                AioMessage(
                    body=json.dumps(request_body).encode("utf-8"),
                    content_type="application/json",
                    delivery_mode=DeliveryMode.PERSISTENT,
                    correlation_id=correlation_id,
                ),
                routing_key=request_queue,
            )

            async def wait_for_response() -> dict:
                async with response_queue_obj.iterator() as queue_iter:
                    async for message in queue_iter:
                        async with message.process():
                            payload = json.loads(message.body.decode("utf-8"))
                            if payload.get("correlation_id") == correlation_id:
                                return payload
                raise AssertionError("No response received")

            response_payload = await asyncio.wait_for(wait_for_response(), timeout=10)

        assert response_payload["message_type"] == RESPONSE_MESSAGE_TYPE
        assert response_payload["correlation_id"] == correlation_id
        assert response_payload["status"] in {"success", "partial", "error"}
        assert isinstance(response_payload["data"]["transactions"]["items"], list)
    finally:
        worker.stop()
