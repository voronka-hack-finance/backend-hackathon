from common.messaging import MessageWorker, ok_reply
from common.redis_client import MessageIdempotencyGuard


class FakeRedis:
    def __init__(self) -> None:
        self._keys: set[str] = set()

    def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool | None:
        if nx and key in self._keys:
            return None
        self._keys.add(key)
        return True


def test_idempotency_guard_claims_message_id_once():
    guard = MessageIdempotencyGuard(FakeRedis(), ttl_seconds=60)
    assert guard.claim("msg-1") is True
    assert guard.claim("msg-1") is False
    assert guard.claim("msg-2") is True


def test_worker_skips_duplicate_message_id():
    guard = MessageIdempotencyGuard(FakeRedis(), ttl_seconds=60)
    worker = MessageWorker(
        rabbitmq_url="amqp://guest:guest@localhost:5672/%2F",
        queue_name="sample-service",
        service_name="sample-service",
        handlers={"tasks.echo": lambda payload, envelope: {"echo": payload}},
        idempotency_guard=guard,
    )

    class FakeMessage:
        correlation_id = "corr-dup"
        reply_to = None
        body = b'{"type":"tasks.echo","message_id":"dup-1","payload":{"x":1}}'

    first = worker._handle_message(FakeMessage())
    second = worker._handle_message(FakeMessage())

    assert first["ok"] is True
    assert first["payload"] == {"echo": {"x": 1}}
    assert second == ok_reply("corr-dup", {"status": "duplicate_skipped"})
