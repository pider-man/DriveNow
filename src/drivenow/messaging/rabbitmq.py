"""RabbitMQ implementation of EventPublisher (D4), using pika."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from typing import Any

import pika

from drivenow.domain.events import DomainEvent

logger = logging.getLogger(__name__)

EXCHANGE = "drivenow.events"
EXCHANGE_TYPE = "topic"


def declare_exchange(channel: Any, exchange: str = EXCHANGE) -> None:
    """Declare the durable topic exchange. Shared by the publisher and the worker."""
    channel.exchange_declare(exchange=exchange, exchange_type=EXCHANGE_TYPE, durable=True)


def connection_factory_for(url: str) -> Callable[[], Any]:
    """Return a factory for blocking connections with short timeouts.

    Short timeouts keep a request from stalling for long when the broker is down.
    """

    def connect() -> pika.BlockingConnection:
        params = pika.URLParameters(url)
        params.socket_timeout = 2
        params.blocked_connection_timeout = 5
        params.connection_attempts = 1
        return pika.BlockingConnection(params)

    return connect


class RabbitMQPublisher:
    """Publishes domain events as persistent JSON messages to a durable topic exchange.

    The routing key is the event type (for example ``rental.started``). A pika
    connection isn't thread-safe, so a lock serializes all use of the single,
    lazily opened connection; FastAPI calls this from its thread pool. Publisher
    confirms make the broker acknowledge every message. On failure the publisher
    reconnects once and retries; if that fails too, it logs an ERROR and returns,
    so the request still succeeds (best-effort delivery, Decision 11).
    """

    def __init__(
        self,
        url: str,
        *,
        exchange: str = EXCHANGE,
        connection_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._exchange = exchange
        self._connect = connection_factory or connection_factory_for(url)
        self._lock = threading.Lock()
        self._connection: Any = None
        self._channel: Any = None

    def publish(self, event: DomainEvent) -> None:
        body = json.dumps(event.to_message()).encode("utf-8")
        properties = pika.BasicProperties(
            content_type="application/json",
            delivery_mode=pika.DeliveryMode.Persistent,
            message_id=event.id,
            type=event.name,
        )
        with self._lock:
            for attempt in (1, 2):
                try:
                    channel = self._open_channel()
                    channel.basic_publish(
                        exchange=self._exchange, routing_key=event.name, body=body, properties=properties
                    )
                    return
                except Exception as exc:
                    self._drop_connection()
                    if attempt == 1:
                        logger.warning("Publishing %s failed (%s); reconnecting once", event.name, exc)
                    else:
                        logger.error(
                            "Failed to publish event %s id=%s after reconnecting: %s", event.name, event.id, exc
                        )

    def close(self) -> None:
        """Close the connection, if any."""
        with self._lock:
            self._drop_connection()

    def _open_channel(self) -> Any:
        if self._channel is None or not self._channel.is_open:
            self._drop_connection()
            self._connection = self._connect()
            channel = self._connection.channel()
            declare_exchange(channel, self._exchange)
            channel.confirm_delivery()
            self._channel = channel
            logger.info("Connected to RabbitMQ, publishing to exchange %s", self._exchange)
        return self._channel

    def _drop_connection(self) -> None:
        connection, self._connection, self._channel = self._connection, None, None
        if connection is not None:
            try:
                if connection.is_open:
                    connection.close()
            except Exception:  # already broken; nothing more to do
                pass
