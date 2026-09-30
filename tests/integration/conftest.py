"""Fixtures for data-layer tests: a fresh in-memory SQLite database per test."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from drivenow.db.models import Car, Rental
from drivenow.db.session import create_db_engine, create_session_factory, create_tables
from drivenow.domain.enums import CarStatus
from drivenow.repositories.unit_of_work import SqlAlchemyUnitOfWork

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


@pytest.fixture
def engine() -> Iterator[Engine]:
    engine = create_db_engine("sqlite://")
    create_tables(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(engine)


@pytest.fixture
def uow(session_factory: sessionmaker[Session]) -> Callable[[], SqlAlchemyUnitOfWork]:
    """Return a factory: each call gives a new Unit of Work (a new transaction)."""
    return lambda: SqlAlchemyUnitOfWork(session_factory)


@pytest.fixture
def add_car(uow: Callable[[], SqlAlchemyUnitOfWork]) -> Callable[..., Car]:
    """Commit a car and return it."""

    def _add_car(
        model: str = "Toyota Corolla", year: int = 2022, status: CarStatus | None = None
    ) -> Car:
        with uow() as tx:
            car = Car(model=model, year=year)
            if status is not None:
                car.status = status
            tx.cars.add(car)
            tx.commit()
        return car

    return _add_car


@pytest.fixture
def add_rental(uow: Callable[[], SqlAlchemyUnitOfWork]) -> Callable[..., Rental]:
    """Commit a rental and return it."""

    def _add_rental(
        car_id: int,
        customer_name: str = "Dana Levi",
        start_date: datetime = T0,
        end_date: datetime | None = None,
    ) -> Rental:
        with uow() as tx:
            rental = Rental(
                car_id=car_id, customer_name=customer_name, start_date=start_date, end_date=end_date
            )
            tx.rentals.add(rental)
            tx.commit()
        return rental

    return _add_rental
