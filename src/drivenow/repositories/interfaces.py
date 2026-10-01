"""Repository and Unit of Work abstractions the service layer depends on (DIP).

The SQLAlchemy classes in this package implement them; unit tests can use
in-memory fakes instead.
"""

from __future__ import annotations

from datetime import datetime
from types import TracebackType
from typing import Protocol, Self

from drivenow.db.models import Car, Rental
from drivenow.domain.enums import CarStatus


class CarRepository(Protocol):
    """Persistence operations for cars."""

    def add(self, car: Car) -> Car:
        """Stage a new car and assign its ID."""
        ...

    def get(self, car_id: int, *, for_update: bool = False) -> Car | None:
        """Return the car, or None. ``for_update`` locks the row until commit (PostgreSQL)."""
        ...

    def list(self, status: CarStatus | None = None) -> list[Car]:
        """Return all cars ordered by ID, optionally only those with ``status``."""
        ...

    def delete(self, car: Car) -> None:
        """Delete the car. Fails with IntegrityError while it still has rentals."""
        ...

    def count_active(self) -> int:
        """Count cars not under maintenance (D5)."""
        ...


class RentalRepository(Protocol):
    """Persistence operations for rentals."""

    def add(self, rental: Rental) -> Rental:
        """Stage a new rental and assign its ID."""
        ...

    def get(self, rental_id: int, *, for_update: bool = False) -> Rental | None:
        """Return the rental, or None. ``for_update`` locks the row until commit (PostgreSQL)."""
        ...

    def list(self, car_id: int | None = None, ongoing: bool | None = None) -> list[Rental]:
        """Return rentals ordered by ID, optionally filtered by car and by ongoing/finished."""
        ...

    def get_ongoing_for_car(self, car_id: int) -> Rental | None:
        """Return the car's rental with no end date, if any."""
        ...

    def get_latest_end_for_car(self, car_id: int) -> datetime | None:
        """Return the latest end date among the car's finished rentals, if any (B10)."""
        ...

    def delete_finished_for_car(self, car_id: int) -> int:
        """Delete the car's finished rentals and return how many were deleted."""
        ...

    def count_ongoing(self) -> int:
        """Count rentals with no end date."""
        ...


class UnitOfWork(Protocol):
    """A transaction boundary that gives access to the repositories.

    Use it as a context manager. Nothing is saved unless ``commit()`` is called
    inside the ``with`` block; leaving the block rolls back anything uncommitted.
    """

    cars: CarRepository
    rentals: RentalRepository

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    def commit(self) -> None:
        """Make all staged changes permanent."""
        ...

    def rollback(self) -> None:
        """Discard all staged changes."""
        ...
