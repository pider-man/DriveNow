"""Logging to the console and a rotating file (N4, N5).

``setup_logging`` is idempotent: it replaces only the handlers it added itself,
so calling it twice never duplicates output, and handlers added by others
(for example pytest's log capture) are left alone.
"""

from __future__ import annotations

import logging
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

# ISO 8601 in UTC, e.g. 2026-10-01T17:39:00.123Z, matching the times in the API and messages.
LOG_FORMAT = "%(asctime)s.%(msecs)03dZ %(levelname)-7s [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 3

# uvicorn installs its own handlers on these; we route them through ours instead.
UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")

_MARKER = "_drivenow_handler"


def setup_logging(level: str = "INFO", log_file: str = "logs/drivenow.log") -> None:
    """Send all logs (ours and uvicorn's) to stdout and to ``log_file``, in one format."""
    reset_logging()

    path = Path(log_file)
    path.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    formatter.converter = time.gmtime  # UTC timestamps
    console = logging.StreamHandler(sys.stdout)
    file_handler = RotatingFileHandler(path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8")

    root = logging.getLogger()
    for handler in (console, file_handler):
        handler.setFormatter(formatter)
        setattr(handler, _MARKER, True)
        root.addHandler(handler)
    root.setLevel(level.upper())

    for name in UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        for handler in uvicorn_logger.handlers[:]:
            uvicorn_logger.removeHandler(handler)
        uvicorn_logger.propagate = True


def reset_logging() -> None:
    """Remove and close the handlers added by ``setup_logging``."""
    root = logging.getLogger()
    for handler in root.handlers[:]:
        if getattr(handler, _MARKER, False):
            root.removeHandler(handler)
            handler.close()
