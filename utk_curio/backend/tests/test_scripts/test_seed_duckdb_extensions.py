"""Seeding DuckDB's spatial extension so neither the sandbox nor the backend downloads it (#318).

autk-db's ``init()`` runs ``INSTALL spatial; LOAD spatial;``. In Node,
duckdb-wasm installs into ``~/.duckdb/extensions/<repository>/<version>/<platform>/``
and only downloads what is not already there, so putting Curio's vendored copy
in that directory is the whole fix for the server-side path: no 23 MB fetch on a
cold container, and an offline install still runs an Autark data node.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from utk_curio.cli import dependencies

REPO = Path(dependencies.__file__).resolve().parents[2]
VENDORED = REPO / "vendor" / "duckdb-extensions"

# Asks the installed duckdb-wasm, through its Node build, which DuckDB it runs.
# That version names the extension folder duckdb-wasm requests, in Node and in
# the browser alike, so it is the folder Curio must ship.
_DUCKDB_VERSION_JS = r"""
const path = require('path');
const duckdb = require('@duckdb/duckdb-wasm/dist/duckdb-node-blocking.cjs');
const dist = path.dirname(require.resolve('@duckdb/duckdb-wasm/dist/duckdb-node-blocking.cjs'));
(async () => {
  const bundles = {
    mvp: { mainModule: path.join(dist, 'duckdb-mvp.wasm'), mainWorker: path.join(dist, 'duckdb-node-mvp.worker.cjs') },
    eh: { mainModule: path.join(dist, 'duckdb-eh.wasm'), mainWorker: path.join(dist, 'duckdb-node-eh.worker.cjs') },
  };
  const db = await duckdb.createDuckDB(bundles, new duckdb.VoidLogger(), duckdb.NODE_RUNTIME);
  await db.instantiate(() => {});
  const conn = db.connect();
  const table = conn.query('SELECT library_version FROM pragma_version()');
  process.stdout.write(String(table.getChildAt(0).get(0)));
  process.exit(0);
})().catch((err) => { console.error(err); process.exit(1); });
"""


def _lockfile_duckdb_wasm(lockfile: Path) -> str:
    packages = json.loads(lockfile.read_text())["packages"]
    return packages["node_modules/@duckdb/duckdb-wasm"]["version"]


def test_the_vendored_extensions_are_the_version_duckdb_wasm_runs():
    """A duckdb-wasm bump moves the folder it requests. With the old folder
    vendored, every new database fetched both extensions from the CDN again,
    and an offline install lost its Autark nodes, with nothing failing."""
    result = subprocess.run(
        ["node", "-e", _DUCKDB_VERSION_JS], cwd=REPO, capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, result.stderr
    running = result.stdout.strip()
    assert re.fullmatch(r"v\d+\.\d+\.\d+", running), f"unexpected version {running!r}"

    shipped = {p.parent.parent.name for p in VENDORED.rglob("*.duckdb_extension.wasm")}
    assert running in shipped, (
        f"duckdb-wasm runs DuckDB {running}, but vendor/duckdb-extensions ships {sorted(shipped)}"
    )


def test_the_browser_and_the_sandbox_pin_the_same_duckdb_wasm():
    """The browser's copy (frontend lockfile) and the sandbox's (repository
    lockfile) must request the same folder, or one of them goes to the CDN."""
    frontend = REPO / "utk_curio" / "frontend" / "urban-workflows" / "package-lock.json"
    assert _lockfile_duckdb_wasm(frontend) == _lockfile_duckdb_wasm(REPO / "package-lock.json")


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

    dependencies.seed_duckdb_extensions()

    target = tmp_path / ".duckdb" / "extensions" / "extensions.duckdb.org"
    seeded = {p.relative_to(target) for p in target.rglob("*.duckdb_extension.wasm")}
    shipped = {p.relative_to(VENDORED) for p in VENDORED.rglob("*.duckdb_extension.wasm")}
    # Same relative layout duckdb resolves: <version>/<platform>/<file>.
    assert seeded == shipped, f"seeded {seeded}, ships {shipped}"


@pytest.mark.parametrize("server", ["all", "backend", "sandbox"])
def test_every_start_that_runs_autk_db_seeds_it(server, tmp_path, monkeypatch):
    """autk-db runs in Node in the sandbox (Autark's data path) and in the
    backend (the Discovery Catalog's OpenStreetMap downloads,
    ``discovery/providers/autark_osm.mjs``), so a start of either seeds the
    HOME its servers run under. ``start backend`` did not, and a backend
    started alone fetched the extension from extensions.duckdb.org on its first
    OpenStreetMap download."""
    from utk_curio.backend.tests.test_scripts.test_launcher_start_order import _start

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    _, _, code = _start(
        monkeypatch, must_build=False, server=server, seed=dependencies.seed_duckdb_extensions,
    )

    target = tmp_path / ".duckdb" / "extensions" / "extensions.duckdb.org"
    seeded = sorted(p.relative_to(target).as_posix() for p in target.rglob("*.duckdb_extension.wasm"))
    shipped = sorted(p.relative_to(VENDORED).as_posix() for p in VENDORED.rglob("*.duckdb_extension.wasm"))
    assert code == 0
    assert shipped, "Curio ships no DuckDB extension to seed"
    assert seeded == shipped, f"curio.py start {server} seeded {seeded}, Curio ships {shipped}"


def test_it_does_not_recopy_what_is_already_there(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    dependencies.seed_duckdb_extensions()
    seeded = next((tmp_path / ".duckdb").rglob("spatial.duckdb_extension.wasm"))
    stamp = seeded.stat().st_mtime_ns

    dependencies.seed_duckdb_extensions()

    assert seeded.stat().st_mtime_ns == stamp


def test_a_read_only_home_does_not_stop_the_launch(tmp_path, monkeypatch):
    # Worst case is the download Curio has always done, not a failed start.
    blocked = tmp_path / "nope"
    blocked.write_text("not a directory")
    monkeypatch.setattr(Path, "home", lambda: blocked)

    dependencies.seed_duckdb_extensions()  # must not raise
