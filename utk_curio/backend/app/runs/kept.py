"""Kept outputs: what a run's steps make, kept under a key of what made them.

A dashboard viewer's runs (``runs/viewer.py``) keep each step's output, so a
visitor who opens the page or picks values someone ran before gets the outputs
at once, and a request for a run already going joins it. So do the owner's own
runs of a saved dataflow, a play or a run on the server
(``execution/node_exec.py``), whose outputs the owner reads through the
dataflow's routes, and the runs of an editor the owner invited, whose outputs
are his: kept for his account alone (:func:`account_private`), read under any
of his sign-ins and by no one else. Each output is kept for :data:`KEPT_DAYS`
after it was made, under a key of what made it (:func:`step_key`); past that
time it goes, and the next run that needs it makes it again. An output kept
replaces what earlier runs kept of the same node under the same key, by the
same maker for the same reader (:func:`keep`), which still serve every read
they served for :data:`REPLACED_HOURS` and go at the first sweep after: a
step run again with the same code on the same input artifacts keeps one copy
of what it made, files and all.

A step whose key holds an output it may read answers with it and runs
nothing (:func:`kept_reply`): a dashboard viewer's step, whoever made the
output, and a step of the owner's or an editor's runs that its run was not
asked for (a Run All's, and the nodes above a Play's node), with what its
maker's own runs kept of its node (:func:`kept_output`'s ``made_by`` and
``node_id``, :func:`reader_of`). A reused output keeps its artifact names, so
the step below it keys the same and is reused too: a Run All repeated with
nothing changed runs nothing and keeps nothing new. A step whose inputs ran
again reads new artifacts, so its key is new and its output kept beside the
last one's. Each dataflow
keeps at most :data:`MAX_KEPT_BYTES` of what its viewers made, the files
their steps derived counted in; past it the least recently used go. What the
owner's and the editors' runs made (``made_by``) is bounded by its days alone:
their open canvases show it. An output goes with its artifacts: the sandbox
forgets the session that made them (``common/kept_sessions.py``). The files a
run derived, in its own folder (``media_dirs.derived_root``), go once no kept
output names the folder (its run's, or a later step's that read it and so may
hand its rows on: ``media_folders``) and no saved output of the account
records it (``datasets/install/media_records.py``): :func:`forget_kept_media`.
The sweep runs every :data:`PRUNE_INTERVAL_HOURS` (:func:`start_prune_scheduler`),
at the end of each run, and at the first start after a restart. Every
:data:`PRUNE_INTERVAL_HOURS` it also removes a run's folder that nothing names
and nothing has written in for :data:`KEPT_DAYS` (:func:`sweep_kept_media`),
and the thumbnails of the folders that are gone.

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
from dataclasses import dataclass
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
#: How long an output a later run of its step replaced (:func:`keep`) still
#: serves the pages and runs that read it, a canvas or a dashboard open on it
#: or a run whose next step reads it; the first sweep after that drops it.
REPLACED_HOURS = 1
#: The most one dataflow keeps of what one maker made; past it the least
#: recently used go.
MAX_KEPT_BYTES = 2 * 1024 ** 3
#: Who made a kept output: the dataflow's owner, an editor the owner invited,
#: or a viewer of its dashboard.
MADE_BY_OWNER = "owner"
MADE_BY_EDITOR = "editor"
MADE_BY_VIEWER = "viewer"
#: The makers whose outputs are bounded by their days alone, private or not.
_FOR_THEIR_DAYS = (MADE_BY_OWNER, MADE_BY_EDITOR)
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


def account_private(user_id) -> str:
    """The ``private_to`` of an output the runs of an editor the owner
    invited kept: his account's alone. Never a digest (64 hex digits) or
    :data:`OWNER_ONLY`, so no run token and no owner reads it."""
    return f"account:{user_id}"


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


def packages_key(owner_key: str, runner_key: Optional[str] = None) -> str:
    """The packages a step's key holds: the dataflow owner's store
    (:func:`packages_fingerprint`), as a dashboard viewer's step keys it,
    and, for a run of an editor she invited (*runner_key* another store), his
    store too: his run reads her packages for her dataflow's nodes and his
    own for his own nodes, so a change to either makes what it kept stale."""
    owners = packages_fingerprint(owner_key)
    if not runner_key or runner_key == owner_key:
        return owners
    return hashlib.sha256(canonical([owners, packages_fingerprint(runner_key)]).encode("utf-8")).hexdigest()


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
    from utk_curio.backend.app.datasets.infrastructure import left_out_files
    from utk_curio.backend.app.execution import node_exec

    if paths is None:
        # A file a pip install leaves out downloads as it resolves, before
        # the step's lookup knows whether it runs: the node that shows its
        # progress is told when that is over (``left_out_files.downloading``).
        with left_out_files.downloading():
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


@dataclass(frozen=True)
class StepCall:
    """What a run of one step sends the sandbox: its code, the engine that
    runs it, its input and its wired circles."""

    code: str
    engine: str
    input: object
    slots: Optional[tuple]


def step_call(plan, step, code: str, input_ref) -> StepCall:
    """What a run of *step* sends, given its *code* as the engine sends it
    (``run_engine.sent_code``) and its *input_ref*. An Autark node whose
    document only loads data runs as the JavaScript it compiles to, as the
    browser's run of it does (``autkLayerMaterialize.ts``): on no input, or,
    when its data section reads tables of its input (``step.autk_input``), on
    its input with no circles named, so the sandbox gives each input under its
    place among the node's inputs, the name the node reads it by. Its input is
    then part of the key its output is kept under."""
    if step.autk_data:
        from utk_curio.common.autk_data_compiler import compile_data_spec

        return StepCall(compile_data_spec(code), "javascript", input_ref if step.autk_input else None, None)
    return StepCall(code, step.engine, input_ref, tuple(plan.spec.input_slots(step.node_id)) or None)


def call_key(call: StepCall, *, packages: str, node_type: str, datasets: dict) -> str:
    """The key the output of *call* is kept under (:func:`step_key`), with
    *datasets* the identities of the datasets its code reads
    (:func:`datasets_read`)."""
    return step_key(
        packages=packages, node_type=node_type, engine=call.engine, code=call.code,
        input_ref=input_identity(call.input), input_slots=call.slots, datasets=datasets,
    )


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
    run since: a shared one, and every one the owner's or an editor's runs
    made, for :data:`KEPT_DAYS` after it was made; a tab's own for
    :data:`TAB_OWN_HOURS`."""
    for_their_days = KeptStepOutput.made_by.in_(_FOR_THEIR_DAYS)
    return db.or_(
        db.and_(
            db.or_(KeptStepOutput.private_to.is_(None), for_their_days),
            KeptStepOutput.created_at >= now - timedelta(days=KEPT_DAYS),
        ),
        db.and_(
            KeptStepOutput.private_to.isnot(None),
            db.not_(for_their_days),
            KeptStepOutput.created_at >= now - timedelta(hours=TAB_OWN_HOURS),
        ),
    )


