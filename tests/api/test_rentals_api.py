"""Rental endpoints: F4, F5, F7 and their error mappings."""

from __future__ import annotations

from .conftest import NOW_ISO, assert_error

# --- POST /rentals (F4) ---------------------------------------------------------------


def test_start_rental_returns_201_and_iso_utc_times(client, new_car):
    car = new_car()
    response = client.post("/rentals", json={"car_id": car["id"], "customer_name": "Dana Levi"})
    assert response.status_code == 201
    assert response.json() == {
        "id": 1,
        "car_id": car["id"],
        "customer_name": "Dana Levi",
        "start_date": NOW_ISO,
        "end_date": None,
    }
    assert client.get(f"/cars/{car['id']}").json()["status"] == "in_use"


def test_start_rental_naive_time_is_utc(client, new_car, new_rental):
    car = new_car()
    rental = new_rental(car["id"], start_date="2026-10-01T08:00:00")
    assert rental["start_date"] == "2026-10-01T08:00:00Z"


def test_start_rental_offset_time_is_converted_to_utc(client, new_car, new_rental):
    car = new_car()
    rental = new_rental(car["id"], start_date="2026-10-01T10:00:00+03:00")
    assert rental["start_date"] == "2026-10-01T07:00:00Z"


def test_start_rental_car_not_found_is_404(client):
    assert_error(client.post("/rentals", json={"car_id": 99, "customer_name": "Dana"}), 404, "CAR_NOT_FOUND")


def test_start_rental_car_not_available_is_409(client, new_car, new_rental):
    maintenance = new_car(status="under_maintenance")
    assert_error(
        client.post("/rentals", json={"car_id": maintenance["id"], "customer_name": "Dana"}), 409, "CAR_NOT_AVAILABLE"
    )
    rented = new_car()
    new_rental(rented["id"])
    assert_error(
        client.post("/rentals", json={"car_id": rented["id"], "customer_name": "Noa"}), 409, "CAR_NOT_AVAILABLE"
    )


def test_start_rental_in_future_is_422(client, new_car):
    car = new_car()
    body = {"car_id": car["id"], "customer_name": "Dana", "start_date": "2026-10-01T12:00:01Z"}
    assert_error(client.post("/rentals", json=body), 422, "DATE_IN_FUTURE")


def test_start_before_previous_end_is_422(client, new_car, new_rental):
    car = new_car()
    first = new_rental(car["id"], start_date="2026-10-01T08:00:00Z")
    client.post(f"/rentals/{first['id']}/end", json={"end_date": "2026-10-01T10:00:00Z"})
    body = {"car_id": car["id"], "customer_name": "Noa", "start_date": "2026-10-01T09:00:00Z"}
    assert_error(client.post("/rentals", json=body), 422, "START_BEFORE_PREVIOUS_END")


def test_start_rental_request_validation_is_422(client, new_car):
    car = new_car()
    assert_error(client.post("/rentals", json={"car_id": car["id"]}), 422, "VALIDATION_ERROR")
    assert_error(client.post("/rentals", json={"car_id": car["id"], "customer_name": ""}), 422, "VALIDATION_ERROR")
    body = {"car_id": car["id"], "customer_name": "Dana", "start_date": "yesterday"}
    assert_error(client.post("/rentals", json=body), 422, "VALIDATION_ERROR")


# --- POST /rentals/{id}/end (F5) ------------------------------------------------------


def test_end_rental_without_body(client, new_car, new_rental):
    car = new_car()
    rental = new_rental(car["id"], start_date="2026-10-01T08:00:00Z")
    response = client.post(f"/rentals/{rental['id']}/end")
    assert response.status_code == 200
    assert response.json() == {**rental, "end_date": NOW_ISO}
    assert client.get(f"/cars/{car['id']}").json()["status"] == "available"


def test_end_rental_with_end_date(client, new_car, new_rental):
    car = new_car()
    rental = new_rental(car["id"], start_date="2026-10-01T08:00:00Z")
    response = client.post(f"/rentals/{rental['id']}/end", json={"end_date": "2026-10-01T09:30:00"})
    assert response.status_code == 200
    assert response.json()["end_date"] == "2026-10-01T09:30:00Z"


def test_end_rental_with_empty_body(client, new_car, new_rental):
    car = new_car()
    rental = new_rental(car["id"], start_date="2026-10-01T08:00:00Z")
    response = client.post(f"/rentals/{rental['id']}/end", json={})
    assert response.status_code == 200
    assert response.json()["end_date"] == NOW_ISO


def test_end_rental_twice_is_409(client, new_car, new_rental):
    rental = new_rental(new_car()["id"], start_date="2026-10-01T08:00:00Z")
    client.post(f"/rentals/{rental['id']}/end")
    assert_error(client.post(f"/rentals/{rental['id']}/end"), 409, "RENTAL_ALREADY_ENDED")


def test_end_before_start_is_422(client, new_car, new_rental):
    rental = new_rental(new_car()["id"], start_date="2026-10-01T08:00:00Z")
    response = client.post(f"/rentals/{rental['id']}/end", json={"end_date": "2026-10-01T07:59:00Z"})
    assert_error(response, 422, "END_BEFORE_START")


def test_end_in_future_is_422(client, new_car, new_rental):
    rental = new_rental(new_car()["id"], start_date="2026-10-01T08:00:00Z")
    response = client.post(f"/rentals/{rental['id']}/end", json={"end_date": "2026-10-02T08:00:00Z"})
    assert_error(response, 422, "DATE_IN_FUTURE")


def test_end_rental_not_found_is_404(client):
    assert_error(client.post("/rentals/99/end"), 404, "RENTAL_NOT_FOUND")


# --- GET /rentals, GET /rentals/{id} (F7) ---------------------------------------------


def test_get_rental(client, new_car, new_rental):
    rental = new_rental(new_car()["id"])
    response = client.get(f"/rentals/{rental['id']}")
    assert response.status_code == 200
    assert response.json() == rental


def test_get_rental_not_found_is_404(client):
    error = assert_error(client.get("/rentals/99"), 404, "RENTAL_NOT_FOUND")
    assert error["message"] == "Rental 99 not found"


def test_list_rentals_with_filters(client, new_car, new_rental):
    car1, car2 = new_car(model="One"), new_car(model="Two")
    finished = new_rental(car1["id"], start_date="2026-10-01T06:00:00Z")
    client.post(f"/rentals/{finished['id']}/end", json={"end_date": "2026-10-01T07:00:00Z"})
    ongoing1 = new_rental(car1["id"], start_date="2026-10-01T08:00:00Z")
    ongoing2 = new_rental(car2["id"])

    def ids(**params):
        response = client.get("/rentals", params=params)
        assert response.status_code == 200
        return [r["id"] for r in response.json()]

    assert ids() == [finished["id"], ongoing1["id"], ongoing2["id"]]
    assert ids(car_id=car1["id"]) == [finished["id"], ongoing1["id"]]
    assert ids(ongoing="true") == [ongoing1["id"], ongoing2["id"]]
    assert ids(ongoing="false") == [finished["id"]]
    assert ids(car_id=car2["id"], ongoing="false") == []


def test_list_rentals_bad_filter_is_422(client):
    assert_error(client.get("/rentals", params={"ongoing": "maybe"}), 422, "VALIDATION_ERROR")
    assert_error(client.get("/rentals", params={"car_id": "x"}), 422, "VALIDATION_ERROR")
