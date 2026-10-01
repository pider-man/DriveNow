"""Composition root: builds the concrete objects and hands them to routes.

This is the only place in the API package that knows about the database and
the concrete repository / publisher / clock / metrics classes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Request
from sqlalchemy import Engine, text

from drivenow.config import Settings
from drivenow.db.session import create_db_engine, create_session_factory
from drivenow.messaging.publisher import EventPublisher
from drivenow.observability.metrics import AppMetrics
from drivenow.repositories.unit_of_work import SqlAlchemyUnitOfWork
from drivenow.services.car_service import CarService
from drivenow.services.clock import Clock
from drivenow.services.rental_service import RentalService
from drivenow.services.stats_service import StatsService

HealthCheck = Callable[[], None]
"""Raises if the service isn't healthy."""


@dataclass
class Container:
    engine: Engine
    publisher: EventPublisher
    metrics: AppMetrics
    car_service: CarService
    rental_service: RentalService
    stats_service: StatsService
    health_check: HealthCheck


def build_container(settings: Settings, clock: Clock, publisher: EventPublisher) -> Container:
    engine = create_db_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    metrics = AppMetrics()

    def uow_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory)

    def ping_database() -> None:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    stats_service = StatsService(uow_factory)
    metrics.bind_stats(stats_service)

    return Container(
        engine=engine,
        publisher=publisher,
        metrics=metrics,
        car_service=CarService(uow_factory, publisher, clock, metrics),
        rental_service=RentalService(uow_factory, publisher, clock, metrics),
        stats_service=stats_service,
        health_check=ping_database,
    )


def _container(request: Request) -> Container:
    return request.app.state.container


def get_car_service(request: Request) -> CarService:
    return _container(request).car_service


def get_rental_service(request: Request) -> RentalService:
    return _container(request).rental_service


def get_stats_service(request: Request) -> StatsService:
    return _container(request).stats_service


def get_metrics(request: Request) -> AppMetrics:
    return _container(request).metrics


def get_health_check(request: Request) -> HealthCheck:
    return _container(request).health_check
