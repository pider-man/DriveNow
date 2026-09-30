# DriveNow Car Rental System: Architecture

Status: approved 2026-09-30 (build plan step 1) · Source of truth: [PRD.md](PRD.md)

This document shows how the requirements in the PRD will be built. Where the two disagree, the PRD wins. The IDs used below (F1–F7, B1–B9, N1–N12, D1–D10) refer to the PRD's tables. The recommendations for D1–D10 and the rules B1–B9 are approved. The answers to the design questions are recorded in [Decisions](#13-decisions).

## 1. Overview and technology stack

DriveNow is a single Python service with a REST interface, plus a small background worker that consumes domain events from RabbitMQ.

| Concern | Choice | PRD reference |
| --- | --- | --- |
| Language | Python 3.12+ (Docker image 3.12; also developed and tested on 3.14) | N8 |
| Interface | REST API with FastAPI (Swagger UI at `/docs`) | D1 |
| Validation / DTOs | Pydantic v2 | N2 |
| Configuration | pydantic-settings (environment variables, `.env`) | N8, N10 |
| ORM | SQLAlchemy 2.0 (synchronous, typed `Mapped[]` models) | N3, D3 |
| Database | PostgreSQL in Docker, SQLite when standalone | D2 |
| Logging | Python's built-in `logging`, console + rotating file | N4, N5 |
| Metrics | `prometheus_client` | N6 |
| Message queue | RabbitMQ with `pika` | D4 |
| Tests | pytest, FastAPI `TestClient` | N7 |
| Dependencies | `pyproject.toml` (installable with `pip install -e .[dev]`) | N9 |
| Containers | `Dockerfile` + `docker-compose.yml` (api, worker, postgres, rabbitmq) | N10 |

The data access is synchronous on purpose. FastAPI runs sync endpoints in its thread pool, and the sync code is simpler to read, test and lock than async code. The load for this exercise doesn't justify async.

## 2. Layers and responsibilities

The code is split into three layers (N1), plus two cross-cutting modules. Dependencies point inward only: API → services → abstractions ← data access.

| Layer | Package | Responsible for | Must not |
| --- | --- | --- | --- |
| API (interface) | `drivenow.api` | HTTP routing, request/response schemas (Pydantic), shape validation, dependency wiring, mapping domain errors to HTTP status codes | contain business rules, or import ORM models or sessions |
| Services (business logic) | `drivenow.services` | All business rules B1–B9, transaction boundaries (via Unit of Work), logging critical actions, publishing domain events after commit, fleet statistics for `/stats` and the gauges | import FastAPI, or build SQL queries |
| Data access | `drivenow.db`, `drivenow.repositories` | ORM models, engine and session factory, repository implementations, Unit of Work, DB constraints | enforce business rules (constraints act only as a safety net) |
| Domain (shared) | `drivenow.domain` | `CarStatus` enum, domain exceptions, domain event definitions, plain data objects the services return | depend on anything else in the project |
| Observability | `drivenow.observability` | Logging configuration, Prometheus metrics, request-timing middleware | contain business logic |
| Messaging | `drivenow.messaging` | Event publisher interface and implementations, RabbitMQ worker | be required for the API to work |

How SOLID applies (N2):

- **Single responsibility.** Each class does one job: `CarService` handles fleet rules, `RentalService` handles rental rules, repositories handle persistence, routers handle HTTP, and the publisher handles transport.
- **Open/closed.** New event consumers or publishers (for example Kafka) plug in through the `EventPublisher` interface without changing the services. New error types map to HTTP through one table in `api/errors.py`.
- **Liskov substitution.** Every implementation of `CarRepository`, `RentalRepository`, `UnitOfWork`, `EventPublisher` and `Clock` can replace another. This is what lets the unit tests use in-memory fakes.
- **Interface segregation.** The repository interfaces are small and split per aggregate (`CarRepository`, `RentalRepository`), not one generic DAO.
- **Dependency inversion.** Services depend on `typing.Protocol` abstractions defined in `repositories/interfaces.py`, `messaging/publisher.py` and `services/clock.py`. The concrete objects are wired in `api/dependencies.py`, the composition root.

