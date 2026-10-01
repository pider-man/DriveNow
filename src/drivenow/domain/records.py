"""Plain, immutable data objects that services return.

They decouple callers (the API, the worker) from the ORM: no session, no lazy
loading, safe to pass around after the transaction has closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from drivenow.domain.enums import CarStatus

if TYPE_CHECKING:
    from drivenow.db.models import Car, Rental


@dataclass(frozen=True, slots=True)
class CarRecord:
    id: int
    model: str
    year: int
    status: CarStatus

    @classmethod
    def from_model(cls, car: Car) -> CarRecord:
        return cls(id=car.id, model=car.model, year=car.year, status=CarStatus(car.status))

    def to_payload(self) -> dict[str, Any]:
        """JSON-ready representation, used in event payloads."""
        return {"id": self.id, "model": self.model, "year": self.year, "status": self.status.value}


@dataclass(frozen=True, slots=True)
class RentalRecord:
    id: int
    car_id: int
    customer_name: str
    start_date: datetime
    end_date: datetime | None

    @property
    def ongoing(self) -> bool:
        return self.end_date is None

    @classmethod
    def from_model(cls, rental: Rental) -> RentalRecord:
        return cls(
            id=rental.id,
            car_id=rental.car_id,
            customer_name=rental.customer_name,
            start_date=rental.start_date,
            end_date=rental.end_date,
        )

    def to_payload(self) -> dict[str, Any]:
        """JSON-ready representation, used in event payloads."""
        return {
            "id": self.id,
            "car_id": self.car_id,
            "customer_name": self.customer_name,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat() if self.end_date else None,
        }
