"""Rentals: start, end, read and list (F4, F5, F7)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

from drivenow.db.models import CUSTOMER_NAME_MAX_LENGTH, Rental
from drivenow.domain.enums import CarStatus
from drivenow.domain.events import RENTAL_ENDED, RENTAL_STARTED, DomainEvent
from drivenow.domain.exceptions import (
    DATE_IN_FUTURE,
    END_BEFORE_START,
    START_BEFORE_PREVIOUS_END,
    CarNotAvailableError,
    CarNotFoundError,
    DataIntegrityError,
    InvalidInputError,
    RentalAlreadyEndedError,
    RentalNotFoundError,
)
from drivenow.domain.records import RentalRecord
from drivenow.domain.timeutil import to_utc
from drivenow.messaging.publisher import EventPublisher
from drivenow.repositories.interfaces import UnitOfWork
from drivenow.services._support import publish_after_commit, rejections_logged, validate_text
from drivenow.services.clock import Clock

logger = logging.getLogger(__name__)


class RentalService:
    """Business rules for rentals. The rental and its car change in one Unit of Work (B1)."""

    def __init__(
        self, uow_factory: Callable[[], UnitOfWork], publisher: EventPublisher, clock: Clock
    ) -> None:
        self._uow_factory = uow_factory
        self._publisher = publisher
        self._clock = clock

    @rejections_logged(logger, "start_rental")
    def start_rental(
        self, car_id: int, customer_name: str, start_date: datetime | None = None
    ) -> RentalRecord:
        """F4: rent an available car (B2, B3) and mark it in use (B1).

        ``start_date`` defaults to now; a naive value is UTC; it can't be in the
        future, or before the end of the car's previous rental (B10).
        """
        customer_name = validate_text(customer_name, "customer_name", CUSTOMER_NAME_MAX_LENGTH)
        now = self._clock.now()
        start = to_utc(start_date) if start_date is not None else now
        if start > now:
            raise InvalidInputError("start_date can't be in the future", code=DATE_IN_FUTURE, field="start_date")

        with self._uow_factory() as uow:
            car = uow.cars.get(car_id, for_update=True)  # SELECT ... FOR UPDATE
            if car is None:
                raise CarNotFoundError(car_id)
            if car.status != CarStatus.AVAILABLE:
                raise CarNotAvailableError(f"Car {car_id} is {car.status.value} and can't be rented")
            if uow.rentals.get_ongoing_for_car(car_id) is not None:
                raise CarNotAvailableError(f"Car {car_id} already has an ongoing rental")
            previous_end = uow.rentals.get_latest_end_for_car(car_id)
            if previous_end is not None and start < previous_end:
                raise InvalidInputError(
                    f"start_date can't be before the end of car {car_id}'s previous rental "
                    f"({previous_end.isoformat()})",
                    code=START_BEFORE_PREVIOUS_END,
                    field="start_date",
                )
            try:
                rental = uow.rentals.add(
                    Rental(car_id=car_id, customer_name=customer_name, start_date=start, end_date=None)
                )
                car.status = CarStatus.IN_USE
                uow.commit()
            except DataIntegrityError as exc:
                # A concurrent request won the race; the one-ongoing-rental index rejected this one.
                raise CarNotAvailableError(f"Car {car_id} already has an ongoing rental") from exc
            record = RentalRecord.from_model(rental)

        logger.info(
            "Rental started: id=%s car_id=%s customer=%r start=%s",
            record.id, record.car_id, record.customer_name, record.start_date.isoformat(),
        )
        self._publish(RENTAL_STARTED, record.to_payload())
        return record

    @rejections_logged(logger, "end_rental")
    def end_rental(self, rental_id: int, end_date: datetime | None = None) -> RentalRecord:
        """F5: end a rental once (B7) and make its car available (B1).

        ``end_date`` defaults to now; a naive value is UTC; it can't be in the
        future or before the start.
        """
        now = self._clock.now()
        end = to_utc(end_date) if end_date is not None else now
        if end > now:
            raise InvalidInputError("end_date can't be in the future", code=DATE_IN_FUTURE, field="end_date")

        with self._uow_factory() as uow:
            rental = uow.rentals.get(rental_id, for_update=True)
            if rental is None:
                raise RentalNotFoundError(rental_id)
            if rental.end_date is not None:
                raise RentalAlreadyEndedError(f"Rental {rental_id} has already ended")
            if end < rental.start_date:
                raise InvalidInputError(
                    "end_date can't be before start_date", code=END_BEFORE_START, field="end_date"
                )
            car = uow.cars.get(rental.car_id, for_update=True)
            rental.end_date = end
            if car is not None:
                car.status = CarStatus.AVAILABLE
            uow.commit()
            record = RentalRecord.from_model(rental)

        logger.info(
            "Rental ended: id=%s car_id=%s end=%s", record.id, record.car_id, end.isoformat()
        )
        self._publish(RENTAL_ENDED, record.to_payload())
        return record

    @rejections_logged(logger, "get_rental")
    def get_rental(self, rental_id: int) -> RentalRecord:
        """F7: one rental."""
        with self._uow_factory() as uow:
            rental = uow.rentals.get(rental_id)
            if rental is None:
                raise RentalNotFoundError(rental_id)
            return RentalRecord.from_model(rental)

    @rejections_logged(logger, "list_rentals")
    def list_rentals(self, car_id: int | None = None, ongoing: bool | None = None) -> list[RentalRecord]:
        """F7: rentals, optionally for one car and/or only ongoing or finished ones."""
        with self._uow_factory() as uow:
            return [RentalRecord.from_model(r) for r in uow.rentals.list(car_id=car_id, ongoing=ongoing)]

    def _publish(self, name: str, payload: dict) -> None:
        event = DomainEvent(name=name, occurred_at=self._clock.now(), payload=payload)
        publish_after_commit(self._publisher, event, logger)
