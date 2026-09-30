"""Helpers shared by the services: input validation, rejection logging, safe publishing."""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from typing import ParamSpec, TypeVar

from drivenow.domain.events import DomainEvent
from drivenow.domain.exceptions import DomainError, InvalidInputError
from drivenow.messaging.publisher import EventPublisher
from drivenow.services.clock import Clock

P = ParamSpec("P")
R = TypeVar("R")

FIRST_CAR_YEAR = 1886  # B8: Benz Patent-Motorwagen


def rejections_logged(logger: logging.Logger, operation: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Log any ``DomainError`` raised by the wrapped operation at WARNING, then re-raise it."""

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                return func(*args, **kwargs)
            except DomainError as exc:
                logger.warning("%s rejected: %s: %s", operation, exc.code, exc.message)
                raise

        return wrapper

    return decorator


def publish_after_commit(publisher: EventPublisher, event: DomainEvent, logger: logging.Logger) -> None:
    """Publish ``event``, best effort: a failure is logged and never fails the operation."""
    try:
        publisher.publish(event)
    except Exception:
        logger.exception("Failed to publish event %s", event.name)


def validate_text(value: str, field: str, max_length: int) -> str:
    """B8: return ``value`` stripped; it must not be blank or longer than ``max_length``."""
    if not isinstance(value, str):
        raise InvalidInputError(f"{field} must be a string", field=field)
    stripped = value.strip()
    if not stripped:
        raise InvalidInputError(f"{field} is required", field=field)
    if len(stripped) > max_length:
        raise InvalidInputError(f"{field} must be at most {max_length} characters", field=field)
    return stripped


def validate_year(year: int, clock: Clock) -> int:
    """B8: a realistic car year, from 1886 up to next year."""
    latest = clock.now().year + 1
    if isinstance(year, bool) or not isinstance(year, int) or not FIRST_CAR_YEAR <= year <= latest:
        raise InvalidInputError(f"year must be between {FIRST_CAR_YEAR} and {latest}", field="year")
    return year