### Key abstractions

```python
class CarRepository(Protocol):
    def add(self, car: Car) -> Car: ...
    def get(self, car_id: int, *, for_update: bool = False) -> Car | None: ...
    def list(self, status: CarStatus | None = None) -> list[Car]: ...
    def delete(self, car: Car) -> None: ...
    def count_active(self) -> int: ...            # status != under_maintenance (D5)

class RentalRepository(Protocol):
    def add(self, rental: Rental) -> Rental: ...
    def get(self, rental_id: int, *, for_update: bool = False) -> Rental | None: ...
    def list(self, car_id: int | None = None, ongoing: bool | None = None) -> list[Rental]: ...
    def get_ongoing_for_car(self, car_id: int) -> Rental | None: ...
    def delete_finished_for_car(self, car_id: int) -> int: ...
    def count_ongoing(self) -> int: ...

class UnitOfWork(Protocol):                         # context manager
    cars: CarRepository
    rentals: RentalRepository
    def commit(self) -> None: ...
    def rollback(self) -> None: ...

class EventPublisher(Protocol):
    def publish(self, event: DomainEvent) -> None: ...

class Clock(Protocol):
    def now(self) -> datetime: ...                  # timezone-aware UTC
```

## 3. Component and request-flow diagrams

### Components

```mermaid
flowchart LR
    client["Client: Swagger UI, curl"]
    prom["Prometheus or reviewer browser"]

    subgraph api_proc["API process: FastAPI + uvicorn"]
        mw["Timing middleware"]
        routers["Routers: cars, rentals, system"]
        schemas["Pydantic schemas"]
        errors["Error mapper"]
        subgraph svc["Service layer"]
            carsvc["CarService"]
            rentsvc["RentalService"]
            statsvc["StatsService"]
        end
        subgraph dal["Data access layer"]
            uow["SqlAlchemyUnitOfWork"]
            repos["CarRepository, RentalRepository"]
            orm["ORM models: cars, rentals"]
        end
        metrics["Metrics registry"]
        logger["Logging: console + file"]
        pub["EventPublisher"]
    end

    db[("PostgreSQL in Docker or SQLite standalone")]
    logfile[/"logs/drivenow.log"/]
    mq{{"RabbitMQ exchange drivenow.events"}}

    subgraph worker_proc["Worker process"]
        worker["Event worker"]
        wlog[/"logs/worker.log"/]
    end

    client -->|HTTP JSON| mw --> routers
    routers --> schemas
    routers --> carsvc
    routers --> rentsvc
    routers -.->|domain errors| errors
    carsvc --> uow
    rentsvc --> uow
    uow --> repos --> orm --> db
    carsvc --> logger
    rentsvc --> logger
    errors --> logger
    logger --> logfile
    carsvc -->|after commit| pub
    rentsvc -->|after commit| pub
    pub -->|JSON event| mq --> worker --> wlog
    mw -->|request duration| metrics
    carsvc -->|operation duration| metrics
    rentsvc -->|operation duration| metrics
    prom -->|GET /metrics, GET /stats| routers
    routers --> statsvc
    statsvc --> uow
    metrics -.->|gauges read counts at scrape time| statsvc
```

