"""The migration of a dataflow's editors must agree with the model that reads
the table, as ``test_kept_output_migration.py`` holds the kept outputs to
theirs: the suite builds its schema with ``db.create_all()``, so a column
forgotten in a migration would fail only on a real deployment.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa

EDITORS = "f4a5b6c7d8e9"
TABLE = "project_editor"
VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "versions"


def _module(revision: str):
    found = sorted(VERSIONS.glob(f"{revision}_*.py"))
    assert len(found) == 1, f"one migration should be revision {revision}, found {found}"
    path = found[0]
    spec = importlib.util.spec_from_file_location(f"_rev_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _run(func: str, engine) -> None:
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            getattr(_module(EDITORS), func)()


def _migrated():
    engine = sa.create_engine("sqlite://")
    _run("upgrade", engine)
    return engine


def _model():
    from utk_curio.backend.app.projects.models import ProjectEditor

    return ProjectEditor.__table__


def test_it_follows_the_head_it_was_written_on():
    """The kept outputs' revision was the head; nothing else revises it."""
    assert _module(EDITORS).down_revision == "e3f4a5b6c7d8"
    parents = [
        line for path in VERSIONS.glob("*.py")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith("down_revision") and "e3f4a5b6c7d8" in line
    ]
    assert len(parents) == 1, parents


def test_the_migration_creates_the_models_columns_types_and_nullability():
    engine = _migrated()
    migrated = {c["name"]: c for c in sa.inspect(engine).get_columns(TABLE)}
    assert set(migrated) == {c.name for c in _model().columns}
    mismatched = []
    for name, col in _model().columns.items():
        want = col.type.compile(engine.dialect).upper()
        got = str(migrated[name]["type"]).upper()
        if want != got:
            mismatched.append(f"{name}: model={want} migration={got}")
        if not col.primary_key and bool(col.nullable) != bool(migrated[name]["nullable"]):
            mismatched.append(f"{name}: nullable differs")
    assert not mismatched, "; ".join(mismatched)


def test_the_migration_creates_the_models_indexes_and_unique_pair():
    inspector = sa.inspect(_migrated())
    migrated = {ix["name"]: tuple(ix["column_names"]) for ix in inspector.get_indexes(TABLE)}
    model = {ix.name: tuple(c.name for c in ix.columns) for ix in _model().indexes}
    assert migrated == model
    unique = {u["name"]: tuple(u["column_names"]) for u in inspector.get_unique_constraints(TABLE)}
    assert unique == {"uq_project_editor_project_user": ("project_id", "user_id")}


def test_the_downgrade_drops_the_table():
    engine = _migrated()
    _run("downgrade", engine)
    assert TABLE not in sa.inspect(engine).get_table_names()
