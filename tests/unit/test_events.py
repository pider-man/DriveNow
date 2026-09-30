"""Domain events: payloads, publish-after-commit, and best-effort publishing."""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest

from drivenow.domain.enums import CarStatus
from drivenow.domain.events import DomainEvent
from drivenow.domain.exceptions import CarNotAvailableError
from drivenow.messaging.publisher import InMemoryPublisher, NullPublisher

from .fakes import NOW


def test_each_operation_publishes_its_event_after_commit(car_service, rental_service, db, publisher):
    car = car_service.add_car("Toyota Corolla", 2022)
    car_service.update_car(car.id, year=2023)
    rental = rental_service.start_rental(car.id, "Dana Levi", start_date=NOW - timedelta(hours=1))
    rental_service.end_rental(rental.id)
    car_service.delete_car(car.id)

    assert [e.name for e in publisher.events] == [
        "car.created",
        "car.updated",
        "rental.started",
        "rental.ended",
        "car.deleted",
    ]
    # Every publish comes right after a commit.
    for i, entry in enumerate(db.journal):
        if entry.startswith("publish:"):
            assert db.journal[i - 1] == "commit"
    assert all(e.occurred_at == NOW for e in publisher.events)


def test_event_payloads(car_service, rental_service, publisher):
    car = car_service.add_car("Toyota Corolla", 2022)
    car_service.update_car(car.id, year=2023)
    rental = rental_service.start_rental(car.id, "Dana Levi", start_date=NOW - timedelta(hours=1))
    rental_service.end_rental(rental.id)
    car_service.delete_car(car.id)
    created, updated, started, ended, deleted = (e.payload for e in publisher.events)

    assert created == {"id": car.id, "model": "Toyota Corolla", "year": 2022, "status": "available"}
    assert updated == {**created, "year": 2023, "changed_fields": ["year"]}
    assert started == {
        "id": rental.id,
        "car_id": car.id,
        "customer_name": "Dana Levi",
        "start_date": (NOW - timedelta(hours=1)).isoformat(),
        "end_date": None,
    }
    assert ended == {**started, "end_date": NOW.isoformat()}
    assert deleted == {"car_id": car.id, "deleted_rentals": 1}


def test_event_message_shape():
    event = DomainEvent(name="car.created", occurred_at=NOW, payload={"id": 1})
    assert event.to_message() == {"event": "car.created", "occurred_at": NOW.isoformat(), "payload": {"id": 1}}


def test_rejected_operation_publishes_nothing(rental_service, db, publisher):
    car = db.seed_car(status=CarStatus.UNDER_MAINTENANCE)
    with pytest.raises(CarNotAvailableError):
        rental_service.start_rental(car.id, "Dana")
    assert publisher.events == []


def test_commit_failure_publishes_nothing(car_service, db, publisher):
    db.fail_commit = RuntimeError("database is down")
    with pytest.raises(RuntimeError):
        car_service.add_car("Toyota Corolla", 2022)
    assert publisher.events == []
    assert db.journal[-1] == "rollback"


def test_publisher_failure_is_logged_and_does_not_fail_the_operation(car_service, db, publisher, caplog):
    publisher.fail_with = ConnectionError("broker unreachable")
    car = car_service.add_car("Toyota Corolla", 2022)
    assert car.id in db.cars
    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert errors and errors[0].getMessage() == "Failed to publish event car.created"


def test_in_memory_and_null_publishers():
    event = DomainEvent(name="car.created", occurred_at=NOW)
    memory = InMemoryPublisher()
    memory.publish(event)
    assert memory.events == [event]
    NullPublisher().publish(event)  # no error, no effect


def test_logging_uses_module_loggers(car_service, caplog):
    caplog.set_level(logging.INFO)
    car_service.add_car("Toyota Corolla", 2022)
    assert caplog.records[0].name == "drivenow.services.car_service"
