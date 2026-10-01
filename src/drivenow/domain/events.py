"""Domain events published after a successful commit (docs/ARCHITECTURE.md, section 11)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

CAR_CREATED = "car.created"
CAR_UPDATED = "car.updated"
CAR_DELETED = "car.deleted"
RENTAL_STARTED = "rental.started"
RENTAL_ENDED = "rental.ended"


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """Something that happened. ``name`` is the event type and the RabbitMQ routing key."""

    name: str
    occurred_at: datetime
    payload: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid4()))

    def to_message(self) -> dict[str, Any]:
        """The JSON message body: ``{"id", "type", "occurred_at", "payload"}``."""
        return {
            "id": self.id,
            "type": self.name,
            "occurred_at": self.occurred_at.isoformat(),
            "payload": self.payload,
        }