### Request flow: register a rental (F4)

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant M as Timing middleware
    participant R as rentals router
    participant S as RentalService
    participant U as UnitOfWork + repos
    participant D as Database
    participant L as Logger
    participant P as EventPublisher
    participant Q as RabbitMQ
    participant W as Worker

    C->>M: POST /rentals {car_id, customer_name, start_date?}
    M->>R: forward, start timer
    R->>R: validate body with Pydantic (B8)
    R->>S: start_rental(car_id, customer_name, start_date)
    S->>S: start_date defaults to clock.now(), reject if in the future (B7)
    S->>U: cars.get(car_id, for_update=True)
    U->>D: SELECT ... FOR UPDATE
    alt car missing
        S-->>R: CarNotFoundError
        R-->>C: 404
    else car not available or already rented (B2, B3)
        S->>L: WARNING rule violation
        S-->>R: CarNotAvailableError
        R-->>C: 409
    else ok
        S->>U: rentals.add(start_date)
        S->>U: car.status = in_use (B1)
        S->>U: commit()
        U->>D: INSERT rental, UPDATE car, COMMIT
        S->>L: INFO rental started
        S->>P: publish rental.started
        P->>Q: basic_publish (best effort)
        Q-->>W: deliver
        W->>W: log event
        S-->>R: Rental
        R-->>C: 201 Rental JSON
    end
    S->>S: observe operation duration (start_rental)
    M->>M: observe request duration
```

## 4. Folder and module structure

```
.
├── CLAUDE.md
├── README.md                     # step 9
├── pyproject.toml                # dependencies, pytest config (step 2)
├── Dockerfile                    # step 8
├── docker-compose.yml            # api, worker, postgres, rabbitmq (step 8)
├── .env.example
├── docs/
│   ├── PRD.md
│   └── ARCHITECTURE.md
├── src/drivenow/
│   ├── __init__.py
│   ├── main.py                   # create_app(); `python -m drivenow` runs uvicorn standalone
│   ├── config.py                 # Settings: DATABASE_URL, LOG_LEVEL, LOG_FILE, RABBITMQ_URL, ...
│   ├── domain/
│   │   ├── enums.py              # CarStatus
│   │   ├── exceptions.py         # DomainError, NotFoundError, BusinessRuleViolation, InvalidInputError, DataIntegrityError
│   │   ├── events.py             # DomainEvent + event name constants
│   │   ├── records.py            # CarRecord, RentalRecord: plain objects the services return
│   │   └── timeutil.py           # to_utc (naive = UTC)
│   ├── db/
│   │   ├── base.py               # DeclarativeBase
│   │   ├── models.py             # Car, Rental ORM models
│   │   └── session.py            # engine + sessionmaker from DATABASE_URL, init_db()
│   ├── repositories/
│   │   ├── interfaces.py         # CarRepository, RentalRepository, UnitOfWork protocols
│   │   ├── car_repository.py     # SqlAlchemyCarRepository
│   │   ├── rental_repository.py  # SqlAlchemyRentalRepository
│   │   ├── errors.py             # IntegrityError -> DataIntegrityError
│   │   └── unit_of_work.py       # SqlAlchemyUnitOfWork
│   ├── services/
│   │   ├── _support.py           # validation, rejection logging, best-effort publish
│   │   ├── clock.py              # Clock protocol, SystemClock (UTC)
│   │   ├── car_service.py        # CarService (F1, F2, F3, F6, F7)
│   │   ├── rental_service.py     # RentalService (F4, F5, F7)
│   │   └── stats_service.py      # StatsService: active cars, ongoing rentals
│   ├── api/
│   │   ├── app.py                # FastAPI app, routers, middleware, exception handlers
│   │   ├── dependencies.py       # composition root: UoW, services, publisher
│   │   ├── errors.py             # domain error -> HTTP mapping, error body
│   │   ├── schemas.py            # CarCreate, CarUpdate, CarRead, RentalCreate, RentalRead, ErrorResponse
│   │   └── routers/
│   │       ├── cars.py
│   │       ├── rentals.py
│   │       └── system.py         # /health, /metrics, /stats
│   ├── observability/
│   │   ├── logging_config.py     # setup_logging(): console + rotating file
│   │   ├── metrics.py            # gauges, histograms, track_operation decorator
│   │   └── middleware.py         # request timing middleware
│   └── messaging/
│       ├── publisher.py          # EventPublisher protocol, NullPublisher, InMemoryPublisher, RabbitMQPublisher
│       └── worker.py             # `python -m drivenow.messaging.worker`
└── tests/
    ├── conftest.py               # SQLite in-memory engine, fakes, TestClient fixtures
    ├── unit/                     # services with in-memory fake UoW/publisher/clock
    ├── integration/              # repositories + UoW against SQLite
    └── api/                      # endpoints through TestClient
