"""SQLAlchemy implementation of UnitOfWork."""

from __future__ import annotations

from types import TracebackType
from typing import Self

from sqlalchemy.orm import Session, sessionmaker

from drivenow.repositories.car_repository import SqlAlchemyCarRepository
from drivenow.repositories.rental_repository import SqlAlchemyRentalRepository


class SqlAlchemyUnitOfWork:
    """One database transaction with its repositories.

    ``with uow:`` opens a session; ``uow.commit()`` saves; leaving the block
    discards whatever was not committed (an exception is re-raised) and closes
    the session. Objects loaded inside stay readable afterwards because the
    session factory uses ``expire_on_commit=False`` and closing doesn't expire them.
    """

    cars: SqlAlchemyCarRepository
    rentals: SqlAlchemyRentalRepository

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None

    def __enter__(self) -> Self:
        self._session = self._session_factory()
        self.cars = SqlAlchemyCarRepository(self._session)
        self.rentals = SqlAlchemyRentalRepository(self._session)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        session = self._require_session()
        try:
            if exc_type is not None:
                session.rollback()
        finally:
            # close() also discards any uncommitted transaction. Unlike rollback(),
            # it detaches objects without expiring them, so they stay readable.
            session.close()
            self._session = None

    def commit(self) -> None:
        self._require_session().commit()

    def rollback(self) -> None:
        self._require_session().rollback()

    def _require_session(self) -> Session:
        if self._session is None:
            raise RuntimeError("UnitOfWork used outside of a 'with' block")
        return self._session
