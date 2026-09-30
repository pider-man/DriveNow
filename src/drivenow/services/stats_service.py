"""Fleet statistics for GET /stats and the Prometheus gauges."""

from __future__ import annotations

from collections.abc import Callable

from drivenow.repositories.interfaces import UnitOfWork


class StatsService:
    """Read-only counts, computed from the database on each call."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    def active_cars(self) -> int:
        """Cars not under maintenance (D5): available + in use."""
        with self._uow_factory() as uow:
            return uow.cars.count_active()

    def ongoing_rentals(self) -> int:
        """Rentals with no end date."""
        with self._uow_factory() as uow:
            return uow.rentals.count_ongoing()
