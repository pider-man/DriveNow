"""CarService: rules B4, B5, B6, B8, B9 and not-found cases."""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest

from drivenow.domain.enums import CarStatus
from drivenow.domain.exceptions import (
    CarNotFoundError,
    CarRentedError,
    DataIntegrityError,
    InvalidInputError,
)
from drivenow.domain.records import CarRecord

from .fakes import NOW

# --- B6: initial status -----------------------------------------------------------


def test_new_car_defaults_to_available(car_service, db):
    car = car_service.add_car("Toyota Corolla", 2022)
    assert car == CarRecord(id=car.id, model="Toyota Corolla", year=2022, status=CarStatus.AVAILABLE)
    assert db.cars[car.id].status == CarStatus.AVAILABLE
    assert db.journal == ["commit", "publish:car.created"]


def test_new_car_can_start_under_maintenance(car_service):
    car = car_service.add_car("Mazda 3", 2020, status=CarStatus.UNDER_MAINTENANCE)
    assert car.status == CarStatus.UNDER_MAINTENANCE
    assert car_service.add_car("Kia", 2020, status="under_maintenance").status == CarStatus.UNDER_MAINTENANCE


# --- B4: in_use only through rentals ----------------------------------------------


def test_add_car_with_in_use_status_rejected(car_service, db, publisher):
    with pytest.raises(InvalidInputError) as err:
        car_service.add_car("Toyota Corolla", 2022, status=CarStatus.IN_USE)
    assert err.value.code == "VALIDATION_ERROR"
    assert err.value.field == "status"
    assert db.cars == {} and publisher.events == []


def test_update_car_to_in_use_rejected(car_service, db):
    car = db.seed_car()
    with pytest.raises(InvalidInputError) as err:
        car_service.update_car(car.id, status=CarStatus.IN_USE)
    assert err.value.code == "VALIDATION_ERROR"
    assert db.cars[car.id].status == CarStatus.AVAILABLE


def test_unknown_status_rejected(car_service, db):
    car = db.seed_car()
    with pytest.raises(InvalidInputError):
        car_service.add_car("X", 2020, status="stolen")
    with pytest.raises(InvalidInputError):
        car_service.update_car(car.id, status="stolen")
    with pytest.raises(InvalidInputError):
        car_service.list_cars("stolen")


# --- B8: required fields and realistic year ---------------------------------------


@pytest.mark.parametrize(
    ("model", "year", "field"),
    [
        ("", 2022, "model"),
        ("   ", 2022, "model"),
        ("x" * 101, 2022, "model"),
        ("Toyota", 1885, "year"),
        ("Toyota", NOW.year + 2, "year"),
        ("Toyota", True, "year"),
    ],
    ids=["empty-model", "blank-model", "long-model", "year-1885", "year-too-new", "year-bool"],
)
def test_add_car_rejects_invalid_input(car_service, db, model, year, field):
    with pytest.raises(InvalidInputError) as err:
        car_service.add_car(model, year)
    assert err.value.code == "VALIDATION_ERROR"
    assert err.value.field == field
    assert db.cars == {}


def test_add_car_accepts_year_bounds(car_service):
    assert car_service.add_car("Benz Patent-Motorwagen", 1886).year == 1886
    assert car_service.add_car("Next year's model", NOW.year + 1).year == NOW.year + 1


def test_text_is_stripped(car_service):
    assert car_service.add_car("  Toyota Corolla  ", 2022).model == "Toyota Corolla"


def test_update_car_validates_fields(car_service, db):
    car = db.seed_car()
    with pytest.raises(InvalidInputError) as err:
        car_service.update_car(car.id, model="  ")
    assert err.value.field == "model"
    with pytest.raises(InvalidInputError) as err:
        car_service.update_car(car.id, year=1800)
    assert err.value.field == "year"
    assert db.cars[car.id].model == "Toyota Corolla"


def test_update_car_requires_a_field(car_service, db):
    car = db.seed_car()
    with pytest.raises(InvalidInputError) as err:
        car_service.update_car(car.id)
    assert err.value.code == "VALIDATION_ERROR"


# --- F2 update --------------------------------------------------------------------


def test_update_car_saves_changed_fields(car_service, db, publisher):
    car = db.seed_car()
    updated = car_service.update_car(car.id, model="Toyota Yaris", status=CarStatus.UNDER_MAINTENANCE)
    assert updated == CarRecord(car.id, "Toyota Yaris", 2022, CarStatus.UNDER_MAINTENANCE)
    assert db.journal == [f"lock:car:{car.id}", "commit", "publish:car.updated"]
    assert publisher.events[0].payload["changed_fields"] == ["model", "status"]

    back = car_service.update_car(car.id, status="available")
    assert back.status == CarStatus.AVAILABLE


def test_update_with_no_actual_change_publishes_nothing(car_service, db, publisher):
    car = db.seed_car()
    record = car_service.update_car(car.id, model="Toyota Corolla", year=2022)
    assert record.model == "Toyota Corolla"
    assert "commit" not in db.journal
    assert publisher.events == []


# --- B5: rented car -----------------------------------------------------------------