```

## 5. Database choice (D2, D3)

- **PostgreSQL in Docker** (`docker compose up`). The data is relational: every rental belongs to a car. Rules B2, B3 and B5 span both tables and must hold under concurrent requests. That needs real transactions, foreign keys, row locks (`SELECT … FOR UPDATE`) and partial unique indexes, and PostgreSQL provides all of them. A document store such as MongoDB would push these guarantees into application code.
- **SQLite for standalone runs** (N8). With no server to install, `pip install -e .` followed by `python -m drivenow` just works. SQLite is also used for the fast test suite. It supports the same foreign keys (enabled with `PRAGMA foreign_keys=ON`), partial unique index and CHECK constraint. It serializes writers, so `FOR UPDATE` isn't needed there (SQLAlchemy omits it).
- **SQLAlchemy 2.0** is the ORM (N3). It is the most widely used Python ORM, and its typed `Mapped[]` declarative models work unchanged on both engines. It fits the repository and Unit of Work patterns. It keeps the ORM out of the API layer, where SQLModel would blur the line between the API schema and the table model.
- Only `DATABASE_URL` changes between the two setups: `sqlite:///./drivenow.db` by default, and `postgresql+psycopg://drivenow:drivenow@postgres:5432/drivenow` in compose.
- **Schema creation**: `Base.metadata.create_all()` runs at startup. This is idempotent and enough for two tables. Alembic is listed as future work (Decision 9).

## 6. ORM schema

The tables have exactly the fields the PRD names. Constraints and indexes aren't fields.

### `cars`

| Column | SQLAlchemy type | Null | Notes |
| --- | --- | --- | --- |
| `id` | `Integer`, primary key, autoincrement | no | "car ID" |
| `model` | `String(100)` | no | B8: non-blank |
| `year` | `Integer` | no | B8: realistic year |
| `status` | `Enum(CarStatus, native_enum=False, length=20)` | no | `available`, `in_use`, `under_maintenance`; default `available` (B6) |

### `rentals`

| Column | SQLAlchemy type | Null | Notes |
| --- | --- | --- | --- |
| `id` | `Integer`, primary key, autoincrement | no | "rental ID" |
| `car_id` | `Integer`, `ForeignKey("cars.id", ondelete="RESTRICT")` | no | "car ID"; indexed |
| `customer_name` | `String(100)` | no | B8: non-blank |
| `start_date` | `UTCDateTime` (wraps `DateTime(timezone=True)`) | no | UTC (D7) |
| `end_date` | `UTCDateTime` | yes | `NULL` while the rental is ongoing |

Constraints (safety nets for rules the service enforces first):

- `ix_rentals_one_ongoing_per_car`: unique index on `rentals(car_id)` `WHERE end_date IS NULL` (B3). Declared with both `postgresql_where` and `sqlite_where`.
- `ck_rentals_end_after_start`: `CHECK (end_date IS NULL OR end_date >= start_date)` (B7).
- `ck_cars_year_positive`: `CHECK (year > 0)` (B8). The realistic range itself depends on the current year, so the application enforces it.
- The foreign key uses `RESTRICT`, not `CASCADE`. B9's history delete is an explicit step in the service, so a car is never removed with its rental history by accident.

`CarStatus` is a `str` enum. Its values (`available`, `in_use`, `under_maintenance`) appear the same in the DB, the API and the logs. `native_enum=False` stores them as `VARCHAR` with a CHECK constraint, which behaves the same on PostgreSQL and SQLite.

