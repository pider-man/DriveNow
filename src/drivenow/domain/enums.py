"""Enumerations shared by every layer."""

from enum import StrEnum


class CarStatus(StrEnum):
    """Status of a car in the fleet (PRD data model).

    The values are used as-is in the database, the API and the logs.
    """

    AVAILABLE = "available"
    IN_USE = "in_use"
    UNDER_MAINTENANCE = "under_maintenance"
