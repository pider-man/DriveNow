"""Services on the real SQLAlchemy Unit of Work (in-memory SQLite): transactions and races."""

from __future__ import annotations

from datetime import timedelta

import pytest

from drivenow.domain.enums import CarStatus
from drivenow.domain.exceptions import CarNotAvailableError
from drivenow.messaging.publisher import InMemoryPublisher
from drivenow.repositories.car_repository import SqlAlchemyCarRepository
from drivenow.repositories.rental_repository import SqlAlchemyRentalRepository
from drivenow.services.car_service import CarService
from drivenow.services.rental_service import RentalService
from drivenow.services.stats_service import StatsService

from .conftest import T0


class FixedClock:
    def now(self):
        return T0 + timedelta(hours=12)


@pytest.fixture
def publisher():
    return InMemoryPublisher()


@pytest.fixture
def cars(uow, publisher):
    return CarService(uow, publisher, FixedClock())


@pytest.fixture
def rentals(uow, publisher):
    return RentalService(uow, publisher, FixedClock())


def test_rental_lifecycle_end_to_end(cars, rentals, uow, publisher):
    car = cars.add_car("Toyota Corolla", 2022)
    rental = rentals.start_rental(car.id, "Dana Levi", start_date=T0)
    assert cars.get_car(car.id).status == CarStatus.IN_USE

    ended = rentals.end_rental(rental.id, end_date=T0 + timedelta(hours=3))
    assert ended.end_date == T0 + timedelta(hours=3)
    assert cars.get_car(car.id).status == CarStatus.AVAILABLE

    stats = StatsService(uow)
    assert (stats.active_cars(), stats.ongoing_rentals()) == (1, 0)

    cars.delete_car(car.id)
    assert cars.list_cars() == [] and rentals.list_rentals() == []
    assert [e.name for e in publisher.events] == [
        "car.created", "rental.started", "rental.ended", "car.deleted",
    ]


def test_delete_car_is_one_transaction(cars, rentals, add_car, add_rental, publisher, monkeypatch):
    car = add_car()
    add_rental(car.id, start_date=T0, end_date=T0 + timedelta(hours=1))

    def failing_delete(self, car):
        raise RuntimeError("disk full")

    monkeypatch.setattr(SqlAlchemyCarRepository, "delete", failing_delete)
    with pytest.raises(RuntimeError):
        cars.delete_car(car.id)

    # The finished rentals deleted earlier in the same transaction were rolled back.
    assert len(rentals.list_rentals(car_id=car.id)) == 1
    assert cars.get_car(car.id).id == car.id
    assert publisher.events == []


def test_concurrent_rental_hits_db_index_and_becomes_conflict(rentals, add_car, add_rental, uow, monkeypatch):
    # Simulate a race: another request's rental is already committed, but this
    # request's checks didn't see it (stale status, ongoing check missed it).
    car = add_car()
    add_rental(car.id, start_date=T0)
    monkeypatch.setattr(SqlAlchemyRentalRepository, "get_ongoing_for_car", lambda self, car_id: None)

    with pytest.raises(CarNotAvailableError) as err:
        rentals.start_rental(car.id, "Second Customer", start_date=T0 + timedelta(hours=1))
    assert err.value.code == "CAR_NOT_AVAILABLE"

    with uow() as tx:
        assert len(tx.rentals.list(car_id=car.id)) == 1
        assert tx.cars.get(car.id).status == CarStatus.AVAILABLE  # unchanged: rolled back
