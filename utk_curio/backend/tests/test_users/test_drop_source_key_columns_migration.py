"""The account row holds no Data source key.

``c1d2e3f4a5b6`` drops the four key columns: an account's Data source keys
live in its owner-only file (``users/source_keys.py``), keyed by the secret id
a source manifest declares. The suite builds its schema with
``db.create_all()``, so a missing revision would pass every other test while a
real database kept the columns; this runs the revision against a scratch
SQLite database, following ``test_drop_llm_config_migration.py``.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa

REVISION = "c1d2e3f4a5b6"
KEY_COLUMNS = {"huggingface_token", "socrata_app_token", "google_maps_api_key", "mapillary_access_token"}

# The user table as the migration finds it, written out because the model does
# not have these columns.
_PRE_SCHEMA = """
    CREATE TABLE "user" (
        id INTEGER NOT NULL PRIMARY KEY,
        username VARCHAR(64) NOT NULL,
        name VARCHAR(100) NOT NULL,
        is_guest BOOLEAN NOT NULL DEFAULT 0,
        huggingface_token VARCHAR(255),
        socrata_app_token VARCHAR(255),
        google_maps_api_key VARCHAR(255),
        mapillary_access_token VARCHAR(255)
    )
"""


def _load_revision():
    versions = Path(__file__).resolve().parents[2] / "migrations" / "versions"
    matches = list(versions.glob(f"{REVISION}_*.py"))
    assert len(matches) == 1, f"expected one {REVISION} revision, found {matches}"
    spec = importlib.util.spec_from_file_location(f"_rev_{REVISION}", matches[0])
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _run(module, engine, func="upgrade") -> None:
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            getattr(module, func)()


def _columns(engine) -> set[str]:
    return {c["name"] for c in sa.inspect(engine).get_columns("user")}


def test_the_revision_follows_the_head_it_was_written_against():
    module = _load_revision()
    assert module.down_revision == "b0c1d2e3f4a5"


def test_upgrade_drops_the_columns_and_keeps_the_account():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text(_PRE_SCHEMA))
        conn.execute(sa.text(
            "INSERT INTO \"user\" (id, username, name, is_guest, huggingface_token, socrata_app_token, "
            "google_maps_api_key, mapillary_access_token) "
            "VALUES (1, 'alice', 'Alice', 0, 'hf-old', 'socrata-old', 'AIza-old', 'MLY|old')"
        ))
    _run(_load_revision(), engine)
    assert not (_columns(engine) & KEY_COLUMNS)
    with engine.connect() as conn:
        row = conn.execute(sa.text("SELECT id, username, name, is_guest FROM \"user\"")).one()
    assert tuple(row) == (1, "alice", "Alice", 0)


def test_downgrade_restores_the_columns_empty():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text(_PRE_SCHEMA))
        conn.execute(sa.text(
            "INSERT INTO \"user\" (id, username, name, is_guest, huggingface_token) "
            "VALUES (1, 'alice', 'Alice', 0, 'hf-old')"
        ))
    module = _load_revision()
    _run(module, engine)
    _run(module, engine, "downgrade")
    assert KEY_COLUMNS <= _columns(engine)
    with engine.connect() as conn:
        row = conn.execute(sa.text(
            "SELECT username, huggingface_token, socrata_app_token, google_maps_api_key, "
            "mapillary_access_token FROM \"user\""
        )).one()
    assert tuple(row) == ("alice", None, None, None, None)


def test_the_model_does_not_declare_them():
    from utk_curio.backend.app.users.models import User

    assert not ({c.name for c in User.__table__.columns} & KEY_COLUMNS)
