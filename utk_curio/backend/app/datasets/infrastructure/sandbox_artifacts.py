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


#: The most artifacts one call to the sandbox's ``/artifacts/readable`` names
#: (its ``MAX_SESSIONS_PER_CALL``).
_READS_PER_CALL = 500
#: The most sessions one such call names, its reads' and those every read is
#: read under together (its ``MAX_READ_SESSIONS_PER_CALL``).
_SESSIONS_PER_CALL = 10_000


def _local_readable(asked: dict, shared: list) -> set[str] | None:
    """:func:`readable` read directly, in a process that owns the database
    (:func:`_local_row`), or None in one that does not."""
    try:
        from utk_curio.sandbox.util import db as sandbox_db

        if not sandbox_db._writer_process:
            return None
    except Exception:  # noqa: BLE001 - asked of the sandbox instead
        return None
    from utk_curio.sandbox.util.parsers import readable_artifacts

    try:
        return set(readable_artifacts(asked, shared))
    except Exception:  # noqa: BLE001 - absent table or DB reads as nothing readable
        return set()


def _calls(asked: dict, shared: list) -> list[dict]:
    """*asked* in as few calls to ``/artifacts/readable`` as its bounds allow:
    one, unless a request names more than :data:`_READS_PER_CALL` outputs."""
    calls: list[tuple[dict, int]] = []
    room = _SESSIONS_PER_CALL - len(shared)
    for art_id, own in asked.items():
        named = len(own) if isinstance(own, list) else 1
        if not calls or len(calls[-1][0]) >= _READS_PER_CALL or calls[-1][1] + named > room:
            calls.append(({}, 0))
        call, count = calls[-1]
        call[art_id] = own
        calls[-1] = (call, count + named)
    return [call for call, _count in calls]


def readable(reads: dict, sessions=()) -> set[str]:
    """The artifact ids among *reads*, ``{id: the session it is read under,
    or a list of sessions}``, whose rows one of its sessions or of
    *sessions*, which every id is read under, may read
    (``sandbox/util/parsers.session_may_read``).

    For a caller vouching for a request: an id read under no session (None)
    is not among them, though a read under none reads any row. One read under
    a list reads a row that carries no session, so an empty list reads only
    such a row. Nor is an id with no row, nor any the sandbox does not answer
    for. A kept run's session goes only in a read's own list: it reads what
    every kept run made."""
    asked: dict = {}
    for art_id, own in reads.items():
        if isinstance(own, str):
            own = own or None
        elif own is not None:
            own = [str(session) for session in own if session]
        if art_id and own is not None:
            asked[str(art_id)] = own
    shared = [str(session) for session in dict.fromkeys(sessions or ()) if session]
    if not asked:
        return set()
    local = _local_readable(asked, shared)
    if local is not None:
        return local
    found: set[str] = set()
    for call in _calls(asked, shared):
        try:
            response = _session.post(
                _sandbox_url("/artifacts/readable"),
                json={"reads": call, **({"sessions": shared} if shared else {})},
                headers=_headers(),
                timeout=_TIMEOUT_S,
            )
            response.raise_for_status()
            found.update(str(art_id) for art_id in (response.json() or {}).get("readable") or [])
        except (requests.RequestException, ValueError) as exc:
            log.warning("could not ask the sandbox which of %d outputs are readable: %s", len(call), exc)
    return found & set(asked)


def wrapped_names(art_id: str, saved_path: str | None = None) -> list[str] | None:
    """The outputs *art_id* names when it holds a persisted ``outputs``
    wrapper, which the sandbox reads for a run whose input it is
    (``sandbox/util/staging.outputs_wrapper_names``); [] for any other
    artifact, or none; None when the sandbox does not answer. With no row,
    the saved output's file *saved_path*, which a run reads in its place."""
    if not art_id:
        return []
    try:
        from utk_curio.sandbox.util import db as sandbox_db

        local = bool(sandbox_db._writer_process)
    except Exception:  # noqa: BLE001 - asked of the sandbox instead
        local = False
    if local:
        from utk_curio.sandbox.util.staging import outputs_wrapper_names

        try:
            return outputs_wrapper_names(art_id, saved_path)
        except Exception:  # noqa: BLE001 - an unreadable row says nothing
            return None
    params = {"fileName": art_id}
    if saved_path:
        params["savedPath"] = saved_path
    try:
        response = _session.get(
            _sandbox_url("/artifacts/wraps"), params=params, headers=_headers(), timeout=_TIMEOUT_S,
        )
    except requests.RequestException:
        return None
    if not response.ok:
        return None
    try:
        wraps = (response.json() or {}).get("wraps")
    except ValueError:
        return None
    return [str(name) for name in wraps if name] if isinstance(wraps, list) else None


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
