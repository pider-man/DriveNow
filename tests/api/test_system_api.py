"""/health, generic error handling and the OpenAPI docs."""

from __future__ import annotations

import logging

from fastapi.testclient import TestClient

from drivenow.api.dependencies import get_car_service, get_health_check

from .conftest import assert_error


def test_health_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_database_down_is_503(app, client):
    def failing_check() -> None:
        raise ConnectionError("database down")

    app.dependency_overrides[get_health_check] = lambda: failing_check
    assert_error(client.get("/health"), 503, "DATABASE_UNAVAILABLE")


def test_unknown_route_is_404_in_error_shape(client):
    assert_error(client.get("/nope"), 404, "NOT_FOUND")


def test_wrong_method_is_405_in_error_shape(client):
    assert_error(client.put("/cars"), 405, "METHOD_NOT_ALLOWED")


def test_unexpected_exception_is_generic_500_and_logged(app, caplog):
    class BrokenService:
        def list_cars(self, status=None):
            raise RuntimeError("secret internal detail")

    app.dependency_overrides[get_car_service] = lambda: BrokenService()
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/cars")

    error = assert_error(response, 500, "INTERNAL_ERROR")
    assert error["message"] == "Internal server error"
    assert "secret" not in response.text

    records = [r for r in caplog.records if r.levelno == logging.ERROR and r.name == "drivenow.api.errors"]
    assert records and records[0].exc_info is not None
    assert "Unhandled error on GET /cars" in records[0].getMessage()


def test_swagger_docs_and_openapi(client):
    assert client.get("/docs").status_code == 200
    paths = client.get("/openapi.json").json()["paths"]
    routes = {(method.upper(), path) for path, ops in paths.items() for method in ops}
    assert routes == {
        ("POST", "/cars"),
        ("GET", "/cars"),
        ("GET", "/cars/{car_id}"),
        ("PATCH", "/cars/{car_id}"),
        ("DELETE", "/cars/{car_id}"),
        ("POST", "/rentals"),
        ("POST", "/rentals/{rental_id}/end"),
        ("GET", "/rentals"),
        ("GET", "/rentals/{rental_id}"),
        ("GET", "/health"),
        ("GET", "/metrics"),
        ("GET", "/stats"),
    }
