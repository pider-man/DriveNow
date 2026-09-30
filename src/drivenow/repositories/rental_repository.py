"""SQLAlchemy implementation of RentalRepository."""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from drivenow.db.models import Rental
from drivenow.repositories.errors import integrity_errors_translated


class SqlAlchemyRentalRepository:
    """Rental persistence on a SQLAlchemy session. The Unit of Work owns the transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, rental: Rental) -> Rental:
        self._session.add(rental)
        with integrity_errors_translated():
            self._session.flush()
        return rental

    def get(self, rental_id: int, *, for_update: bool = False) -> Rental | None:
        stmt = select(Rental).where(Rental.id == rental_id)
        if for_update:
            stmt = stmt.with_for_update()
        return self._session.scalars(stmt).one_or_none()

    def list(self, car_id: int | None = None, ongoing: bool | None = None) -> list[Rental]:
        stmt = select(Rental).order_by(Rental.id)
        if car_id is not None:
            stmt = stmt.where(Rental.car_id == car_id)
        if ongoing is True:
            stmt = stmt.where(Rental.end_date.is_(None))
        elif ongoing is False:
            stmt = stmt.where(Rental.end_date.is_not(None))
        return list(self._session.scalars(stmt))

    def get_ongoing_for_car(self, car_id: int) -> Rental | None:
        stmt = select(Rental).where(Rental.car_id == car_id, Rental.end_date.is_(None))
        return self._session.scalars(stmt).one_or_none()

    def delete_finished_for_car(self, car_id: int) -> int:
        stmt = delete(Rental).where(Rental.car_id == car_id, Rental.end_date.is_not(None))
        result = self._session.execute(stmt)
        return result.rowcount or 0

    def count_ongoing(self) -> int:
        stmt = select(func.count()).select_from(Rental).where(Rental.end_date.is_(None))
        return self._session.scalar(stmt) or 0
