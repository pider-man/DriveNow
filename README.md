# DriveNow Car Rental System

[![CI](https://github.com/pider-man/DriveNow/actions/workflows/ci.yml/badge.svg)](https://github.com/pider-man/DriveNow/actions/workflows/ci.yml)

A Python service that manages the DriveNow fleet: add, update, list and delete cars, register and end rentals, and always know each car's status (`available`, `in_use`, `under_maintenance`). It exposes a REST API (FastAPI, with Swagger UI). Every critical action is logged to the console and a file. It collects Prometheus metrics and publishes domain events to RabbitMQ, where an audit worker consumes them.

- **REST API** for cars and rentals, with one consistent JSON error format.
- **Business rules** that keep car status and rentals consistent (B1–B10), enforced in a service layer and backed by database constraints.
- **Observability**: console and rotating-file logs in UTC, `/metrics` for Prometheus, and `/stats` as plain JSON.
- **Message queue**: events such as `rental.started` go to RabbitMQ, and a worker writes an audit line for each one.
- **Runs two ways**: `docker compose up` (PostgreSQL, RabbitMQ, API, worker, Prometheus), or standalone Python on SQLite with no broker.
- **213 tests**, which pass on both SQLite and PostgreSQL.

The approved spec is [docs/PRD.md](docs/PRD.md), and the full design is [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Contents

- [Architecture](#architecture)
- [Run it](#run-it)
- [Use the API](#use-the-api)
- [Examples](#examples)
- [Logging](#logging)
- [Metrics](#metrics)
- [Message queue](#message-queue)
- [Tests](#tests)
- [Business rules](#business-rules)
- [Requirements checklist](#requirements-checklist)
- [Future work](#future-work)
- [How this was built](#how-this-was-built)
- [Screenshots](#screenshots)
- [Project layout](#project-layout)

---

## Architecture

### Components and request flow

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

### Renting a car (`POST /rentals`)

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
    else start before the car's previous rental end (B10)
        S-->>R: InvalidInputError START_BEFORE_PREVIOUS_END
        R-->>C: 422
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

### Layers

| Layer | Package | Responsibility |
| --- | --- | --- |
| API (interface) | `drivenow.api` | HTTP only: routes, Pydantic request and response models, and mapping domain errors to HTTP status codes. It contains no business rules, and only its composition root wires the data layer. |
| Services (business logic) | `drivenow.services` | Every business rule B1–B10, transaction boundaries, logging critical actions, publishing events after commit. It never imports FastAPI or SQLAlchemy. |
| Data access | `drivenow.db`, `drivenow.repositories` | ORM models, engine and session, repositories, and the Unit of Work. Database constraints act as a safety net for the rules. |
| Domain | `drivenow.domain` | Car status enum, typed errors with stable codes, events, and the plain records the services return. |
| Cross-cutting | `drivenow.observability`, `drivenow.messaging` | Logging setup, Prometheus metrics, timing middleware, the RabbitMQ publisher and the worker. |

These boundaries aren't just a convention. [`tests/test_architecture.py`](tests/test_architecture.py) checks every module's imports, and fails if, for example, a service imports SQLAlchemy or a router imports the data layer.

### SOLID in practice

- **Single responsibility**: `CarService` holds fleet rules and `RentalService` holds rental rules. Repositories only persist, routers only translate HTTP, and the publisher only transports.
- **Open/closed**: a new transport (for example Kafka) is a new `EventPublisher` implementation, with no service changes. A new error type maps to HTTP through one table in `api/errors.py`.
- **Liskov substitution**: any `UnitOfWork`, `EventPublisher`, `Clock` or `OperationRecorder` implementation can stand in for another. The unit tests run the real services against in-memory fakes and a fixed clock.
- **Interface segregation**: small protocols per concern (`CarRepository`, `RentalRepository`, `EventPublisher`, `Clock`, `OperationRecorder`), not one large DAO.
- **Dependency inversion**: for persistence, publishing, time and metrics, services depend on `typing.Protocol` abstractions. The concrete repositories, RabbitMQ publisher and Prometheus metrics are wired in one composition root, [`api/dependencies.py`](src/drivenow/api/dependencies.py). Even metrics are injected: `@track_operation` never imports Prometheus. The one deliberate shortcut is the entities: the SQLAlchemy models in `db/models.py` double as domain objects, so services use those classes directly. They still never touch a session or a query.

### Database choice

- **PostgreSQL in Docker, SQLite when standalone, with SQLAlchemy 2.0** (decisions D2 and D3).
- **Why relational:** the data is relational, since every rental belongs to a car. The rules span both tables and must hold under concurrent requests: only an available car can be rented, and a car has at most one ongoing rental. That needs transactions, foreign keys, row locks (`SELECT … FOR UPDATE`), a partial unique index (one ongoing rental per car) and CHECK constraints (an end can't be before its start). PostgreSQL provides all of them.
- **Why SQLite as well:** it gives the same guarantees with zero setup, so `pip install` and `python -m drivenow` just work, and the test suite runs fast.
- **Why SQLAlchemy 2.0:** its typed models run unchanged on both databases, and it fits the repository and Unit of Work patterns. Only `DATABASE_URL` changes between the two setups.

The two tables have exactly the fields the PDF names:

| Table | Columns |
| --- | --- |
| `cars` | `id`, `model`, `year`, `status` (`available` \| `in_use` \| `under_maintenance`) |
| `rentals` | `id`, `car_id` → `cars.id`, `customer_name`, `start_date`, `end_date` (NULL while ongoing) |

---

## Run it

### a) Everything with Docker Compose

```bash
docker compose up --build        # add -d to run in the background
```

| Service | URL | Notes |
| --- | --- | --- |
| API | http://localhost:8000 | REST API |
| Swagger UI | http://localhost:8000/docs | try every endpoint in the browser |
| Health / stats / metrics | http://localhost:8000/health, `/stats`, `/metrics` | |
| RabbitMQ management | http://localhost:15672 | user `drivenow`, password `drivenow` |
| Prometheus | http://localhost:9090 | query `drivenow_active_cars` |
| PostgreSQL | `localhost:5432` | db `drivenow` (the app) and `drivenow_test` (tests), user and password `drivenow` |
| Worker | none | `docker compose logs -f worker` |

```bash
docker compose ps                # all services up; postgres, rabbitmq and api report "healthy"
docker compose logs -f worker    # one AUDIT line per event
docker compose down              # stop; add -v to also delete the database and log volumes
```

The API and worker write their log files to the named volume `logs` (`/app/logs` in the containers). The credentials above are local development defaults, defined in `docker-compose.yml`. They aren't secrets; change them before exposing the stack anywhere.

### b) Standalone Python (SQLite, no broker)

Requires Python 3.12 or newer.

```bash
python -m venv .venv
# Windows:      .venv\Scripts\activate
# Linux/macOS:  source .venv/bin/activate
pip install -e ".[dev]"
python -m drivenow                  # http://127.0.0.1:8000/docs
```

This uses a SQLite file, `./drivenow.db`, and writes logs to `./logs/drivenow.log`. Events are dropped, because no broker is configured. All settings are environment variables; see [`.env.example`](.env.example):

| Variable | Default | Meaning |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./drivenow.db` | any SQLAlchemy URL, for example `postgresql+psycopg://user:pass@host:5432/db` |
| `RABBITMQ_URL` | *(empty)* | set it to publish events to RabbitMQ, for example `amqp://drivenow:drivenow@localhost:5672/` |
| `LOG_LEVEL` | `INFO` | `DEBUG` … `CRITICAL` |
| `LOG_FILE` / `WORKER_LOG_FILE` | `logs/drivenow.log` / `logs/worker.log` | log file paths |
| `API_HOST` / `API_PORT` | `127.0.0.1` / `8000` | where the API listens |

The worker runs standalone too, with `RABBITMQ_URL` set: `python -m drivenow.worker`.

---

## Use the API

| Method | Path | What it does | Success | Errors |
| --- | --- | --- | --- | --- |
| `POST` | `/cars` | add a car (F1) | `201` car | `422` |
| `GET` | `/cars?status=` | list cars, optionally one status (F3) | `200` list | `422` unknown status |
| `GET` | `/cars/{car_id}` | one car (F7) | `200` car | `404` |
| `PATCH` | `/cars/{car_id}` | update model, year and/or status (F2) | `200` car | `404`, `409`, `422` |
| `DELETE` | `/cars/{car_id}` | delete a car and its finished rentals (F6) | `204` | `404`, `409` |
| `POST` | `/rentals` | rent a car; it becomes `in_use` (F4) | `201` rental | `404`, `409`, `422` |
| `POST` | `/rentals/{rental_id}/end` | end a rental; the car becomes `available` (F5) | `200` rental | `404`, `409`, `422` |
| `GET` | `/rentals?car_id=&ongoing=` | list rentals, optionally filtered (F7) | `200` list | `422` |
| `GET` | `/rentals/{rental_id}` | one rental (F7) | `200` rental | `404` |
| `GET` | `/health` | API and database check | `200` | `503` |
| `GET` | `/stats` | key metrics as JSON | `200` | |
| `GET` | `/metrics` | Prometheus text format | `200` | |

**Car statuses.**
- `available`: the default for a new car.
- `under_maintenance`: set by hand, at creation or with `PATCH`.
- `in_use`: set **only** by starting a rental (B4). Ending the rental sets the car back to `available`.

**Dates.**
- All times are ISO 8601. Responses are always UTC (`…Z`).
- `start_date` and `end_date` are optional and default to now. A time without a timezone is taken as UTC.
- Future times are rejected.

**Errors.** Every error, including FastAPI's own validation errors, has one shape:

```json
{"error": {"code": "CAR_NOT_AVAILABLE", "message": "Car 1 is in_use and can't be rented"}}
```

| Code | HTTP | When |
| --- | --- | --- |
| `CAR_NOT_FOUND`, `RENTAL_NOT_FOUND` | 404 | the ID doesn't exist |
| `CAR_NOT_AVAILABLE` | 409 | renting a car that isn't available, or already has an ongoing rental (B2, B3) |
| `CAR_RENTED` | 409 | changing the status of, or deleting, a rented car (B5) |
| `RENTAL_ALREADY_ENDED` | 409 | ending a rental twice (B7) |
| `VALIDATION_ERROR` | 422 | bad or missing fields, an unrealistic year, a blank name, status `in_use` (B4, B8) |
| `DATE_IN_FUTURE` | 422 | a start or end time in the future |
| `END_BEFORE_START` | 422 | an end before the rental's start (B7) |
| `START_BEFORE_PREVIOUS_END` | 422 | a start before the end of the car's previous rental (B10) |
| `NOT_FOUND`, `METHOD_NOT_ALLOWED` | 404, 405 | an unknown route or method |
| `DATABASE_UNAVAILABLE` | 503 | `/health` can't reach the database |
| `INTERNAL_ERROR` | 500 | an unexpected error (logged with its stack trace; no details are leaked) |

---

## Examples

These were run against the compose stack, and the responses are real. PowerShell users should call `curl.exe` instead of `curl`.

**Add a car.** Returns `201`:
```bash
curl -X POST http://localhost:8000/cars -H "Content-Type: application/json" \
     -d '{"model": "Toyota Corolla", "year": 2022}'
```
```json
{"id":1,"model":"Toyota Corolla","year":2022,"status":"available"}
```

**Add a car that starts under maintenance.** Returns `201`:
```bash
curl -X POST http://localhost:8000/cars -H "Content-Type: application/json" \
     -d '{"model": "Kia Picanto", "year": 2020, "status": "under_maintenance"}'
```
```json
{"id":3,"model":"Kia Picanto","year":2020,"status":"under_maintenance"}
```

**List only the available cars.** Returns `200`:
```bash
curl "http://localhost:8000/cars?status=available"
```
```json
[{"id":1,"model":"Toyota Corolla","year":2022,"status":"available"},{"id":2,"model":"Mazda 3","year":2021,"status":"available"}]
```

**Rent a car.** Returns `201`, and the car becomes `in_use`:
```bash
curl -X POST http://localhost:8000/rentals -H "Content-Type: application/json" \
     -d '{"car_id": 1, "customer_name": "Dana Levi"}'
```
```json
{"id":1,"car_id":1,"customer_name":"Dana Levi","start_date":"2026-10-01T18:17:59.128771Z","end_date":null}
```

**Rent the same car again.** Returns `409`:
```bash
curl -X POST http://localhost:8000/rentals -H "Content-Type: application/json" \
     -d '{"car_id": 1, "customer_name": "Noa Cohen"}'
```
```json
{"error":{"code":"CAR_NOT_AVAILABLE","message":"Car 1 is in_use and can't be rented"}}
```

**End the rental.** Returns `200`, and the car becomes `available` again. You can optionally send a body such as `{"end_date": "2026-10-01T17:30:00Z"}`:
```bash
curl -X POST http://localhost:8000/rentals/1/end
```
```json
{"id":1,"car_id":1,"customer_name":"Dana Levi","start_date":"2026-10-01T18:17:59.128771Z","end_date":"2026-10-01T18:17:59.193388Z"}
```

**Update a car**, here taking it out of maintenance. Returns `200`:
```bash
curl -X PATCH http://localhost:8000/cars/3 -H "Content-Type: application/json" \
     -d '{"status": "available"}'
```
```json
{"id":3,"model":"Kia Picanto","year":2020,"status":"available"}
```

**Delete a car.** Returns `204` with no body. Deleting it again returns `404`:
```bash
curl -X DELETE http://localhost:8000/cars/2
curl -X DELETE http://localhost:8000/cars/2
```
```json
{"error":{"code":"CAR_NOT_FOUND","message":"Car 2 not found"}}
```

**Validation errors.** Both return `422`:
```bash
curl -X POST http://localhost:8000/cars -H "Content-Type: application/json" -d '{"model": "Toyota", "year": "old"}'
curl -X POST http://localhost:8000/rentals -H "Content-Type: application/json" \
     -d '{"car_id": 3, "customer_name": "Avi", "start_date": "2099-01-01T00:00:00Z"}'
```
```json
{"error":{"code":"VALIDATION_ERROR","message":"body.year: Input should be a valid integer, unable to parse string as an integer"}}
{"error":{"code":"DATE_IN_FUTURE","message":"start_date can't be in the future"}}
```

---

## Logging

Python's built-in `logging` writes to **both the console and a rotating file** (5 MB × 3 backups). It uses one format, with ISO 8601 **UTC** timestamps. These lines are from the example run above:

```
2026-10-01T18:17:59.001Z INFO    [drivenow.services.car_service] Car added: id=1 model='Toyota Corolla' year=2022 status=available
2026-10-01T18:17:59.135Z INFO    [drivenow.services.rental_service] Rental started: id=1 car_id=1 start=2026-10-01T18:17:59.128771+00:00
2026-10-01T18:17:59.166Z WARNING [drivenow.services.rental_service] start_rental rejected: CAR_NOT_AVAILABLE: Car 1 is in_use and can't be rented
2026-10-01T18:17:59.197Z INFO    [drivenow.services.rental_service] Rental ended: id=1 car_id=1 end=2026-10-01T18:17:59.193388+00:00
2026-10-01T18:17:59.229Z INFO    [drivenow.services.car_service] Car updated: id=3 changed=status model='Kia Picanto' year=2020 status=available
2026-10-01T18:17:59.262Z INFO    [drivenow.services.car_service] Car deleted: id=2 deleted_rentals=0
2026-10-01T18:17:59.315Z WARNING [drivenow.api.errors] POST /cars rejected: VALIDATION_ERROR: body.year: Input should be a valid integer, unable to parse string as an integer
```

What gets logged:
- **INFO**: adding, updating and deleting a car; starting and ending a rental; startup.
- **WARNING**: every rejected operation, both business rules and invalid requests.
- **ERROR**: unexpected errors (with the stack trace) and failed event publishes.

uvicorn's server and access logs go through the same handlers and format.

Where the files are:
- standalone: `logs/drivenow.log`
- Docker: the `logs` volume at `/app/logs`, for example `docker compose exec api tail -f /app/logs/drivenow.log`

`LOG_LEVEL` and `LOG_FILE` configure it.

---

## Metrics

`GET /metrics` exposes Prometheus metrics, from a registry owned by the app:

| Metric | Type | Meaning |
| --- | --- | --- |
| `drivenow_active_cars` | gauge | cars **not under maintenance** (`available` + `in_use`). Read from the database at every scrape, so it's always correct. |
| `drivenow_ongoing_rentals` | gauge | rentals with no end date, also read from the database |
| `drivenow_request_duration_seconds` | histogram | HTTP request time, by `method`, route template (`/cars/{car_id}`, not the real ID) and `status_code` |
| `drivenow_operation_duration_seconds` | histogram | service-operation time, by `operation` (`add_car`, `start_rental`, …) |
| `drivenow_operation_failures_total` | counter | failed operations, by `operation` and error `code` |

**Average response time** is `_sum / _count` of the request histogram. In PromQL: `rate(drivenow_request_duration_seconds_sum[5m]) / rate(drivenow_request_duration_seconds_count[5m])`. `/health`, `/metrics` and `/stats` are left out, so monitoring calls don't skew it.

`GET /stats` gives the key numbers as JSON, with no Prometheus needed. `avg_response_time_ms` is `null` until the first request has been measured:

```json
{"active_cars":3,"ongoing_rentals":1,"avg_response_time_ms":4.536}
```

With Docker, Prometheus scrapes `api:8000/metrics` every 15 s. Open http://localhost:9090 and query `drivenow_active_cars`.

---

## Message queue

- **Publisher.** After every successful commit, the API publishes a domain event to the durable **topic** exchange `drivenow.events`. The routing key is the event type: `car.created`, `car.updated`, `car.deleted`, `rental.started` or `rental.ended`.
- **Messages** are persistent JSON:
  ```json
  {"id": "76767cc4-1a25-4644-928e-da654f775d5d", "type": "rental.started", "occurred_at": "2026-10-01T18:06:15.452956+00:00",
   "payload": {"id": 1, "car_id": 1, "customer_name": "Dana Levi", "start_date": "2026-10-01T18:06:15.444699+00:00", "end_date": null}}
  ```
- **Thread safety.** The publisher serializes its single connection with a lock, which makes it safe for FastAPI's thread pool. Publisher confirms are on.
- **Best effort.** If the broker is down, the publisher reconnects once. If that fails too, it logs an ERROR, and **the request still succeeds**, because the database is the source of truth.
- **Worker.** The worker (`python -m drivenow.worker`) consumes the durable queue `drivenow.audit`, which is bound to all events (`#`). It writes an audit line for each one, then acknowledges it:
  ```
  2026-10-01T18:06:15.453Z INFO    [drivenow.messaging.worker] AUDIT rental.started id=76767cc4-… occurred_at=2026-10-01T18:06:15.452956+00:00 payload={"car_id": 1, "end_date": null, "id": 1, …}
  ```
  The audit line leaves out `customer_name`, so personal data stays out of the logs; the event itself still carries it. A malformed message is rejected without requeueing. If the broker goes away, the worker reconnects, waiting 1, 2, 4 … up to 30 s between tries.
- **Without a broker.** When `RABBITMQ_URL` isn't set, events are simply dropped.

---

## Tests

```bash
pytest                                   # 213 tests, in-memory SQLite, no Docker needed
```

**The same suite on PostgreSQL.** Run it against the compose database `drivenow_test`, which Postgres creates on first start:

```bash
docker compose up -d postgres
TEST_DATABASE_URL=postgresql+psycopg://drivenow:drivenow@localhost:5432/drivenow_test pytest
# PowerShell: $env:TEST_DATABASE_URL="postgresql+psycopg://drivenow:drivenow@localhost:5432/drivenow_test"; pytest
```

Each database-backed test drops and recreates the tables. For safety, the suite refuses any database whose name doesn't end in `_test`.

| Folder | What it covers |
| --- | --- |
| `tests/unit/` | services with in-memory fakes and a fixed clock (every rule B1–B10, dates, events), the logging setup, metrics and `@track_operation`, the RabbitMQ publisher and worker with fake pika connections |
| `tests/integration/` | repositories, Unit of Work and DB constraints (partial unique index, CHECK, FK RESTRICT) on a real database; transactions and race handling |
| `tests/api/` | every endpoint and error mapping through FastAPI's `TestClient`, a full add → rent → end → delete flow, the log file contents, `/metrics` and `/stats` |
| `tests/test_architecture.py` | layer boundaries, checked from the imports |

---

## Business rules

| Rule | What it enforces | If broken |
| --- | --- | --- |
| B1 | Starting a rental sets the car to `in_use`; ending it sets the car to `available`, in the same transaction | n/a |
| B2 | Only an `available` car can be rented | 409 `CAR_NOT_AVAILABLE` |
| B3 | At most one ongoing rental per car (also a partial unique index in the database) | 409 `CAR_NOT_AVAILABLE` |
| B4 | `in_use` is set only by rentals, never by hand | 422 `VALIDATION_ERROR` |
| B5 | A rented car's status can't change, and it can't be deleted (its model and year can still be corrected) | 409 `CAR_RENTED` |
| B6 | A new car starts `available`, or `under_maintenance` if requested | 422 for `in_use` |
| B7 | A rental can't be ended twice, or end before its start | 409 `RENTAL_ALREADY_ENDED`, 422 `END_BEFORE_START` |
| B8 | The model and customer name are required, and the year is realistic (1886 to next year) | 422 `VALIDATION_ERROR` |
| B9 | Deleting a car also deletes its finished rental history, in one transaction | (blocked by B5 while it's rented) |
| B10 | A rental can't start before the end of the car's most recent rental | 422 `START_BEFORE_PREVIOUS_END` |

Where each rule is enforced is in [ARCHITECTURE.md §8](docs/ARCHITECTURE.md#8-business-rule-enforcement-b1b10).

---

## Requirements checklist

The PRD's acceptance checklist, with where each item is met:

- [x] **Architecture design, shown as a graphic in the README.** [Architecture](#architecture) (Mermaid), and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
- [x] **`cars` and `rentals` tables with exactly the PDF fields, accessed through an ORM.** [`db/models.py`](src/drivenow/db/models.py); `test_schema_has_exactly_the_prd_fields` in [`tests/integration/test_repositories.py`](tests/integration/test_repositories.py).
- [x] **Database choice explained in the README.** [Database choice](#database-choice).
- [x] **F1 to F6 work through the chosen interface.** [`tests/api/test_cars_api.py`](tests/api/test_cars_api.py), [`test_rentals_api.py`](tests/api/test_rentals_api.py), and `test_full_rental_flow` in [`test_flow.py`](tests/api/test_flow.py).
- [x] **Business rules agreed in the PRD are enforced.** [Business rules](#business-rules). [`tests/unit/test_car_service.py`](tests/unit/test_car_service.py), [`test_rental_service.py`](tests/unit/test_rental_service.py) and [`tests/integration/test_services.py`](tests/integration/test_services.py).
- [x] **Critical actions and errors are logged to the console and a file.** [Logging](#logging); `test_critical_actions_reach_console_and_log_file` in [`tests/api/test_observability_api.py`](tests/api/test_observability_api.py).
- [x] **Metrics for active cars, ongoing rentals and average response time.** [Metrics](#metrics); `test_metrics_gauges_follow_the_database` and `test_stats_values_and_average_exclude_ops_endpoints`.
- [x] **Separate data access, service and interface layers.** [Layers](#layers); [`tests/test_architecture.py`](tests/test_architecture.py).
- [x] **At least 4 unit tests, all passing.** [Tests](#tests): 213 passing, on SQLite and on PostgreSQL.
- [x] **Runs standalone, with documented install steps and dependency management.** [`pyproject.toml`](pyproject.toml) and [Run it (b)](#b-standalone-python-sqlite-no-broker).
- [x] **`docker-compose up` starts the full system.** [`docker-compose.yml`](docker-compose.yml) and [Run it (a)](#a-everything-with-docker-compose).
- [x] **Public repo, feature branch, clear commit messages.** All work is on `feature/vehicle-management`, with one descriptive commit per build step.
- [x] **README covers the architecture graphic, how to run, how to use, the architecture description, example usage and screenshots.** This file.
- [x] **Message queue (D4: include).** [Message queue](#message-queue); [`messaging/rabbitmq.py`](src/drivenow/messaging/rabbitmq.py), [`messaging/worker.py`](src/drivenow/messaging/worker.py), and the [`tests/unit/test_rabbitmq_publisher.py`](tests/unit/test_rabbitmq_publisher.py) and [`test_worker.py`](tests/unit/test_worker.py) tests.

---

## Future work

- **Pagination** for `GET /cars` and `GET /rentals`. They currently return every row.
- **Alembic migrations.** Tables are currently created at startup with `create_all`, which is fine for two fixed tables but can't evolve a schema.
- **A transactional outbox**, for guaranteed event delivery. Publishing is currently best effort: an event is lost if the broker is down at that moment, though the request still succeeds.
- **Out of scope for this exercise**, per the PRD: authentication and roles, customers as their own entity, pricing and payments, reservations for future dates, and a web front end.

---

## How this was built

I designed and reviewed this project step by step, with [Claude Code](https://claude.com/claude-code) as the coding assistant.

- [`docs/PRD.md`](docs/PRD.md) is the plan we agreed on before any code was written: requirements, business rules, open decisions and a build plan.
- [`CLAUDE.md`](CLAUDE.md) holds the working rules Claude Code followed. It built one step at a time and stopped for my review after each one. Tests had to pass before every commit, and nothing was pushed without my approval.
- Each build step is one commit on `feature/vehicle-management`, so the history shows how the design in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) became code.

---

## Screenshots

All of these were taken from the running `docker compose` stack.

**Swagger UI** (`/docs`):

![Swagger UI](docs/screenshots/swagger-ui.png)

**Adding a car from Swagger** ("Try it out" → Execute, `201 Created`):

![Request executed in Swagger](docs/screenshots/swagger-execute.png)

**`/stats`:**

![/stats](docs/screenshots/stats.png)

**Prometheus graphing `drivenow_active_cars`:**

![Prometheus](docs/screenshots/prometheus-active-cars.png)

**RabbitMQ management UI**, showing the durable `drivenow.audit` queue:

![RabbitMQ management](docs/screenshots/rabbitmq-management.png)

**Worker audit log.** This is the output of `docker compose logs worker`, rendered as an image:

![Worker log](docs/screenshots/worker-log.png)

---

## Project layout

```
├── src/drivenow/
│   ├── api/              # FastAPI app factory, routers, schemas, error mapping, composition root
│   ├── services/         # CarService, RentalService, StatsService: the business rules
│   ├── repositories/     # repository protocols, SQLAlchemy repositories, Unit of Work
│   ├── db/               # ORM models, UTC datetime type, engine and session
│   ├── domain/           # CarStatus, typed errors, events, records
│   ├── observability/    # logging setup, Prometheus metrics, timing middleware, @track_operation
│   ├── messaging/        # EventPublisher, RabbitMQ publisher, audit worker
│   ├── config.py         # settings from environment variables
│   ├── main.py           # python -m drivenow
│   └── worker.py         # python -m drivenow.worker
├── tests/                # unit/, integration/, api/, test_architecture.py
├── docs/                 # PRD.md, ARCHITECTURE.md, screenshots/
├── docker/postgres/      # creates the drivenow_test database
├── prometheus/           # prometheus.yml
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```
