"""Kept outputs: what a run's steps make, kept under a key of what made them.

A dashboard viewer's runs (``runs/viewer.py``) keep each step's output, so a
visitor who opens the page or picks values someone ran before gets the outputs
at once, and a request for a run already going joins it. So do the owner's own
runs of a saved dataflow, a play or a run on the server
(``execution/node_exec.py``), whose outputs the owner reads through the
dataflow's routes. Each output is kept for :data:`KEPT_DAYS` after it was
made, under a key of what made it (:func:`step_key`); past that time it goes,
and the next run that needs it makes it again. Each dataflow keeps at most
:data:`MAX_KEPT_BYTES` of what its viewers made; past it the least recently
used go. What the owner's runs made (``made_by``) is bounded by its days
alone: the owner's open canvas shows it. An output goes with its artifacts:
the sandbox forgets the session that made them (``common/kept_sessions.py``).
The sweep runs every :data:`PRUNE_INTERVAL_HOURS` (:func:`start_prune_scheduler`),
at the end of each run, and at the first start after a restart.

An output built on what one tab's browser sent is kept for that tab alone
(``private_to``, the digest of its run's token), for :data:`TAB_OWN_HOURS`.
One the owner's keys made, or one made from it, is the owner's alone
(:data:`OWNER_ONLY`), for its full days.

The same sweep empties the sandbox's store of what it made more than
:data:`KEPT_DAYS` ago that no kept output holds (:func:`sweep_store`), so the
shared data directory holds at most that many days of results.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import threading
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import event
from sqlalchemy.orm import object_session

from utk_curio.backend.app.execution.sandbox_client import sandbox_request
from utk_curio.backend.app.runs.models import KeptStepOutput, naive_utc_now
from utk_curio.backend.app.runs.service import RunError
from utk_curio.backend.extensions import commit_with_retry, db

log = logging.getLogger(__name__)

#: How long a kept output serves the runs that need it, from when it was made;
#: then it goes, and the next run that needs it makes it again.
KEPT_DAYS = 7
#: How often the kept outputs past their time are swept, with no run to sweep them.
PRUNE_INTERVAL_HOURS = 6
#: How long an output built on what one tab's browser sent serves that tab.
TAB_OWN_HOURS = 1
#: The most one dataflow keeps of what one maker made; past it the least
#: recently used go.
MAX_KEPT_BYTES = 2 * 1024 ** 3
#: Who made a kept output: the dataflow's owner, or a viewer of its dashboard.
MADE_BY_OWNER = "owner"
MADE_BY_VIEWER = "viewer"
#: The ``private_to`` of an output the owner's keys made, or one made from
#: such an output: never a digest, so no run token, and so no viewer, reads
#: or reuses it.
OWNER_ONLY = "owner"
#: The backend's deadline for asking the sandbox about sessions.
SANDBOX_SESSIONS_TIMEOUT = 30
#: The most sessions one call to the sandbox names (its ``MAX_SESSIONS_PER_CALL``).
SESSIONS_PER_CALL = 500
#: The backend's deadline for a sweep of the sandbox's store, which reads every row.
STORE_SWEEP_TIMEOUT = 300


def digest(token: str) -> str:
    """The digest a run token is kept as (``private_to``)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def canonical(value) -> str:
    """*value* as the one JSON text a key hashes."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


# ---------------------------------------------------------------------------
# Step keys
# ---------------------------------------------------------------------------

def packages_fingerprint(user_key: str) -> str:
    """A digest of the owner's package store: each package's folder and its
    ``integrity.json`` (else its manifest). Installing, removing or upgrading
    any package, a model package included, changes it."""
    from utk_curio.backend.app.packages.repositories.store import user_packages_dir

    found = hashlib.sha256()
    try:
        root = user_packages_dir(user_key)
        folders = sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
    except OSError:
        folders = []
    for folder in folders:
        found.update(folder.name.encode("utf-8") + b"\0")
        for name in ("integrity.json", "manifest.json"):
            path = folder / name
            if path.is_file():
                found.update(path.read_bytes())
                break
    return found.hexdigest()


def _file_identity(path: str) -> list:
    """What says a dataset file changed: its size and time, or, for a folder,
    each file's under it (at most a few hundred)."""
    try:
        if os.path.isdir(path):
            found = []
            for folder, _dirs, files in os.walk(path):
                for name in sorted(files):
                    stat = os.stat(os.path.join(folder, name))
                    found.append([os.path.relpath(os.path.join(folder, name), path), stat.st_size, stat.st_mtime_ns])
                    if len(found) >= 500:
                        return sorted(found)
            return sorted(found)
        stat = os.stat(path)
        return [stat.st_size, stat.st_mtime_ns]
    except OSError:
        return ["missing"]