def _newest_holding(query, name: str, made_by: Optional[str] = MADE_BY_OWNER) -> Optional[KeptStepOutput]:
    """The newest live entry of *query* that *made_by* kept, anyone for None,
    and that holds the artifact *name*, or None."""
    now = naive_utc_now()
    if made_by is not None:
        query = query.filter(KeptStepOutput.made_by == made_by)
    for entry in (
        query.filter(db.or_(
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


def project_entry(project_id: str, name: str) -> Optional[KeptStepOutput]:
    """The live output a run of *project_id* kept, its owner's or a
    viewer's, that holds the artifact *name*, the newest, or None: whether
    *name* is one of that dataflow's kept outputs. An editor's are his own,
    so none of them is one."""
    if not name:
        return None
    return _newest_holding(
        KeptStepOutput.query.filter(
            KeptStepOutput.project_id == project_id, KeptStepOutput.made_by != MADE_BY_EDITOR,
        ),
        name, made_by=None,
    )


def _editors(user_id):
    """The entries the runs of the account *user_id* kept as an editor."""
    return KeptStepOutput.query.filter(KeptStepOutput.private_to == account_private(user_id))


def editor_entry(project_id: str, user_id, name: str) -> Optional[KeptStepOutput]:
    """The live output the runs of the account *user_id* kept as an editor
    of *project_id* that holds the artifact *name*, the newest, or None. Only
    that account reads it, as only the owner reads hers (:func:`owner_entry`)."""
    if not name or user_id is None:
        return None
    return _newest_holding(
        _editors(user_id).filter(KeptStepOutput.project_id == project_id), name, made_by=MADE_BY_EDITOR,
    )


def editor_outputs_by_key(project_id: str, user_id) -> dict:
    """``{step key: entry}``: the newest live output the runs of the account
    *user_id* kept as an editor of *project_id* under each key, as
    :func:`owner_outputs_by_key` gives the owner's."""
    newest: dict = {}
    if user_id is None:
        return newest
    for entry in (
        _editors(user_id).filter(
            KeptStepOutput.project_id == project_id, KeptStepOutput.made_by == MADE_BY_EDITOR,
        )
        .filter(_alive(naive_utc_now()), _not_replaced())
        .order_by(KeptStepOutput.created_at.desc())
        .all()
    ):
        newest.setdefault(entry.step_key, entry)
    return newest


def owner_outputs_by_key(project_id: str) -> dict:
    """``{step key: entry}``: the newest live output the owner's runs of
    *project_id* kept under each key, none a later run replaced. Read only:
    nothing is touched, since an owner's outputs are bounded by their days
    alone."""
    newest: dict = {}
    for entry in (
        KeptStepOutput.query.filter_by(project_id=project_id, made_by=MADE_BY_OWNER)
        .filter(_alive(naive_utc_now()), _not_replaced())
        .order_by(KeptStepOutput.created_at.desc())
        .all()
    ):
        newest.setdefault(entry.step_key, entry)
    return newest


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


def editor_session(user_id, name: str) -> Optional[str]:
    """The kept session that made the artifact *name*, when the runs of the
    account *user_id* kept it as an editor of another account's dataflow,
    else None."""
    if not name or user_id is None:
        return None
    entry = _newest_holding(_editors(user_id), name, made_by=MADE_BY_EDITOR)
    return entry.session_id if entry is not None else None


def visitor_session(user_id, name: str, sign_in: Optional[str]) -> Optional[str]:
    """The kept session that made the artifact *name*, when a play of the
    hosted guest signed in as *sign_in* kept it on their own copy of a
    dataflow (``projects/visitor_copies.py``), which has no row of its own;
    else None. Every hosted guest signs in to the account *user_id*, so the
    copy must be this sign-in's."""
    from utk_curio.backend.app.projects import visitor_copies
    from utk_curio.backend.app.projects.models import Project
    from utk_curio.backend.app.users.models import User

    if not name or not sign_in or user_id is None or not visitor_copies.copies_for(db.session.get(User, user_id)):
        return None
    entry = _newest_holding(
        KeptStepOutput.query.outerjoin(Project, Project.id == KeptStepOutput.project_id)
        .filter(Project.id.is_(None)),
        name,
    )
    if entry is None or not visitor_copies.is_own_copy(sign_in, entry.project_id):
        return None
    return entry.session_id


def read_session(user_id, name: str, sign_in: Optional[str]) -> Optional[str]:
    """The session the account *user_id*, signed in as *sign_in*, reads the
    artifact *name* under where no dataflow is named: the kept session that
    made it, when the runs of a dataflow the account owns kept it
    (:func:`owner_session`), the account's own runs as an editor did
    (:func:`editor_session`) or the sign-in's plays as a hosted guest did
    (:func:`visitor_session`), else the sign-in, as when that lookup fails."""
    try:
        session = (
            owner_session(user_id, name) or editor_session(user_id, name)
            or visitor_session(user_id, name, sign_in)
        )
    except Exception:  # noqa: BLE001 - a read never fails on this lookup
        log.warning("could not look up the kept output %s", name)
        try:
            db.session.rollback()
        except Exception:  # noqa: BLE001 - no database to roll back
            pass
        session = None
    return session or sign_in


def readable_by(user_id, sign_in: Optional[str], names) -> set:
    """The artifacts among *names*, which a request named, that the account
    *user_id* signed in as *sign_in* may read: each under its
    :func:`read_session`, as the sandbox's rule has it
    (``datasets/infrastructure/sandbox_artifacts.readable``). One another
    account's run made is not among them, nor one no session of the account
    can read."""
    from utk_curio.backend.app.datasets.infrastructure import sandbox_artifacts

    return sandbox_artifacts.readable({
        name: read_session(user_id, name, sign_in)
        for name in dict.fromkeys(str(name) for name in names if name)
    })


#: The most sign-ins of one account that vouch for its outputs
#: (:func:`account_sign_ins`).
ACCOUNT_SIGN_INS = 5_000


def account_sign_ins(user_id) -> list[str]:
    """The sign-ins of the account *user_id* that can have made an output the
    store still holds, signed out or not: those seen in its last
    :data:`KEPT_DAYS` days and one, or never stamped, the newest first, at
    most :data:`ACCOUNT_SIGN_INS`. A request stamps its sign-in as it is
    served (``users/dependencies.get_current_user``), and the store forgets
    what it made :data:`KEPT_DAYS` days ago (:func:`sweep_store`)."""
    from utk_curio.backend.app.users.models import UserSession

    if user_id is None:
        return []
    seen_since = naive_utc_now() - timedelta(days=KEPT_DAYS + 1)
    rows = (
        UserSession.query.with_entities(UserSession.token)
        .filter(UserSession.user_id == user_id)
        .filter(db.or_(UserSession.last_seen_at.is_(None), UserSession.last_seen_at >= seen_since))
        .order_by(UserSession.id.desc())
        .limit(ACCOUNT_SIGN_INS)
        .all()
    )
    return [token for (token,) in rows if token]


def readable_by_account(user_id, names) -> set:
    """The artifacts among *names* that the account *user_id* vouches for,
    where no sign-in names them: a dataset ref a dataflow of the account
    carries, as node code, the agents, the Scenario Catalog and discovery read
    it. Each is read under every sign-in of the account
    (:func:`account_sign_ins`) and, when the runs of a dataflow the account
    owns kept it, under the kept session that made it, for that artifact
    alone (:func:`read_session`), since a kept run's session reads what every
    kept run made. A row that carries no session is read, as every session
    reads one. One another account made is not among them, nor one nothing
    vouches for."""
    from utk_curio.backend.app.datasets.infrastructure import sandbox_artifacts

    names = list(dict.fromkeys(str(name) for name in names if name))
    if not names:
        return set()
    reads = {}
    for name in names:
        kept_session = read_session(user_id, name, None) if user_id is not None else None
        reads[name] = [kept_session] if kept_session else []
    try:
        sign_ins = account_sign_ins(user_id)
    except Exception:  # noqa: BLE001 - the account's rows alone then
        log.warning("could not read the sign-ins of account %s", user_id)
        try:
            db.session.rollback()
        except Exception:  # noqa: BLE001 - no database to roll back
            pass
        sign_ins = []
    return sandbox_artifacts.readable(reads, sessions=sign_ins)


def _kept_entry(project_id: str, key: str, private_to: Optional[str] = None, *,
                made_by: Optional[str] = None, node_id: Optional[str] = None) -> Optional[KeptStepOutput]:
    """The newest output kept under *key* that this run may read, a shared one
    or one private to *private_to*, live and not replaced, or None; with
    *made_by*, only one that maker's runs kept, and with *node_id* only one of
    that node. Touches it, so it is the last to go."""
    now = naive_utc_now()
    readable = KeptStepOutput.private_to.is_(None)
    if private_to is not None:
        readable = db.or_(readable, KeptStepOutput.private_to == private_to)
    query = KeptStepOutput.query.filter_by(project_id=project_id, step_key=key)
    if made_by is not None:
        query = query.filter(KeptStepOutput.made_by == made_by)
    if node_id is not None:
        query = query.filter(KeptStepOutput.node_id == node_id)
    entry = (
        query.filter(readable, _not_replaced())
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
    return entry


def kept_output(project_id: str, key: str, private_to: Optional[str] = None, *,
                made_by: Optional[str] = None, node_id: Optional[str] = None) -> Optional[tuple[dict, list]]:
    """The output kept under *key* that this run may read, a shared one or
    one private to *private_to*, with its artifact ids (:func:`_kept_entry`).
    A dashboard viewer's step names neither *made_by* nor *node_id*, so it
    reads whoever made the output; a step of the owner's or an editor's runs
    names its maker and its node (:func:`reader_of`)."""
    entry = _kept_entry(project_id, key, private_to, made_by=made_by, node_id=node_id)
    if entry is None:
        return None
    return json.loads(entry.output), json.loads(entry.artifact_ids or "[]")


def kept_reply(project_id: str, key: str, private_to: Optional[str] = None, *,
               made_by: Optional[str] = None, node_id: Optional[str] = None) -> Optional[dict]:
    """The reply of a step whose key holds an output it may read
    (:func:`kept_output`), which runs nothing: no logs, the kept output, its
    artifact ids, and when it was made (``reused``). A dashboard viewer's
    step answers with it, and so does a step of the owner's or an editor's
    runs that its run was not asked for (``runs/service.py``,
    ``execution/node_exec.py``). None when no such output is kept."""
    from utk_curio.backend.app.runs.service import _iso

    entry = _kept_entry(project_id, key, private_to, made_by=made_by, node_id=node_id)
    if entry is None:
        return None
    return {
        "stdout": [], "stderr": "",
        "output": json.loads(entry.output), "artifactIds": json.loads(entry.artifact_ids or "[]"),
        "reused": {"madeAt": _iso(entry.created_at)},
    }


def reader_of(made_by: str, user_id) -> Optional[str]:
    """The ``private_to`` a run of *made_by* reads its own kept outputs
    with: the owner's, shared or hers alone (:data:`OWNER_ONLY`); an invited
    editor's, his account's (:func:`account_private`)."""
    if made_by == MADE_BY_EDITOR:
        return account_private(user_id)
    return OWNER_ONLY


def serves_its_save(output: dict, *, engine: str, saves: bool) -> bool:
    """Whether a kept *output* may answer a run of *engine* that saves its
    output when *saves*: a JavaScript node's saved table is an artifact of
    its own that its run makes only when it saves (``output.dataset``), so a
    run that saves takes only an output whose run saved it too."""
    return not (saves and engine == "javascript" and not (output or {}).get("dataset"))


def keep(
    project_id: str, node_id: str, key: str, session_id: str, output: dict,
    private_to: Optional[str] = None, made_by: str = MADE_BY_VIEWER,
    media_folders=None, media_bytes: int = 0,
) -> list:
    """Keep a step's output under *key*, with what its session made, as one
    *made_by* made; its artifact ids. *media_folders* are the folders of the
    runs before it whose files its rows may name, which stay while it does
    (:func:`forget_kept_media`), as its own run's folder does. *media_bytes*,
    the bytes of the files its run derived, count in its size, with its
    session's.

    It replaces what earlier runs kept of *node_id* on *project_id* under
    *key*, by *made_by* for the same reader (:func:`_replaced`): it marks
    them replaced (:func:`_mark_replaced`), and they serve every read they
    served, so a page, a canvas or a run still on one finds it, until the
    first sweep :data:`REPLACED_HOURS` on drops them (:func:`prune`).
    Identical runs keep one copy of what they made, the last one's; a folder
    of theirs that another kept output or a saved output's record names
    stays when they go. A step that reuses a kept output keeps nothing
    (:func:`kept_reply`), so only a run that ran replaces one."""
    try:
        described = describe_session(session_id)
    except Exception:  # noqa: BLE001 - the output is kept with what is known of it
        described = {}
    path = str(output.get("path") or "")
    ids = [str(i) for i in described.get("ids") or []] or [path]
    folders = json.dumps(sorted(set(media_folders))) if media_folders else None
    size = int(described.get("bytes") or 0) + int(media_bytes or 0)
    # Dated by the clock its lookup and its sweep read.
    now = naive_utc_now()

    def _apply():
        entry = KeptStepOutput(
            project_id=project_id, node_id=node_id, step_key=key, session_id=session_id,
            output=json.dumps(output), output_path=path, artifact_ids=json.dumps(ids),
            size_bytes=size, private_to=private_to, made_by=made_by,
            media_folders=folders, created_at=now, used_at=now,
        )
        db.session.add(entry)
        db.session.flush()
        return entry.id

    kept_id = commit_with_retry(_apply)
    try:
        _mark_replaced(_replaced(kept_id, project_id, node_id, key, made_by, private_to), now)
    except Exception:  # noqa: BLE001 - the output is kept; the older ones go with their days
        log.warning("could not mark the kept outputs that node %s's new output on %s replaces", node_id, project_id)
        try:
            db.session.rollback()
        except Exception:  # noqa: BLE001
            # No database to roll back: the older ones go with their days.
            pass
    return ids


def _not_replaced():
    """The kept outputs no later run of their step replaced (:func:`keep`):
    the ones a reuse, a reopen or a replace may pick."""
    return KeptStepOutput.replaced_at.is_(None)


def _replaced(kept_id: str, project_id: str, node_id: str, key: str, made_by: str,
              private_to: Optional[str]) -> list:
    """The outputs the one kept as *kept_id* replaces: those kept before it
    of *node_id* on *project_id* under *key*, by *made_by* for the same
    reader (*private_to*), whose runs made what its run made again, and that
    no run replaced yet."""
    reader = (
        KeptStepOutput.private_to.is_(None) if private_to is None
        else KeptStepOutput.private_to == private_to
    )
    return (
        KeptStepOutput.query
        .filter_by(project_id=project_id, node_id=node_id, step_key=key, made_by=made_by)
        .filter(reader, KeptStepOutput.id != kept_id, _not_replaced())
        .all()
    )


def _mark_replaced(entries, when) -> int:
    """Mark *entries* replaced at *when* (``replaced_at``): each serves every
    read it served, by its names, under its session and from its folder, but
    no reuse, reopen or later replace picks it, and the first sweep
    :data:`REPLACED_HOURS` on drops it (:func:`prune`). How many."""
    ids = [entry.id for entry in entries]
    if not ids:
        return 0

    def _apply():
        db.session.query(KeptStepOutput).filter(KeptStepOutput.id.in_(ids)).update(
            {"replaced_at": when}, synchronize_session=False,
        )

    commit_with_retry(_apply)
    return len(ids)


def _drop(entries) -> int:
    """Delete the kept outputs *entries*: the sandbox forgets the sessions
    that made their artifacts, and the runs' folders only they named go,
    with the files the runs derived (:func:`forget_kept_media`). How many
    went."""
    entries = list(entries)
    if not entries:
        return 0
    sessions = [entry.session_id for entry in entries]
    media = _entries_media(entries)
    ids = [entry.id for entry in entries]

    def _apply():
        db.session.query(KeptStepOutput).filter(
            KeptStepOutput.id.in_(ids)).delete(synchronize_session=False)

    commit_with_retry(_apply)
    forget_sessions(sessions)
    forget_kept_media(media)
    return len(ids)


#: A run's folder that nothing names goes once nothing has been written in it
#: for this long (:func:`sweep_kept_media`): as long as the store keeps the
#: artifacts of a run that keeps no output (:func:`sweep_store`), so a canvas
#: still showing such a run's rows finds their files, and a Solve's later
#: attempts read an earlier one's by their path.
KEPT_MEDIA_GRACE_SECONDS = KEPT_DAYS * 24 * 60 * 60


def _media_of(session_id: str, media_folders: Optional[str]) -> set:
    """The runs' folders whose files the rows of one kept output may name
    (``media_dirs.derived_root``): its own run's, named after its session,
    whoever made it, and those it was kept naming, the ones the outputs its
    run read name (:func:`folders_named_by`)."""
    from utk_curio.backend.app.discovery.infrastructure import media_dirs

    named = {media_dirs.kept_media_name(session_id)}
    try:
        named.update(str(name) for name in json.loads(media_folders or "[]"))
    except (TypeError, ValueError):
        log.warning("a kept output's folders could not be read: %r", media_folders)
    return named


def _named_folders(query) -> set:
    """Every folder the kept outputs of *query* name (:func:`_media_of`)."""
    named: set = set()
    for session_id, media_folders in query.with_entities(
        KeptStepOutput.session_id, KeptStepOutput.media_folders,
    ).all():
        named |= _media_of(session_id, media_folders)
    return named


def folders_named_by(project_id: str, names, saved=None) -> set:
    """The runs' folders that the rows of the outputs *names*, kept on
    *project_id*, may name: what the rows of a step that reads them may name
    too, since a step hands on rows it read (a filter, a join). A saved
    output among them (*saved*, ``{name: {"path"}}`` as a run's saved inputs
    hold them, ``node_exec.resolve_saved_inputs``) names those its data
    file's record names (``media_records``), kept output or not."""
    from utk_curio.backend.app.datasets.install import media_records

    found: set = set()
    for entry in (saved or {}).values():
        path = entry.get("path") if isinstance(entry, dict) else None
        if path:
            found |= media_records.folders_of_data_file(path)
    names = [str(name) for name in names or () if name]
    if not names:
        return found
    holding = db.or_(
        KeptStepOutput.output_path.in_(names),
        *[KeptStepOutput.artifact_ids.contains(json.dumps(name)) for name in names],
    )
    return found | _named_folders(
        KeptStepOutput.query.filter(KeptStepOutput.project_id == project_id).filter(holding)
    )


def _account_of(private_to: Optional[str]) -> Optional[str]:
    """The storage key of the account an output is private to
    (:func:`account_private`), or None for any other ``private_to``."""
    prefix = account_private("")
    if isinstance(private_to, str) and private_to.startswith(prefix) and private_to[len(prefix):].isdigit():
        return private_to[len(prefix):]
    return None


def _entries_media(entries) -> list:
    """``(project_id, media key, folders)`` of *entries*, read before they
    go: the folders their rows may name (:func:`_media_of`), each in the
    media folder its run derived in. An invited editor's run derives in his
    own (his ``private_to``, :func:`account_private`), any other run of the
    dataflow in its owner's (:func:`_media_owner`), whose row a delete may
    take before the folders go."""
    owners: dict = {}
    found = []
    for entry in entries:
        key = _account_of(entry.private_to) if entry.made_by == MADE_BY_EDITOR else None
        if key is None:
            if entry.project_id not in owners:
                owners[entry.project_id] = _media_owner(entry.project_id)
            key = owners[entry.project_id]
        found.append((entry.project_id, key, _media_of(entry.session_id, entry.media_folders)))
    return found


def forget_kept_media(gone) -> None:
    """Remove the runs' folders that the kept outputs that went named,
    *gone* being their ``(project_id, media key, folders)``
    (:func:`_entries_media`), with the files the runs derived, each in its
    run's own media folder: but a folder an output left on the dataflow
    names, since a step's output can go before the output of a later step
    that handed on its rows, whose rows still read the files; and a folder a
    saved output of that account records (``media_records``), which stays as
    long as that output does. Best effort: a sweep never fails on it."""
    from utk_curio.backend.app.datasets.install import media_records
    from utk_curio.backend.app.discovery.infrastructure import media_dirs

    by_dataflow: dict = {}
    for project_id, key, folders in gone or ():
        by_dataflow.setdefault((project_id, key), set()).update(folders)
    saved: dict = {}
    for (project_id, key), folders in by_dataflow.items():
        try:
            still = _named_folders(KeptStepOutput.query.filter(KeptStepOutput.project_id == project_id))
            if key not in saved:
                saved[key] = media_records.account_folders(key)
            media_dirs.forget_kept(key, sorted(folders - still - saved[key]))
        except Exception:  # noqa: BLE001 - the files stay, and nothing fails
            log.warning("could not remove what the runs of %s derived", project_id)
            try:
                db.session.rollback()
            except Exception:  # noqa: BLE001 - no database to roll back
                pass


def forget_unnamed_media(user_key: str, names) -> list:
    """Remove the runs' folders *names* in *user_key*'s media folder that no
    kept output and no saved output of the account names any more, as a
    Data Catalog delete of a saved output that recorded them asks
    (``datasets/application/mutations.py``): a play of a canvas not saved
    yet keeps no output, so only its saved output named its files. The
    names that went."""
    from utk_curio.backend.app.datasets.install import media_records
    from utk_curio.backend.app.discovery.infrastructure import media_dirs

    going = sorted(set(names or ()) - _named_folders(KeptStepOutput.query) - media_records.account_folders(user_key))
    media_dirs.forget_kept(user_key, going)
    return going


def sweep_kept_media(now: Optional[float] = None) -> int:
    """Remove every run's folder, in every account's media folder and in
    each hosted guest's folder in it, that no kept output names, no saved
    output of the account records, and nothing has been written in for
    :data:`KEPT_MEDIA_GRACE_SECONDS`, with what the run derived: the folder
    of a run that kept no output (a play of a canvas not saved yet, Solve's
    and the agents' runs), of one whose output was never kept (the backend
    stopped between the run's write and its keep), or of entries that went
    without it (a dataflow whose row was dropped, its spec file gone). Then
    the thumbnails of the folders that are gone, however they went. *now*
    is a time as ``time.time()`` gives it. Returns how many folders went."""
    import shutil
    import time

    from utk_curio.backend.app.datasets.install import media_records
    from utk_curio.backend.app.discovery.infrastructure import media_dirs

    named = _named_folders(KeptStepOutput.query)
    cutoff = (time.time() if now is None else now) - KEPT_MEDIA_GRACE_SECONDS
    saved: dict = {}
    gone = 0
    for account, folder in media_dirs.run_folders():
        if folder.name in named:
            continue
        if account not in saved:
            saved[account] = media_records.account_folders(account)
        if folder.name in saved[account] or media_dirs.last_written(folder) > cutoff:
            continue
        shutil.rmtree(folder, ignore_errors=True)
        gone += 1
    media_dirs.forget_gone_runs_thumbnails()
    return gone


def sweep_kept_media_quietly() -> None:
    """:func:`sweep_kept_media`, logging a failure rather than raising it."""
    try:
        sweep_kept_media()
    except Exception:  # noqa: BLE001 - the next sweep tries again
        log.exception("could not sweep the runs' folders")
        try:
            db.session.rollback()
        except Exception:  # noqa: BLE001 - no database to roll back
            pass


def _media_owner(project_id: str) -> str:
    """The store whose media folder holds what the runs on *project_id*
    derived, but an invited editor's: its owner's, as those runs run as the
    owner, or the shared guest's for a hosted guest's copy or new dataflow."""
    from utk_curio.backend.app.common.user_storage import GUEST_KEY
    from utk_curio.backend.app.projects.models import Project
    from utk_curio.backend.app.projects.services import _owner_user_dir_key

    project = db.session.get(Project, project_id)
    return _owner_user_dir_key(project) if project is not None else GUEST_KEY


def dataflow_media(project_id: str) -> list:
    """``(project_id, media key, folders)`` of the outputs kept on
    *project_id*, whoever made them, whose folders a delete of the dataflow
    removes once its row is gone (:func:`forget_kept_media`)."""
    return _entries_media(KeptStepOutput.query.filter_by(project_id=project_id).all())


def forget_node(project_id: str, node_id: str) -> int:
    """Drop every output kept for *node_id* of *project_id*, whoever made it,
    as deleting the node's saved output asks; their artifacts go once the
    delete commits (:func:`_note_deleted_entry`), and the files their runs
    derived with them. Returns how many went."""
    media: list = []

    def _apply():
        entries = KeptStepOutput.query.filter_by(project_id=project_id, node_id=node_id).all()
        media[:] = _entries_media(entries)
        for entry in entries:
            db.session.delete(entry)
        return len(entries)

    gone = commit_with_retry(_apply)
    forget_kept_media(media)
    return gone


def forget_dataflows(project_ids) -> int:
    """Drop every output kept for each of *project_ids*, whoever made it, as
    the server's start drops the hosted guests' copies of dataflows
    (``projects/visitor_copies.drop_all``), which have no row whose delete
    would take them; their artifacts go once the delete commits
    (:func:`_note_deleted_entry`), and the files their runs derived with
    them. Returns how many went."""
    ids = list(dict.fromkeys(str(project_id) for project_id in project_ids or () if project_id))
    if not ids:
        return 0
    media: list = []

    def _apply():
        entries = KeptStepOutput.query.filter(KeptStepOutput.project_id.in_(ids)).all()
        media[:] = _entries_media(entries)
        for entry in entries:
            db.session.delete(entry)
        return len(entries)

    gone = commit_with_retry(_apply)
    forget_kept_media(media)
    return gone


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
    :data:`TAB_OWN_HOURS` for a tab's own), those a later run of their step
    replaced :data:`REPLACED_HOURS` or more ago (:func:`keep`), and, on a
    dataflow whose outputs from one maker pass :data:`MAX_KEPT_BYTES`, that
    maker's least recently used until they are under. Their artifacts go with
    them, and so do the files their runs derived (:func:`forget_kept_media`).
    Returns how many went."""
    now = now or naive_utc_now()
    expired = KeptStepOutput.query.filter(db.or_(
        db.not_(_alive(now)),
        KeptStepOutput.replaced_at <= now - timedelta(hours=REPLACED_HOURS),
    )).all()
    going = {entry.id: entry for entry in expired}
    totals = (
        db.session.query(
            KeptStepOutput.project_id, KeptStepOutput.made_by, db.func.sum(KeptStepOutput.size_bytes),
        )
        .group_by(KeptStepOutput.project_id, KeptStepOutput.made_by).all()
    )
    for project_id, made_by, total in totals:
        if made_by in _FOR_THEIR_DAYS:
            # Bounded by its days alone: the owner's or the editor's open
            # canvas shows it.
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
    return _drop(going.values())


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
                sweep_kept_media_quietly()
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
