# DriveNow Car Rental System: PRD

Sep 30, 2026 · @Eldad · Approved 2026-09-30

## Overview and goals

DriveNow needs a Python service to manage its fleet, register rentals and show each car's status, delivered by 2026-10-02 as a public Git repository. The source is the exercise PDF (CAR-RENTAL-SYSTEM-EXERCISE.pdf); every requirement below traces back to it.

Goals:

1. Staff can add, update and delete cars, and see each car's status (available, in use, under maintenance).
2. Staff can register a rental and end it, with the car's status kept correct automatically.
3. The code is a clean foundation for future growth: separated layers, SOLID where it fits, tested and documented.
4. The system is observable: critical actions are logged, and key metrics are collected.

Success means every item in the Acceptance checklist below is met and shown in the README.

## Scope

In scope is everything the PDF marks as required; the message queue is the one optional extra, and we decide below whether to include it.

| Area | Status | PDF section |
| --- | --- | --- |
| System architecture design | Required | Objectives 0 |
| Data access layer with ORM, `cars` and `rentals` tables | Required | Technical 1 |
| Business logic layer | Required | Objectives 2 |
| User interface: REST API or CLI | Required (one of the two) | Objectives 3 |
| Logging to console and file | Required | Technical 3 |
| Metrics: active cars, ongoing rentals, average response time | Required | Technical 4 |
| At least 4 unit tests | Required | Technical 5 |
| Dependency management, docker-compose.yml, runs standalone | Required | Technical 6 |
| Public GitHub/GitLab repo, feature branch, clear commits | Required | Technical 7 |
| README with architecture graphic, run, usage, examples | Required | Deliverables 2 |
| Screenshots in README | Recommended | Deliverables 2 |
| Message queue communication | Optional, recommended | Extra |

Out of scope (not in the PDF): authentication and user roles, customers as their own entity, pricing and payments, reservations for future dates, a web front end.

## Users and user stories

The system has two kinds of users: DriveNow fleet staff, who run the daily operations, and the engineers or reviewers who run and assess the service.

| # | As a | I want to | So that |
| --- | --- | --- | --- |
| U1 | Fleet staff | add a new car with its model and year | it can be rented |
| U2 | Fleet staff | update a car's details, including its status | records stay accurate, e.g. a car goes to maintenance |
| U3 | Fleet staff | delete a car | retired cars leave the fleet |
| U4 | Fleet staff | list all cars, optionally only those with one status | I can see what is available right now |
| U5 | Fleet staff | register a rental for a customer on a car | the car is marked in use |
| U6 | Fleet staff | end a rental | the car becomes available again |
| U7 | Engineer | read logs of critical actions and errors in the console and a file | I can trace what happened |
| U8 | Engineer | see metrics for active cars, ongoing rentals and response time | I can monitor the service |
| U9 | Reviewer | start the whole system with one docker-compose command | I can evaluate it quickly |

## Functional requirements

The data model is exactly the two tables the PDF names; the operations are the five it lists plus delete, which the Background section asks for.

Data model:

| Table | Fields (from the PDF) | Notes |
| --- | --- | --- |
| cars | car ID, model, year, status | status is one of available, in use, under maintenance |
| rentals | rental ID, car ID, customer name, start date, end date | end date is empty while the rental is ongoing |

Operations:

| ID | Operation | Result | Source |
| --- | --- | --- | --- |
| F1 | Add a new car | Car saved with a new ID | Required operations |
| F2 | Update car details (e.g. status) | Changed fields saved | Required operations |
| F3 | List all cars, optional status filter | All cars, or only those with the given status | Required operations |
| F4 | Register a new rental | Rental saved, car becomes in use | Required operations |
| F5 | End a rental and update car status | End date saved, car becomes available | Required operations |
| F6 | Delete a car | Car removed | Background: manage vehicles |
| F7 | Get one car or one rental; list rentals | Supporting reads for the above | Not in PDF, suggested |

## Business rules

The PDF states only that ending a rental updates the car's status; the rules below are proposed to keep status and rentals consistent, and each needs your OK.

| ID | Proposed rule | From PDF? |
| --- | --- | --- |
| B1 | Registering a rental sets the car to in use; ending it sets the car to available | Yes (end); implied (start) |
| B2 | Only an available car can be rented (not in use, not under maintenance) | Proposed |
| B3 | A car has at most one ongoing rental at a time | Proposed |
| B4 | In use is set only by rentals, never by hand | Proposed |
| B5 | A rented car's status can't be changed, and it can't be deleted, until the rental ends | Proposed |
| B6 | A new car starts as available (or under maintenance) | Proposed |
| B7 | A rental can't be ended twice, and its end date can't be before its start date | Proposed |
| B8 | Model and customer name are required; year is a realistic car year | Proposed |
| B9 | Deleting a car also deletes its finished rental history | Proposed, see open decisions |

## Non-functional requirements

These come straight from the PDF's Technical Requirements and Deliverables.

