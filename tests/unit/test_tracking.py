"""@track_operation and AppMetrics as the operation recorder."""

from __future__ import annotations

import pytest

from drivenow.domain.exceptions import CarNotFoundError
from drivenow.observability.metrics import AppMetrics
from drivenow.observability.tracking import track_operation


class RecordingRecorder:
    def __init__(self) -> None:
        self.observed: list[tuple[str, float]] = []
        self.failures: list[tuple[str, str]] = []

    def observe(self, operation: str, seconds: float) -> None:
        self.observed.append((operation, seconds))

    def failed(self, operation: str, code: str) -> None:
        self.failures.append((operation, code))


class Service:
    def __init__(self, recorder=None) -> None:
        self._operation_recorder = recorder

    @track_operation("ok_op")
    def ok(self, value: int, *, double: bool = False) -> int:
        return value * 2 if double else value

    @track_operation("not_found_op")
    def not_found(self) -> None:
        raise CarNotFoundError(7)

    @track_operation("crash_op")
    def crash(self) -> None:
        raise RuntimeError("boom")


def test_records_duration_on_success_and_passes_result_through():
    recorder = RecordingRecorder()
    assert Service(recorder).ok(21, double=True) == 42
    assert [name for name, _ in recorder.observed] == ["ok_op"]
    assert recorder.observed[0][1] >= 0
    assert recorder.failures == []


def test_domain_error_is_counted_under_its_code_and_reraised():
    recorder = RecordingRecorder()
    with pytest.raises(CarNotFoundError):
        Service(recorder).not_found()
    assert recorder.failures == [("not_found_op", "CAR_NOT_FOUND")]
    assert [name for name, _ in recorder.observed] == ["not_found_op"]


def test_unexpected_error_is_counted_as_internal_error():
    recorder = RecordingRecorder()
    with pytest.raises(RuntimeError):
        Service(recorder).crash()
    assert recorder.failures == [("crash_op", "INTERNAL_ERROR")]
    assert [name for name, _ in recorder.observed] == ["crash_op"]


def test_works_without_a_recorder():
    assert Service().ok(1) == 1


def test_app_metrics_records_operations_and_failures():
    metrics = AppMetrics()
    service = Service(metrics)
    service.ok(1)
    service.ok(2)
    with pytest.raises(CarNotFoundError):
        service.not_found()

    value = metrics.registry.get_sample_value
    assert value("drivenow_operation_duration_seconds_count", {"operation": "ok_op"}) == 2
    assert value("drivenow_operation_duration_seconds_sum", {"operation": "ok_op"}) >= 0
    assert value("drivenow_operation_duration_seconds_count", {"operation": "not_found_op"}) == 1
    assert value("drivenow_operation_failures_total", {"operation": "not_found_op", "code": "CAR_NOT_FOUND"}) == 1
    assert value("drivenow_operation_failures_total", {"operation": "ok_op", "code": "CAR_NOT_FOUND"}) is None


def test_each_app_metrics_has_its_own_registry():
    first, second = AppMetrics(), AppMetrics()  # no "Duplicated timeseries" error
    first.observe("add_car", 0.1)
    assert first.registry.get_sample_value("drivenow_operation_duration_seconds_count", {"operation": "add_car"}) == 1
    assert second.registry.get_sample_value("drivenow_operation_duration_seconds_count", {"operation": "add_car"}) is None


def test_average_request_ms():
    metrics = AppMetrics()
    assert metrics.average_request_ms() is None
    metrics.observe_request("GET", "/cars", 200, 0.010)
    metrics.observe_request("POST", "/cars", 201, 0.030)
    assert metrics.average_request_ms() == pytest.approx(20.0)


def test_gauges_read_stats_and_survive_errors():
    class Stats:
        def active_cars(self) -> int:
            return 4

        def ongoing_rentals(self) -> int:
            raise ConnectionError("db down")

    metrics = AppMetrics()
    metrics.bind_stats(Stats())
    assert metrics.registry.get_sample_value("drivenow_active_cars") == 4
    ongoing = metrics.registry.get_sample_value("drivenow_ongoing_rentals")
    assert ongoing != ongoing  # NaN
    body, content_type = metrics.render()
    assert b"drivenow_active_cars 4.0" in body
    assert content_type.startswith("text/plain")
