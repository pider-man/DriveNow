"""RentalService: rules B1, B2, B3, B7, B8, the date decisions and not-found cases."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta, timezone

import pytest

from drivenow.domain.enums import CarStatus
from drivenow.domain.exceptions import (
    CarNotAvailableError,
    CarNotFoundError,
    DataIntegrityError,
    InvalidInputError,
    RentalAlreadyEndedError,
    RentalNotFoundError,
)

from .fakes import NOW

# --- B1: rental and car status change together --------------------------------------


def test_start_rental_sets_car_in_use_in_one_commit(rental_service, db):
    car = db.seed_car()
    rental = rental_service.start_rental(car.id, "Dana Levi")

    assert rental.car_id == car.id and rental.ongoing
    assert db.cars[car.id].status == CarStatus.IN_USE
    assert db.journal.count("commit") == 1
    assert db.journal == [f"lock:car:{car.id}", "commit", "publish:rental.started"]


def test_start_rental_locks_car_row(rental_service, db):
    car = db.seed_car()
    rental_service.start_rental(car.id, "Dana Levi")
    assert db.journal[0] == f"lock:car:{car.id}"


def test_end_rental_sets_car_available_in_one_commit(rental_service, db):
    car = db.seed_car(status=CarStatus.IN_USE)
    seeded = db.seed_rental(car.id, start_date=NOW - timedelta(hours=2))

    ended = rental_service.end_rental(seeded.id)

    assert ended.end_date == NOW and not ended.ongoing
    assert db.cars[car.id].status == CarStatus.AVAILABLE
    assert db.journal == [
        f"lock:car:{car.id}",
        f"lock:rental:{seeded.id}",
        "commit",
        "publish:rental.ended",
    ]


def test_end_rental_locks_car_before_rental(rental_service, db):
    # Same lock order as start_rental and delete_car (car first), so they can't deadlock.
    car = db.seed_car(status=CarStatus.IN_USE)
    seeded = db.seed_rental(car.id, start_date=NOW - timedelta(hours=2))
    rental_service.end_rental(seeded.id)
    locks = [entry for entry in db.journal if entry.startswith("lock:")]
    assert locks == [f"lock:car:{car.id}", f"lock:rental:{seeded.id}"]


# --- B2: only an available car can be rented ----------------------------------------


def test_cannot_rent_car_under_maintenance(rental_service, db, publisher):
    car = db.seed_car(status=CarStatus.UNDER_MAINTENANCE)
    with pytest.raises(CarNotAvailableError) as err:
        rental_service.start_rental(car.id, "Dana Levi")
    assert err.value.code == "CAR_NOT_AVAILABLE"
    assert db.rentals == {} and "commit" not in db.journal and publisher.events == []


def test_cannot_rent_car_in_use(rental_service, db):
    car = db.seed_car(status=CarStatus.IN_USE)
    db.seed_rental(car.id, start_date=NOW - timedelta(hours=1))
    with pytest.raises(CarNotAvailableError):
        rental_service.start_rental(car.id, "Second Customer")
    assert len(db.rentals) == 1


# --- B3: at most one ongoing rental per car -----------------------------------------


def test_cannot_start_second_ongoing_rental(rental_service, db):
    # The car's status says available, but an ongoing rental exists: still rejected.
    car = db.seed_car(status=CarStatus.AVAILABLE)
    db.seed_rental(car.id, start_date=NOW - timedelta(hours=1))
    with pytest.raises(CarNotAvailableError) as err:
        rental_service.start_rental(car.id, "Second Customer")
    assert "ongoing rental" in err.value.message
    assert len(db.rentals) == 1


def test_db_index_conflict_becomes_car_not_available(rental_service, db, publisher):
    # A concurrent request inserted a rental first; the partial unique index rejects ours.
    car = db.seed_car()
    db.fail_rental_add = DataIntegrityError("UNIQUE constraint failed: rentals.car_id")
    with pytest.raises(CarNotAvailableError) as err:
        rental_service.start_rental(car.id, "Dana Levi")
    assert isinstance(err.value.__cause__, DataIntegrityError)
    assert publisher.events == []


def test_rent_again_after_rental_ended(rental_service, db):
    car = db.seed_car()
    first = rental_service.start_rental(car.id, "First", start_date=NOW - timedelta(hours=3))
    rental_service.end_rental(first.id, end_date=NOW - timedelta(hours=2))
    second = rental_service.start_rental(car.id, "Second")
    assert second.ongoing and db.cars[car.id].status == CarStatus.IN_USE


# --- B7: end once, end not before start ---------------------------------------------


def test_cannot_end_rental_twice(rental_service, db, publisher):
    car = db.seed_car(status=CarStatus.IN_USE)
    rental = db.seed_rental(car.id, start_date=NOW - timedelta(hours=2))
    rental_service.end_rental(rental.id)
    publisher.events.clear()

    with pytest.raises(RentalAlreadyEndedError) as err:
        rental_service.end_rental(rental.id)
    assert err.value.code == "RENTAL_ALREADY_ENDED"
    assert db.rentals[rental.id].end_date == NOW
    assert publisher.events == []


def test_end_before_start_rejected(rental_service, db):
    car = db.seed_car(status=CarStatus.IN_USE)
    rental = db.seed_rental(car.id, start_date=NOW - timedelta(hours=2))
    with pytest.raises(InvalidInputError) as err:
        rental_service.end_rental(rental.id, end_date=NOW - timedelta(hours=3))
    assert err.value.code == "END_BEFORE_START"
    assert err.value.field == "end_date"
    assert db.rentals[rental.id].end_date is None
    assert db.cars[car.id].status == CarStatus.IN_USE


def test_end_equal_to_start_allowed(rental_service, db):
    car = db.seed_car(status=CarStatus.IN_USE)
    start = NOW - timedelta(hours=2)
    rental = db.seed_rental(car.id, start_date=start)
    assert rental_service.end_rental(rental.id, end_date=start).end_date == start


# --- B10: start not before the car's previous rental end ----------------------------


def test_start_before_previous_end_rejected(rental_service, db, publisher):
    car = db.seed_car()
    db.seed_rental(car.id, start_date=NOW - timedelta(days=3), end_date=NOW - timedelta(days=2))
    db.seed_rental(car.id, start_date=NOW - timedelta(hours=5), end_date=NOW - timedelta(hours=2))

    with pytest.raises(InvalidInputError) as err:
        rental_service.start_rental(car.id, "Dana", start_date=NOW - timedelta(hours=3))
    assert err.value.code == "START_BEFORE_PREVIOUS_END"
    assert err.value.field == "start_date"
    assert len(db.rentals) == 2
    assert db.cars[car.id].status == CarStatus.AVAILABLE
    assert publisher.events == []


def test_start_equal_to_previous_end_allowed(rental_service, db):
    car = db.seed_car()
    previous_end = NOW - timedelta(hours=2)
    db.seed_rental(car.id, start_date=NOW - timedelta(hours=5), end_date=previous_end)
    assert rental_service.start_rental(car.id, "Dana", start_date=previous_end).start_date == previous_end


def test_previous_end_of_other_car_ignored(rental_service, db):
    car = db.seed_car()
    other = db.seed_car(model="Other")
    db.seed_rental(other.id, start_date=NOW - timedelta(hours=5), end_date=NOW - timedelta(hours=1))
    rental = rental_service.start_rental(car.id, "Dana", start_date=NOW - timedelta(hours=3))
    assert rental.start_date == NOW - timedelta(hours=3)


# --- B8: customer name required -----------------------------------------------------


@pytest.mark.parametrize("name", ["", "   ", "x" * 101])
def test_start_rental_rejects_blank_customer_name(rental_service, db, name):
    car = db.seed_car()
    with pytest.raises(InvalidInputError) as err:
        rental_service.start_rental(car.id, name)
    assert err.value.code == "VALIDATION_ERROR"
    assert err.value.field == "customer_name"
    assert db.rentals == {}


def test_customer_name_is_stripped(rental_service, db):
    car = db.seed_car()
    assert rental_service.start_rental(car.id, "  Dana Levi ").customer_name == "Dana Levi"


# --- Dates (Decision 3, D7) ---------------------------------------------------------


def test_start_defaults_to_now(rental_service, db):
    car = db.seed_car()
    assert rental_service.start_rental(car.id, "Dana").start_date == NOW


def test_end_defaults_to_now(rental_service, db):
    car = db.seed_car(status=CarStatus.IN_USE)
    rental = db.seed_rental(car.id, start_date=NOW - timedelta(days=1))
    assert rental_service.end_rental(rental.id).end_date == NOW


def test_start_in_future_rejected(rental_service, db):
    car = db.seed_car()
    with pytest.raises(InvalidInputError) as err:
        rental_service.start_rental(car.id, "Dana", start_date=NOW + timedelta(seconds=1))
    assert err.value.code == "DATE_IN_FUTURE"
    assert err.value.field == "start_date"
    assert db.cars[car.id].status == CarStatus.AVAILABLE


def test_end_in_future_rejected(rental_service, db):
    car = db.seed_car(status=CarStatus.IN_USE)
    rental = db.seed_rental(car.id, start_date=NOW - timedelta(hours=1))
    with pytest.raises(InvalidInputError) as err:
        rental_service.end_rental(rental.id, end_date=NOW + timedelta(minutes=5))
    assert err.value.code == "DATE_IN_FUTURE"
    assert err.value.field == "end_date"
    assert db.rentals[rental.id].end_date is None


def test_naive_times_treated_as_utc(rental_service, db):
    car = db.seed_car()
    rental = rental_service.start_rental(car.id, "Dana", start_date=datetime(2026, 10, 1, 8, 0))
    assert rental.start_date == datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
    ended = rental_service.end_rental(rental.id, end_date=datetime(2026, 10, 1, 9, 30))
    assert ended.end_date == datetime(2026, 10, 1, 9, 30, tzinfo=UTC)


def test_naive_future_time_rejected(rental_service, db):
    # 12:30 naive = 12:30 UTC, after the clock's 12:00 UTC.
    car = db.seed_car()
    with pytest.raises(InvalidInputError) as err:
        rental_service.start_rental(car.id, "Dana", start_date=datetime(2026, 10, 1, 12, 30))
    assert err.value.code == "DATE_IN_FUTURE"


def test_offset_times_converted_to_utc(rental_service, db):
    israel = timezone(timedelta(hours=3))
    car = db.seed_car()
    # 14:30+03:00 is 11:30 UTC: in the past, accepted, stored as UTC.
    rental = rental_service.start_rental(car.id, "Dana", start_date=datetime(2026, 10, 1, 14, 30, tzinfo=israel))
    assert rental.start_date == datetime(2026, 10, 1, 11, 30, tzinfo=UTC)
    assert rental.start_date.utcoffset() == timedelta(0)
    # 14:45+03:00 is 11:45 UTC: after the start and before now.
    ended = rental_service.end_rental(rental.id, end_date=datetime(2026, 10, 1, 14, 45, tzinfo=israel))
    assert ended.end_date == datetime(2026, 10, 1, 11, 45, tzinfo=UTC)


def test_backdated_start_and_end_accepted(rental_service, db):
    car = db.seed_car()
    start = NOW - timedelta(days=3)
    end = NOW - timedelta(days=1)
    rental = rental_service.start_rental(car.id, "Dana", start_date=start)
    ended = rental_service.end_rental(rental.id, end_date=end)
    assert (ended.start_date, ended.end_date) == (start, end)
    assert db.cars[car.id].status == CarStatus.AVAILABLE


# --- F7 get / list, not found -------------------------------------------------------


def test_get_and_list_rentals(rental_service, db):
    car1 = db.seed_car()
    car2 = db.seed_car(model="Other")
    finished = db.seed_rental(car1.id, start_date=NOW - timedelta(days=2), end_date=NOW - timedelta(days=1))
    ongoing1 = db.seed_rental(car1.id, start_date=NOW - timedelta(hours=1))
    ongoing2 = db.seed_rental(car2.id, start_date=NOW - timedelta(hours=1))

    assert rental_service.get_rental(finished.id).end_date == NOW - timedelta(days=1)
    assert [r.id for r in rental_service.list_rentals()] == [finished.id, ongoing1.id, ongoing2.id]
    assert [r.id for r in rental_service.list_rentals(car_id=car1.id)] == [finished.id, ongoing1.id]
    assert [r.id for r in rental_service.list_rentals(ongoing=True)] == [ongoing1.id, ongoing2.id]
    assert [r.id for r in rental_service.list_rentals(ongoing=False)] == [finished.id]
    assert [r.id for r in rental_service.list_rentals(car_id=car2.id, ongoing=False)] == []


def test_start_rental_car_not_found(rental_service, db, publisher):
    with pytest.raises(CarNotFoundError) as err:
        rental_service.start_rental(99, "Dana")
    assert err.value.code == "CAR_NOT_FOUND"
    assert db.rentals == {} and publisher.events == []


@pytest.mark.parametrize(
    "call", [lambda s: s.end_rental(99), lambda s: s.get_rental(99)], ids=["end", "get"]
)
def test_rental_not_found(rental_service, call):
    with pytest.raises(RentalNotFoundError) as err:
        call(rental_service)
    assert err.value.code == "RENTAL_NOT_FOUND"


# --- Logging ------------------------------------------------------------------------


def test_logs_rental_actions_and_rejections(rental_service, db, caplog):
    caplog.set_level(logging.INFO, logger="drivenow")
    car = db.seed_car()
    rental = rental_service.start_rental(car.id, "Dana Levi")
    rental_service.end_rental(rental.id)
    with pytest.raises(RentalAlreadyEndedError):
        rental_service.end_rental(rental.id)

    messages = [(r.levelname, r.getMessage()) for r in caplog.records]
    assert (
        "INFO",
        f"Rental started: id={rental.id} car_id={car.id} customer='Dana Levi' start={NOW.isoformat()}",
    ) in messages
    assert ("INFO", f"Rental ended: id={rental.id} car_id={car.id} end={NOW.isoformat()}") in messages
    assert (
        "WARNING",
        f"end_rental rejected: RENTAL_ALREADY_ENDED: Rental {rental.id} has already ended",
    ) in messages
