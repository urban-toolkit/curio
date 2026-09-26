"""The dataset-index migrations must agree with the model that reads the table.

The test suite builds its schema with ``db.create_all()`` (see ``conftest.py``),
so the alembic revisions are never executed by any other test. A column added
to ``DatasetIndexEntry`` but forgotten in a migration therefore passes CI and
fails only on a real deployment, at the first query after ``flask db upgrade``.

This runs the migration CHAIN against a scratch SQLite database and compares
the resulting table with the model's own metadata. The chain rather than the
one creating revision: a column may perfectly well be added later, and a test
that only ran ``d4e5f6a7b8c9`` would report every such column as missing from a
migration that was never supposed to have it.
"""
from __future__ import annotations

import sqlalchemy as sa

from utk_curio.backend.app.datasets.models import DatasetIndexEntry

REVISION = "d4e5f6a7b8c9"
TABLE = "dataset_index_entry"


def _load(path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(f"_rev_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _chain_from(revision: str) -> list:
    """Every revision from *revision* to the head, in order.

    Walked from ``down_revision`` links rather than listed by hand, so a
    migration added later is picked up without anyone remembering to come back
    here.
    """
    import re
    from pathlib import Path

    versions = Path(__file__).resolve().parents[2] / "migrations" / "versions"
    modules = {}
    children: dict[str, str] = {}
    for path in versions.glob("*.py"):
        text = path.read_text()
        rev = re.search(r'^revision\s*=\s*["\']([^"\']+)', text, re.M)
        down = re.search(r'^down_revision\s*=\s*["\']?([^"\'\s]+)', text, re.M)
        if not rev:
            continue
        modules[rev.group(1)] = path
        if down and down.group(1) != "None":
            children[down.group(1)] = rev.group(1)

    assert revision in modules, f"no {revision} revision under {versions}"
    ordered = [modules[revision]]
    current = revision
    while current in children:
        current = children[current]
        ordered.append(modules[current])
    # Only the ones that touch THIS table. The scratch database holds nothing
    # else, so a revision altering `user` would fail here for a reason that has
    # nothing to do with what is being checked.
    return [p for p in ordered if TABLE in p.read_text()]


def _run_upgrade(engine) -> None:
    """Execute every revision from the table's creation to the head."""
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    for path in _chain_from(REVISION):
        module = _load(path)
        with engine.begin() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                module.upgrade()


def _migrated_engine():
    engine = sa.create_engine("sqlite://")
    _run_upgrade(engine)
    return engine


def test_migration_creates_the_table_the_model_expects():
    engine = _migrated_engine()
    inspector = sa.inspect(engine)
    assert TABLE in inspector.get_table_names()

    migrated = {c["name"]: c for c in inspector.get_columns(TABLE)}
    model = {c.name: c for c in DatasetIndexEntry.__table__.columns}

    assert set(migrated) == set(model), (
        "migration and model disagree on columns; "
        f"only in migration: {sorted(set(migrated) - set(model))}, "
        f"only in model: {sorted(set(model) - set(migrated))}"
    )


def test_migration_and_model_agree_on_nullability():
    engine = _migrated_engine()
    migrated = {c["name"]: c for c in sa.inspect(engine).get_columns(TABLE)}

    mismatched = [
        name
        for name, col in DatasetIndexEntry.__table__.columns.items()
        # The primary key is NOT NULL either way; SQLite reports it inconsistently.
        if not col.primary_key and bool(col.nullable) != bool(migrated[name]["nullable"])
    ]
    assert not mismatched, f"nullability differs for: {mismatched}"


def test_migration_and_model_agree_on_column_types():
    engine = _migrated_engine()
    migrated = {c["name"]: c for c in sa.inspect(engine).get_columns(TABLE)}

    mismatched = []
    for name, col in DatasetIndexEntry.__table__.columns.items():
        want = col.type.compile(engine.dialect).upper()
        got = str(migrated[name]["type"]).upper()
        if want != got:
            mismatched.append(f"{name}: model={want} migration={got}")
    assert not mismatched, "; ".join(mismatched)


def test_migration_creates_the_uniqueness_the_index_relies_on():
    # upsert_from_dir keys on (user_key, dir_name) and callers look rows up by
    # (user_key, dataset_id); without these constraints a duplicated row would
    # make either lookup non-deterministic.
    engine = _migrated_engine()
    inspector = sa.inspect(engine)
    got = {
        tuple(uc["column_names"])
        for uc in inspector.get_unique_constraints(TABLE)
    }
    assert ("user_key", "dataset_id") in got
    assert ("user_key", "dir_name") in got

    model_uniques = {
        tuple(c.name for c in con.columns)
        for con in DatasetIndexEntry.__table__.constraints
        if isinstance(con, sa.UniqueConstraint)
    }
    assert model_uniques == got


def test_downgrade_removes_the_table():
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    engine = _migrated_engine()
    versions = Path(__file__).resolve().parents[2] / "migrations" / "versions"
    spec = importlib.util.spec_from_file_location(
        f"_rev_{REVISION}_down", next(versions.glob(f"{REVISION}_*.py"))
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            module.downgrade()

    assert TABLE not in sa.inspect(engine).get_table_names()
