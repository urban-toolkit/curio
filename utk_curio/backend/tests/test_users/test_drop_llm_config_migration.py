"""The account row no longer holds an LLM configuration.

``c9d0e1f2a3b4`` drops the four ``llm_*`` columns ``c3d4e5f6a7b8`` added: an
account's LLM configurations live in an owner-only file now
(``agents/llm_configs.py``). The suite builds its schema with
``db.create_all()``, so a missing revision would pass every other test while a
real database kept the columns; this runs the revision against a scratch
SQLite database, following ``test_projects/test_drop_archived_at_migration.py``.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa

REVISION = "c9d0e1f2a3b4"
LLM_COLUMNS = {"llm_api_type", "llm_base_url", "llm_api_key", "llm_model"}

# The user table as the migration finds it, written out because the model no
# longer has these columns.
_PRE_SCHEMA = """
    CREATE TABLE "user" (
        id INTEGER NOT NULL PRIMARY KEY,
        username VARCHAR(80) NOT NULL,
        is_guest BOOLEAN NOT NULL DEFAULT 0,
        llm_api_type VARCHAR(50),
        llm_base_url VARCHAR(500),
        llm_api_key VARCHAR(255),
        llm_model VARCHAR(100),
        huggingface_token VARCHAR(255)
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
    assert module.down_revision == "b8c9d0e1f2a3"


def test_upgrade_drops_the_columns_and_keeps_the_account():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text(_PRE_SCHEMA))
        conn.execute(sa.text(
            "INSERT INTO \"user\" (id, username, is_guest, llm_model, llm_api_key, huggingface_token) "
            "VALUES (1, 'alice', 0, 'gpt-4o', 'sk-old', 'hf-token')"
        ))
    _run(_load_revision(), engine)
    assert not (_columns(engine) & LLM_COLUMNS)
    with engine.connect() as conn:
        row = conn.execute(sa.text("SELECT username, huggingface_token FROM \"user\"")).one()
    assert tuple(row) == ("alice", "hf-token")


def test_downgrade_restores_the_columns_empty():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text(_PRE_SCHEMA))
    module = _load_revision()
    _run(module, engine)
    _run(module, engine, "downgrade")
    assert LLM_COLUMNS <= _columns(engine)


def test_the_model_no_longer_declares_them():
    from utk_curio.backend.app.users.models import User

    assert not ({c.name for c in User.__table__.columns} & LLM_COLUMNS)
