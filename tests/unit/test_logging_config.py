"""setup_logging: console + rotating file, one format, idempotent, uvicorn included."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from logging.handlers import RotatingFileHandler

import pytest

from drivenow.observability.logging_config import reset_logging, setup_logging

LINE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z (INFO|WARNING|ERROR) +\[[\w.]+\] .+$")


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    yield
    reset_logging()


def _our_handlers() -> list[logging.Handler]:
    return [h for h in logging.getLogger().handlers if getattr(h, "_drivenow_handler", False)]


def test_creates_folder_and_writes_to_console_and_file(tmp_path, capsys):
    log_file = tmp_path / "nested" / "logs" / "drivenow.log"
    setup_logging("INFO", str(log_file))

    logging.getLogger("drivenow.test").info("Car added: id=1")
    logging.getLogger("drivenow.test").debug("not shown at INFO")

    file_lines = log_file.read_text(encoding="utf-8").splitlines()
    console_lines = [line for line in capsys.readouterr().out.splitlines() if "drivenow.test" in line]
    assert len(file_lines) == 1
    assert file_lines == console_lines
    assert LINE.match(file_lines[0])
    assert file_lines[0].endswith("INFO    [drivenow.test] Car added: id=1")


def test_setup_twice_does_not_duplicate_handlers(tmp_path):
    log_file = tmp_path / "drivenow.log"
    setup_logging("INFO", str(log_file))
    setup_logging("INFO", str(log_file))

    handlers = _our_handlers()
    assert len(handlers) == 2
    assert sum(isinstance(h, RotatingFileHandler) for h in handlers) == 1

    logging.getLogger("drivenow.test").warning("once")
    assert log_file.read_text(encoding="utf-8").count("once") == 1


def test_uvicorn_logs_use_the_same_handlers_and_format(tmp_path):
    uvicorn_logger = logging.getLogger("uvicorn.access")
    uvicorn_logger.addHandler(logging.StreamHandler())  # as if uvicorn had configured itself
    uvicorn_logger.propagate = False

    log_file = tmp_path / "drivenow.log"
    setup_logging("INFO", str(log_file))
    uvicorn_logger.info('127.0.0.1:5000 - "GET /cars HTTP/1.1" 200')

    assert uvicorn_logger.handlers == [] and uvicorn_logger.propagate
    [line] = log_file.read_text(encoding="utf-8").splitlines()
    assert LINE.match(line) and "[uvicorn.access]" in line


def test_level_comes_from_settings(tmp_path):
    log_file = tmp_path / "drivenow.log"
    setup_logging("WARNING", str(log_file))
    logging.getLogger("drivenow.test").info("hidden")
    logging.getLogger("drivenow.test").warning("shown")
    content = log_file.read_text(encoding="utf-8")
    assert "hidden" not in content and "shown" in content


def test_reset_removes_only_our_handlers(tmp_path):
    other = logging.NullHandler()
    logging.getLogger().addHandler(other)
    try:
        setup_logging("INFO", str(tmp_path / "drivenow.log"))
        reset_logging()
        assert _our_handlers() == []
        assert other in logging.getLogger().handlers
    finally:
        logging.getLogger().removeHandler(other)
