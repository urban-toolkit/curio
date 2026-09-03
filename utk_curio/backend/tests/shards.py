"""One e2e worker, one backend+sandbox pair: the environment shard ``k`` runs in.

Single source of truth for how a shard maps onto ports and directories. It is
imported by ``tests/conftest.py`` before anything else reads the environment,
and driven from the shell (``scripts/test.sh``, CI) through::

    python -m utk_curio.backend.tests.shards 2          # export lines for shard 2
    python -m utk_curio.backend.tests.shards 2 --json

Why a shard is a whole backend+sandbox pair and not merely a pytest worker: the
suite truncates ``user`` / ``project`` / ``user_session`` between tests through
``POST /api/testing/reset-db``, so two workers on one backend delete each
other's logged-in users mid-test (measured: every stubbed session 401s within
seconds). Everything a pair writes therefore moves with it -- the sqlite test
DB, the DuckDB artifact store (single writer across processes), the per-user
stores under ``.curio/users/<id>/``, the dataset catalog it publishes to, and
the launcher log. ``CURIO_STATE_DIR`` relocates all of that at once; see
``backend/app/common/user_storage.py::curio_root``.

What deliberately does NOT move:

* ``CURIO_LAUNCH_CWD`` -- it is also the DATA root. ``GET /file/<path>`` serves
  ``docs/examples/data/*.pbf`` relative to it, and ``safe_paths.is_within``
  resolves symlinks before checking containment, so a per-shard copy or link
  farm 403s every autark PBF fetch (issue #248 again). It stays the repo root.
* the frontend -- one webpack build, one dev server. The bundle picks its
  backend at runtime from ``window.__CURIO_BACKEND_URL__``, which the
  ``browser`` fixture injects per context (``src/utils/backendUrl.ts``).
* ``<repo>/packages/`` -- the package catalog root is not overridable, but no
  e2e test writes it; the driver asserts that with ``git status`` afterwards.

Ports are the workspace's base pair plus ``k`` (times
``CURIO_E2E_SHARD_PORT_STRIDE``), so a checkout that pins its own triple in
``.curio-ports.sh`` gets shards that stay clear of its siblings the same way.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

_WORKER_RE = re.compile(r"^gw(\d+)$")
_APPLIED = "CURIO_E2E_SHARD_APPLIED"


def shard_index(environ=os.environ) -> int:
    """This process's shard: xdist's ``gwN`` first, then ``CURIO_E2E_SHARD``, else 0."""
    m = _WORKER_RE.match(environ.get("PYTEST_XDIST_WORKER", ""))
    if m:
        return int(m.group(1))
    return int(environ.get("CURIO_E2E_SHARD") or 0)


def shard_count(environ=os.environ) -> int:
    return int(environ.get("PYTEST_XDIST_WORKER_COUNT") or environ.get("CURIO_E2E_SHARDS") or 1)


def is_sharded(environ=os.environ) -> bool:
    return (
        "PYTEST_XDIST_WORKER" in environ
        or "CURIO_E2E_SHARD" in environ
        or shard_count(environ) > 1
    )


def shard_state_dir(k: int, environ=os.environ) -> Path:
    root = environ.get("CURIO_E2E_SHARD_STATE_ROOT") or (REPO_ROOT / ".curio" / "shards")
    # Keep ``.curio`` in the path: backend/server.py's reloader exclude and
    # .gitignore both match on it.
    return Path(root) / str(k)


def shard_env(k: int, environ=os.environ) -> dict[str, str]:
    """The environment for shard *k*, derived from the BASE values in *environ*.

    Call it on the driver's environment (or a worker's inherited copy of it),
    never on one this function already produced -- the ports would compound.
    ``apply_shard_env`` guards against that.
    """
    base_backend = int(environ.get("CURIO_E2E_BACKEND_PORT") or environ.get("BACKEND_PORT") or 5002)
    base_sandbox = int(environ.get("CURIO_E2E_SANDBOX_PORT") or environ.get("SANDBOX_PORT") or 2000)
    stride = int(environ.get("CURIO_E2E_SHARD_PORT_STRIDE") or 1)
    host = environ.get("CURIO_E2E_HOST") or "localhost"
    backend = base_backend + k * stride
    sandbox = base_sandbox + k * stride
    common = {
        "CURIO_E2E_USE_EXISTING": "1",
        "CURIO_TESTING": "1",
        "CURIO_LAUNCH_CWD": str(REPO_ROOT),
        "CURIO_E2E_HOST": host,
        "CURIO_E2E_BACKEND_PORT": str(backend),
        "BACKEND_PORT": str(backend),
        "CURIO_E2E_SANDBOX_PORT": str(sandbox),
        "SANDBOX_PORT": str(sandbox),
        # Second precedence tier of utils.sandbox_base_url(); the backend also
        # reads these to dial its own sandbox.
        "FLASK_SANDBOX_HOST": host,
        "FLASK_SANDBOX_PORT": str(sandbox),
        # The backend and ITS sandbox must agree; every shard may share one.
        "CURIO_SANDBOX_TOKEN": environ.get("CURIO_SANDBOX_TOKEN") or "curio-e2e-shards",
    }
    if k == 0:
        # Shard 0 IS the stack as configured -- the one ``curio.py start`` (or
        # CI's compose container) already runs on the base ports with the
        # default ``.curio/``. Relocating its state would point the worker at
        # directories that backend never writes. Only k >= 1 get their own.
        return common
    state = shard_state_dir(k, environ)
    test_dir = state / "test"
    db = test_dir / "urban_workflow_test.db"
    return {
        **common,
        "CURIO_STATE_DIR": str(state),
        "CURIO_SHARED_DATA": str(test_dir / "data"),
        "DATABASE_URL_TEST": f"sqlite:///{db}",
        "DATABASE_URL": f"sqlite:///{db}",
        "CURIO_CATALOG_ROOT": str(state / "datasets"),
        # N launchers from one checkout must not pip/npm install concurrently;
        # the driver warms the environment once beforehand.
        "CURIO_SKIP_DEP_INSTALL": "1",
        # N Flask processes must not rotate one utk_curio/logs/*.log file.
        "LOG_TO_STDOUT": "1",
    }


def apply_shard_env(environ=os.environ) -> dict[str, str] | None:
    """Put this process on its shard. No-op (returns None) in a serial run.

    Idempotent: a second call in the same process returns the same mapping
    without re-deriving ports from already-shifted values.
    """
    if not is_sharded(environ):
        return None
    k = shard_index(environ)
    if environ.get(_APPLIED) == str(k):
        return shard_env(k, _base_of(environ))
    env = shard_env(k, environ)
    for key in ("BACKEND_PORT", "SANDBOX_PORT"):
        environ.setdefault(
            f"CURIO_E2E_BASE_{key}",
            environ.get(f"CURIO_E2E_{key}") or environ.get(key) or "",
        )
    environ.update(env)
    environ[_APPLIED] = str(k)
    for key in ("CURIO_SHARED_DATA", "CURIO_CATALOG_ROOT"):
        if key in env:
            Path(env[key]).mkdir(parents=True, exist_ok=True)
    return env


def _base_of(environ) -> dict[str, str]:
    """Reconstruct the base ports a previous apply_shard_env shifted away from."""
    base = dict(environ)
    for key in ("BACKEND_PORT", "SANDBOX_PORT"):
        saved = environ.get(f"CURIO_E2E_BASE_{key}")
        if saved:
            base[f"CURIO_E2E_{key}"] = saved
            base[key] = saved
    return base


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    if len(args) != 1 or not args[0].isdigit():
        print("usage: python -m utk_curio.backend.tests.shards <k> [--json]", file=sys.stderr)
        return 2
    env = shard_env(int(args[0]))
    if as_json:
        print(json.dumps(env, indent=2))
    else:
        for key, value in env.items():
            print(f"export {key}={json.dumps(value)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
