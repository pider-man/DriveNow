"""Fleet management: add, read, list, update and delete cars (F1, F2, F3, F6, F7)."""

from __future__ import annotations

import logging
from collections.abc import Callable

from drivenow.db.models import MODEL_MAX_LENGTH, Car
from drivenow.domain.enums import CarStatus
from drivenow.domain.events import CAR_CREATED, CAR_DELETED, CAR_UPDATED, DomainEvent
from drivenow.domain.exceptions import (
    CarNotFoundError,
    CarRentedError,
    DataIntegrityError,
    InvalidInputError,
)
from drivenow.domain.records import CarRecord
from drivenow.messaging.publisher import EventPublisher
from drivenow.observability.tracking import NullRecorder, OperationRecorder, track_operation
from drivenow.repositories.interfaces import UnitOfWork
from drivenow.services._support import (
    publish_after_commit,
    rejections_logged,
    validate_text,
    validate_year,
)
from drivenow.services.clock import Clock

logger = logging.getLogger(__name__)

# B4/B6: statuses that can be set by hand. in_use is set only by rentals.
MANUAL_STATUSES = frozenset({CarStatus.AVAILABLE, CarStatus.UNDER_MAINTENANCE})


def _parse_manual_status(status: CarStatus | str) -> CarStatus:
    try:
        parsed = CarStatus(status)
    except ValueError:
        raise InvalidInputError(f"Unknown status {status!r}", field="status") from None
    if parsed not in MANUAL_STATUSES:
        raise InvalidInputError(
            "status can only be set to available or under_maintenance; in_use is set by rentals",
            field="status",
        )
    return parsed


class CarService:
    """Business rules for cars. Every write is one Unit of Work; events go out after commit."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        publisher: EventPublisher,
        clock: Clock,
        recorder: OperationRecorder | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._publisher = publisher
        self._clock = clock
        self._operation_recorder = recorder or NullRecorder()  # read by @track_operation

    @rejections_logged(logger, "add_car")
    @track_operation("add_car")
    def add_car(self, model: str, year: int, status: CarStatus | str | None = None) -> CarRecord:
        """F1: add a car. B6: it starts available unless under_maintenance is given (B4)."""
        model = validate_text(model, "model", MODEL_MAX_LENGTH)
        year = validate_year(year, self._clock)
        initial_status = CarStatus.AVAILABLE if status is None else _parse_manual_status(status)

        with self._uow_factory() as uow:
            car = uow.cars.add(Car(model=model, year=year, status=initial_status))
            uow.commit()
            record = CarRecord.from_model(car)

        logger.info(
            "Car added: id=%s model=%r year=%s status=%s",
            record.id, record.model, record.year, record.status.value,
        )
        self._publish(CAR_CREATED, record.to_payload())
        return record

    @rejections_logged(logger, "get_car")
    @track_operation("get_car")
    def get_car(self, car_id: int) -> CarRecord:
        """F7: one car."""
        with self._uow_factory() as uow:
            car = uow.cars.get(car_id)
            if car is None:
                raise CarNotFoundError(car_id)
            return CarRecord.from_model(car)

    @rejections_logged(logger, "list_cars")
    @track_operation("list_cars")
    def list_cars(self, status: CarStatus | str | None = None) -> list[CarRecord]:
        """F3: all cars, or only those with ``status``."""
        if status is not None:
            try:
                status = CarStatus(status)
            except ValueError:
                raise InvalidInputError(f"Unknown status {status!r}", field="status") from None
        with self._uow_factory() as uow:
            return [CarRecord.from_model(car) for car in uow.cars.list(status)]

    @rejections_logged(logger, "update_car")
    @track_operation("update_car")
    def update_car(
        self,
        car_id: int,
        *,
        model: str | None = None,
        year: int | None = None,
        status: CarStatus | str | None = None,
    ) -> CarRecord:
        """F2: change any of model, year, status.

        B4: status can't be set to in_use. B5: a rented car's status can't change,
        but its model and year can still be corrected.
        """
        if model is None and year is None and status is None:
            raise InvalidInputError("Give at least one of model, year, status")
        if model is not None:
            model = validate_text(model, "model", MODEL_MAX_LENGTH)
        if year is not None:
            year = validate_year(year, self._clock)
        new_status = _parse_manual_status(status) if status is not None else None

        with self._uow_factory() as uow:
            car = uow.cars.get(car_id, for_update=True)
            if car is None:
                raise CarNotFoundError(car_id)
            if new_status is not None and self._is_rented(uow, car):
                raise CarRentedError(f"Car {car_id} is rented; its status can't change until the rental ends")

            changed: list[str] = []
            for field, value in (("model", model), ("year", year), ("status", new_status)):
                if value is not None and getattr(car, field) != value:
                    setattr(car, field, value)
                    changed.append(field)

            if changed:
                uow.commit()
            record = CarRecord.from_model(car)

        if changed:
            logger.info(
                "Car updated: id=%s changed=%s model=%r year=%s status=%s",
                record.id, ",".join(changed), record.model, record.year, record.status.value,
            )
            self._publish(CAR_UPDATED, {**record.to_payload(), "changed_fields": changed})
        return record

    @rejections_logged(logger, "delete_car")
    @track_operation("delete_car")
    def delete_car(self, car_id: int) -> None:
        """F6: delete a car with its finished rental history (B9), unless it's rented (B5)."""
        with self._uow_factory() as uow:
            car = uow.cars.get(car_id, for_update=True)
            if car is None:
                raise CarNotFoundError(car_id)
            if self._is_rented(uow, car):
                raise CarRentedError(f"Car {car_id} is rented and can't be deleted until the rental ends")
            try:
                deleted_rentals = uow.rentals.delete_finished_for_car(car_id)
                uow.cars.delete(car)
                uow.commit()
            except DataIntegrityError as exc:
                # A rental appeared despite the lock; the FK (RESTRICT) caught it.
                raise CarRentedError(f"Car {car_id} is rented and can't be deleted") from exc

        logger.info("Car deleted: id=%s deleted_rentals=%s", car_id, deleted_rentals)
        self._publish(CAR_DELETED, {"car_id": car_id, "deleted_rentals": deleted_rentals})

    @staticmethod
    def _is_rented(uow: UnitOfWork, car: Car) -> bool:
        return car.status == CarStatus.IN_USE or uow.rentals.get_ongoing_for_car(car.id) is not None

    def _publish(self, name: str, payload: dict) -> None:
        event = DomainEvent(name=name, occurred_at=self._clock.now(), payload=payload)
        publish_after_commit(self._publisher, event, logger)
