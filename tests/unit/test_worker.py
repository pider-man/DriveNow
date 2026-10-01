"""Audit worker: message handling and reconnect loop, with fakes."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from types import SimpleNamespace

from pika.exceptions import AMQPConnectionError

from drivenow.domain.events import DomainEvent
from drivenow.messaging import worker


class FakeChannel:
    def __init__(self, on_consume=None) -> None:
        self.calls: list[tuple] = []
        self.on_consume = on_consume

    def exchange_declare(self, **kwargs):
        self.calls.append(("exchange_declare", kwargs))

    def queue_declare(self, **kwargs):
        self.calls.append(("queue_declare", kwargs))

    def queue_bind(self, **kwargs):
        self.calls.append(("queue_bind", kwargs))

    def basic_qos(self, **kwargs):
        self.calls.append(("basic_qos", kwargs))

    def basic_consume(self, **kwargs):
        self.calls.append(("basic_consume", kwargs))

    def start_consuming(self):
        self.calls.append(("start_consuming", {}))
        if self.on_consume:
            self.on_consume()

    def basic_ack(self, **kwargs):
        self.calls.append(("basic_ack", kwargs))

    def basic_nack(self, **kwargs):
        self.calls.append(("basic_nack", kwargs))


class FakeConnection:
    def __init__(self, channel: FakeChannel) -> None:
        self._channel = channel
        self.is_open = True

    def channel(self) -> FakeChannel:
        return self._channel

    def close(self) -> None:
        self.is_open = False


def method(tag: int = 1, routing_key: str = "rental.started"):
    return SimpleNamespace(delivery_tag=tag, routing_key=routing_key)


def test_handle_message_logs_audit_line_and_acks(caplog):
    caplog.set_level(logging.INFO)
    event = DomainEvent(
        name="rental.started",
        occurred_at=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
        payload={"id": 1, "car_id": 3},
    )
    channel = FakeChannel()

    worker.handle_message(channel, method(tag=42), None, json.dumps(event.to_message()).encode())

    assert channel.calls == [("basic_ack", {"delivery_tag": 42})]
    [record] = [r for r in caplog.records if r.name == "drivenow.messaging.worker"]
    assert record.levelno == logging.INFO
    assert record.getMessage() == (
        f'AUDIT rental.started id={event.id} occurred_at=2026-10-01T12:00:00+00:00 payload={{"car_id": 3, "id": 1}}'
    )


def test_audit_line_leaves_out_customer_name(caplog):
    caplog.set_level(logging.INFO)
    payload = {
        "id": 1,
        "car_id": 3,
        "customer_name": "Dana Levi",
        "start_date": "2026-10-01T09:00:00+00:00",
        "end_date": None,
    }
    event = DomainEvent(name="rental.started", occurred_at=datetime(2026, 10, 1, 12, 0, tzinfo=UTC), payload=payload)
    body = json.dumps(event.to_message()).encode()
    channel = FakeChannel()

    worker.handle_message(channel, method(tag=7), None, body)

    [record] = [r for r in caplog.records if r.name == "drivenow.messaging.worker"]
    line = record.getMessage()
    assert "Dana Levi" not in line and "customer_name" not in line
    assert 'payload={"car_id": 3, "end_date": null, "id": 1, "start_date": "2026-10-01T09:00:00+00:00"}' in line
    assert channel.calls == [("basic_ack", {"delivery_tag": 7})]
    assert event.payload["customer_name"] == "Dana Levi"  # the event itself is unchanged


def test_malformed_message_is_rejected_without_requeue(caplog):
    for body in (b"not json", json.dumps({"payload": {}}).encode(), b"[]"):
        caplog.clear()
        channel = FakeChannel()
        worker.handle_message(channel, method(tag=5), None, body)
        assert channel.calls == [("basic_nack", {"delivery_tag": 5, "requeue": False})]
        assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_consume_declares_topology():
    def stop():
        raise KeyboardInterrupt

    channel = FakeChannel(on_consume=stop)
    worker.run(lambda: FakeConnection(channel), sleep=lambda s: None)

    names = [name for name, _ in channel.calls]
    assert names == ["exchange_declare", "queue_declare", "queue_bind", "basic_qos", "basic_consume", "start_consuming"]
    kwargs = dict(channel.calls)
    assert kwargs["exchange_declare"] == {"exchange": "drivenow.events", "exchange_type": "topic", "durable": True}
    assert kwargs["queue_declare"] == {"queue": "drivenow.audit", "durable": True}
    assert kwargs["queue_bind"] == {"queue": "drivenow.audit", "exchange": "drivenow.events", "routing_key": "#"}
    assert kwargs["basic_consume"]["on_message_callback"] is worker.handle_message


def test_run_reconnects_with_backoff_when_broker_is_away(caplog):
    attempts = {"n": 0}
    sleeps: list[float] = []

    def stop():
        raise KeyboardInterrupt

    def factory():
        attempts["n"] += 1
        if attempts["n"] <= 3:
            raise AMQPConnectionError("connection refused")
        return FakeConnection(FakeChannel(on_consume=stop))

    worker.run(factory, sleep=sleeps.append)

    assert attempts["n"] == 4
    assert sleeps == [1, 2, 4]
    messages = [r.getMessage() for r in caplog.records if "RabbitMQ unavailable" in r.getMessage()]
    assert len(messages) == 3
    assert messages[0] == "RabbitMQ unavailable (AMQPConnectionError: connection refused); retrying in 1 s"


def test_run_reconnects_after_lost_connection():
    consumed = {"n": 0}

    def on_consume():
        consumed["n"] += 1
        if consumed["n"] == 1:
            raise ConnectionResetError("broker went away")
        raise KeyboardInterrupt

    channel = FakeChannel(on_consume=on_consume)
    connections: list[FakeConnection] = []

    def factory():
        connections.append(FakeConnection(channel))
        return connections[-1]

    sleeps: list[float] = []
    worker.run(factory, sleep=sleeps.append)

    assert len(connections) == 2
    assert sleeps == [1]
    assert not connections[0].is_open