def datasets_read(code: str, project_id: str, owner, *, paths: Optional[dict] = None) -> dict:
    """``{dataset id: identity}`` of the datasets *code* reads: re-importing a
    dataset under the same id changes its identity. *paths*, when the run
    already resolved them (``node_exec.resolve_dataset_paths``), saves
    resolving them again."""
    from utk_curio.backend.app.execution import node_exec

    if paths is None:
        paths = node_exec.resolve_dataset_paths(code, project_id, owner) or {}
    return {dataset_id: _file_identity(str(path)) for dataset_id, path in sorted(paths.items())}


def input_identity(raw) -> dict:
    """What a step's key holds of its input: the names it reads and its data
    type, as the run reads them (``node_exec.parse_input_ref``), whichever
    shape the input came in. A play sends the canvas's reference, a run on
    the server the engine's; the same input keys the same."""
    from utk_curio.backend.app.execution import node_exec

    ref = node_exec.parse_input_ref(raw)
    path = ref["path"]
    if not isinstance(path, str):
        path = node_exec.input_names(ref)
    return {"path": path, "dataType": ref["dataType"]}


def step_key(*, packages: str, node_type: str, engine: str, code: str, input_ref, input_slots, datasets) -> str:
    """The key a step's output is kept under: everything that made it. Its
    code as sent, the values written in; its inputs, which are saved outputs
    or other kept outputs, each its own artifact; the owner's packages; the
    datasets its code reads; and Curio's version, whose helpers it calls.
    Its type is keyed in its one canonical spelling: a play posts it with its
    version, and a saved dataflow may hold it without one."""
    from utk_curio import __version__
    from utk_curio.backend.app.packages.service import canonical_template_id

    return hashlib.sha256(canonical({
        "curio": __version__,
        "packages": packages,
        "type": canonical_template_id(node_type),
        "engine": engine,
        "code": code,
        "input": input_ref,
        "slots": list(input_slots or ()),
        "datasets": datasets,
    }).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# The sessions that tag what a kept run makes
# ---------------------------------------------------------------------------

def _sandbox_sessions(path: str, session_ids: list) -> list:
    """POST *session_ids* to the sandbox's ``/artifact-sessions/<path>``, a
    batch at a time; the answer of each batch."""
    answers = []
    for start in range(0, len(session_ids), SESSIONS_PER_CALL):
        response = sandbox_request(
            "post", f"/artifact-sessions/{path}",
            label=f"/artifact-sessions/{path}", timeout=SANDBOX_SESSIONS_TIMEOUT,
            data=json.dumps({"sessionIds": session_ids[start:start + SESSIONS_PER_CALL]}),
            headers={"Content-Type": "application/json"},
        )
        try:
            answers.append(response.json() or {})
        except ValueError:
            answers.append({})
    return answers


def describe_session(session_id: str) -> dict:
    """``{"bytes", "ids"}``: what the session made, as the sandbox counts it."""
    for answer in _sandbox_sessions("describe", [session_id]):
        described = (answer.get("sessions") or {}).get(session_id)
        if isinstance(described, dict):
            return described
    return {}


def forget_sessions(session_ids) -> None:
    """Ask the sandbox to delete what the sessions made. Best effort: an
    unreachable sandbox leaves the artifacts, never a refused request."""
    session_ids = [s for s in session_ids if s]
    if not session_ids:
        return
    try:
        _sandbox_sessions("forget", session_ids)
    except Exception:  # noqa: BLE001 - the rows go either way
        log.warning("could not forget %d kept sessions in the sandbox", len(session_ids))


# ---------------------------------------------------------------------------
# Keeping and reading
# ---------------------------------------------------------------------------

def _alive(now):
    """The kept outputs still within their time, whether or not a sweep has
    run since: a shared one, and every one the owner's runs made, for
    :data:`KEPT_DAYS` after it was made; a tab's own for :data:`TAB_OWN_HOURS`."""
    owners = KeptStepOutput.made_by == MADE_BY_OWNER
    return db.or_(
        db.and_(
            db.or_(KeptStepOutput.private_to.is_(None), owners),
            KeptStepOutput.created_at >= now - timedelta(days=KEPT_DAYS),
        ),
        db.and_(
            KeptStepOutput.private_to.isnot(None),
            db.not_(owners),
            KeptStepOutput.created_at >= now - timedelta(hours=TAB_OWN_HOURS),
        ),
    )


def _newest_holding(query, name: str) -> Optional[KeptStepOutput]:
    """The newest live entry of *query* that the owner's runs kept and that
    holds the artifact *name*, or None."""
    now = naive_utc_now()
    for entry in (
        query.filter(KeptStepOutput.made_by == MADE_BY_OWNER)
        .filter(db.or_(
            KeptStepOutput.output_path == name,
            KeptStepOutput.artifact_ids.contains(json.dumps(name)),
        ))
        .filter(_alive(now))
        .order_by(KeptStepOutput.created_at.desc())
        .all()
    ):
        if name == entry.output_path or name in json.loads(entry.artifact_ids or "[]"):
            return entry
    return None


def owner_entry(project_id: str, name: str) -> Optional[KeptStepOutput]:
    """The live output the owner's runs of *project_id* kept that holds the
    artifact *name*, the newest, or None. Only the owner reads it: through
    the dataflow's routes, and as the input of their next run."""
    if not name:
        return None
    return _newest_holding(KeptStepOutput.query.filter(KeptStepOutput.project_id == project_id), name)


def owner_session(user_id, name: str) -> Optional[str]:
    """The kept session that made the artifact *name*, when the runs of a
    dataflow *user_id* owns kept it, else None: what the owner's sign-in
    reads it under on the routes that name no dataflow (``/get``,
    ``/get-preview``, ``/raster``), as a package's node reads its input."""
    from utk_curio.backend.app.projects.models import Project

    if not name or user_id is None:
        return None
    entry = _newest_holding(
        KeptStepOutput.query.join(Project, Project.id == KeptStepOutput.project_id)
        .filter(Project.user_id == user_id),
        name,
    )
    return entry.session_id if entry is not None else None


def kept_output(project_id: str, key: str, private_to: Optional[str] = None) -> Optional[tuple[dict, list]]:
    """The output kept under *key* that this run may read, a shared one or
    one private to *private_to*, with its artifact ids. Touches it, so it is
    the last to go."""
    now = naive_utc_now()
    readable = KeptStepOutput.private_to.is_(None)
    if private_to is not None:
        readable = db.or_(readable, KeptStepOutput.private_to == private_to)
    entry = (
        KeptStepOutput.query
        .filter_by(project_id=project_id, step_key=key)
        .filter(readable)
        .filter(_alive(now))
        .order_by(KeptStepOutput.created_at.desc())
        .first()
    )
    if entry is None:
        return None
    entry_id = entry.id

    def _touch():
        db.session.query(KeptStepOutput).filter_by(id=entry_id).update({"used_at": now})

    commit_with_retry(_touch)
    return json.loads(entry.output), json.loads(entry.artifact_ids or "[]")


def keep(
    project_id: str, node_id: str, key: str, session_id: str, output: dict,
    private_to: Optional[str] = None, made_by: str = MADE_BY_VIEWER,
) -> list:
    """Keep a step's output under *key*, with what its session made, as one
    *made_by* made; its artifact ids."""
    try:
        described = describe_session(session_id)
    except Exception:  # noqa: BLE001 - the output is kept with what is known of it
        described = {}
    path = str(output.get("path") or "")
    ids = [str(i) for i in described.get("ids") or []] or [path]
    # Dated by the clock its lookup and its sweep read.
    now = naive_utc_now()

    def _apply():
        db.session.add(KeptStepOutput(
            project_id=project_id, node_id=node_id, step_key=key, session_id=session_id,
            output=json.dumps(output), output_path=path, artifact_ids=json.dumps(ids),
            size_bytes=int(described.get("bytes") or 0), private_to=private_to, made_by=made_by,
            created_at=now, used_at=now,
        ))

    commit_with_retry(_apply)
    return ids


def readable_output(project_id: str, file_name: str, token: Optional[str]) -> KeptStepOutput:
    """The kept output of *project_id* that holds the artifact *file_name*,
    if the caller may read it: a shared one, or one private to the run whose
    token the caller sends. Anything else is not found, so no other artifact
    can be read this way."""
    if not file_name:
        raise RunError("No artifact id specified.", 400)
    now = naive_utc_now()
    candidates = (
        KeptStepOutput.query.filter_by(project_id=project_id)
        .filter(db.or_(
            KeptStepOutput.output_path == file_name,
            KeptStepOutput.artifact_ids.contains(json.dumps(file_name)),
        ))
        .filter(_alive(now))
        .order_by(KeptStepOutput.created_at.desc())
        .all()
    )
    token_digest = digest(token) if token else None
    for entry in candidates:
        if file_name != entry.output_path and file_name not in json.loads(entry.artifact_ids or "[]"):
            continue
        if entry.private_to is None or (
            token_digest is not None and secrets.compare_digest(entry.private_to, token_digest)
        ):
            return entry
    raise RunError("No such output on this dashboard.", 404)


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------

def prune(now=None) -> int:
    """Drop the kept outputs past their time (:data:`KEPT_DAYS`, or
    :data:`TAB_OWN_HOURS` for a tab's own), and, on a dataflow whose outputs
    from one maker pass :data:`MAX_KEPT_BYTES`, that maker's least recently
    used until they are under. Their artifacts go with them. Returns how many
    went."""
    now = now or naive_utc_now()
    expired = KeptStepOutput.query.filter(db.not_(_alive(now))).all()
    going = {entry.id: entry for entry in expired}
    totals = (
        db.session.query(
            KeptStepOutput.project_id, KeptStepOutput.made_by, db.func.sum(KeptStepOutput.size_bytes),
        )
        .group_by(KeptStepOutput.project_id, KeptStepOutput.made_by).all()
    )
    for project_id, made_by, total in totals:
        if made_by == MADE_BY_OWNER:
            # Bounded by its days alone: the owner's open canvas shows it.
            continue
        total = int(total or 0) - sum(
            e.size_bytes for e in going.values() if e.project_id == project_id and e.made_by == made_by
        )
        if total <= MAX_KEPT_BYTES:
            continue
        for entry in (
            KeptStepOutput.query.filter_by(project_id=project_id, made_by=made_by)
            .order_by(KeptStepOutput.used_at.asc(), KeptStepOutput.created_at.asc()).all()
        ):
            if total <= MAX_KEPT_BYTES:
                break
            if entry.id not in going:
                going[entry.id] = entry
                total -= entry.size_bytes
    if not going:
        return 0
    sessions = [entry.session_id for entry in going.values()]
    ids = list(going)

    def _apply():
        db.session.query(KeptStepOutput).filter(
            KeptStepOutput.id.in_(ids)).delete(synchronize_session=False)

    commit_with_retry(_apply)
    forget_sessions(sessions)
    return len(ids)


def prune_quietly() -> None:
    """:func:`prune`, logging a failure rather than raising it."""
    try:
        prune()
    except Exception:  # noqa: BLE001 - a sweep never fails a run
        log.exception("could not prune the kept outputs")


def sweep_store(now=None) -> int:
    """Have the sandbox delete what its store made more than :data:`KEPT_DAYS`
    ago that no kept output holds (``/artifacts/sweep``), and return how many
    artifacts went. Every run's output is kept that long, saved or not; a saved
    output is the Data Catalog's file, which keeps it after the store's goes."""
    now = now or naive_utc_now()
    made_before = int((now - timedelta(days=KEPT_DAYS) - datetime(1970, 1, 1)).total_seconds() * 1000)
    response = sandbox_request(
        "post", "/artifacts/sweep", label="/artifacts/sweep", timeout=STORE_SWEEP_TIMEOUT,
        data=json.dumps({"madeBefore": made_before}),
        headers={"Content-Type": "application/json"},
    )
    try:
        return int((response.json() or {}).get("forgotten") or 0)
    except (TypeError, ValueError):
        return 0


def sweep_store_quietly() -> None:
    """:func:`sweep_store`, logging a failure rather than raising it."""
    try:
        sweep_store()
    except Exception:  # noqa: BLE001 - the next sweep tries again
        log.exception("could not sweep the store's artifacts")


_prune_timer: Optional[threading.Timer] = None


def start_prune_scheduler(app) -> None:
    """Sweep the kept outputs every :data:`PRUNE_INTERVAL_HOURS`, the first
    time a minute after the backend starts, so an output goes once its time is
    up whether or not anyone runs a step. Off under ``--testing``, whose tests
    call :func:`prune` themselves."""
    from utk_curio.backend.config import _is_testing

    global _prune_timer
    if _is_testing() or _prune_timer is not None:
        return

    def _sweep():
        try:
            with app.app_context():
                prune_quietly()
                sweep_store_quietly()
        finally:
            _schedule(PRUNE_INTERVAL_HOURS * 3600)

    def _schedule(seconds: float):
        global _prune_timer
        _prune_timer = threading.Timer(seconds, _sweep)
        _prune_timer.daemon = True
        _prune_timer.start()

    _schedule(60)


#: Where a session notes the sandbox sessions of the entries it deleted.
_FORGET_ON_COMMIT = "curio_forget_kept_sessions"


def _note_deleted_entry(_mapper, _connection, entry) -> None:
    """An entry deleted through the session, a deleted dataflow's by its
    cascade among them, has its artifacts forgotten once the delete commits."""
    session = object_session(entry)
    if session is not None:
        session.info.setdefault(_FORGET_ON_COMMIT, set()).add(entry.session_id)


def _forget_after_commit(session) -> None:
    sessions = session.info.pop(_FORGET_ON_COMMIT, None)
    if sessions:
        forget_sessions(sorted(sessions))


def _keep_after_rollback(session, *_args) -> None:
    session.info.pop(_FORGET_ON_COMMIT, None)


def _listen_for_deletes() -> None:
    if not event.contains(KeptStepOutput, "after_delete", _note_deleted_entry):
        event.listen(KeptStepOutput, "after_delete", _note_deleted_entry)
        event.listen(db.session, "after_commit", _forget_after_commit)
        event.listen(db.session, "after_rollback", _keep_after_rollback)


_listen_for_deletes()
