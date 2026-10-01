"""System endpoints: /health, /metrics and /stats."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse

from drivenow.api.dependencies import HealthCheck, get_health_check, get_metrics, get_stats_service
from drivenow.api.errors import error_response
from drivenow.api.schemas import ErrorResponse, HealthRead, StatsRead
from drivenow.observability.metrics import AppMetrics
from drivenow.services.stats_service import StatsService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system"])


@router.get(
    "/health",
    response_model=HealthRead,
    responses={503: {"model": ErrorResponse, "description": "DATABASE_UNAVAILABLE"}},
)
def health(check: Annotated[HealthCheck, Depends(get_health_check)]) -> HealthRead | JSONResponse:
    """Liveness and database check, used by the docker-compose healthcheck."""
    try:
        check()
    except Exception:
        logger.exception("Health check failed")
        return error_response(503, "DATABASE_UNAVAILABLE", "Database is not reachable")
    return HealthRead()


@router.get(
    "/metrics",
    response_class=Response,
    responses={200: {"content": {"text/plain": {}}, "description": "Prometheus text format"}},
)
def metrics(app_metrics: Annotated[AppMetrics, Depends(get_metrics)]) -> Response:
    """Prometheus metrics: active cars, ongoing rentals, request and operation durations."""
    body, content_type = app_metrics.render()
    return Response(content=body, media_type=content_type)


@router.get("/stats", response_model=StatsRead)
def stats(
    stats_service: Annotated[StatsService, Depends(get_stats_service)],
    app_metrics: Annotated[AppMetrics, Depends(get_metrics)],
) -> StatsRead:
    """The key metrics as JSON, for reading without Prometheus."""
    return StatsRead(
        active_cars=stats_service.active_cars(),
        ongoing_rentals=stats_service.ongoing_rentals(),
        avg_response_time_ms=app_metrics.average_request_ms(),
    )
