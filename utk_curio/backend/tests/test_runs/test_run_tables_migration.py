"""The run-table migrations must agree with the models that read the tables.

The suite builds its schema with ``db.create_all()``, so no other test runs the
alembic revisions. A column added to ``DataflowRun`` or ``DataflowRunStep`` but
forgotten in a migration would pass CI and fail only on a real deployment, at
the first query after ``flask db upgrade``.

This runs the migration chain from the creating revision to the head against a
scratch SQLite database and compares each table with its model, following
``test_datasets/test_dataset_index_migration.py``.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest
import sqlalchemy as sa

REVISION = "f7a8b9c0d1e2"
TABLES = ("dataflow_run", "dataflow_run_step")
VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "versions"


def _models():
    from utk_curio.backend.app.runs.models import DataflowRun, DataflowRunStep

    return {"dataflow_run": DataflowRun, "dataflow_run_step": DataflowRunStep}


def _load(path):
    spec = importlib.util.spec_from_file_location(f"_rev_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _chain_from(revision: str) -> list:
    """Every revision from *revision* to the head that touches these tables."""
    modules = {}
    children: dict[str, str] = {}
    for path in VERSIONS.glob("*.py"):
        text = path.read_text()
        rev = re.search(r'^revision\s*=\s*["\']([^"\']+)', text, re.M)
        down = re.search(r'^down_revision\s*=\s*["\']?([^"\'\s]+)', text, re.M)
        if not rev:
            continue
        modules[rev.group(1)] = path
        if down and down.group(1) != "None":
            children[down.group(1)] = rev.group(1)

    assert revision in modules, f"no {revision} revision under {VERSIONS}"
    ordered = [modules[revision]]
    current = revision
    while current in children:
        current = children[current]
        ordered.append(modules[current])
    return [p for p in ordered if any(table in p.read_text() for table in TABLES)]


def _run(module, engine, func="upgrade") -> None:
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            getattr(module, func)()


def _migrated_engine():
    engine = sa.create_engine("sqlite://")
    for path in _chain_from(REVISION):
        _run(_load(path), engine)
    return engine


def test_the_revision_follows_the_previous_head():
    """Exactly one head: a second branch would make ``flask db upgrade`` refuse."""
    revisions, parents = set(), set()
    for path in VERSIONS.glob("*.py"):
        text = path.read_text()
        rev = re.search(r'^revision\s*=\s*["\']([^"\']+)', text, re.M)
        down = re.search(r'^down_revision\s*=\s*["\']?([^"\'\s]+)', text, re.M)
        if rev:
            revisions.add(rev.group(1))
        if down and down.group(1) != "None":
            parents.add(down.group(1))
    heads = revisions - parents
    assert len(heads) == 1, f"more than one migration head: {sorted(heads)}"


@pytest.mark.parametrize("table", TABLES)
def test_the_migration_creates_the_columns_the_model_has(table):
    inspector = sa.inspect(_migrated_engine())
    assert table in inspector.get_table_names()
    migrated = {c["name"] for c in inspector.get_columns(table)}
    model = {c.name for c in _models()[table].__table__.columns}
    assert migrated == model, (
        f"only in migration: {sorted(migrated - model)}, "
        f"only in model: {sorted(model - migrated)}"
    )


@pytest.mark.parametrize("table", TABLES)
def test_the_migration_and_model_agree_on_nullability_and_types(table):
    engine = _migrated_engine()
    migrated = {c["name"]: c for c in sa.inspect(engine).get_columns(table)}
    mismatched = []
    for name, col in _models()[table].__table__.columns.items():
        want = col.type.compile(engine.dialect).upper()
        got = str(migrated[name]["type"]).upper()
        if want != got:
            mismatched.append(f"{name}: model={want} migration={got}")
        # The primary key is NOT NULL either way; SQLite reports it inconsistently.
        if not col.primary_key and bool(col.nullable) != bool(migrated[name]["nullable"]):
            mismatched.append(f"{name}: nullable differs")
    assert not mismatched, "; ".join(mismatched)


@pytest.mark.parametrize("table", TABLES)
def test_the_migration_creates_the_models_indexes_and_uniqueness(table):
    inspector = sa.inspect(_migrated_engine())
    model = _models()[table].__table__

    migrated_indexes = {
        ix["name"]: tuple(ix["column_names"]) for ix in inspector.get_indexes(table)
    }
    model_indexes = {
        ix.name: tuple(c.name for c in ix.columns) for ix in model.indexes
    }
    for name, columns in model_indexes.items():
        assert migrated_indexes.get(name) == columns, f"index {name} differs"

    migrated_uniques = {
        tuple(uc["column_names"]) for uc in inspector.get_unique_constraints(table)
    }
    model_uniques = {
        tuple(c.name for c in con.columns)
        for con in model.constraints
        if isinstance(con, sa.UniqueConstraint)
    }
    assert model_uniques == migrated_uniques


def test_the_downgrade_removes_both_tables():
    engine = _migrated_engine()
    _run(_load(next(VERSIONS.glob(f"{REVISION}_*.py"))), engine, "downgrade")
    remaining = set(sa.inspect(engine).get_table_names())
    assert not remaining & set(TABLES)
