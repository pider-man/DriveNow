"""Car endpoints: F1, F2, F3, F6, F7 and their error mappings."""

from __future__ import annotations

import pytest

from .conftest import NOW, assert_error

# --- POST /cars (F1) ------------------------------------------------------------------


def test_add_car_returns_201_and_the_car(client):
    response = client.post("/cars", json={"model": "Toyota Corolla", "year": 2022})
    assert response.status_code == 201
    assert response.json() == {"id": 1, "model": "Toyota Corolla", "year": 2022, "status": "available"}


def test_add_car_under_maintenance(client):
    response = client.post("/cars", json={"model": "Mazda 3", "year": 2020, "status": "under_maintenance"})
    assert response.status_code == 201
    assert response.json()["status"] == "under_maintenance"


def test_add_car_in_use_is_422(client):
    error = assert_error(
        client.post("/cars", json={"model": "Mazda 3", "year": 2020, "status": "in_use"}), 422, "VALIDATION_ERROR"
    )
    assert "status" in error["message"]


@pytest.mark.parametrize(
    "body",
    [
        {"year": 2022},
        {"model": "Toyota", "year": "old"},
        {"model": "", "year": 2022},
        {"model": "Toyota", "year": 2022, "color": "red"},
    ],
    ids=["missing-model", "bad-year-type", "empty-model", "unknown-field"],
)
def test_add_car_request_validation_is_422(client, body):
    assert_error(client.post("/cars", json=body), 422, "VALIDATION_ERROR")


@pytest.mark.parametrize("year", [1885, NOW.year + 2])
def test_add_car_unrealistic_year_is_422(client, year):
    error = assert_error(client.post("/cars", json={"model": "Toyota", "year": year}), 422, "VALIDATION_ERROR")
    assert "year" in error["message"]


def test_add_car_blank_model_is_422(client):
    # Passes the schema (length 3) but the service rejects a blank name (B8).
    assert_error(client.post("/cars", json={"model": "   ", "year": 2022}), 422, "VALIDATION_ERROR")


def test_invalid_json_is_422(client):
    response = client.post("/cars", content="{not json", headers={"content-type": "application/json"})
    assert_error(response, 422, "VALIDATION_ERROR")


# --- GET /cars, GET /cars/{id} (F3, F7) -----------------------------------------------


def test_list_cars_with_and_without_status(client, new_car):
    a = new_car(model="A")
    b = new_car(model="B", status="under_maintenance")
    assert [c["id"] for c in client.get("/cars").json()] == [a["id"], b["id"]]
    assert client.get("/cars", params={"status": "available"}).json() == [a]
    assert client.get("/cars", params={"status": "under_maintenance"}).json() == [b]
    assert client.get("/cars", params={"status": "in_use"}).json() == []


def test_list_cars_unknown_status_is_422(client):
    assert_error(client.get("/cars", params={"status": "stolen"}), 422, "VALIDATION_ERROR")


def test_get_car(client, new_car):
    car = new_car()
    response = client.get(f"/cars/{car['id']}")
    assert response.status_code == 200
    assert response.json() == car


def test_get_car_not_found_is_404(client):
    error = assert_error(client.get("/cars/99"), 404, "CAR_NOT_FOUND")
    assert error["message"] == "Car 99 not found"


def test_non_integer_id_is_422(client):
    assert_error(client.get("/cars/abc"), 422, "VALIDATION_ERROR")


# --- PATCH /cars/{id} (F2) ------------------------------------------------------------


def test_update_car(client, new_car):
    car = new_car()
    response = client.patch(f"/cars/{car['id']}", json={"model": "Toyota Yaris", "status": "under_maintenance"})
    assert response.status_code == 200
    assert response.json() == {**car, "model": "Toyota Yaris", "status": "under_maintenance"}
    assert client.get(f"/cars/{car['id']}").json()["status"] == "under_maintenance"


def test_update_car_empty_body_is_422(client, new_car):
    car = new_car()
    assert_error(client.patch(f"/cars/{car['id']}", json={}), 422, "VALIDATION_ERROR")


def test_update_car_unknown_field_is_422(client, new_car):
    car = new_car()
    assert_error(client.patch(f"/cars/{car['id']}", json={"colour": "red"}), 422, "VALIDATION_ERROR")


def test_update_car_to_in_use_is_422(client, new_car):
    car = new_car()
    assert_error(client.patch(f"/cars/{car['id']}", json={"status": "in_use"}), 422, "VALIDATION_ERROR")


def test_update_car_not_found_is_404(client):
    assert_error(client.patch("/cars/99", json={"model": "X"}), 404, "CAR_NOT_FOUND")


def test_update_rented_car_status_is_409_but_model_is_ok(client, new_car, new_rental):
    car = new_car()
    new_rental(car["id"])
    assert_error(client.patch(f"/cars/{car['id']}", json={"status": "under_maintenance"}), 409, "CAR_RENTED")
    response = client.patch(f"/cars/{car['id']}", json={"model": "Toyota Corolla Hybrid"})
    assert response.status_code == 200
    assert response.json()["status"] == "in_use"


# --- DELETE /cars/{id} (F6) -----------------------------------------------------------


def test_delete_car_returns_204_then_404(client, new_car):
    car = new_car()
    response = client.delete(f"/cars/{car['id']}")
    assert response.status_code == 204
    assert response.content == b""
    assert_error(client.get(f"/cars/{car['id']}"), 404, "CAR_NOT_FOUND")
    assert_error(client.delete(f"/cars/{car['id']}"), 404, "CAR_NOT_FOUND")


def test_delete_rented_car_is_409(client, new_car, new_rental):
    car = new_car()
    new_rental(car["id"])
    assert_error(client.delete(f"/cars/{car['id']}"), 409, "CAR_RENTED")
    assert client.get(f"/cars/{car['id']}").status_code == 200
