"""Car endpoints: F1 add, F2 update, F3 list, F6 delete, F7 get."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from drivenow.api.dependencies import get_car_service
from drivenow.api.schemas import CarCreate, CarRead, CarUpdate, ErrorResponse
from drivenow.domain.enums import CarStatus
from drivenow.services.car_service import CarService

router = APIRouter(prefix="/cars", tags=["cars"])

CarServiceDep = Annotated[CarService, Depends(get_car_service)]

NOT_FOUND = {404: {"model": ErrorResponse, "description": "CAR_NOT_FOUND"}}
INVALID = {422: {"model": ErrorResponse, "description": "VALIDATION_ERROR"}}
RENTED = {409: {"model": ErrorResponse, "description": "CAR_RENTED (B5)"}}


@router.post("", status_code=status.HTTP_201_CREATED, response_model=CarRead, responses=INVALID)
def add_car(body: CarCreate, cars: CarServiceDep) -> CarRead:
    """F1: add a car. It starts available unless under_maintenance is given."""
    return CarRead.model_validate(cars.add_car(body.model, body.year, body.status))


@router.get("", response_model=list[CarRead], responses=INVALID)
def list_cars(
    cars: CarServiceDep,
    car_status: Annotated[CarStatus | None, Query(alias="status", description="Only cars with this status.")] = None,
) -> list[CarRead]:
    """F3: all cars, optionally only those with one status."""
    return [CarRead.model_validate(car) for car in cars.list_cars(car_status)]


@router.get("/{car_id}", response_model=CarRead, responses={**NOT_FOUND, **INVALID})
def get_car(car_id: int, cars: CarServiceDep) -> CarRead:
    """F7: one car."""
    return CarRead.model_validate(cars.get_car(car_id))


@router.patch("/{car_id}", response_model=CarRead, responses={**NOT_FOUND, **RENTED, **INVALID})
def update_car(car_id: int, body: CarUpdate, cars: CarServiceDep) -> CarRead:
    """F2: change model, year and/or status. A rented car's status can't change (B5)."""
    record = cars.update_car(car_id, model=body.model, year=body.year, status=body.status)
    return CarRead.model_validate(record)


@router.delete(
    "/{car_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={**NOT_FOUND, **RENTED, **INVALID},
)
def delete_car(car_id: int, cars: CarServiceDep) -> Response:
    """F6: delete a car and its finished rentals (B9). Blocked while it's rented (B5)."""
    cars.delete_car(car_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
