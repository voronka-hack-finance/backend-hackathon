import json

from common.messaging import MessageWorker, error_reply


class FakeChannel:
    def __init__(self) -> None:
        self.declared = []
        self.published = []

    def queue_declare(self, **kwargs):
        self.declared.append(kwargs)

    def basic_publish(self, **kwargs):
        self.published.append(kwargs)


def test_worker_declares_retry_queue_with_ttl_dead_letter_back_to_main_queue():
    worker = MessageWorker(
        rabbitmq_url="amqp://guest:guest@localhost:5672/%2F",
        queue_name="sample-service",
        service_name="sample-service",
        handlers={},
        retry_delay_ms=2500,
    )
    channel = FakeChannel()

    worker._declare_retry_and_dead_queues_sync(channel)

    assert {"queue": "sample-service.dead", "durable": True} in channel.declared
    assert {
        "queue": "sample-service.retry",
        "durable": True,
        "arguments": {
            "x-message-ttl": 2500,
            "x-dead-letter-exchange": "",
            "x-dead-letter-routing-key": "sample-service",
        },
    } in channel.declared


def test_failed_background_message_is_published_to_retry_queue_before_dead_letter():
    worker = MessageWorker(
        rabbitmq_url="amqp://guest:guest@localhost:5672/%2F",
        queue_name="sample-service",
        service_name="sample-service",
        handlers={},
        max_retries=3,
        retry_delay_ms=100,
    )
    channel = FakeChannel()
    body = json.dumps({"type": "tasks.fail", "payload": {"id": 1}}).encode("utf-8")

    worker._retry_or_dead_letter_sync(channel, body, error_reply("corr-1", 500, "boom"))

    assert len(channel.published) == 1
    published = channel.published[0]
    assert published["routing_key"] == "sample-service.retry"
    retried = json.loads(published["body"].decode("utf-8"))
    assert retried["retry"]["attempts"] == 1
    assert retried["retry"]["max_attempts"] == 3
    assert retried["retry"]["delay_ms"] == 100
    assert retried["retry"]["errors"][0]["status_code"] == 500
    assert retried["retry"]["errors"][0]["error"] == "boom"


def test_failed_background_message_goes_to_dead_queue_after_retry_limit():
    worker = MessageWorker(
        rabbitmq_url="amqp://guest:guest@localhost:5672/%2F",
        queue_name="sample-service",
        service_name="sample-service",
        handlers={},
        max_retries=2,
    )
    channel = FakeChannel()
    body = json.dumps(
        {
            "type": "tasks.fail",
            "payload": {"id": 1},
            "retry": {"attempts": 2, "max_attempts": 2, "errors": []},
        }
    ).encode("utf-8")

    worker._retry_or_dead_letter_sync(channel, body, error_reply("corr-1", 500, "boom"))

    assert {"queue": "sample-service.dead", "durable": True} in channel.declared
    assert len(channel.published) == 1
    published = channel.published[0]
    assert published["routing_key"] == "sample-service.dead"
    dead_payload = json.loads(published["body"].decode("utf-8"))
    assert dead_payload["service"] == "sample-service"
    assert dead_payload["queue"] == "sample-service"
    assert dead_payload["error"]["status_code"] == 500
    assert dead_payload["original"]["retry"]["attempts"] == 2
