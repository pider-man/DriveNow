"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from drivenow import __version__
from drivenow.api.dependencies import build_container
from drivenow.api.errors import register_error_handlers
from drivenow.api.routers import cars, rentals, system
from drivenow.config import Settings, get_settings
from drivenow.db.session import create_tables
from drivenow.messaging.publisher import EventPublisher, NullPublisher
from drivenow.services.clock import Clock, SystemClock

DESCRIPTION = """
Manage the DriveNow fleet and its rentals.

* **Cars**: add, list (optionally by status), read, update and delete.
* **Rentals**: start (the car becomes `in_use`), end (the car becomes `available`), read and list.

Times are ISO 8601. A time without a timezone is taken as UTC; responses are always in UTC.
Every error has the body `{"error": {"code": ..., "message": ...}}`.
"""


def create_app(
    settings: Settings | None = None,
    *,
    clock: Clock | None = None,
    publisher: EventPublisher | None = None,
) -> FastAPI:
    """Build the app: wire services, routers and error handlers.

    ``clock`` and ``publisher`` can be injected (tests); by default the system
    clock and a no-op publisher are used (RabbitMQ is added in build step 7).
    """
    settings = settings or get_settings()
    container = build_container(settings, clock or SystemClock(), publisher or NullPublisher())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        create_tables(container.engine)
        yield
        container.engine.dispose()

    app = FastAPI(title="DriveNow Car Rental API", version=__version__, description=DESCRIPTION, lifespan=lifespan)
    app.state.container = container

    register_error_handlers(app)
    app.include_router(cars.router)
    app.include_router(rentals.router)
    app.include_router(system.router)
    return app