`UTCDateTime` (`db/types.py`) stores every timestamp in UTC. A naive value is treated as UTC, and values are always read back as aware UTC. PostgreSQL stores `TIMESTAMP WITH TIME ZONE`. SQLite has no time zone support, so values are stored as naive UTC text in one fixed format, which keeps the CHECK comparison correct.

The models define no ORM relationships. Repositories query rentals by `car_id`, so there are no lazy loads that could fail after the session closes (DetachedInstanceError). The session factory uses `expire_on_commit=False`, and the Unit of Work closes the session without expiring objects, so returned objects stay readable.

## 7. REST API (F1–F7)

JSON in and out. Timestamps are ISO 8601 in UTC (for example `2026-10-01T09:30:00Z`). Interactive docs are at `/docs`.

### Resource shapes

```jsonc
// Car
{ "id": 1, "model": "Toyota Corolla", "year": 2022, "status": "available" }

// Rental
{ "id": 7, "car_id": 1, "customer_name": "Dana Levi",
  "start_date": "2026-10-01T09:30:00Z", "end_date": null }

// Error (every 4xx/5xx)
{ "error": { "code": "CAR_NOT_AVAILABLE", "message": "Car 1 is in_use and cannot be rented" } }
```

### Endpoints

| ID | Method and path | Request | Success | Errors |
| --- | --- | --- | --- | --- |
| F1 | `POST /cars` | `{ "model": str, "year": int, "status"?: "available" \| "under_maintenance" }` | `201` Car | `422 VALIDATION_ERROR` (blank model, bad year, status `in_use`) |
| F2 | `PATCH /cars/{car_id}` | any of `{ "model"?, "year"?, "status"?: "available" \| "under_maintenance" }`, at least one | `200` Car | `404 CAR_NOT_FOUND`; `409 CAR_RENTED` (B5); `422 VALIDATION_ERROR` (includes status `in_use`, B4) |
| F3 | `GET /cars?status={status}` | optional `status` query parameter | `200` Car[] (ordered by id) | `422 VALIDATION_ERROR` (unknown status) |
| F6 | `DELETE /cars/{car_id}` | none | `204` no body | `404 CAR_NOT_FOUND`; `409 CAR_RENTED` (B5) |
| F7 | `GET /cars/{car_id}` | none | `200` Car | `404 CAR_NOT_FOUND` |
| F4 | `POST /rentals` | `{ "car_id": int, "customer_name": str, "start_date"?: datetime }` | `201` Rental | `404 CAR_NOT_FOUND`; `409 CAR_NOT_AVAILABLE` (B2/B3); `422 VALIDATION_ERROR`, `DATE_IN_FUTURE` |
| F5 | `POST /rentals/{rental_id}/end` | optional body `{ "end_date"?: datetime }` | `200` Rental (with `end_date` set) | `404 RENTAL_NOT_FOUND`; `409 RENTAL_ALREADY_ENDED` (B7); `422 DATE_IN_FUTURE`, `END_BEFORE_START` (B7) |
| F7 | `GET /rentals?car_id={id}&ongoing={bool}` | both filters optional | `200` Rental[] (ordered by id) | `422 VALIDATION_ERROR` |
| F7 | `GET /rentals/{rental_id}` | none | `200` Rental | `404 RENTAL_NOT_FOUND` |

