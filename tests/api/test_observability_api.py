"""Logging, /metrics and /stats through the running app."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families

from drivenow.api.dependencies import get_car_service

from .conftest import assert_error


def metric_value(text: str, name: str, labels: dict[str, str] | None = None) -> float | None:
    for family in text_string_to_metric_families(text):
        for sample in family.samples:
            if sample.name == name and (labels or {}) == {k: sample.labels[k] for k in (labels or {})}:
                if labels is None and sample.labels:
                    continue
                return sample.value
    return None


# --- Logging ------------------------------------------------------------------------


def test_critical_actions_reach_console_and_log_file(app, log_file, capsys):
    with TestClient(app) as client:  # setup_logging runs in the lifespan, after capsys is active
        car_id = client.post("/cars", json={"model": "Toyota Corolla", "year": 2022}).json()["id"]
        client.patch(f"/cars/{car_id}", json={"year": 2023})
        rental_id = client.post("/rentals", json={"car_id": car_id, "customer_name": "Dana Levi"}).json()["id"]
        assert_error(client.post("/rentals", json={"car_id": car_id, "customer_name": "Noa"}), 409, "CAR_NOT_AVAILABLE")
        client.post(f"/rentals/{rental_id}/end")
        assert client.delete(f"/cars/{car_id}").status_code == 204

    class BrokenService:
        def list_cars(self, status=None):
            raise RuntimeError("boom")

    app.dependency_overrides[get_car_service] = lambda: BrokenService()
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/cars").status_code == 500

    expected = [
        "INFO    [drivenow.api.app] DriveNow API started: database=sqlite:// publisher=InMemoryPublisher",
        "INFO    [drivenow.services.car_service] Car added: id=1 model='Toyota Corolla' year=2022 status=available",
        "INFO    [drivenow.services.car_service] Car updated: id=1 changed=year",
        "INFO    [drivenow.services.rental_service] Rental started: id=1 car_id=1 customer='Dana Levi'",
        "WARNING [drivenow.services.rental_service] start_rental rejected: CAR_NOT_AVAILABLE",
        "INFO    [drivenow.services.rental_service] Rental ended: id=1 car_id=1",
        "INFO    [drivenow.services.car_service] Car deleted: id=1 deleted_rentals=1",
        "ERROR   [drivenow.api.errors] Unhandled error on GET /cars",
    ]
    file_text = Path(log_file).read_text(encoding="utf-8")
    console_text = capsys.readouterr().out
    for fragment in expected:
        assert fragment in file_text, fragment
        assert fragment in console_text, fragment
    assert "Traceback (most recent call last)" in file_text
    assert "RuntimeError: boom" in file_text


# --- /metrics -----------------------------------------------------------------------


def test_metrics_gauges_follow_the_database(client, new_car, new_rental):
    a = new_car(model="A")
    new_car(model="B")
    new_car(model="C", status="under_maintenance")
    rental = new_rental(a["id"])

    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    text = response.text
    assert metric_value(text, "drivenow_active_cars") == 2
    assert metric_value(text, "drivenow_ongoing_rentals") == 1

    client.post(f"/rentals/{rental['id']}/end")
    client.patch(f"/cars/{a['id']}", json={"status": "under_maintenance"})
    text = client.get("/metrics").text
    assert metric_value(text, "drivenow_active_cars") == 1
    assert metric_value(text, "drivenow_ongoing_rentals") == 0


def test_metrics_request_histogram_uses_route_templates(client, new_car):
    first, second = new_car(), new_car()
    client.get(f"/cars/{first['id']}")
    client.get(f"/cars/{second['id']}")
    client.get("/cars/999")
    client.get("/nope")

    text = client.get("/metrics").text
    count = "drivenow_request_duration_seconds_count"
    assert metric_value(text, count, {"method": "GET", "route": "/cars/{car_id}", "status_code": "200"}) == 2
    assert metric_value(text, count, {"method": "GET", "route": "/cars/{car_id}", "status_code": "404"}) == 1
    assert metric_value(text, count, {"method": "POST", "route": "/cars", "status_code": "201"}) == 2
    assert metric_value(text, count, {"method": "GET", "route": "<unmatched>", "status_code": "404"}) == 1
    assert f'route="/cars/{first["id"]}"' not in text


def test_metrics_operations_and_failures(client, new_car):
    car = new_car()
    new_car()
    new_car()
    client.post("/rentals", json={"car_id": car["id"], "customer_name": "Dana"})
    client.post("/rentals", json={"car_id": car["id"], "customer_name": "Noa"})  # 409

    text = client.get("/metrics").text
    assert metric_value(text, "drivenow_operation_duration_seconds_count", {"operation": "add_car"}) == 3
    assert metric_value(text, "drivenow_operation_duration_seconds_count", {"operation": "start_rental"}) == 2
    assert metric_value(
        text, "drivenow_operation_failures_total", {"operation": "start_rental", "code": "CAR_NOT_AVAILABLE"}
    ) == 1


# --- /stats -------------------------------------------------------------------------


def test_stats_average_is_null_until_a_measured_request(client):
    for path in ("/health", "/metrics", "/stats", "/health"):
        client.get(path)
    assert client.get("/stats").json() == {"active_cars": 0, "ongoing_rentals": 0, "avg_response_time_ms": None}


def test_stats_values_and_average_exclude_ops_endpoints(app, client, new_car, new_rental):
    a = new_car()
    new_car()
    new_car(status="under_maintenance")
    new_rental(a["id"])
    client.get("/cars")
    for path in ("/health", "/metrics", "/stats"):
        client.get(path)

    stats = client.get("/stats").json()
    assert stats["active_cars"] == 2
    assert stats["ongoing_rentals"] == 1
    assert stats["avg_response_time_ms"] > 0

    # Exactly the 5 domain requests were measured: 3 cars + 1 rental + 1 list.
    registry = app.state.container.metrics.registry
    measured = sum(
        sample.value
        for family in registry.collect()
        if family.name == "drivenow_request_duration_seconds"
        for sample in family.samples
        if sample.name.endswith("_count")
    )
    assert measured == 5
    assert app.state.container.metrics.average_request_ms() == stats["avg_response_time_ms"]


def test_two_apps_have_independent_metrics(app, client, new_car):
    from drivenow.api.app import create_app
    from drivenow.config import Settings

    new_car()
    other = create_app(Settings(database_url="sqlite://", _env_file=None))
    assert other.state.container.metrics.average_request_ms() is None
    assert app.state.container.metrics.average_request_ms() is not None
