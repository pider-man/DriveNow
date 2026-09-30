"""Smoke test: the package installs, every layer imports, and settings load from the environment."""

import importlib

from drivenow.config import Settings

LAYER_PACKAGES = [
    "drivenow",
    "drivenow.domain",
    "drivenow.db",
    "drivenow.repositories",
    "drivenow.services",
    "drivenow.api",
    "drivenow.api.routers",
    "drivenow.observability",
    "drivenow.messaging",
]

SETTINGS_ENV_VARS = [
    "DATABASE_URL",
    "LOG_LEVEL",
    "LOG_FILE",
    "WORKER_LOG_FILE",
    "RABBITMQ_URL",
    "API_HOST",
    "API_PORT",
]


def test_package_imports_and_settings_load(monkeypatch):
    for name in LAYER_PACKAGES:
        importlib.import_module(name)

    for var in SETTINGS_ENV_VARS:
        monkeypatch.delenv(var, raising=False)

    defaults = Settings(_env_file=None)
    assert defaults.database_url == "sqlite:///./drivenow.db"
    assert defaults.log_level == "INFO"
    assert defaults.log_file == "logs/drivenow.log"
    assert defaults.rabbitmq_url is None
    assert defaults.api_port == 8000

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/drivenow")
    monkeypatch.setenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")
    monkeypatch.setenv("API_PORT", "9000")

    overridden = Settings(_env_file=None)
    assert overridden.database_url == "postgresql+psycopg://u:p@db:5432/drivenow"
    assert overridden.rabbitmq_url == "amqp://guest:guest@rabbitmq:5672/"
    assert overridden.api_port == 9000