| ID | Requirement | PDF wording |
| --- | --- | --- |
| N1 | Separate layers: data access, services (business logic), interface | Separation of layers (data access / services / API) |
| N2 | SOLID where applicable; clean, readable, documented code | Architecture and Code Quality |
| N3 | Data access through an ORM | Implement data access via an ORM |
| N4 | Python's built-in logging; log critical actions (add, update, error, end rental) | Logging |
| N5 | Logs go to both the console and a file | Support logging both to console and to a file |
| N6 | Metrics for active cars, ongoing rentals, average request/operation response time | Metrics (prometheus\_client or another library) |
| N7 | At least 4 unit tests | Include at least 4 unit tests |
| N8 | Runs as a standalone Python application | Environment Setup |
| N9 | Dependency management for installation | Environment Setup |
| N10 | docker-compose.yml for setup | Environment Setup |
| N11 | Public GitHub or GitLab repo, clear commits, dedicated feature branch | GIT |
| N12 | README: architecture graphic, how to run, how to use, architecture description, examples, screenshots | Deliverables |

## Open decisions

These choices are yours; each has my recommendation, and none is settled until you confirm it.

| # | Decision | Options | Recommendation |
| --- | --- | --- | --- |
| D1 | Interface | REST API | REST API (FastAPI), with interactive docs for reviewers |
| D2 | Database | PostgreSQL, MySQL, MongoDB, SQLite | PostgreSQL in Docker plus SQLite for standalone runs; the data is relational and rules span both tables |
| D3 | ORM | SQLAlchemy, SQLModel, Django ORM | SQLAlchemy 2.0 |
| D4 | Message queue (optional) | Skip, or RabbitMQ / Redis / Kafka | Include RabbitMQ with a small worker, since the PDF recommends it |
| D5 | Meaning of "active cars" | Cars not under maintenance, or cars currently rented | Not under maintenance, because rented cars are already counted by ongoing rentals |
| D6 | Deleting a car with past rentals | Delete history too, block the delete, or soft-delete | Block only while rented; delete finished history with it |
| D7 | Dates | Date only, or date and time | Date and time in UTC, since the PDF says only "date" |
| D8 | Hosting | GitHub or GitLab; who creates the repo | Your GitHub account; you create an empty public repo, or link GitHub so Claude Code can push |
| D9 | Where coding runs | Claude Code in the cloud, or on your device via Remote Control | My device via Remote Control |
| D10 | Existing prototype | Reuse parts, or start clean | Start clean from the agreed plan, and use the prototype only as a reference |

## Deliverables and acceptance checklist

The PDF asks for three deliverables: full source code, a README.md, and a link to the Git repository. The project is done when every box below is ticked.

- [ ] Architecture design, shown as a graphic in the README
- [ ] `cars` and `rentals` tables with exactly the PDF fields, accessed through an ORM
- [ ] Database choice explained in the README
- [ ] F1 to F6 work through the chosen interface
- [ ] Business rules agreed in this PRD are enforced
- [ ] Critical actions and errors are logged to both the console and a file
- [ ] Metrics exposed for active cars, ongoing rentals and average response time
- [ ] Separate data access, service and interface layers
- [ ] At least 4 unit tests, all passing
- [ ] Runs standalone with documented install steps and dependency management
- [ ] `docker-compose up` starts the full system
- [ ] Public repo, work on a feature branch, clear commit messages
- [ ] README covers: architecture graphic, how to run, how to use, architecture description, example usage, screenshots
- [ ] Message queue, if D4 says include it

## Build plan

We build in 10 steps in Claude Code on your machine. Each step ends with a commit on `feature/vehicle-management` and a checkpoint, and the next step starts only after you approve.

| Step | What Claude Code does | Checkpoint (you check) |
| --- | --- | --- |
| 0 | You: create the project folder and git repo, create the feature branch, save this PRD as `docs/PRD.md` | Folder open in VS Code, PRD in place |
| 1 | Architecture design: `docs/ARCHITECTURE.md` (layers, folders, diagram, DB choice, API endpoints) and `CLAUDE.md` working rules. No code | You approve the design |
| 2 | Project skeleton: package layout, `pyproject.toml`/requirements, settings, pytest set up | `pip install -e .` and `pytest` run |
| 3 | Data layer: ORM models for `cars` and `rentals`, DB session, repositories, tests | Tests pass; schema matches the PRD |
| 4 | Business logic: car and rental services enforcing B1 to B9, unit tests | Tests pass; rules match the PRD |
| 5 | REST API: FastAPI endpoints for F1 to F7, error mapping, API tests | Try every endpoint in Swagger at `/docs` |
| 6 | Logging (console + file) and Prometheus metrics | Log file written; `/metrics` shows active cars, ongoing rentals, response time |
| 7 | Message queue: RabbitMQ publisher and worker | Events appear in the worker log |
| 8 | Dockerfile and `docker-compose.yml` | `docker compose up` starts everything |
| 9 | README, screenshots, final check against the acceptance checklist | You push to the public repo and merge |
