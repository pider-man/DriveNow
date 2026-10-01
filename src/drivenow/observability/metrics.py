"""Prometheus metrics (N6), in a registry owned by one app instance."""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from typing import Protocol

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

logger = logging.getLogger(__name__)


class FleetStats(Protocol):
    def active_cars(self) -> int: ...

    def ongoing_rentals(self) -> int: ...


class AppMetrics:
    """All metrics of one app. Implements ``OperationRecorder`` for the services.

    Each instance has its own ``CollectorRegistry``, so several apps (tests)
    can live in one process without duplicate-metric errors.
    """

    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.request_duration = Histogram(
            "drivenow_request_duration_seconds",
            "HTTP request duration in seconds, by method, route template and status code.",
            ["method", "route", "status_code"],
            registry=self.registry,
        )
        self.operation_duration = Histogram(
            "drivenow_operation_duration_seconds",
            "Service operation duration in seconds (successful and failed calls).",
            ["operation"],
            registry=self.registry,
        )
        self.operation_failures = Counter(
            "drivenow_operation_failures",
            "Failed service operations, by operation and error code.",
            ["operation", "code"],
            registry=self.registry,
        )
        self.active_cars = Gauge(
            "drivenow_active_cars",
            "Cars not under maintenance (available or in use).",
            registry=self.registry,
        )
        self.ongoing_rentals = Gauge(
            "drivenow_ongoing_rentals",
            "Rentals that have not ended.",
            registry=self.registry,
        )

    # --- OperationRecorder --------------------------------------------------------------

    def observe(self, operation: str, seconds: float) -> None:
        self.operation_duration.labels(operation=operation).observe(seconds)

    def failed(self, operation: str, code: str) -> None:
        self.operation_failures.labels(operation=operation, code=code).inc()

    # --- Requests -----------------------------------------------------------------------

    def observe_request(self, method: str, route: str, status_code: int, seconds: float) -> None:
        self.request_duration.labels(method=method, route=route, status_code=str(status_code)).observe(seconds)

    def average_request_ms(self) -> float | None:
        """Mean request duration since start, in ms; None before the first measured request."""
        total = count = 0.0
        for metric in self.request_duration.collect():
            for sample in metric.samples:
                if sample.name.endswith("_sum"):
                    total += sample.value
                elif sample.name.endswith("_count"):
                    count += sample.value
        if count == 0:
            return None
        return round(total / count * 1000, 3)

    # --- Gauges -------------------------------------------------------------------------

    def bind_stats(self, stats: FleetStats) -> None:
        """Read the gauges from the database (through ``stats``) on every collection."""
        self.active_cars.set_function(_safe(stats.active_cars, "drivenow_active_cars"))
        self.ongoing_rentals.set_function(_safe(stats.ongoing_rentals, "drivenow_ongoing_rentals"))

    # --- Exposition ---------------------------------------------------------------------

    def render(self) -> tuple[bytes, str]:
        """The registry in the Prometheus text format, with its content type."""
        return generate_latest(self.registry), CONTENT_TYPE_LATEST


def _safe(read: Callable[[], int], metric: str) -> Callable[[], float]:
    """Wrap a DB read so a failure yields NaN (and a log line) instead of breaking /metrics."""

    def value() -> float:
        try:
            return float(read())
        except Exception:
            logger.exception("Could not read %s from the database", metric)
            return math.nan

    return value
