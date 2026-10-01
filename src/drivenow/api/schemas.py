"""Request and response models for the REST API.

These are the HTTP contract only. They are separate from the service records,
and they do only shape checks: the business rules live in the services.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from drivenow.domain.enums import CarStatus

ManualStatus = Literal["available", "under_maintenance"]
"""Statuses a client can set (B4: in_use is set only by rentals)."""


# --- Cars -----------------------------------------------------------------------------


class CarCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"model": "Toyota Corolla", "year": 2022}]},
    )

    model: str = Field(min_length=1, max_length=100, description="Car model, e.g. 'Toyota Corolla'.")
    year: int = Field(description="Model year, from 1886 up to next year.")
    status: ManualStatus = Field(
        default="available", description="Initial status (B6). in_use is set only by rentals (B4)."
    )


class CarUpdate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"status": "under_maintenance"}, {"model": "Toyota Corolla Hybrid"}]},
    )

    model: str | None = Field(default=None, min_length=1, max_length=100)
    year: int | None = None
    status: ManualStatus | None = Field(
        default=None, description="A rented car's status can't be changed (B5)."
    )


class CarRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    model: str
    year: int
    status: CarStatus


# --- Rentals --------------------------------------------------------------------------


class RentalCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"car_id": 1, "customer_name": "Dana Levi"}]},
    )

    car_id: int
    customer_name: str = Field(min_length=1, max_length=100)
    start_date: datetime | None = Field(
        default=None,
        description="Defaults to now. A time without a timezone is taken as UTC. Can't be in the future.",
    )


class RentalEnd(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{}, {"end_date": "2026-10-01T09:30:00Z"}]},
    )

    end_date: datetime | None = Field(
        default=None,
        description="Defaults to now. A time without a timezone is taken as UTC. "
        "Can't be in the future or before the start.",
    )


class RentalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    car_id: int
    customer_name: str
    start_date: datetime
    end_date: datetime | None = Field(description="null while the rental is ongoing.")


# --- Errors and system ----------------------------------------------------------------


class ErrorDetail(BaseModel):
    code: str = Field(description="Stable error code, e.g. CAR_NOT_FOUND or VALIDATION_ERROR.")
    message: str = Field(description="Human-readable explanation.")


class ErrorResponse(BaseModel):
    """The body of every error response."""

    error: ErrorDetail


class HealthRead(BaseModel):
    status: Literal["ok"] = "ok"


class StatsRead(BaseModel):
    active_cars: int = Field(description="Cars not under maintenance (available or in use).")
    ongoing_rentals: int = Field(description="Rentals that have not ended.")
    avg_response_time_ms: float | None = Field(
        description="Mean HTTP response time since start, excluding /health, /metrics and /stats. "
        "null before the first measured request."
    )
