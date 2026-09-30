"""Application settings, read from environment variables (and an optional ``.env`` file)."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Runtime configuration for the API and the worker.

    Each field maps to an environment variable of the same name in upper case
    (for example ``database_url`` <- ``DATABASE_URL``). The defaults run the app
    standalone: SQLite in the working directory and no message broker.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./drivenow.db"
    """SQLAlchemy URL. PostgreSQL in Docker, SQLite when standalone (D2)."""

    log_level: LogLevel = "INFO"
    """Minimum level for the console and file log handlers."""

    log_file: str = "logs/drivenow.log"
    """Log file for the API process."""

    worker_log_file: str = "logs/worker.log"
    """Log file for the RabbitMQ worker process."""

    rabbitmq_url: str | None = None
    """AMQP URL. When unset, events go to a no-op publisher (D4)."""

    api_host: str = "127.0.0.1"
    """Interface the standalone API server binds to."""

    api_port: int = 8000
    """Port the standalone API server listens on."""


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings, loaded once on first use."""
    return Settings()
