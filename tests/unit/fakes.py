"""In-memory fakes for service unit tests.

A shared ``journal`` records locks, commits and publishes in order, so tests can
check that a car row was locked, that the rental and the car changed in one
commit, and that events went out only after that commit.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Self

from drivenow.db.models import Car, Rental
from drivenow.domain.enums import CarStatus
from drivenow.domain.events import DomainEvent

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


class FixedClock:
    def __init__(self, now: datetime = NOW) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class FakeDatabase:
    def __init__(self) -> None:
        self.cars: dict[int, Car] = {}
        self.rentals: dict[int, Rental] = {}
        self.journal: list[str] = []
        self._next_car_id = 1
        self._next_rental_id = 1
        self.fail_commit: Exception | None = None
        self.fail_rental_add: Exception | None = None

    def next_car_id(self) -> int:
        self._next_car_id += 1
        return self._next_car_id - 1

    def next_rental_id(self) -> int:
        self._next_rental_id += 1
        return self._next_rental_id - 1

    # Seeding helpers (bypass the services).
    def seed_car(self, status: CarStatus = CarStatus.AVAILABLE, model: str = "Toyota Corolla", year: int = 2022) -> Car:
        car = Car(id=self.next_car_id(), model=model, year=year, status=status)
        self.cars[car.id] = car
        return car

    def seed_rental(self, car_id: int, start_date: datetime, end_date: datetime | None = None,
                    customer_name: str = "Dana Levi") -> Rental:
        rental = Rental(id=self.next_rental_id(), car_id=car_id, customer_name=customer_name,
                        start_date=start_date, end_date=end_date)
        self.rentals[rental.id] = rental
        return rental


class FakeCarRepository:
    def __init__(self, db: FakeDatabase) -> None:
        self._db = db

    def add(self, car: Car) -> Car:
        car.id = self._db.next_car_id()
        self._db.cars[car.id] = car
        return car

    def get(self, car_id: int, *, for_update: bool = False) -> Car | None:
        if for_update:
            self._db.journal.append(f"lock:car:{car_id}")
        return self._db.cars.get(car_id)

    def list(self, status: CarStatus | None = None) -> list[Car]:
        return [c for _, c in sorted(self._db.cars.items()) if status is None or c.status == status]

    def delete(self, car: Car) -> None:
        self._db.journal.append(f"delete:car:{car.id}")
        del self._db.cars[car.id]

    def count_active(self) -> int:
        return sum(1 for c in self._db.cars.values() if c.status != CarStatus.UNDER_MAINTENANCE)


class FakeRentalRepository:
    def __init__(self, db: FakeDatabase) -> None:
        self._db = db

    def add(self, rental: Rental) -> Rental:
        if self._db.fail_rental_add is not None:
            raise self._db.fail_rental_add
        rental.id = self._db.next_rental_id()
        self._db.rentals[rental.id] = rental
        return rental

    def get(self, rental_id: int, *, for_update: bool = False) -> Rental | None:
        if for_update:
            self._db.journal.append(f"lock:rental:{rental_id}")
        return self._db.rentals.get(rental_id)

    def list(self, car_id: int | None = None, ongoing: bool | None = None) -> list[Rental]:
        result = []
        for _, r in sorted(self._db.rentals.items()):
            if car_id is not None and r.car_id != car_id:
                continue
            if ongoing is not None and (r.end_date is None) != ongoing:
                continue
            result.append(r)
        return result

    def get_ongoing_for_car(self, car_id: int) -> Rental | None:
        return next((r for r in self._db.rentals.values() if r.car_id == car_id and r.end_date is None), None)

    def get_latest_end_for_car(self, car_id: int) -> datetime | None:
        ends = [r.end_date for r in self._db.rentals.values() if r.car_id == car_id and r.end_date is not None]
        return max(ends, default=None)

    def delete_finished_for_car(self, car_id: int) -> int:
        doomed = [rid for rid, r in self._db.rentals.items() if r.car_id == car_id and r.end_date is not None]
        for rid in doomed:
            del self._db.rentals[rid]
        self._db.journal.append(f"delete_finished:car:{car_id}")
        return len(doomed)

    def count_ongoing(self) -> int:
        return sum(1 for r in self._db.rentals.values() if r.end_date is None)


class FakeUnitOfWork:
    """Changes apply to the shared FakeDatabase directly; commit only records itself.

    Real rollback behavior is covered by the integration tests on SQLite.
    """

    def __init__(self, db: FakeDatabase) -> None:
        self._db = db
        self.cars = FakeCarRepository(db)
        self.rentals = FakeRentalRepository(db)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is not None:
            self._db.journal.append("rollback")

    def commit(self) -> None:
        if self._db.fail_commit is not None:
            raise self._db.fail_commit
        self._db.journal.append("commit")

    def rollback(self) -> None:
        self._db.journal.append("rollback")


class JournalPublisher:
    """Records events, and their position relative to commits in the journal."""

    def __init__(self, db: FakeDatabase) -> None:
        self._db = db
        self.events: list[DomainEvent] = []
        self.fail_with: Exception | None = None

    def publish(self, event: DomainEvent) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self._db.journal.append(f"publish:{event.name}")
        self.events.append(event)
