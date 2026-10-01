"""Layer boundaries (N1, docs/ARCHITECTURE.md section 2), checked from the source imports."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "drivenow"

# The API's composition root is the only API code allowed to know the data layer.
COMPOSITION_ROOT = {"api/dependencies.py", "api/app.py"}


def imports_of(path: Path) -> set[str]:
    """Absolute module names imported by a source file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def modules(layer: str) -> list[Path]:
    return sorted((PACKAGE / layer).rglob("*.py"))


def offending(path: Path, forbidden: tuple[str, ...]) -> list[str]:
    return sorted(
        name for name in imports_of(path) if any(name == f or name.startswith(f + ".") for f in forbidden)
    )


def rel(path: Path) -> str:
    return path.relative_to(PACKAGE).as_posix()


@pytest.mark.parametrize("path", modules("services"), ids=rel)
def test_services_do_not_import_web_or_sql_frameworks(path):
    assert offending(path, ("fastapi", "starlette", "sqlalchemy")) == []


@pytest.mark.parametrize(
    "path", [p for p in modules("api") if rel(p) not in COMPOSITION_ROOT], ids=rel
)
def test_api_does_not_touch_the_data_layer(path):
    assert offending(path, ("drivenow.db", "drivenow.repositories", "sqlalchemy")) == []


@pytest.mark.parametrize("path", modules("domain"), ids=rel)
def test_domain_depends_on_no_other_layer(path):
    forbidden = (
        "drivenow.api", "drivenow.services", "drivenow.repositories", "drivenow.messaging",
        "drivenow.observability", "fastapi", "sqlalchemy", "pika", "prometheus_client",
    )
    # records.py names the ORM models only under TYPE_CHECKING, for from_model() hints.
    allowed = {"drivenow.db.models"} if rel(path) == "domain/records.py" else set()
    assert [m for m in offending(path, forbidden + ("drivenow.db",)) if m not in allowed] == []


@pytest.mark.parametrize("path", modules("repositories"), ids=rel)
def test_data_layer_does_not_know_services_or_api(path):
    assert offending(path, ("drivenow.services", "drivenow.api", "fastapi")) == []
