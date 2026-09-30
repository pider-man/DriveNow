"""StatsService: active cars (D5) and ongoing rentals."""

from __future__ import annotations

from datetime import timedelta

from drivenow.domain.enums import CarStatus

from .fakes import NOW


def test_active_cars_excludes_maintenance(stats_service, db):
    db.seed_car(status=CarStatus.AVAILABLE)
    db.seed_car(status=CarStatus.IN_USE)
    db.seed_car(status=CarStatus.UNDER_MAINTENANCE)
    assert stats_service.active_cars() == 2


def test_ongoing_rentals(stats_service, db):
    car = db.seed_car()
    db.seed_rental(car.id, start_date=NOW - timedelta(days=2), end_date=NOW - timedelta(days=1))
    db.seed_rental(car.id, start_date=NOW - timedelta(hours=1))
    assert stats_service.ongoing_rentals() == 1


def test_empty_fleet(stats_service):
    assert (stats_service.active_cars(), stats_service.ongoing_rentals()) == (0, 0)
