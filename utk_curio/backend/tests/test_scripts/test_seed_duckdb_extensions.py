"""Seeding DuckDB's spatial extension so the sandbox never downloads it (#318).

autk-db's ``init()`` runs ``INSTALL spatial; LOAD spatial;``. In Node,
duckdb-wasm installs into ``~/.duckdb/extensions/<repository>/<version>/<platform>/``
and only downloads what is not already there, so putting Curio's vendored copy
in that directory is the whole fix for the server-side path: no 23 MB fetch on a
cold container, and an offline install still runs an Autark data node.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from utk_curio import main as curio_main

VENDORED = Path(curio_main.__file__).resolve().parent.parent / "vendor" / "duckdb-extensions"


def test_curio_actually_ships_the_extensions():
    """The rest of this file is theatre if the files are not in the repo.

    Both of them: DuckDB autoloads ``json`` as well as ``spatial`` for the
    grammar's ``json_object`` SQL, and a run with only ``spatial`` local still
    reaches the CDN (and fails without it, deep inside the wasm as
    "table index is out of bounds").
    """
    names = {p.name for p in VENDORED.rglob("*.duckdb_extension.wasm")}
    assert {"spatial.duckdb_extension.wasm", "json.duckdb_extension.wasm"} <= names
    for found in VENDORED.rglob("*.duckdb_extension.wasm"):
        # A real extension, not a git-lfs pointer (~130 bytes).
        assert found.stat().st_size > 100_000, found


def test_it_lands_where_duckdb_looks(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    curio_main.seed_duckdb_extensions()

    target = tmp_path / ".duckdb" / "extensions" / "extensions.duckdb.org"
    seeded = {p.relative_to(target) for p in target.rglob("*.duckdb_extension.wasm")}
    shipped = {p.relative_to(VENDORED) for p in VENDORED.rglob("*.duckdb_extension.wasm")}
    # Same relative layout duckdb resolves: <version>/<platform>/<file>.
    assert seeded == shipped, f"seeded {seeded}, ships {shipped}"


def test_it_does_not_recopy_what_is_already_there(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    curio_main.seed_duckdb_extensions()
    seeded = next((tmp_path / ".duckdb").rglob("spatial.duckdb_extension.wasm"))
    stamp = seeded.stat().st_mtime_ns

    curio_main.seed_duckdb_extensions()

    assert seeded.stat().st_mtime_ns == stamp


def test_a_read_only_home_does_not_stop_the_launch(tmp_path, monkeypatch):
    # Worst case is the download Curio has always done, not a failed start.
    blocked = tmp_path / "nope"
    blocked.write_text("not a directory")
    monkeypatch.setattr(Path, "home", lambda: blocked)

    curio_main.seed_duckdb_extensions()  # must not raise
