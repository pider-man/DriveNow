"""Domain events published after a successful commit (docs/ARCHITECTURE.md, section 11)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

CAR_CREATED = "car.created"
CAR_UPDATED = "car.updated"
CAR_DELETED = "car.deleted"
RENTAL_STARTED = "rental.started"
RENTAL_ENDED = "rental.ended"


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """Something that happened. ``name`` is also the RabbitMQ routing key."""

    name: str
    occurred_at: datetime
    payload: dict[str, Any] = field(default_factory=dict)

    def to_message(self) -> dict[str, Any]:
        """The JSON message body: ``{"event", "occurred_at", "payload"}``."""
        return {"event": self.name, "occurred_at": self.occurred_at.isoformat(), "payload": self.payload}
