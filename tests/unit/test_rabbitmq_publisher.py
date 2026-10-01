"""RabbitMQPublisher against a fake pika connection (no broker needed)."""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import UTC, datetime

import pika
import pytest
from pika.exceptions import AMQPConnectionError, StreamLostError

from drivenow.api.dependencies import build_publisher
from drivenow.config import Settings
from drivenow.domain.events import DomainEvent
from drivenow.messaging.publisher import NullPublisher
from drivenow.messaging.rabbitmq import RabbitMQPublisher

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


class FakeBroker:
    """Shared state for the fake connections: what was published, and injected failures."""

    def __init__(self) -> None:
        self.connections: list[FakeConnection] = []
        self.published: list[dict] = []
        self.fail_next_publishes = 0
        self.fail_connects = 0
        self.in_publish = False
        self.overlaps = 0

    def connect(self) -> FakeConnection:
        if self.fail_connects:
            self.fail_connects -= 1
            raise AMQPConnectionError("broker down")
        connection = FakeConnection(self)
        self.connections.append(connection)
        return connection


class FakeConnection:
    def __init__(self, broker: FakeBroker) -> None:
        self.broker = broker
        self.is_open = True
        self.channels: list[FakeChannel] = []

    def channel(self) -> FakeChannel:
        channel = FakeChannel(self.broker)
        self.channels.append(channel)
        return channel

    def close(self) -> None:
        self.is_open = False


class FakeChannel:
    def __init__(self, broker: FakeBroker) -> None:
        self.broker = broker
        self.is_open = True
        self.declared: list[dict] = []
        self.confirms = False

    def exchange_declare(self, **kwargs) -> None:
        self.declared.append(kwargs)

    def confirm_delivery(self) -> None:
        self.confirms = True

    def basic_publish(self, exchange, routing_key, body, properties) -> None:
        broker = self.broker
        if broker.in_publish:
            broker.overlaps += 1
        broker.in_publish = True
        try:
            time.sleep(0.001)  # widen the window for interleaving
            if broker.fail_next_publishes:
                broker.fail_next_publishes -= 1
                self.is_open = False
                raise StreamLostError("connection lost")
            broker.published.append(
                {"exchange": exchange, "routing_key": routing_key, "body": body, "properties": properties}
            )
        finally:
            broker.in_publish = False


@pytest.fixture
def broker() -> FakeBroker:
    return FakeBroker()


@pytest.fixture
def publisher(broker: FakeBroker) -> RabbitMQPublisher:
    return RabbitMQPublisher("amqp://unused", connection_factory=broker.connect)


def event(name: str = "rental.started", **payload) -> DomainEvent:
    return DomainEvent(name=name, occurred_at=NOW, payload=payload or {"id": 1})


def test_declares_durable_topic_exchange_with_confirms(publisher, broker):
    publisher.publish(event())
    [channel] = broker.connections[0].channels
    assert channel.declared == [{"exchange": "drivenow.events", "exchange_type": "topic", "durable": True}]
    assert channel.confirms


def test_message_routing_body_and_persistence(publisher, broker):
    e = event("rental.started", id=7, car_id=3)
    publisher.publish(e)

    [message] = broker.published
    assert message["exchange"] == "drivenow.events"
    assert message["routing_key"] == "rental.started"
    assert json.loads(message["body"]) == {
        "id": e.id,
        "type": "rental.started",
        "occurred_at": "2026-10-01T12:00:00+00:00",
        "payload": {"id": 7, "car_id": 3},
    }
    props = message["properties"]
    assert props.delivery_mode == pika.DeliveryMode.Persistent.value
    assert props.content_type == "application/json"
    assert props.message_id == e.id
    assert props.type == "rental.started"


def test_reuses_one_connection(publisher, broker):
    for name in ("car.created", "car.updated", "car.deleted"):
        publisher.publish(event(name))
    assert len(broker.connections) == 1
    assert [m["routing_key"] for m in broker.published] == ["car.created", "car.updated", "car.deleted"]


def test_reconnects_once_after_a_failure(publisher, broker, caplog):
    publisher.publish(event("car.created"))
    broker.fail_next_publishes = 1

    publisher.publish(event("car.updated"))

    assert len(broker.connections) == 2
    assert not broker.connections[0].is_open
    assert [m["routing_key"] for m in broker.published] == ["car.created", "car.updated"]
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_gives_up_after_the_retry_logs_error_and_does_not_raise(publisher, broker, caplog):
    broker.fail_next_publishes = 2
    e = event("rental.ended")

    publisher.publish(e)  # must not raise: the request still succeeds

    assert broker.published == []
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert f"Failed to publish event rental.ended id={e.id}" in errors[0].getMessage()

    # The next publish starts with a fresh connection and works.
    publisher.publish(event("car.created"))
    assert [m["routing_key"] for m in broker.published] == ["car.created"]


def test_broker_unreachable_logs_error_and_does_not_raise(publisher, broker, caplog):
    broker.fail_connects = 2
    publisher.publish(event())
    assert broker.published == []
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_thread_safe_publishing(publisher, broker):
    def worker(n: int) -> None:
        for i in range(10):
            publisher.publish(event("car.updated", n=n, i=i))

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(broker.published) == 80
    assert broker.overlaps == 0
    assert len(broker.connections) == 1


def test_close(publisher, broker):
    publisher.publish(event())
    publisher.close()
    assert not broker.connections[0].is_open
    publisher.close()  # idempotent


def test_build_publisher_uses_rabbitmq_only_when_url_is_set():
    assert isinstance(build_publisher(Settings(rabbitmq_url=None, _env_file=None)), NullPublisher)
    assert isinstance(
        build_publisher(Settings(rabbitmq_url="amqp://u:p@localhost:5672/", _env_file=None)), RabbitMQPublisher
    )
