"""API test fixtures: the real app on in-memory SQLite with a fixed clock."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from drivenow.api.app import create_app
from drivenow.config import Settings
from drivenow.messaging.publisher import InMemoryPublisher

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
NOW_ISO = "2026-10-01T12:00:00Z"


class FixedClock:
    def now(self) -> datetime:
        return NOW


@pytest.fixture
def publisher() -> InMemoryPublisher:
    return InMemoryPublisher()


@pytest.fixture
def app(publisher: InMemoryPublisher) -> FastAPI:
    settings = Settings(database_url="sqlite://", _env_file=None)
    return create_app(settings, clock=FixedClock(), publisher=publisher)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as client:  # runs the lifespan: tables are created
        yield client


@pytest.fixture
def new_car(client: TestClient):
    """Create a car through the API and return its JSON."""

    def _new_car(**fields) -> dict:
        body = {"model": "Toyota Corolla", "year": 2022, **fields}
        response = client.post("/cars", json=body)
        assert response.status_code == 201, response.text
        return response.json()

    return _new_car


@pytest.fixture
def new_rental(client: TestClient):
    """Start a rental through the API and return its JSON."""

    def _new_rental(car_id: int, **fields) -> dict:
        body = {"car_id": car_id, "customer_name": "Dana Levi", **fields}
        response = client.post("/rentals", json=body)
        assert response.status_code == 201, response.text
        return response.json()

    return _new_rental


def assert_error(response, status_code: int, code: str) -> dict:
    """Check the status and the shared error shape; return the error object."""
    assert response.status_code == status_code, response.text
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}
    assert body["error"]["code"] == code
    assert body["error"]["message"]
    return body["error"]
