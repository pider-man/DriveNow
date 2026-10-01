"""Audit worker: consumes every domain event from RabbitMQ and logs it.

Run it with ``python -m drivenow.worker``.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from collections.abc import Callable
from typing import Any

from drivenow.config import get_settings
from drivenow.messaging.rabbitmq import EXCHANGE, connection_factory_for, declare_exchange
from drivenow.observability.logging_config import setup_logging

logger = logging.getLogger(__name__)

QUEUE = "drivenow.audit"
BINDING_KEY = "#"  # all events
PREFETCH = 10
MAX_BACKOFF_SECONDS = 30

# Personal data kept out of the audit log. The events themselves are not changed.
LOG_EXCLUDED_FIELDS = frozenset({"customer_name"})


def handle_message(channel: Any, method: Any, properties: Any, body: bytes) -> None:
    """Log one event as an audit line and acknowledge it.

    A malformed message is logged and rejected without requeueing, so it can't
    be redelivered forever.
    """
    try:
        message = json.loads(body)
        event_type = message["type"]
        event_id = message["id"]
        occurred_at = message["occurred_at"]
        payload = message.get("payload", {})
    except (ValueError, KeyError, TypeError) as exc:
        logger.error("Discarding malformed message (routing key %s): %s: %r", method.routing_key, exc, body[:200])
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        return

    logger.info(
        "AUDIT %s id=%s occurred_at=%s payload=%s",
        event_type, event_id, occurred_at, json.dumps(_loggable(payload), sort_keys=True),
    )
    channel.basic_ack(delivery_tag=method.delivery_tag)


def _loggable(payload: Any) -> Any:
    """The payload as it may be logged: without the fields in LOG_EXCLUDED_FIELDS."""
    if isinstance(payload, dict):
        return {key: value for key, value in payload.items() if key not in LOG_EXCLUDED_FIELDS}
    return payload


def consume(connection: Any) -> None:
    """Declare the topology on ``connection`` and consume until it closes."""
    channel = connection.channel()
    declare_exchange(channel, EXCHANGE)
    channel.queue_declare(queue=QUEUE, durable=True)
    channel.queue_bind(queue=QUEUE, exchange=EXCHANGE, routing_key=BINDING_KEY)
    channel.basic_qos(prefetch_count=PREFETCH)
    channel.basic_consume(queue=QUEUE, on_message_callback=handle_message)
    logger.info("Worker consuming queue %s bound to %s with %r", QUEUE, EXCHANGE, BINDING_KEY)
    channel.start_consuming()


def run(connection_factory: Callable[[], Any], *, sleep: Callable[[float], None] = time.sleep) -> None:
    """Consume forever, reconnecting with backoff (1, 2, 4 ... 30 s) when the broker goes away."""
    backoff = 1
    while True:
        connection = None
        try:
            connection = connection_factory()
            backoff = 1  # connected: reset the backoff
            consume(connection)
            logger.warning("Consumer stopped; reconnecting")
        except KeyboardInterrupt:
            logger.info("Worker stopping")
            _close(connection)
            return
        except Exception as exc:  # noqa: BLE001 - the worker must survive any broker error and reconnect
            logger.warning("RabbitMQ unavailable (%s: %s); retrying in %s s", type(exc).__name__, exc, backoff)
            _close(connection)
            sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)


def _close(connection: Any) -> None:
    if connection is None:
        return
    try:
        if connection.is_open:
            connection.close()
    except Exception:  # noqa: BLE001, S110 - closing a broken connection; nothing more to do
        pass


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level, settings.worker_log_file)
    if not settings.rabbitmq_url:
        logger.error("RABBITMQ_URL is not set; the worker needs a broker")
        sys.exit(1)
    logger.info("DriveNow worker starting")
    run(connection_factory_for(settings.rabbitmq_url))
