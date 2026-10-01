"""Fixtures wiring the services to in-memory fakes and a fixed clock."""

from __future__ import annotations

import pytest

from drivenow.services.car_service import CarService
from drivenow.services.rental_service import RentalService
from drivenow.services.stats_service import StatsService

from .fakes import FakeDatabase, FakeUnitOfWork, FixedClock, JournalPublisher


@pytest.fixture
def db() -> FakeDatabase:
    return FakeDatabase()


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock()


@pytest.fixture
def publisher(db: FakeDatabase) -> JournalPublisher:
    return JournalPublisher(db)


@pytest.fixture
def car_service(db, publisher, clock) -> CarService:
    return CarService(lambda: FakeUnitOfWork(db), publisher, clock)


@pytest.fixture
def rental_service(db, publisher, clock) -> RentalService:
    return RentalService(lambda: FakeUnitOfWork(db), publisher, clock)


@pytest.fixture
def stats_service(db) -> StatsService:
    return StatsService(lambda: FakeUnitOfWork(db))
