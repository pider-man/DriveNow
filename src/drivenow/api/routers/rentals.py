"""Rental endpoints: F4 start, F5 end, F7 get and list."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query, status

from drivenow.api.dependencies import get_rental_service
from drivenow.api.schemas import ErrorResponse, RentalCreate, RentalEnd, RentalRead
from drivenow.services.rental_service import RentalService

router = APIRouter(prefix="/rentals", tags=["rentals"])

RentalServiceDep = Annotated[RentalService, Depends(get_rental_service)]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=RentalRead,
    responses={
        404: {"model": ErrorResponse, "description": "CAR_NOT_FOUND"},
        409: {"model": ErrorResponse, "description": "CAR_NOT_AVAILABLE (B2, B3)"},
        422: {
            "model": ErrorResponse,
            "description": "VALIDATION_ERROR, DATE_IN_FUTURE, START_BEFORE_PREVIOUS_END (B10)",
        },
    },
)
def start_rental(body: RentalCreate, rentals: RentalServiceDep) -> RentalRead:
    """F4: rent an available car. The car becomes in_use."""
    record = rentals.start_rental(body.car_id, body.customer_name, body.start_date)
    return RentalRead.model_validate(record)


@router.post(
    "/{rental_id}/end",
    response_model=RentalRead,
    responses={
        404: {"model": ErrorResponse, "description": "RENTAL_NOT_FOUND"},
        409: {"model": ErrorResponse, "description": "RENTAL_ALREADY_ENDED (B7)"},
        422: {"model": ErrorResponse, "description": "VALIDATION_ERROR, DATE_IN_FUTURE, END_BEFORE_START (B7)"},
    },
)
def end_rental(
    rental_id: int,
    rentals: RentalServiceDep,
    body: Annotated[RentalEnd | None, Body()] = None,
) -> RentalRead:
    """F5: end a rental. The car becomes available. The body is optional."""
    end_date = body.end_date if body is not None else None
    return RentalRead.model_validate(rentals.end_rental(rental_id, end_date))


@router.get(
    "",
    response_model=list[RentalRead],
    responses={422: {"model": ErrorResponse, "description": "VALIDATION_ERROR"}},
)
def list_rentals(
    rentals: RentalServiceDep,
    car_id: Annotated[int | None, Query(description="Only rentals of this car.")] = None,
    ongoing: Annotated[bool | None, Query(description="true: only ongoing; false: only finished.")] = None,
) -> list[RentalRead]:
    """F7: rentals, optionally filtered by car and by ongoing/finished."""
    return [RentalRead.model_validate(r) for r in rentals.list_rentals(car_id=car_id, ongoing=ongoing)]


@router.get(
    "/{rental_id}",
    response_model=RentalRead,
    responses={
        404: {"model": ErrorResponse, "description": "RENTAL_NOT_FOUND"},
        422: {"model": ErrorResponse, "description": "VALIDATION_ERROR"},
    },
)
def get_rental(rental_id: int, rentals: RentalServiceDep) -> RentalRead:
    """F7: one rental."""
    return RentalRead.model_validate(rentals.get_rental(rental_id))
