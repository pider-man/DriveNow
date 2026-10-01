"""Event publisher abstraction and its non-broker implementations.

``RabbitMQPublisher`` is added in build step 7.
"""

from __future__ import annotations

from typing import Protocol

from drivenow.domain.events import DomainEvent


class EventPublisher(Protocol):
    def publish(self, event: DomainEvent) -> None:
        """Send ``event`` to subscribers. Called only after a successful commit."""
        ...


class NullPublisher:
    """Discards events. Used when no message broker is configured."""

    def publish(self, event: DomainEvent) -> None:
        pass


class InMemoryPublisher:
    """Keeps published events in a list. Used until RabbitMQ is added, and in tests."""

    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    def publish(self, event: DomainEvent) -> None:
        self.events.append(event)
