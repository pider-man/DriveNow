"""SQLAlchemy implementation of CarRepository."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from drivenow.db.models import Car
from drivenow.domain.enums import CarStatus
from drivenow.repositories.errors import integrity_errors_translated


class SqlAlchemyCarRepository:
    """Car persistence on a SQLAlchemy session. The Unit of Work owns the transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, car: Car) -> Car:
        self._session.add(car)
        with integrity_errors_translated():
            self._session.flush()
        return car

    def get(self, car_id: int, *, for_update: bool = False) -> Car | None:
        stmt = select(Car).where(Car.id == car_id)
        if for_update:
            stmt = stmt.with_for_update()
        return self._session.scalars(stmt).one_or_none()

    def list(self, status: CarStatus | None = None) -> list[Car]:
        stmt = select(Car).order_by(Car.id)
        if status is not None:
            stmt = stmt.where(Car.status == status)
        return list(self._session.scalars(stmt))

    def delete(self, car: Car) -> None:
        self._session.delete(car)
        with integrity_errors_translated():
            self._session.flush()

    def count_active(self) -> int:
        stmt = select(func.count()).select_from(Car).where(Car.status != CarStatus.UNDER_MAINTENANCE)
        return self._session.scalar(stmt) or 0
