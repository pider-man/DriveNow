"""Standalone entry point: ``python -m drivenow`` starts the API server."""

from __future__ import annotations

import uvicorn

from drivenow.api.app import create_app
from drivenow.config import get_settings
from drivenow.observability.logging_config import setup_logging

__all__ = ["create_app", "main"]


def main() -> None:
    """Run the API with uvicorn on ``API_HOST``:``API_PORT``.

    Logging is set up before uvicorn starts, and ``log_config=None`` stops
    uvicorn from installing its own handlers, so its lines share our format,
    console and file.
    """
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_file)
    uvicorn.run(
        "drivenow.main:create_app",
        factory=True,
        host=settings.api_host,
        port=settings.api_port,
        log_config=None,
    )


if __name__ == "__main__":
    main()
