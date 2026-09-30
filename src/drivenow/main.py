"""Standalone entry point: ``python -m drivenow`` starts the API server."""

from __future__ import annotations

import uvicorn

from drivenow.api.app import create_app
from drivenow.config import get_settings

__all__ = ["create_app", "main"]


def main() -> None:
    """Run the API with uvicorn on ``API_HOST``:``API_PORT``."""
    settings = get_settings()
    uvicorn.run("drivenow.main:create_app", factory=True, host=settings.api_host, port=settings.api_port)


if __name__ == "__main__":
    main()