Supporting endpoints (not in the PRD's list):

| Method and path | Purpose |
| --- | --- |
| `GET /metrics` | Prometheus text format (N6) |
| `GET /stats` | `200 { "active_cars": int, "ongoing_rentals": int, "avg_response_time_ms": float \| null }`, the key metrics as JSON so they can be read without Prometheus (`null` until a request has been measured) |
| `GET /health` | `200 {"status": "ok"}` after a `SELECT 1`, used by the docker-compose healthcheck |
| `GET /docs` | Swagger UI (D1) |

F5 is a `POST` action on the rental, not `PATCH /rentals/{id}`, because ending a rental is a command with side effects on the car (B1), not a field edit.

**Dates (D7, B7).** `start_date` and `end_date` are optional in the requests and default to the server clock (UTC). Staff can supply an earlier time to record a rental that started or ended in the past. A supplied datetime without a timezone is accepted and treated as UTC (reviewers type plain times in Swagger). One with an offset is converted to UTC. A time in the future returns `422 DATE_IN_FUTURE`, and an end before the start returns `422 END_BEFORE_START`.

### Error mapping (`api/errors.py`)

| Domain exception | HTTP | Codes |
| --- | --- | --- |
| `NotFoundError` | 404 | `CAR_NOT_FOUND`, `RENTAL_NOT_FOUND` |
| `BusinessRuleViolation` | 409 | `CAR_NOT_AVAILABLE`, `CAR_RENTED`, `RENTAL_ALREADY_ENDED` |
| `InvalidInputError` (service-level validation) and FastAPI `RequestValidationError` | 422 | `VALIDATION_ERROR` (the message lists the fields), `DATE_IN_FUTURE`, `END_BEFORE_START` |
| any other exception | 500 | `INTERNAL_ERROR` (logged at ERROR with the stack trace, no details leaked) |

## 8. Business rule enforcement (B1–B9)

Every rule lives in the service layer, so it holds for any interface. The API schemas reject bad input early for better messages, and the DB constraints catch anything that slips through.

| Rule | Primary enforcement | Early check (API) | Safety net (DB) |
| --- | --- | --- | --- |
| B1 rental start → `in_use`, end → `available` | `RentalService.start_rental` / `end_rental` change the car status in the same Unit of Work as the rental insert/update | none | single transaction |
| B2 only an `available` car can be rented | `RentalService.start_rental` loads the car `for_update=True` and raises `CarNotAvailableError` unless the status is `available` | none | row lock (PostgreSQL) |
| B3 at most one ongoing rental per car | `RentalService.start_rental` checks `rentals.get_ongoing_for_car` | none | partial unique index `ix_rentals_one_ongoing_per_car`; the data layer raises `DataIntegrityError` and the service turns it into `CAR_NOT_AVAILABLE` (409), never a 500 |
| B4 `in_use` only through rentals | `CarService.create_car` / `update_car` reject `status == in_use` | `CarCreate` / `CarUpdate` schemas allow only `available` / `under_maintenance` | none |
| B5 a rented car's status can't change and it can't be deleted | `CarService.update_car` (when `status` is in the payload) and `delete_car` raise `CarRentedError` when the car has an ongoing rental | none | FK `RESTRICT` blocks deleting a car that has rentals |
| B6 new car is `available` or `under_maintenance` | `CarService.create_car` defaults to `available` | `CarCreate.status` default and allowed values | column default |
| B7 no double end; end ≥ start; no future times | `RentalService.start_rental` rejects `start_date > clock.now()`. `RentalService.end_rental` loads the rental `for_update=True`, raises `RentalAlreadyEndedError` if `end_date` is set, uses the given `end_date` or `clock.now()`, and requires `start_date ≤ end_date ≤ clock.now()` | Pydantic parses datetimes; naive values are treated as UTC | `ck_rentals_end_after_start` |
| B8 model and customer name required; realistic year | `CarService` / `RentalService` validate (strip, non-blank; `1886 ≤ year ≤ current_year + 1`) | Pydantic: `min_length=1`, stripped strings, year bounds | `NOT NULL`, `ck_cars_year_positive` |
| B9 deleting a car deletes its finished history (D6) | `CarService.delete_car`: after the B5 check, `rentals.delete_finished_for_car` and then `cars.delete`, in one Unit of Work | none | FK `RESTRICT` ensures the order is explicit |

State transitions for `car.status` that the services allow:

```mermaid
stateDiagram-v2
    [*] --> available: create (default)
    [*] --> under_maintenance: create
    available --> under_maintenance: PATCH status
    under_maintenance --> available: PATCH status
    available --> in_use: start rental (only path, B4)
    in_use --> available: end rental (B1)
    available --> [*]: delete
    under_maintenance --> [*]: delete
```

## 9. Logging (N4, N5)

- `observability/logging_config.setup_logging(settings)` applies a `logging.config.dictConfig`. It runs once at API startup and once at worker startup.
- Handlers: a `StreamHandler` (stdout) and a `RotatingFileHandler` (`LOG_FILE`, default `logs/drivenow.log`, 5 MB × 3 backups). The directory is created if it's missing. The worker defaults to `logs/worker.log`.
- Format: `%(asctime)s %(levelname)s %(name)s: %(message)s` with ISO timestamps. Level: `LOG_LEVEL` (default `INFO`).
- Each module uses `logging.getLogger(__name__)`.

| Event | Level | Logged by |
| --- | --- | --- |
| Car added / updated / deleted (with id and changed fields) | INFO | `CarService` |
| Rental started / ended (rental id, car id, customer) | INFO | `RentalService` |
| Business rule rejected (for example rent an unavailable car) | WARNING | services, before raising |
| Unhandled exception | ERROR with stack trace | global exception handler in `api/app.py` |
| Event publish failed | ERROR | `RabbitMQPublisher` |
| Event received | INFO | worker |
| Startup (DB URL without credentials, publisher type) | INFO | `main.py` |

## 10. Metrics (N6, D5)

`prometheus_client` provides the metrics. `GET /metrics` returns `generate_latest()` in the Prometheus text format.

| Metric | Type | Meaning | How it's computed |
| --- | --- | --- | --- |
| `drivenow_active_cars` | Gauge | Cars **not under maintenance** (D5): `available` + `in_use` | `Gauge.set_function` calls `StatsService.active_cars()` (a `cars.count_active()` query in a short read-only session) at scrape time |
| `drivenow_ongoing_rentals` | Gauge | Rentals with `end_date IS NULL` | `Gauge.set_function` calls `StatsService.ongoing_rentals()` at scrape time |
| `drivenow_request_duration_seconds` | Histogram, labels `method`, `route`, `status_code` | HTTP request latency | Timing middleware uses `time.perf_counter()`. `route` is the route template (for example `/cars/{car_id}`), so labels stay bounded |
| `drivenow_operation_duration_seconds` | Histogram, label `operation` | Business operation latency, inside the service layer | The `@track_operation("<name>")` decorator on each service method. Operations: `add_car`, `update_car`, `delete_car`, `get_car`, `list_cars`, `start_rental`, `end_rental`, `get_rental`, `list_rentals`. Recorded on success and on failure |

The average response time is `drivenow_request_duration_seconds_sum / drivenow_request_duration_seconds_count`, overall or per route. The same applies to operations. In PromQL it's `rate(..._sum[5m]) / rate(..._count[5m])`. The histogram buckets also give percentiles.

The gauges are computed from the database at scrape time, not kept as counters in memory. That keeps them correct across restarts, multiple uvicorn workers and direct DB changes. `/metrics`, `/stats` and `/health` are excluded from the request histogram so monitoring calls don't skew the average.

`GET /stats` gives the same numbers as JSON for reviewers who don't run Prometheus. `active_cars` and `ongoing_rentals` come from `StatsService`. `avg_response_time_ms` is the request histogram's total `_sum / _count × 1000` since process start, read from the registry, and is `null` before the first measured request. The router calls only `StatsService` and `observability.metrics`, never a repository.

## 11. Message queue (D4)

- **Interface**: `EventPublisher.publish(event: DomainEvent)`. Services call it **after** a successful commit, so no event describes a change that was rolled back.
- **Implementations**:
  - `RabbitMQPublisher` (when `RABBITMQ_URL` is set) uses `pika`. It declares a durable **topic** exchange `drivenow.events` and publishes persistent JSON messages with routing key = event name. A lock and lazy reconnect make it safe across FastAPI's thread pool.
  - `NullPublisher` (standalone default) does nothing, so the app runs without a broker.
  - `InMemoryPublisher` keeps events in a list. It is used in tests, and as the default until `RabbitMQPublisher` is added in step 7.
- **Best effort**: if the broker is down, the failure is logged at ERROR and the HTTP request still succeeds. The DB is the source of truth, and events are notifications. A transactional outbox would guarantee delivery, and is listed as future work.
- **Events**:

  | Routing key | Payload |
  | --- | --- |
  | `car.created` | Car |
  | `car.updated` | Car + `changed_fields` |
  | `car.deleted` | `car_id`, `deleted_rentals` |
  | `rental.started` | Rental |
  | `rental.ended` | Rental |

  Message body: `{"event": "rental.started", "occurred_at": "2026-10-01T09:30:00Z", "payload": {...}}`.
- **Worker** (`python -m drivenow.messaging.worker`, its own compose service): it declares durable queue `drivenow.audit`, binds it with `#`, consumes with manual acks, logs each event through the shared logging config and acks. It retries the connection with backoff at startup while RabbitMQ is still booting. The worker's job is kept small on purpose, as an audit or notification hook. It shows asynchronous decoupling without moving any business rule out of the API.

## 12. Testing strategy (N7)

| Level | Scope | Tools |
| --- | --- | --- |
| Unit | `CarService`, `RentalService`: every rule B1–B9, with an in-memory fake UoW, a fixed `Clock` and a recording publisher | pytest |
| Integration | Repositories, UoW, constraints (partial unique index, CHECK, FK) against SQLite in-memory | pytest + SQLAlchemy |
| API | Every endpoint, status code and error body; `/metrics` contains all four metrics; `/stats` returns the right counts | FastAPI `TestClient` with a dependency override to a SQLite test DB |
| Messaging | Event serialization, and that publisher failure doesn't fail the service | pytest with a mocked `pika` channel |

The tests never need Docker, PostgreSQL or RabbitMQ. `pytest` must pass before every commit (see `CLAUDE.md`).

## 13. Decisions

The open questions from the step 1 review were answered on 2026-09-30. The sections above already reflect these answers.

1. **Approval.** All D1–D10 recommendations and business rules B1–B9 are approved as written in the PRD.
2. **B5 scope.** A rented car's `model` and `year` can still be corrected. Only a status change and deletion are blocked while it is rented.
3. **Dates (B7, D7).** `start_date` and `end_date` default to the server clock (UTC). `POST /rentals` and `POST /rentals/{id}/end` each accept an optional time, so staff can record a rental that started or ended earlier. Future times are rejected (`422 DATE_IN_FUTURE`), and so is an end before the start (`422 END_BEFORE_START`). A time without a timezone is accepted and treated as UTC, and a time with an offset is converted to UTC.
4. **Realistic year (B8).** 1886 up to the current year + 1.
5. **Status values.** `available`, `in_use`, `under_maintenance` in JSON, the DB and query strings.
6. **IDs.** Auto-increment integers.
7. **Rental listing (F7).** Filters `car_id` and `ongoing`. No paging on any list. *README future work:* pagination.
8. **Response time metrics (N6).** Keep the request histogram and add the per-operation histogram `drivenow_operation_duration_seconds`, since the PDF says "request/operation response time". Add `GET /stats`, which returns `active_cars`, `ongoing_rentals` and `avg_response_time_ms` as JSON, so a reviewer can see them without Prometheus.
9. **Schema creation.** Tables are created at startup with `create_all`. *README future work:* Alembic migrations.
10. **Health check.** Add `GET /health`.
11. **Queue delivery.** Best-effort publishing after commit is acceptable for this scope, and failures are logged. *README future work:* a transactional outbox.
12. **D10 prototype.** Ignored. There is no prototype to consult.
13. **Tests per step.** Step 1 was documentation only and has no tests. Every step from step 2 onward includes tests.
14. **`/stats` before any traffic.** `avg_response_time_ms` is `null` until the first request has been measured.