def test_cannot_change_status_of_rented_car(car_service, db, publisher):
    car = db.seed_car(status=CarStatus.IN_USE)
    db.seed_rental(car.id, start_date=NOW - timedelta(hours=1))
    for status in (CarStatus.AVAILABLE, CarStatus.UNDER_MAINTENANCE):
        with pytest.raises(CarRentedError) as err:
            car_service.update_car(car.id, status=status)
        assert err.value.code == "CAR_RENTED"
    assert db.cars[car.id].status == CarStatus.IN_USE
    assert publisher.events == []


def test_can_edit_model_and_year_of_rented_car(car_service, db):
    car = db.seed_car(status=CarStatus.IN_USE)
    db.seed_rental(car.id, start_date=NOW - timedelta(hours=1))
    updated = car_service.update_car(car.id, model="Toyota Corolla Hybrid", year=2023)
    assert (updated.model, updated.year, updated.status) == ("Toyota Corolla Hybrid", 2023, CarStatus.IN_USE)


def test_cannot_delete_rented_car(car_service, db, publisher):
    car = db.seed_car(status=CarStatus.IN_USE)
    db.seed_rental(car.id, start_date=NOW - timedelta(days=3), end_date=NOW - timedelta(days=2))
    db.seed_rental(car.id, start_date=NOW - timedelta(hours=1))
    with pytest.raises(CarRentedError):
        car_service.delete_car(car.id)
    assert car.id in db.cars
    assert len(db.rentals) == 2  # history untouched
    assert publisher.events == []


def test_cannot_delete_car_with_ongoing_rental_even_if_status_is_stale(car_service, db):
    car = db.seed_car(status=CarStatus.AVAILABLE)
    db.seed_rental(car.id, start_date=NOW - timedelta(hours=1))
    with pytest.raises(CarRentedError):
        car_service.delete_car(car.id)


# --- B9: delete with finished history -----------------------------------------------


def test_delete_car_removes_finished_rentals_then_car(car_service, db, publisher):
    car = db.seed_car()
    other = db.seed_car(model="Other")
    db.seed_rental(car.id, start_date=NOW - timedelta(days=5), end_date=NOW - timedelta(days=4))
    db.seed_rental(car.id, start_date=NOW - timedelta(days=3), end_date=NOW - timedelta(days=2))
    kept = db.seed_rental(other.id, start_date=NOW - timedelta(days=3), end_date=NOW - timedelta(days=2))

    car_service.delete_car(car.id)

    assert car.id not in db.cars
    assert list(db.rentals) == [kept.id]
    # One transaction: lock, delete history, delete car, one commit, then the event.
    assert db.journal == [
        f"lock:car:{car.id}",
        f"delete_finished:car:{car.id}",
        f"delete:car:{car.id}",
        "commit",
        "publish:car.deleted",
    ]
    assert publisher.events[0].payload == {"car_id": car.id, "deleted_rentals": 2}


def test_delete_car_fk_conflict_becomes_car_rented(car_service, db):
    car = db.seed_car()
    db.fail_commit = DataIntegrityError("FOREIGN KEY constraint failed")
    with pytest.raises(CarRentedError):
        car_service.delete_car(car.id)


# --- F3 list / F7 get / not found ---------------------------------------------------


def test_list_cars_with_and_without_status(car_service, db):
    a = db.seed_car()
    b = db.seed_car(status=CarStatus.UNDER_MAINTENANCE)
    c = db.seed_car(status=CarStatus.IN_USE)
    assert [car.id for car in car_service.list_cars()] == [a.id, b.id, c.id]
    assert [car.id for car in car_service.list_cars(CarStatus.AVAILABLE)] == [a.id]
    assert [car.id for car in car_service.list_cars("under_maintenance")] == [b.id]
    assert [car.id for car in car_service.list_cars(CarStatus.IN_USE)] == [c.id]


def test_get_car(car_service, db):
    car = db.seed_car()
    assert car_service.get_car(car.id) == CarRecord(car.id, "Toyota Corolla", 2022, CarStatus.AVAILABLE)


@pytest.mark.parametrize(
    "call",
    [
        lambda s: s.get_car(99),
        lambda s: s.update_car(99, model="X"),
        lambda s: s.delete_car(99),
    ],
    ids=["get", "update", "delete"],
)
def test_car_not_found(car_service, publisher, call):
    with pytest.raises(CarNotFoundError) as err:
        call(car_service)
    assert err.value.code == "CAR_NOT_FOUND"
    assert publisher.events == []


# --- Logging ------------------------------------------------------------------------


def test_logs_critical_actions_and_rejections(car_service, db, caplog):
    caplog.set_level(logging.INFO, logger="drivenow")
    car = car_service.add_car("Toyota Corolla", 2022)
    car_service.update_car(car.id, status=CarStatus.UNDER_MAINTENANCE)
    car_service.delete_car(car.id)
    with pytest.raises(CarNotFoundError):
        car_service.delete_car(car.id)

    messages = [(r.levelname, r.getMessage()) for r in caplog.records]
    assert ("INFO", f"Car added: id={car.id} model='Toyota Corolla' year=2022 status=available") in messages
    assert any(lvl == "INFO" and msg.startswith(f"Car updated: id={car.id} changed=status") for lvl, msg in messages)
    assert ("INFO", f"Car deleted: id={car.id} deleted_rentals=0") in messages
    assert ("WARNING", f"delete_car rejected: CAR_NOT_FOUND: Car {car.id} not found") in messages
