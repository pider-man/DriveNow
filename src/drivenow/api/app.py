"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.engine import make_url

from drivenow import __version__
from drivenow.api.dependencies import build_container, build_publisher
from drivenow.api.errors import register_error_handlers
from drivenow.api.routers import cars, rentals, system
from drivenow.config import Settings, get_settings
from drivenow.db.session import create_tables
from drivenow.messaging.publisher import EventPublisher
from drivenow.observability.logging_config import setup_logging
from drivenow.observability.middleware import RequestMetricsMiddleware
from drivenow.services.clock import Clock, SystemClock

logger = logging.getLogger(__name__)

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
    clock is used, and RabbitMQ when ``RABBITMQ_URL`` is set (else a no-op publisher).
    """
    settings = settings or get_settings()
    container = build_container(settings, clock or SystemClock(), publisher or build_publisher(settings))

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        setup_logging(settings.log_level, settings.log_file)
        create_tables(container.engine)
        logger.info(
            "DriveNow API started: database=%s publisher=%s log_file=%s",
            make_url(settings.database_url).render_as_string(hide_password=True),
            type(container.publisher).__name__,
            settings.log_file,
        )
        yield
        logger.info("DriveNow API stopping")
        close_publisher = getattr(container.publisher, "close", None)
        if close_publisher is not None:
            close_publisher()
        container.engine.dispose()

    app = FastAPI(title="DriveNow Car Rental API", version=__version__, description=DESCRIPTION, lifespan=lifespan)
    app.state.container = container

    app.add_middleware(RequestMetricsMiddleware, metrics=container.metrics)
    register_error_handlers(app)
    app.include_router(cars.router)
    app.include_router(rentals.router)
    app.include_router(system.router)
    return app
