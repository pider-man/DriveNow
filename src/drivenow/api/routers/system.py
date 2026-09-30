"""System endpoints: /health. (/metrics and /stats come in build step 6.)"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from drivenow.api.dependencies import HealthCheck, get_health_check
from drivenow.api.errors import error_response
from drivenow.api.schemas import ErrorResponse, HealthRead

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
