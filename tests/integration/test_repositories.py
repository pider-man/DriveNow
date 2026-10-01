"""Data layer tests: ORM models, constraints, repositories and Unit of Work on in-memory SQLite."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateIndex, CreateTable

from drivenow.db.models import ONGOING_RENTAL_INDEX, Car, Rental
from drivenow.domain.enums import CarStatus
from drivenow.domain.exceptions import DataIntegrityError

from .conftest import T0


# --- Cars -------------------------------------------------------------------------


def test_add_and_read_car(uow, add_car):
    car = add_car(model="Mazda 3", year=2021)

    assert car.id is not None
    # Still readable after the Unit of Work has committed and closed the session.
    assert (car.model, car.year, car.status) == ("Mazda 3", 2021, CarStatus.AVAILABLE)

    with uow() as tx:
        loaded = tx.cars.get(car.id)
    assert loaded is not None
    assert (loaded.id, loaded.model, loaded.year, loaded.status) == (
        car.id,
        "Mazda 3",
        2021,
        CarStatus.AVAILABLE,
    )

    with uow() as tx:
        assert tx.cars.get(9999) is None


def test_list_cars_by_status_and_count_active(uow, add_car):
    a = add_car(model="A")
    b = add_car(model="B", status=CarStatus.UNDER_MAINTENANCE)
    c = add_car(model="C", status=CarStatus.IN_USE)

    with uow() as tx:
        assert [car.id for car in tx.cars.list()] == [a.id, b.id, c.id]
        assert [car.id for car in tx.cars.list(CarStatus.AVAILABLE)] == [a.id]
        assert [car.id for car in tx.cars.list(CarStatus.UNDER_MAINTENANCE)] == [b.id]
        assert [car.id for car in tx.cars.list(CarStatus.IN_USE)] == [c.id]
        # D5: active = not under maintenance.
        assert tx.cars.count_active() == 2


def test_update_car_status_is_saved(uow, add_car):
    car = add_car()
    with uow() as tx:
        loaded = tx.cars.get(car.id, for_update=True)
        loaded.status = CarStatus.UNDER_MAINTENANCE
        tx.commit()
    with uow() as tx:
        assert tx.cars.get(car.id).status == CarStatus.UNDER_MAINTENANCE


# --- Rentals ----------------------------------------------------------------------


def test_find_ongoing_rental_of_car(uow, add_car, add_rental):
    car = add_car()
    other = add_car(model="Other")
    add_rental(car.id, start_date=T0 - timedelta(days=5), end_date=T0 - timedelta(days=4))
    ongoing = add_rental(car.id, start_date=T0)

    with uow() as tx:
        found = tx.rentals.get_ongoing_for_car(car.id)
        assert found is not None and found.id == ongoing.id
        assert tx.rentals.get_ongoing_for_car(other.id) is None

        found.end_date = T0 + timedelta(hours=3)
        tx.commit()

    with uow() as tx:
        assert tx.rentals.get_ongoing_for_car(car.id) is None


def test_second_ongoing_rental_for_same_car_is_rejected(uow, add_car, add_rental):
    car = add_car()
    first = add_rental(car.id, customer_name="First")

    with pytest.raises(DataIntegrityError), uow() as tx:
        tx.rentals.add(Rental(car_id=car.id, customer_name="Second", start_date=T0))
        tx.commit()

    # Once the first rental ends, the car can be rented again.
    with uow() as tx:
        tx.rentals.get(first.id).end_date = T0 + timedelta(hours=1)
        tx.commit()
    second = add_rental(car.id, customer_name="Second", start_date=T0 + timedelta(hours=2))
    assert second.id is not None


def test_end_date_before_start_date_is_rejected(uow, add_car):
    car = add_car()
    with pytest.raises(DataIntegrityError), uow() as tx:
        tx.rentals.add(
            Rental(
                car_id=car.id,
                customer_name="Dana",
                start_date=T0,
                end_date=T0 - timedelta(seconds=1),
            )
        )
        tx.commit()

    with uow() as tx:
        assert tx.rentals.list() == []


def test_end_date_equal_to_start_date_is_allowed(add_car, add_rental):
    car = add_car()
    rental = add_rental(car.id, start_date=T0, end_date=T0)
    assert rental.end_date == T0


def test_rental_for_unknown_car_is_rejected(uow):
    # Proves PRAGMA foreign_keys is on for SQLite.
    with pytest.raises(DataIntegrityError), uow() as tx:
        tx.rentals.add(Rental(car_id=12345, customer_name="Dana", start_date=T0))


def test_list_rentals_filters_and_count_ongoing(uow, add_car, add_rental):
    car1 = add_car(model="One")
    car2 = add_car(model="Two")
    finished = add_rental(car1.id, start_date=T0 - timedelta(days=2), end_date=T0 - timedelta(days=1))
    ongoing1 = add_rental(car1.id)
    ongoing2 = add_rental(car2.id)

    with uow() as tx:
        assert [r.id for r in tx.rentals.list()] == [finished.id, ongoing1.id, ongoing2.id]
        assert [r.id for r in tx.rentals.list(car_id=car1.id)] == [finished.id, ongoing1.id]
        assert [r.id for r in tx.rentals.list(ongoing=True)] == [ongoing1.id, ongoing2.id]
        assert [r.id for r in tx.rentals.list(ongoing=False)] == [finished.id]
        assert [r.id for r in tx.rentals.list(car_id=car1.id, ongoing=False)] == [finished.id]
        assert tx.rentals.count_ongoing() == 2


def test_get_latest_end_for_car(uow, add_car, add_rental):
    car = add_car()
    other = add_car(model="Other")
    add_rental(car.id, start_date=T0 - timedelta(days=5), end_date=T0 - timedelta(days=4))
    add_rental(car.id, start_date=T0 - timedelta(days=3), end_date=T0 - timedelta(days=2))
    add_rental(car.id, start_date=T0)  # ongoing: ignored
    add_rental(other.id, start_date=T0 - timedelta(days=1), end_date=T0 - timedelta(hours=1))

    with uow() as tx:
        latest = tx.rentals.get_latest_end_for_car(car.id)
        assert latest == T0 - timedelta(days=2)
        assert latest.tzinfo is not None
        assert tx.rentals.get_latest_end_for_car(add_car(model="New").id) is None


# --- Deleting cars (FK ON DELETE RESTRICT) ----------------------------------------


def test_deleting_car_with_rentals_is_rejected_by_database(uow, add_car, add_rental):
    car = add_car()
    add_rental(car.id, start_date=T0 - timedelta(days=2), end_date=T0 - timedelta(days=1))

    with pytest.raises(DataIntegrityError), uow() as tx:
        tx.cars.delete(tx.cars.get(car.id))
        tx.commit()

    with uow() as tx:
        assert tx.cars.get(car.id) is not None
        assert len(tx.rentals.list(car_id=car.id)) == 1


def test_car_can_be_deleted_after_its_finished_rentals_are_deleted(uow, add_car, add_rental):
    car = add_car()
    other = add_car(model="Other")
    add_rental(car.id, start_date=T0 - timedelta(days=4), end_date=T0 - timedelta(days=3))
    add_rental(car.id, start_date=T0 - timedelta(days=2), end_date=T0 - timedelta(days=1))
    other_rental = add_rental(other.id, start_date=T0 - timedelta(days=2), end_date=T0 - timedelta(days=1))

    with uow() as tx:
        assert tx.rentals.delete_finished_for_car(car.id) == 2
        tx.cars.delete(tx.cars.get(car.id))
        tx.commit()

    with uow() as tx:
        assert tx.cars.get(car.id) is None
        assert tx.rentals.list(car_id=car.id) == []
        assert [r.id for r in tx.rentals.list()] == [other_rental.id]


def test_delete_finished_keeps_ongoing_rental(uow, add_car, add_rental):
    car = add_car()
    add_rental(car.id, start_date=T0 - timedelta(days=2), end_date=T0 - timedelta(days=1))
    ongoing = add_rental(car.id)

    with uow() as tx:
        assert tx.rentals.delete_finished_for_car(car.id) == 1
        tx.commit()

    with uow() as tx:
        assert [r.id for r in tx.rentals.list(car_id=car.id)] == [ongoing.id]


# --- Unit of Work -----------------------------------------------------------------


def test_uow_does_not_persist_without_commit(uow):
    with uow() as tx:
        tx.cars.add(Car(model="Uncommitted", year=2020))
    with uow() as tx:
        assert tx.cars.list() == []


def test_uow_rolls_back_on_exception(uow, add_car):
    car = add_car()
    with pytest.raises(RuntimeError), uow() as tx:
        tx.cars.get(car.id).status = CarStatus.UNDER_MAINTENANCE
        tx.cars.add(Car(model="Rolled back", year=2020))
        raise RuntimeError("boom")

    with uow() as tx:
        assert [c.id for c in tx.cars.list()] == [car.id]
        assert tx.cars.get(car.id).status == CarStatus.AVAILABLE


def test_uow_explicit_rollback(uow):
    with uow() as tx:
        tx.cars.add(Car(model="Temp", year=2020))
        tx.rollback()
        assert tx.cars.list() == []


def test_uow_outside_with_block_raises(uow):
    with pytest.raises(RuntimeError):
        uow().commit()


# --- Dates (D7) -------------------------------------------------------------------


def test_dates_are_stored_and_returned_as_aware_utc(uow, add_car, add_rental):
    car = add_car()
    naive_start = datetime(2026, 10, 1, 8, 0)  # treated as UTC
    israel = timezone(timedelta(hours=3))
    end_in_israel = datetime(2026, 10, 1, 14, 0, tzinfo=israel)  # 11:00 UTC

    rental = add_rental(car.id, start_date=naive_start, end_date=end_in_israel)

    with uow() as tx:
        loaded = tx.rentals.get(rental.id)
    assert loaded.start_date == datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
    assert loaded.start_date.tzinfo is not None
    assert loaded.end_date == datetime(2026, 10, 1, 11, 0, tzinfo=UTC)
    assert loaded.end_date.utcoffset() == timedelta(0)


def test_end_before_start_detected_across_time_zones(uow, add_car):
    # 10:00+03:00 is 07:00 UTC, which is before a 08:00 UTC start.
    car = add_car()
    with pytest.raises(DataIntegrityError), uow() as tx:
        tx.rentals.add(
            Rental(
                car_id=car.id,
                customer_name="Dana",
                start_date=datetime(2026, 10, 1, 8, 0, tzinfo=UTC),
                end_date=datetime(2026, 10, 1, 10, 0, tzinfo=timezone(timedelta(hours=3))),
            )
        )


# --- Schema -----------------------------------------------------------------------


def test_schema_has_exactly_the_prd_fields(engine):
    inspector = inspect(engine)
    assert set(inspector.get_table_names()) == {"cars", "rentals"}

    car_columns = {c["name"]: c for c in inspector.get_columns("cars")}
    rental_columns = {c["name"]: c for c in inspector.get_columns("rentals")}
    assert set(car_columns) == {"id", "model", "year", "status"}
    assert set(rental_columns) == {"id", "car_id", "customer_name", "start_date", "end_date"}

    assert not any(c["nullable"] for name, c in car_columns.items() if name != "id")
    assert rental_columns["end_date"]["nullable"] is True
    assert not rental_columns["start_date"]["nullable"]

    [fk] = inspector.get_foreign_keys("rentals")
    assert fk["referred_table"] == "cars" and fk["constrained_columns"] == ["car_id"]
    assert fk["options"].get("ondelete") == "RESTRICT"


def test_invalid_status_is_rejected_by_database(engine):
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO cars (model, year, status) VALUES ('X', 2020, 'stolen')"
        )


@pytest.mark.parametrize("dialect", [postgresql.dialect(), sqlite.dialect()], ids=["postgresql", "sqlite"])
def test_ddl_compiles_with_rule_backups(dialect):
    index_ddl = str(CreateIndex(ONGOING_RENTAL_INDEX).compile(dialect=dialect))
    assert "CREATE UNIQUE INDEX ix_rentals_one_ongoing_per_car ON rentals (car_id)" in index_ddl
    assert "WHERE end_date IS NULL" in index_ddl

    rentals_ddl = str(CreateTable(Rental.__table__).compile(dialect=dialect))
    assert "REFERENCES cars (id) ON DELETE RESTRICT" in rentals_ddl
    assert "CHECK (end_date IS NULL OR end_date >= start_date)" in rentals_ddl

    cars_ddl = str(CreateTable(Car.__table__).compile(dialect=dialect))
    assert "CHECK (year > 0)" in cars_ddl
    assert "'available', 'in_use', 'under_maintenance'" in cars_ddl
