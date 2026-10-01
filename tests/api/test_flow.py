"""End-to-end flow through the API: add, rent, end, delete."""

from __future__ import annotations

from .conftest import NOW_ISO


def test_full_rental_flow(client, publisher):
    # Add a car.
    response = client.post("/cars", json={"model": "Toyota Corolla", "year": 2022})
    assert response.status_code == 201
    car_id = response.json()["id"]
    assert response.json()["status"] == "available"

    # Rent it; it's now in use.
    response = client.post(
        "/rentals", json={"car_id": car_id, "customer_name": "Dana Levi", "start_date": "2026-10-01T09:00:00Z"}
    )
    assert response.status_code == 201
    rental_id = response.json()["id"]
    assert client.get(f"/cars/{car_id}").json()["status"] == "in_use"
    assert [r["id"] for r in client.get("/rentals", params={"ongoing": "true"}).json()] == [rental_id]

    # End the rental; the car is available again.
    response = client.post(f"/rentals/{rental_id}/end")
    assert response.status_code == 200
    assert response.json()["end_date"] == NOW_ISO
    assert client.get(f"/cars/{car_id}").json()["status"] == "available"
    assert client.get("/rentals", params={"ongoing": "true"}).json() == []

    # Delete the car; its finished rental goes with it (B9).
    assert client.delete(f"/cars/{car_id}").status_code == 204
    assert client.get(f"/cars/{car_id}").status_code == 404
    assert client.get(f"/rentals/{rental_id}").status_code == 404

    assert [e.name for e in publisher.events] == ["car.created", "rental.started", "rental.ended", "car.deleted"]
