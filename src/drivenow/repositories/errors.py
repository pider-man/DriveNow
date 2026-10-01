"""Translate SQLAlchemy constraint errors into the domain's DataIntegrityError."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.exc import IntegrityError

from drivenow.domain.exceptions import DataIntegrityError


@contextmanager
def integrity_errors_translated() -> Iterator[None]:
    """Re-raise ``IntegrityError`` as ``DataIntegrityError`` (original chained as ``__cause__``)."""
    try:
        yield
    except IntegrityError as exc:
        raise DataIntegrityError(str(exc.orig)) from exc
