"""The published dashboard migration must agree with its model.

The suite builds its schema with ``db.create_all()``, so this runs the creating
revision against a scratch SQLite database and compares the table with
``PublishedDashboard``, as ``test_run_tables_migration.py`` does for the runs.
"""
from __future__ import annotations

import sqlalchemy as sa

from utk_curio.backend.tests.test_runs.test_run_tables_migration import VERSIONS, _load, _run

TABLE = "published_dashboard"


def _migrated():
    engine = sa.create_engine("sqlite://")
    _run(_load(VERSIONS / "7c1e4b9a2d53_create_published_dashboard.py"), engine)
    return engine


def _model():
    from utk_curio.backend.app.published.models import PublishedDashboard

    return PublishedDashboard.__table__


def test_the_migration_creates_the_models_columns_types_and_nullability():
    engine = _migrated()
    migrated = {c["name"]: c for c in sa.inspect(engine).get_columns(TABLE)}
    model = _model()
    assert set(migrated) == {c.name for c in model.columns}
    mismatched = []
    for name, col in model.columns.items():
        if col.type.compile(engine.dialect).upper() != str(migrated[name]["type"]).upper():
            mismatched.append(f"{name}: type")
        if not col.primary_key and bool(col.nullable) != bool(migrated[name]["nullable"]):
            mismatched.append(f"{name}: nullable")
    assert not mismatched, mismatched


def test_the_link_token_is_indexed_and_unique():
    inspector = sa.inspect(_migrated())
    indexes = {ix["name"]: ix for ix in inspector.get_indexes(TABLE)}
    token = indexes["ix_published_dashboard_token"]
    assert token["column_names"] == ["token"] and token["unique"]
    model = {ix.name: ix for ix in _model().indexes}
    assert model["ix_published_dashboard_token"].unique


def test_downgrade_drops_the_table():
    engine = _migrated()
    _run(_load(VERSIONS / "7c1e4b9a2d53_create_published_dashboard.py"), engine, "downgrade")
    assert TABLE not in sa.inspect(engine).get_table_names()
