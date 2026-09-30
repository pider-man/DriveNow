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
  - `services` never import FastAPI, and depend only on the Protocols in `repositories/interfaces.py`, `messaging/publisher.py` and `services/clock.py`.
  - Business rules B1–B9 live in the services. DB constraints are only a safety net.
- Type hints everywhere, docstrings on public classes and functions, and `logging.getLogger(__name__)` (never `print`).
- Datetimes are timezone-aware UTC.
- The `cars` and `rentals` tables contain exactly the PRD fields and nothing more.

## Commands

The commands will be filled in as the steps add them (install, run, test, docker compose).
