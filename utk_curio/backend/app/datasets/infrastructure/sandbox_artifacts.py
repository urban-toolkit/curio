"""Read artifact rows from the sandbox instead of the DuckDB file.

DuckDB allows one cross-process writer. The backend used to open
``curio_data.duckdb`` read-only for the two lookups below, which only worked
while the sandbox closed its write handle between executions -- and when the
two collided anyway, the read returned nothing and the caller carried on as
if the artifact did not exist (a silently skipped auto-install).

Asking the process that owns the file removes both problems: the sandbox
keeps one connection for its lifetime, and a collision is no longer possible
because there is nothing to collide with.
"""

from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger(__name__)

SANDBOX_TOKEN_HEADER = "X-Curio-Sandbox-Token"
# Short: this is a single indexed row lookup on a connection that is already
# open. A slow answer means the sandbox is saturated, and the callers all
# treat "no answer" as "no artifact", which is the same thing they did when
# the file was locked.
_TIMEOUT_S = 15

_session = requests.Session()


def _sandbox_url(path: str) -> str:
    host = os.getenv("FLASK_SANDBOX_HOST", "127.0.0.1")
    port = os.getenv("FLASK_SANDBOX_PORT", "2000")
    return f"http://{host}:{port}{path}"


def _headers() -> dict:
    token = os.getenv("CURIO_SANDBOX_TOKEN", "").strip()
    return {SANDBOX_TOKEN_HEADER: token} if token else {}


_COLUMNS = "kind, value_int, value_float, value_str, value_json"


def _local_row(art_id: str) -> tuple | None:
    """Read the row directly, for a process that owns the database itself.

    Two callers are in that position and neither is a deployed backend: the
    unit suites, which write their fixtures straight into DuckDB in-process,
    and any single-process embedding. Asking over HTTP there would mean
    talking to a sandbox that does not exist.
    """
    try:
        from utk_curio.sandbox.util import db as sandbox_db

        if not sandbox_db._writer_process:
            return None
        con = sandbox_db.get_read_connection()
        return con.execute(
            f"SELECT {_COLUMNS} FROM artifacts WHERE id = ?", [art_id],
        ).fetchone()
    except Exception:  # noqa: BLE001 - absent table or DB reads as "no artifact"
        return None


def artifact_row(art_id: str) -> tuple | None:
    """``(kind, value_int, value_float, value_str, value_json)`` or None.

    The tuple shape is the one the previous ``SELECT`` returned, so callers
    read the same way they always did.
    """
    if not art_id:
        return None

    local = _local_row(art_id)
    if local is not None:
        return local

    try:
        response = _session.get(
            _sandbox_url("/artifact-meta"),
            params={"fileName": art_id},
            headers=_headers(),
            timeout=_TIMEOUT_S,
        )
    except requests.RequestException as exc:
        log.debug("artifact-meta lookup for %s failed: %s", art_id, exc)
        return None

    if response.status_code == 404:
        return None
    if not response.ok:
        log.debug("artifact-meta lookup for %s returned %s",
                  art_id, response.status_code)
        return None

    try:
        body = response.json()
    except ValueError:
        return None
    return (
        body.get("kind"),
        body.get("value_int"),
        body.get("value_float"),
        body.get("value_str"),
        body.get("value_json"),
    )


def _local_session(art_id: str) -> tuple[bool, str | None]:
    """``(True, the row's session or None)`` read directly in a process that
    owns the database (:func:`_local_row`), or ``(False, None)`` in one that
    does not."""
    try:
        from utk_curio.sandbox.util import db as sandbox_db

        if not sandbox_db._writer_process:
            return False, None
        row = sandbox_db.get_read_connection().execute(
            "SELECT session_id FROM artifacts WHERE id = ?", [art_id],
        ).fetchone()
        return True, (row[0] if row else None)
    except Exception:  # noqa: BLE001 - asked of the sandbox instead
        return False, None


def made_by_a_kept_run(art_id: str) -> bool:
    """Whether the store's artifact *art_id* was made by a kept run, any
    dataflow's and any maker's (``common/kept_sessions.py``). True as well
    when the sandbox cannot say: a caller deciding whether a name may reach
    a kept session, which reads every kept run's artifacts, takes an unknown
    for one."""
    if not art_id:
        return False
    from utk_curio.common.kept_sessions import is_kept_session

    owned, session = _local_session(art_id)
    if owned:
        return is_kept_session(session)
    try:
        response = _session.get(
            _sandbox_url("/artifact-meta"),
            params={"fileName": art_id},
            headers=_headers(),
            timeout=_TIMEOUT_S,
        )
    except requests.RequestException:
        return True
    if response.status_code == 404:
        return False
    if not response.ok:
        return True
    try:
        return bool((response.json() or {}).get("keptRun"))
    except ValueError:
        return True
