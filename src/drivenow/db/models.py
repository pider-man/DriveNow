"""ORM models for the ``cars`` and ``rentals`` tables.

Each table has exactly the fields listed in the PRD. The constraints and the
partial index back up business rules that the service layer enforces first
(see docs/ARCHITECTURE.md, section 8).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from drivenow.db.base import Base
from drivenow.db.types import UTCDateTime
from drivenow.domain.enums import CarStatus

MODEL_MAX_LENGTH = 100
CUSTOMER_NAME_MAX_LENGTH = 100


class Car(Base):
    """A car in the fleet: car ID, model, year, status."""

    __tablename__ = "cars"
    __table_args__ = (CheckConstraint("year > 0", name="year_positive"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model: Mapped[str] = mapped_column(String(MODEL_MAX_LENGTH), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[CarStatus] = mapped_column(
        Enum(
            CarStatus,
            name="car_status",
            native_enum=False,
            create_constraint=True,
            length=20,
            values_callable=lambda enum: [member.value for member in enum],
            validate_strings=True,
        ),
        nullable=False,
        default=CarStatus.AVAILABLE,
        server_default=CarStatus.AVAILABLE.value,
    )

    def __repr__(self) -> str:
        return f"Car(id={self.id!r}, model={self.model!r}, year={self.year!r}, status={self.status!r})"


class Rental(Base):
    """A rental of one car: rental ID, car ID, customer name, start date, end date.

    ``end_date`` is NULL while the rental is ongoing.
    """

    __tablename__ = "rentals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    car_id: Mapped[int] = mapped_column(
        ForeignKey("cars.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    customer_name: Mapped[str] = mapped_column(String(CUSTOMER_NAME_MAX_LENGTH), nullable=False)
    start_date: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    end_date: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    __table_args__ = (
        # B7: a rental can't end before it starts.
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="end_after_start"),
    )

    def __repr__(self) -> str:
        return (
            f"Rental(id={self.id!r}, car_id={self.car_id!r}, customer_name={self.customer_name!r}, "
            f"start_date={self.start_date!r}, end_date={self.end_date!r})"
        )


# B3: at most one ongoing rental per car. A partial unique index, supported by
# both PostgreSQL and SQLite. Declared after the class so it can use the mapped columns.
ONGOING_RENTAL_INDEX = Index(
    "ix_rentals_one_ongoing_per_car",
    Rental.car_id,
    unique=True,
    postgresql_where=Rental.end_date.is_(None),
    sqlite_where=Rental.end_date.is_(None),
)
