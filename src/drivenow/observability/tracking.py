"""Operation timing for the service layer, independent of any metrics library.

Services get an ``OperationRecorder`` injected (DIP). The Prometheus
implementation is ``observability.metrics.AppMetrics``.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from time import perf_counter
from typing import Any, Concatenate, ParamSpec, Protocol, TypeVar

from drivenow.domain.exceptions import DomainError

P = ParamSpec("P")
R = TypeVar("R")

INTERNAL_ERROR = "INTERNAL_ERROR"


class OperationRecorder(Protocol):
    def observe(self, operation: str, seconds: float) -> None:
        """Record how long one call of ``operation`` took (success or failure)."""
        ...

    def failed(self, operation: str, code: str) -> None:
        """Count one failed call of ``operation`` with error ``code``."""
        ...


class NullRecorder:
    """Records nothing. The default when no metrics are wired in."""

    def observe(self, operation: str, seconds: float) -> None:
        pass

    def failed(self, operation: str, code: str) -> None:
        pass


_NULL_RECORDER = NullRecorder()


def track_operation(
    name: str,
) -> Callable[[Callable[Concatenate[Any, P], R]], Callable[Concatenate[Any, P], R]]:
    """Time a service method and count its failures.

    The recorder is read from the instance's ``_operation_recorder`` attribute.
    A ``DomainError`` is counted under its code; anything else as INTERNAL_ERROR.
    The exception is always re-raised.
    """

    def decorator(func: Callable[Concatenate[Any, P], R]) -> Callable[Concatenate[Any, P], R]:
        @functools.wraps(func)
        def wrapper(self: Any, *args: P.args, **kwargs: P.kwargs) -> R:
            recorder: OperationRecorder = getattr(self, "_operation_recorder", None) or _NULL_RECORDER
            start = perf_counter()
            try:
                return func(self, *args, **kwargs)
            except DomainError as exc:
                recorder.failed(name, exc.code)
                raise
            except Exception:
                recorder.failed(name, INTERNAL_ERROR)
                raise
            finally:
                recorder.observe(name, perf_counter() - start)

        return wrapper

    return decorator
