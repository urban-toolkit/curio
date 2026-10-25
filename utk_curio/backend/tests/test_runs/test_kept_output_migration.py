"""The migrations of the outputs kept runs keep must agree with the model that
reads the table, as ``test_run_tables_migration.py`` holds the run tables to
theirs: the suite builds its schema with ``db.create_all()``, so a column
forgotten in a migration would fail only on a real deployment.

Two revisions build the table: ``d2e3f4a5b6c7`` created the one a dashboard
viewer's runs kept their outputs in, and ``e3f4a5b6c7d8`` turns it into the one
every kept run keeps them in, with ``made_by``, starting empty.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa

VIEWERS = "d2e3f4a5b6c7"
KEPT = "e3f4a5b6c7d8"
OLD_TABLE = "dashboard_step_output"
TABLE = "kept_step_output"
VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "versions"


def _module(revision: str):
    path = next(VERSIONS.glob(f"{revision}_*.py"))
    spec = importlib.util.spec_from_file_location(f"_rev_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _run(revision: str, func: str, engine) -> None:
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            getattr(_module(revision), func)()


def _migrated():
    engine = sa.create_engine("sqlite://")
    _run(VIEWERS, "upgrade", engine)
    _run(KEPT, "upgrade", engine)
    return engine


def _model():
    from utk_curio.backend.app.runs.models import KeptStepOutput

    return KeptStepOutput.__table__


def _columns(engine, table: str) -> dict:
    return {c["name"]: (str(c["type"]).upper(), bool(c["nullable"])) for c in sa.inspect(engine).get_columns(table)}


def test_each_follows_the_head_it_was_written_on():
    assert _module(VIEWERS).down_revision == "c1d2e3f4a5b6"
    assert _module(KEPT).down_revision == VIEWERS


def test_the_migrations_create_the_models_columns_types_and_nullability():
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


def test_the_migrations_create_the_models_indexes():
    migrated = {ix["name"]: tuple(ix["column_names"]) for ix in sa.inspect(_migrated()).get_indexes(TABLE)}
    model = {ix.name: tuple(c.name for c in ix.columns) for ix in _model().indexes}
    assert migrated == model


def test_the_viewers_table_goes_and_the_kept_one_starts_empty():
    engine = sa.create_engine("sqlite://")
    _run(VIEWERS, "upgrade", engine)
    with engine.begin() as conn:
        conn.execute(sa.text(
            "INSERT INTO dashboard_step_output (id, project_id, node_id, step_key, session_id, output, "
            "output_path, artifact_ids, size_bytes, created_at, used_at) VALUES ('e1', 'p1', 'n1', 'k', "
            "'dashboard-0123', '{}', 'a1', '[]', 0, '2026-10-24 00:00:00', '2026-10-24 00:00:00')"
        ))

    _run(KEPT, "upgrade", engine)

    tables = sa.inspect(engine).get_table_names()
    assert OLD_TABLE not in tables and TABLE in tables
    with engine.connect() as conn:
        assert conn.execute(sa.text(f"SELECT COUNT(*) FROM {TABLE}")).scalar() == 0


def test_the_downgrade_puts_the_viewers_table_back_as_it_was():
    engine = _migrated()
    _run(KEPT, "downgrade", engine)

    created = sa.create_engine("sqlite://")
    _run(VIEWERS, "upgrade", created)
    assert TABLE not in sa.inspect(engine).get_table_names()
    assert _columns(engine, OLD_TABLE) == _columns(created, OLD_TABLE)
    indexes = lambda e: {ix["name"]: tuple(ix["column_names"]) for ix in sa.inspect(e).get_indexes(OLD_TABLE)}
    assert indexes(engine) == indexes(created)


def test_the_first_downgrade_drops_the_viewers_table():
    engine = sa.create_engine("sqlite://")
    _run(VIEWERS, "upgrade", engine)
    _run(VIEWERS, "downgrade", engine)
    assert OLD_TABLE not in sa.inspect(engine).get_table_names()
