# CLAUDE.md: working rules for this repo

## Source of truth

- `docs/PRD.md` is the approved spec, and every requirement in it must be met exactly.
- `docs/ARCHITECTURE.md` is the approved design (layers, folders, schema, endpoints, rule enforcement).
- If the two disagree, or if the code would need to differ from either, stop and ask. Never deviate silently or guess.
- If a decision isn't covered by either document, raise it as a question instead of making it.

## Workflow

- Follow the PRD's build plan **one step at a time**.
- At the end of each step, stop and give a short summary for review: what changed, test results, and any open questions.
- **Never start the next step without explicit approval.**
- **Never push** (or open PRs, or change remotes) without explicit approval.

## Git

- All work goes on the branch `feature/vehicle-management`.
- Each build-plan step gets **one clear, descriptive commit** (for example `Add data layer: ORM models, session, repositories (step 3)`).
- Don't rewrite history (no amend, rebase or force) on commits that have been reviewed.

## Tests

- Every step that adds or changes code includes tests for it.
- Run `pytest` before committing. **All tests must pass**, and a failing step isn't committed.
- Step 1 (documentation only) has no tests.

## Code conventions

- src layout: `src/drivenow/...`, tests in `tests/{unit,integration,api}`.
- Respect the layer boundaries in `docs/ARCHITECTURE.md`:
  - `api` never imports ORM models or sessions, and contains no business rules.
  - `services` never import FastAPI or SQLAlchemy. They use the ORM models in `db/models.py` as their entities, and reach everything else through Protocols: `repositories/interfaces.py` keeps them away from sessions, queries and transactions, and `messaging/publisher.py`, `services/clock.py` and `observability/tracking.py` cover publishing, time and metrics.
  - Business rules B1–B10 live in the services. DB constraints are only a safety net.
- Type hints everywhere, docstrings on public classes and functions, and `logging.getLogger(__name__)` (never `print`).
- Datetimes are timezone-aware UTC.
- The `cars` and `rentals` tables contain exactly the PRD fields and nothing more.

## Commands

Run from the repo root. The virtual environment `.venv/` is gitignored.

```bash
python -m venv .venv                          # Python 3.12+
.venv/Scripts/python -m pip install -e ".[dev]"   # Windows; use .venv/bin/python on Linux/macOS
.venv/Scripts/python -m pytest                # all tests
.venv/Scripts/python -m drivenow              # API on http://127.0.0.1:8000, Swagger at /docs
.venv/Scripts/python -m drivenow.worker       # RabbitMQ audit worker (needs RABBITMQ_URL)
```

Settings come from environment variables or `.env` (see `.env.example` and `src/drivenow/config.py`).

Docker (PostgreSQL, RabbitMQ, API, worker, Prometheus):

```bash
docker compose up --build -d                 # API :8000, RabbitMQ UI :15672, Prometheus :9090
docker compose ps                            # all services healthy
docker compose logs worker                   # AUDIT lines for each event
# The full test suite on the compose PostgreSQL (database drivenow_test):
TEST_DATABASE_URL=postgresql+psycopg://drivenow:drivenow@localhost:5432/drivenow_test .venv/Scripts/python -m pytest
```
