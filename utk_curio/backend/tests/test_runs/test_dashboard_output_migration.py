"""The migration of the outputs a dashboard viewer's runs keep must agree with
the model that reads the table, as ``test_run_tables_migration.py`` holds the
run tables to theirs: the suite builds its schema with ``db.create_all()``, so
a column forgotten in the migration would fail only on a real deployment.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa

REVISION = "d2e3f4a5b6c7"
TABLE = "dashboard_step_output"
VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "versions"


def _module():
    path = next(VERSIONS.glob(f"{REVISION}_*.py"))
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
            getattr(_module(), func)()


def _migrated():
    engine = sa.create_engine("sqlite://")
    _run("upgrade", engine)
    return engine


def _model():
    from utk_curio.backend.app.runs.models import DashboardStepOutput

    return DashboardStepOutput.__table__


def test_it_follows_the_head_it_was_written_on():
    assert _module().down_revision == "c1d2e3f4a5b6"


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


def test_the_migration_creates_the_models_indexes():
    migrated = {ix["name"]: tuple(ix["column_names"]) for ix in sa.inspect(_migrated()).get_indexes(TABLE)}
    model = {ix.name: tuple(c.name for c in ix.columns) for ix in _model().indexes}
    assert migrated == model


def test_the_downgrade_drops_the_table():
    engine = _migrated()
    _run("downgrade", engine)
    assert TABLE not in sa.inspect(engine).get_table_names()
