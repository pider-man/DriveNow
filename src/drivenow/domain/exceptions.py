"""Typed errors raised by the service layer.

Every ``DomainError`` has a stable ``code``. The API maps the three families to
HTTP status codes: ``NotFoundError`` -> 404, ``BusinessRuleViolation`` -> 409,
``InvalidInputError`` -> 422 (docs/ARCHITECTURE.md, section 7).
"""

from __future__ import annotations

# Validation error codes (InvalidInputError).
VALIDATION_ERROR = "VALIDATION_ERROR"
DATE_IN_FUTURE = "DATE_IN_FUTURE"
END_BEFORE_START = "END_BEFORE_START"


class DomainError(Exception):
    """Base class for errors the interface layer reports to the client."""

    code: str = "DOMAIN_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


# --- Not found (404) ----------------------------------------------------------------


class NotFoundError(DomainError):
    """The requested car or rental doesn't exist."""


class CarNotFoundError(NotFoundError):
    code = "CAR_NOT_FOUND"

    def __init__(self, car_id: int) -> None:
        super().__init__(f"Car {car_id} not found")
        self.car_id = car_id


class RentalNotFoundError(NotFoundError):
    code = "RENTAL_NOT_FOUND"

    def __init__(self, rental_id: int) -> None:
        super().__init__(f"Rental {rental_id} not found")
        self.rental_id = rental_id


# --- Conflict: a business rule was broken (409) -------------------------------------


class BusinessRuleViolation(DomainError):
    """The request is well formed but breaks a business rule in the current state."""


class CarNotAvailableError(BusinessRuleViolation):
    """B2/B3: only an available car with no ongoing rental can be rented."""

    code = "CAR_NOT_AVAILABLE"


class CarRentedError(BusinessRuleViolation):
    """B5: a rented car's status can't change and it can't be deleted."""

    code = "CAR_RENTED"


class RentalAlreadyEndedError(BusinessRuleViolation):
    """B7: a rental can't be ended twice."""

    code = "RENTAL_ALREADY_ENDED"


# --- Validation: bad input (422) ----------------------------------------------------


class InvalidInputError(DomainError):
    """Input that fails validation. ``code`` is one of the validation codes above."""

    def __init__(self, message: str, *, code: str = VALIDATION_ERROR, field: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.field = field


# --- Data layer ---------------------------------------------------------------------


class DataIntegrityError(Exception):
    """A database constraint rejected a write.

    Raised by the data layer so services can react without importing SQLAlchemy.
    Deliberately not a ``DomainError``: services translate the cases they expect,
    and anything else is an unexpected server error.
    """
