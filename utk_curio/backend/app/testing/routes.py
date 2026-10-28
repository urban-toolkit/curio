"""Dev-only HTTP stubs for Playwright E2E tests.

Instead of driving the signup form through the browser, a test fixture POSTs
to ``/api/testing/stub-login`` to create (or fetch) a user + session, then
installs the returned token as a cookie on the Playwright context so the next
navigation is already authenticated. ``/api/testing/stub-project`` seeds a
workflow row owned by that user so ``/projects`` has something to render.

``/api/testing/agent-script`` is the third stub and the newest: it is the
out-of-process door to the scripted LLM provider's reply queue, so an E2E test
can drive a real agent turn against the running backend without a key or a
network. See ``app/agents/testing_provider.py``.

The blueprint is registered by ``create_app`` in every non-production
environment (``CURIO_ENV != 'prod'``, see ``backend/config.py::_is_dev``), and
**every route in it additionally requires ``CURIO_TESTING``**.

Both factors are needed. ``CURIO_ENV`` defaults to ``"dev"``, so registration
alone would mount these on any deployment whose operator never set it, and
``stub-login`` issues a valid session for an arbitrary username with no
password. ``CURIO_TESTING`` is the deliberate "this process is a test rig"
signal: ``tests/conftest.py`` exports it at import time and the e2e harness
passes it to the server subprocess it starts, so both suites see the routes and
a normal ``curio.py start`` does not.

An app built with ``CURIO_TESTING`` also counts the requests it is serving
(``in_flight.py``), so ``reset-db`` can wait for the ones a test's closed page
left running before it deletes their user.
"""

from __future__ import annotations

import logging
import re
import shutil
import time
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request

from utk_curio.backend.app.common import record_clock
from utk_curio.backend import config
from utk_curio.backend.config import _is_dev, _is_testing
from utk_curio.backend.app.agents import service as agents_service
from utk_curio.backend.app.agents.infrastructure import testing_provider
from utk_curio.backend.extensions import db
from utk_curio.backend.app.testing.in_flight import REFUSAL, RESET_WAIT_SECONDS, InFlightRequests
from utk_curio.backend.app.users import repositories as user_repo
from utk_curio.backend.app.users import security
from utk_curio.backend.app.projects import services as project_services
from utk_curio.backend.app.projects.schemas import ProjectCreate
from utk_curio.backend.app.runs import jobs as run_jobs


testing_bp = Blueprint("testing", __name__, url_prefix="/api/testing")

log = logging.getLogger(__name__)


@testing_bp.before_request
def _guard():
    """Refuse with 404 unless this is a dev environment *and* a test run.

    Two factors, deliberately. ``_is_dev()`` alone is not a gate: ``CURIO_ENV``
    defaults to ``"dev"`` (see ``backend/config.py``), so an operator who never
    sets it gets these routes mounted on a real deployment. That matters more
    here than anywhere else in Curio, because ``stub-login`` below issues a
    valid session for an arbitrary username with no password, and ``reset-db``
    empties tables. Requiring ``CURIO_TESTING`` as well means the endpoints
    exist only when something deliberately said "this process is a test rig".

    ``tests/conftest.py`` exports ``CURIO_TESTING`` at import time and the e2e
    harness passes it to the server subprocess, so both suites are unaffected.

    A ``before_request`` returning a response rather than a per-handler
    ``abort(404)``: it covers every route in the blueprint including any added
    later. It was also written this way to walk past ``create_app``'s
    ``@app.errorhandler(Exception)``, which used to rewrite every
    ``HTTPException`` to a 500; that is fixed (#279) and ``abort(404)`` would
    now answer 404, but the blanket coverage is reason enough to keep it. Same
    reasoning as :func:`_scripted_guard` below.
    """
    if not _is_dev() or not _is_testing():
        return jsonify({"error": "not found"}), 404
    return None


#: Where an app built for a test rig keeps its :class:`InFlightRequests`.
_IN_FLIGHT = "curio.testing.in_flight"
#: Where a counted request keeps its token.
_IN_FLIGHT_TOKEN = "curio.testing.in_flight_token"
#: The liveness probe (``api/routes.py``), which says the backend is up. It
#: reads nothing a reset deletes, and a backend that is resetting is up.
_PROBE = "api.live"


def _count_request_in():
    """Count each request but the harness's own and the liveness probe, or
    refuse it while a reset runs.

    Refused rather than held: a request that arrives during a reset comes from
    a page whose test is over, and it would only run against the next test's
    empty database. The probe answers all the same: the shard isolation e2e
    asks it of the other shards, which reset between their own tests (#1171).
    """
    in_flight = current_app.extensions.get(_IN_FLIGHT)
    if in_flight is None or request.blueprint == testing_bp.name or request.endpoint == _PROBE:
        return None
    token = in_flight.enter(f"{request.method} {request.path}")
    if token is None:
        return jsonify({"error": REFUSAL}), 503
    request.environ[_IN_FLIGHT_TOKEN] = token
    return None


def _count_request_out(_exc=None):
    """Count a request out when it is done, a streamed answer included: a
    stream keeps its request open until it ends."""
    token = request.environ.pop(_IN_FLIGHT_TOKEN, None)
    in_flight = current_app.extensions.get(_IN_FLIGHT)
    if token is not None and in_flight is not None:
        in_flight.leave(token)


def _count_requests(state) -> None:
    """Give an app built for a test rig its request count.

    Decided once, when the blueprint is registered: ``CURIO_ENV`` defaults to
    dev, so a developer's own ``curio.py start`` mounts this blueprint too, and
    without ``CURIO_TESTING`` its requests must not pass through any of this.
    """
    if not _is_testing():
        return
    state.app.extensions[_IN_FLIGHT] = InFlightRequests()
    state.app.before_request(_count_request_in)
    state.app.teardown_request(_count_request_out)


testing_bp.record_once(_count_requests)


#: The only tables ``reset-db`` will empty. Ordered child-before-parent so the
#: deletes do not trip foreign keys.
_RESETTABLE_TABLES: tuple[str, ...] = (
    "exec_cache_entry",
    "dataflow_run_step",
    "dataflow_run",
    "project_editor",
    "project",
    "auth_attempt",
    "user_session",
    "user",
)


def _empty_spec() -> dict:
    """Default workflow spec used when a stub request omits ``spec``.

    Shape matches what ``FlowProvider`` / ``save_project`` expects when a
    brand-new workflow is persisted: an empty dataflow with no nodes or
    edges. Good enough for "/projects lists this project" assertions.

    The name belongs inside ``dataflow``, not beside it. A top-level ``name``
    with no ``dataflow.name`` is the footgun described in this suite's README:
    ``loadParsedTrill`` calls ``setWorkflowName(undefined)``, and the canvas's
    next save then posts ``name: undefined`` and is rejected. Kept alongside
    the inner one because ``execution/workflow_spec.py`` still reads the
    top-level field. Validated against ``docs/schemas/trill.v1.json`` by
    test_projects/test_trill_schema.py.
    """
    return {
        "name": "StubbedWorkflow",
        "dataflow": {
            "name": "StubbedWorkflow",
            "nodes": [],
            "edges": [],
            "task": "",
            "timestamp": 0,
            "provenance_id": "StubbedWorkflow",
        },
    }


@testing_bp.route("/<path:_ignored>", methods=["OPTIONS"])
@testing_bp.route("/", methods=["OPTIONS"], defaults={"_ignored": ""})
def testing_preflight(_ignored):
    return "", 204


@testing_bp.route("/stub-login", methods=["POST"])
def stub_login():
    """Create-or-find a user + issue a session token.

    Body (JSON):
      * ``username`` – required; looked up first, created if missing.
      * ``name`` – display name, required when creating.
      * ``password`` – optional; used only when *creating* the user, so the
        normal ``/api/auth/signin`` form works for the same account in
        follow-up test steps. It is never applied to an account that already
        exists: rewriting a stored hash from an unauthenticated endpoint is an
        account takeover, and no test needs it.
      * ``email`` – optional.

    Response: same shape as ``/api/auth/signup`` / ``/api/auth/signin``
    (``{"user": {...}, "token": "..."}``). Callers install ``token`` as the
    ``session_token`` cookie and the SPA is immediately authenticated.
    """
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    name = (body.get("name") or "").strip() or username
    password = body.get("password") or None
    email = body.get("email") or None
    if not username:
        return jsonify({"error": "username is required"}), 400

    user = user_repo.user_by_identifier(username)
    created = False
    if user is None:
        user = user_repo.create_user(
            username=username,
            name=name,
            email=email,
            password_hash=(
                security.hash_password(password) if password else None
            ),
            type="programmer",
        )
        created = True

    session = user_repo.create_session(user.id)
    return (
        jsonify(
            {
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "name": user.name,
                    "email": user.email,
                    "profile_image": user.profile_image,
                    "type": user.type,
                    "is_guest": user.is_guest,
                },
                "token": session.token,
                "created": created,
            }
        ),
        200,
    )


@testing_bp.route("/dataset-paths", methods=["POST"])
def dataset_paths():
    """Resolve ``curio_data_path("<id>")`` calls the way execution does.

    For the e2e ground-truth harness. It computes each workflow's expected
    output by POSTing node code straight to the sandbox's ``/exec`` (bypassing
    the backend on purpose, so the comparison is independent and DuckDB keeps a
    single writer), which means it also has to supply the ``dataset_paths``
    mapping ``/processPythonCode`` would normally attach.

    It used to build that mapping itself, by scanning the committed
    ``datasets/`` tree in the *pytest process*. That works only while the
    sandbox shares a filesystem with the test runner. Under
    ``CURIO_E2E_USE_EXISTING`` against a compose stack it does not: the harness
    sent host paths like ``/home/runner/work/curio/curio/datasets/...`` to a
    sandbox that sees the same files at ``/app/datasets/...``, and every
    example whose loader resolves a dataset by id died on FileNotFoundError.

    Resolving here fixes that by construction — the answer is computed in the
    process that shares a filesystem with the sandbox — and it reuses
    ``node_exec.resolve_dataset_paths``, so the harness and the real execution
    path cannot drift.

    Body (JSON):
      * ``code`` – node source to scan for literal ``curio_load_data`` /
        ``curio_data_path`` / ``curio_load_collection`` calls.
      * ``username`` – optional; resolve as this user, for ids that live in an
        account store. Omitted means hub datasets only, which is what the
        curated examples use. Ignored without sign-in (``CURIO_NO_AUTH``),
        where the browser runs every node as the shared guest.
      * ``dataflow_id`` – optional, forwarded to the catalog listing.
      * ``nodeType``: optional, the node's type, for ``packageModules``.

    Response: ``{"paths": {"<id>": "<absolute path>"}, "formats": {...},
    "collections": {...}, "mediaDir": ..., "models": {...},
    "packageModules": ...}``: ``formats`` as
    ``/processPythonCode`` sends them for ``curio_load_data``, ``collections``
    and ``mediaDir`` as ``resolve_exec_collections`` gives them for
    ``curio_load_collection`` calls, ``models`` as ``node_exec.resolve_models_for``
    does for ``curio_load_model`` calls, from that user's package store,
    ``packageModules`` as
    ``node_exec.resolve_package_modules`` does for the node's package, as
    that user or the shared guest. Ids that do not resolve are simply absent,
    matching production's fail-open behaviour.
    """
    from flask import g

    from utk_curio.backend.app.discovery.application.exec_collections import (
        resolve_exec_collections,
    )
    from utk_curio.backend.app.execution.node_exec import (
        resolve_dataset_paths,
        resolve_models_for,
        resolve_package_modules,
    )
    from utk_curio.backend.app.common.user_storage import GUEST_KEY
    from utk_curio.backend.app.projects.services import _user_dir_key

    body = request.get_json(silent=True) or {}
    code = body.get("code") or ""
    if not isinstance(code, str):
        return jsonify({"error": "code must be a string"}), 400

    username = (body.get("username") or "").strip()
    # Without sign-in every request the browser makes is the shared guest's,
    # whichever account a test created, so that is whom execution resolves as.
    if config.CURIO_NO_AUTH:
        username = ""
    g.user = user_repo.user_by_identifier(username) if username else None

    formats: dict = {}
    paths = resolve_dataset_paths(code, body.get("dataflow_id"), g.user, formats)
    user_key = _user_dir_key(g.user) if g.user is not None else GUEST_KEY
    collections, media_dir = resolve_exec_collections(code, user_key, user=g.user)
    models = resolve_models_for(code, user_key)
    package_modules = resolve_package_modules(body.get("nodeType"), user_key, body.get("dataflow_id"))
    return jsonify({
        "paths": paths, "formats": formats, "collections": collections, "mediaDir": media_dir,
        "models": models, "packageModules": package_modules,
    }), 200


def _clear_test_user_stores() -> list[str]:
    """Delete the on-disk trees that :func:`reset_db`'s truncate would orphan.

    The work lives in ``common.user_storage.clear_test_stores`` so the e2e
    harness's own truncate path can call it without going through HTTP (#308);
    see its docstring for why leaving the stores behind is a trap.

    The blueprint guard already requires ``CURIO_TESTING``, but this deletes
    user data, so it re-checks rather than trusting a caller to have been
    routed correctly.
    """
    from utk_curio.backend.app.common.user_storage import clear_test_stores

    if not _is_testing():  # pragma: no cover - the blueprint guard precedes us
        return []
    return clear_test_stores()


def _job_name(job) -> str:
    """An agent job as a reset names it: its kind and execution id."""
    return f"{job.kind} {job.job_id}"


def _wait_for_jobs(jobs: list, timeout: float) -> list[str]:
    """Wait up to *timeout* seconds for *jobs* to end, and name those still
    running."""
    deadline = time.monotonic() + timeout
    for job in jobs:
        if job.thread is not None:
            job.thread.join(max(deadline - time.monotonic(), 0.0))
    return sorted(_job_name(job) for job in jobs if job.live)


@testing_bp.route("/reset-db", methods=["POST"])
def reset_db():
    """Truncate mutable tables so the next test starts with a clean slate.

    Called by the ``e2e_clean_db`` fixture over HTTP when the test process
    cannot reach the backend's sqlite file directly (e.g.
    ``CURIO_E2E_USE_EXISTING=1`` pointing at a separately-started server
    whose DB path differs from what ``conftest.py`` resolves).

    Body (JSON, all optional):
      * ``tables`` – subset of the mutable set to truncate. Anything outside
        that set is refused rather than executed: the name goes into raw SQL,
        and "which tables may a test wipe" is a decision for this module, not
        for the request body.
      * ``stores`` – default ``true``. Also delete the per-user files under
        ``.curio/test/``, which the truncate would otherwise orphan onto the
        ids it is about to free. Pass ``false`` only to inspect what a previous
        test left behind; a test that skips it is asking to inherit it.

    Before it deletes anything, it refuses new requests but the liveness probe
    (503) and waits, up to ``RESET_WAIT_SECONDS``, for the ones already
    running, so none of them outlives its user (``in_flight.py``). One still
    running after that is named in ``still_running`` and in the log, and the
    reset goes ahead.

    The agent jobs still running are stopped first, as the user's Stop does,
    and waited for within the same bound: a Solve session keeps making passes
    until its deadline, so the test that started one can end with it running,
    and its calls would take the replies the next test scripts. One still
    running after the wait is named in ``agent_jobs_still_running``.

    Response: ``{"truncated": [...], "stores_cleared": [...], "waited_for":
    [...], "waited_seconds": n, "still_running": [...], "agent_jobs": [...],
    "agent_jobs_still_running": [...]}``, each request named by its method and
    path, each agent job by its kind and execution id.
    """
    body = request.get_json(silent=True) or {}
    requested = body.get("tables")
    if requested is None:
        tables = list(_RESETTABLE_TABLES)
    else:
        if not isinstance(requested, list):
            return jsonify({"error": "tables must be a list"}), 400
        unknown = [t for t in requested if t not in _RESETTABLE_TABLES]
        if unknown:
            return (
                jsonify(
                    {
                        "error": f"not resettable: {', '.join(map(str, unknown))}",
                        "allowed": list(_RESETTABLE_TABLES),
                    }
                ),
                400,
            )
        tables = requested

    in_flight = current_app.extensions.get(_IN_FLIGHT) or InFlightRequests()
    waited_for = in_flight.close()
    try:
        # A hold a failed test left standing would stop the next test's runs,
        # and a held run's stream would hold this reset for the whole wait.
        run_jobs.set_hold(False)
        # Stopped before the wait: a page's stream of a job is a request in
        # flight until the job ends.
        stopped_jobs = agents_service.stop_agent_jobs()
        if waited_for:
            log.info("reset-db waits for %d request(s) in flight: %s",
                     len(waited_for), ", ".join(waited_for))
        if stopped_jobs:
            log.info("reset-db stops %d agent job(s): %s",
                     len(stopped_jobs), ", ".join(map(_job_name, stopped_jobs)))
        started = time.monotonic()
        still_running = in_flight.drain(RESET_WAIT_SECONDS)
        jobs_still_running = _wait_for_jobs(
            stopped_jobs, RESET_WAIT_SECONDS - (time.monotonic() - started),
        )
        waited_seconds = round(time.monotonic() - started, 3)
        if still_running:
            log.warning("reset-db waited %.1f s and resets under %d request(s) still running: %s",
                        waited_seconds, len(still_running), ", ".join(still_running))
        elif waited_for:
            log.info("reset-db waited %.2f s for %s", waited_seconds, ", ".join(waited_for))
        if jobs_still_running:
            log.warning("reset-db waited %.1f s and resets under %d agent job(s) still running: %s",
                        waited_seconds, len(jobs_still_running), ", ".join(jobs_still_running))

        truncated = []
        for table in tables:
            try:
                db.session.execute(db.text(f'DELETE FROM "{table}"'))
                truncated.append(table)
            except Exception:
                pass
        db.session.commit()

        stores_cleared = []
        if body.get("stores", True):
            stores_cleared = _clear_test_user_stores()
        # A clock a failed test left set would date the next test's records.
        record_clock.set_now(None)
    finally:
        in_flight.open()
    return jsonify({
        "truncated": truncated,
        "stores_cleared": stores_cleared,
        "waited_for": waited_for,
        "waited_seconds": waited_seconds,
        "still_running": still_running,
        "agent_jobs": sorted(map(_job_name, stopped_jobs)),
        "agent_jobs_still_running": jobs_still_running,
    }), 200


@testing_bp.route("/run-hold", methods=["GET", "POST"])
def run_hold():
    """Hold runs on the server before each node they execute, or release them.

    The server-side twin of holding a page's node requests (``run_all.py``): a
    run started by the canvas executes on the server, out of the page's reach.

    Body (POST): ``{"hold": true}`` or ``{"hold": false}``.
    Response: ``{"held": bool, "waiting": n}``. ``waiting`` is how many nodes
    wait right now; on a release, how many it let go.
    """
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        if not isinstance(body.get("hold"), bool):
            return jsonify({"error": "hold must be true or false"}), 400
        waiting = run_jobs.set_hold(body["hold"])
        return jsonify({"held": body["hold"], "waiting": waiting}), 200
    return jsonify(run_jobs.hold_state()), 200


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


@testing_bp.route("/clock", methods=["POST", "DELETE"])
def clock():
    """Set the clock catalog records are stamped with (``common/record_clock.py``).

    The server-side twin of Playwright's page clock: an e2e test that
    photographs catalog ages runs its browser on a fixed date, and this puts
    the records it makes on the same date, so they read "1m ago" beside the
    shipped items' fixed dates.

    Body (POST): ``{"now": "<ISO 8601 time with a zone>"}``. The clock reads
    that time now and runs on from it. ``DELETE`` puts it back on the system
    clock, as ``reset-db`` does.
    Response: ``{"now": "<the record clock's time>"}``.
    """
    if request.method == "DELETE":
        record_clock.set_now(None)
        return jsonify({"now": _iso(record_clock.utc_now())}), 200
    body = request.get_json(silent=True) or {}
    raw = body.get("now")
    try:
        moment = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        moment = None
    if moment is None or moment.tzinfo is None:
        return jsonify({"error": "now must be an ISO 8601 time with a zone"}), 400
    record_clock.set_now(moment.astimezone(timezone.utc))
    return jsonify({"now": _iso(record_clock.utc_now())}), 200


@testing_bp.route("/stub-project", methods=["POST"])
def stub_project():
    """Seed a project owned by an existing stub user.

    Body (JSON):
      * ``username`` – required; must already exist (use ``/stub-login``
        first).
      * ``name`` – project display name, defaults to ``"StubbedWorkflow"``.
      * ``spec`` – optional dataflow spec; defaults to an empty workflow.
      * ``description`` / ``thumbnail_accent`` – optional pass-throughs.

    Response: ``ProjectSummary``-shaped JSON for the newly created row.
    """
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    if not username:
        return jsonify({"error": "username is required"}), 400

    user = user_repo.user_by_identifier(username)
    if user is None:
        return jsonify({"error": f"unknown user {username!r}"}), 404

    name = body.get("name") or "StubbedWorkflow"
    spec = body.get("spec") or _empty_spec()
    data = ProjectCreate(
        name=name,
        spec=spec,
        description=body.get("description"),
        thumbnail_accent=body.get("thumbnail_accent") or "peach",
    )
    detail = project_services.save_project(user, data)
    return (
        jsonify(
            {
                "id": detail.id,
                "name": detail.name,
                "slug": detail.slug,
                "description": detail.description,
                "thumbnail_accent": detail.thumbnail_accent,
            }
        ),
        201,
    )


# ── scripted agent turns (see app/agents/testing_provider.py) ────────────────
#
# The scripted provider's FIFO lives in the backend process, so an in-process
# pytest can call push_replies directly. The E2E suite cannot: it drives a
# separate ``curio.py start`` subprocess. These three endpoints are that queue's
# door, and they are the reason an agent turn is testable end to end without a
# key, a network, or a model that answers differently twice.
#
# Guarded twice over: out of production like every other route here, AND off a
# developer's ordinary dev server, because unlike stub-login these read prompt
# text back out of the process.


def _scripted_guard():
    """A 404 response when these routes must not exist, else ``None``.

    Returns the response rather than ``abort(404)``, matching :func:`_guard`.
    The original reason was that ``create_app``'s ``@app.errorhandler(Exception)``
    rewrote every ``HTTPException`` to a 500; since #279 an ``HTTPException``
    keeps its own code, so either form would answer 404 now. Left as-is because
    the two guards should look alike.
    """
    if not _is_dev() or not testing_provider.enabled():
        return jsonify({"error": "not found"}), 404
    return None


#: A scripted node id has the shape of the uuid4 the server would mint.
_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _reply_entry_error(entry: object) -> str | None:
    """Why *entry* is not a scripted reply, or None when it is one: a string,
    ``{text, toolCalls}`` or ``{error, status}``."""
    if isinstance(entry, str):
        return None
    if not isinstance(entry, dict):
        return "each reply must be a string or an object"
    if "error" in entry:
        if set(entry) - {"error", "status"}:
            return "an error reply takes only 'error' and 'status'"
        if not isinstance(entry["error"], str) or not isinstance(entry.get("status", 500), int):
            return "an error reply is {'error': <string>, 'status': <int>}"
        return None
    if set(entry) - {"text", "toolCalls"}:
        return "a reply object takes only 'text' and 'toolCalls'"
    if not isinstance(entry.get("text", ""), str):
        return "'text' must be a string"
    calls = entry.get("toolCalls", [])
    if not isinstance(calls, list):
        return "'toolCalls' must be a list"
    for call in calls:
        if not (
            isinstance(call, dict)
            and not set(call) - {"name", "arguments", "id"}
            and isinstance(call.get("name"), str) and call["name"]
            and isinstance(call.get("arguments", {}), dict)
            and isinstance(call.get("id", ""), str)
        ):
            return "each tool call is {'name': <string>, 'arguments': <object>, 'id': <string, optional>}"
    return None


@testing_bp.route("/agent-script", methods=["POST"])
def agent_script_push():
    """Queue scripted replies for the next agent turns.

    Body (JSON):
      * ``replies`` - list of replies, consumed in order, one per provider
        call. A multi-round run (a tool call and its follow-up) needs one entry
        per round. A reply is its text, ``{"text", "toolCalls"}`` for native
        tool calls (each ``{"name", "arguments", "id"}``, ``id`` optional), or
        ``{"error", "status"}`` for an endpoint error (see
        ``testing_provider``).
      * ``byIntent`` - optional ``{substring: reply}``. A delegated call whose
        ``intent`` contains a key gets that reply instead of the next queued
        one (see ``testing_provider.route_by_intent``).
      * ``chatCapabilities`` - optional ``{tools, structuredOutput}``: what the
        scripted endpoint can do beyond text. ``{"tools": true}`` puts runs on
        native tools; without it they use the fenced protocol.
      * ``nodeIds`` - optional list of uuids: the ids the next nodes an apply
        creates are given, in order (``testing_provider.push_node_ids``).
      * ``reset`` - drop anything queued and captured first. Defaults to true,
        which is what a test almost always wants: a leftover reply from a
        previous test would be consumed by this one and the failure would point
        anywhere but at the cause.

    Response: ``{"pending": n}``
    """
    denied = _scripted_guard()
    if denied is not None:
        return denied
    body = request.get_json(silent=True) or {}
    replies = body.get("replies")
    if replies is None:
        replies = []
    if not isinstance(replies, list):
        return jsonify({"error": "'replies' must be a list"}), 400
    for entry in replies:
        problem = _reply_entry_error(entry)
        if problem:
            return jsonify({"error": problem}), 400
    by_intent = body.get("byIntent") or {}
    if not isinstance(by_intent, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in by_intent.items()
    ):
        return jsonify({"error": "'byIntent' must map strings to strings"}), 400
    capabilities = body.get("chatCapabilities")
    if capabilities is not None and not (
        isinstance(capabilities, dict)
        and not set(capabilities) - {"tools", "structuredOutput"}
        and all(isinstance(v, bool) for v in capabilities.values())
    ):
        return jsonify({"error": "'chatCapabilities' is {'tools': <bool>, 'structuredOutput': <bool>}"}), 400
    node_ids = body.get("nodeIds") or []
    if not isinstance(node_ids, list) or not all(
        isinstance(n, str) and _UUID_RE.fullmatch(n) for n in node_ids
    ):
        return jsonify({"error": "'nodeIds' must be a list of uuids"}), 400
    if body.get("reset", True):
        testing_provider.reset()
    testing_provider.push_replies(*replies)
    testing_provider.push_node_ids(*node_ids)
    if by_intent:
        testing_provider.route_by_intent(by_intent)
    if capabilities is not None:
        testing_provider.script_chat_capabilities(
            tools=capabilities.get("tools", False),
            structured_output=capabilities.get("structuredOutput", False),
        )
    return jsonify({"pending": testing_provider.pending()}), 200


@testing_bp.route("/agent-script", methods=["GET"])
def agent_script_read():
    """What the scripted provider was asked, and what is still queued.

    ``captured`` is one entry per provider call since the last reset, each the
    OpenAI-style ``[{"role", "content"}, ...]`` list the run composed. A
    per-agent test asserts against it that the system turn really carried that
    agent's own instruction bytes - which a reply, being scripted, can never
    show.

    ``calls`` holds ``{configId, model}`` for each of those calls: which LLM
    configuration answered it. ``offered`` holds ``{tools, toolChoice}`` for
    each: the native tools it offered, none on the fenced protocol.

    Response: ``{"pending": n, "captured": [[{role, content}, ...], ...],
    "calls": [{configId, model}, ...], "offered": [{tools, toolChoice}, ...]}``
    """
    denied = _scripted_guard()
    if denied is not None:
        return denied
    return (
        jsonify(
            {
                "pending": testing_provider.pending(),
                "captured": testing_provider.captured(),
                "calls": testing_provider.calls(),
                "offered": testing_provider.offered(),
            }
        ),
        200,
    )


@testing_bp.route("/agent-script", methods=["DELETE"])
def agent_script_reset():
    """Drop the queue and the capture log. ``{"pending": 0}``."""
    denied = _scripted_guard()
    if denied is not None:
        return denied
    testing_provider.reset()
    return jsonify({"pending": testing_provider.pending()}), 200


#: The default identity of the fake distribution :func:`broken_library` mints.
#: A name no index carries, so a stray ``pip install`` of it can only fail —
#: nothing here should ever reach a network, and a name collision would make
#: that hard to notice.
_BROKEN_LIB_NAME = "brokenlib"
_BROKEN_LIB_VERSION = "9.9.9"
_BROKEN_LIB_REASON = (
    "DLL load failed while importing _base: The specified procedure could not "
    "be found."
)


def _broken_lib_root():
    """Where the fake distributions live — inside the test rig's state tree."""
    from utk_curio.backend.app.common.user_storage import curio_root

    return curio_root() / "broken-libs"


@testing_bp.route("/broken-library", methods=["POST"])
def broken_library():
    """Make a library that pip considers installed, and python cannot import.

    This is the bug class the import probe exists for, and it is the one an
    E2E test cannot otherwise stage. pip reports a requirement satisfied from
    ``importlib.metadata`` alone, so a wheel whose native extension will not
    load — a rasterio built against a different GDAL is the everyday case —
    records a perfectly good version, installs "successfully", and raises the
    first time a node touches it. Every layer above reads pip's exit code as
    success.

    Reproduced here as a distribution with valid metadata over a module that
    raises on import. Byte-for-byte the same shape as the real thing, and
    deterministic and offline, which a genuinely broken wheel is not: the
    install path finds the version satisfied and SKIPS pip entirely, so nothing
    in this reaches an index.

    It lives in this process rather than in the harness because that is where
    the question is asked. ``pip_runner`` probes in a subprocess of the backend,
    so the fake has to be on the backend's ``sys.path`` (for the metadata read)
    and its ``PYTHONPATH`` (for the child that attempts the import) — neither of
    which a pytest process can reach, still less one talking to a container.
    Same reason ``dataset-paths`` and ``package-store`` resolve here.

    Body (JSON):
      * ``action``  – ``"install"`` mints it, ``"remove"`` takes it away.
      * ``name``    – distribution name; defaults to ``brokenlib``.
      * ``version`` – defaults to ``9.9.9``.
      * ``reason``  – the ImportError text; defaults to the DLL-load wording.

    Answers ``{"name", "version", "path", "versionSatisfied", "importError"}``
    so a caller can assert the premise — pip WOULD skip this, and the import
    DOES fail — before asserting anything about a user-facing surface.
    """
    import importlib
    import importlib.util
    import os
    import sys

    from utk_curio.backend.app.packages.infrastructure import pip_runner

    body = request.get_json(silent=True) or {}
    action = (body.get("action") or "install").strip()
    name = (body.get("name") or _BROKEN_LIB_NAME).strip()
    version = (body.get("version") or _BROKEN_LIB_VERSION).strip()
    reason = body.get("reason") or _BROKEN_LIB_REASON

    if action not in ("install", "remove"):
        return jsonify({"error": "action must be 'install' or 'remove'"}), 400
    # The name becomes a directory and a module filename, so keep it to the
    # shape a distribution name actually has.
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,40}", name):
        return jsonify({"error": f"invalid name: {name!r}"}), 400
    if not re.fullmatch(r"[0-9][0-9A-Za-z.]{0,20}", version):
        return jsonify({"error": f"invalid version: {version!r}"}), 400

    root = _broken_lib_root()

    if action == "remove":
        # Only what this call names. The API invites naming a distribution, so
        # removing one must not silently take away the others a test staged.
        targets = [root / f"{name}.py", *root.glob(f"{name}-*.dist-info")]
        # Importing the fake leaves compiled bytecode behind, and a stale
        # __pycache__ entry both outlives the source and keeps the directory
        # non-empty, which is how the path stayed on sys.path after a removal.
        targets += list(root.glob(f"__pycache__/{name}.*.pyc"))
        for path in targets:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            elif path.is_file():
                path.unlink()
        remaining = sorted(
            p.name for p in root.glob("*") if p.name != "__pycache__"
        ) if root.is_dir() else []
        if not remaining:
            shutil.rmtree(root, ignore_errors=True)
            _drop_from_import_path(str(root))
        importlib.invalidate_caches()
        pip_runner.forget_import_probes()
        return jsonify({"name": name, "removed": True, "remaining": remaining}), 200

    # Checked here rather than beside the other input validation, because it is
    # only true of `install`: by the time a test removes what it staged, the
    # name resolves precisely because this route made it resolve.
    #
    # A name that ALREADY resolves would not be a fake broken library, it would
    # be a real broken one: the module lands in a directory that goes on
    # sys.path[0] and on PYTHONPATH, so `{"name": "json"}` makes every probe
    # child and every pip child this backend spawns die on startup, and the
    # import failures the suite then reports are its own doing.
    if name in sys.stdlib_module_names or importlib.util.find_spec(name) is not None:
        return jsonify({
            "error": f"{name!r} already resolves; staging it would shadow a real "
                     f"module for this backend and every process it spawns",
        }), 400

    info = root / f"{name}-{version}.dist-info"
    info.mkdir(parents=True, exist_ok=True)
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
        encoding="utf-8",
    )
    (info / "top_level.txt").write_text(f"{name}\n", encoding="utf-8")
    # The module raises rather than being absent, because "absent" is a
    # different bug with a different remedy: pip would reinstall it.
    (root / f"{name}.py").write_text(
        f"raise ImportError({reason!r})\n", encoding="utf-8",
    )

    path = str(root)
    if path not in sys.path:
        sys.path.insert(0, path)
    existing = os.environ.get("PYTHONPATH")
    if not existing or path not in existing.split(os.pathsep):
        os.environ["PYTHONPATH"] = (
            f"{path}{os.pathsep}{existing}" if existing else path
        )
    # The metadata finder caches directory listings, and the probe memoises per
    # (distribution, version) — both would otherwise answer from before this.
    importlib.invalidate_caches()
    pip_runner.forget_import_probes()

    return jsonify({
        "name": name,
        "version": version,
        "path": path,
        # The premise, measured rather than asserted: pip is satisfied ...
        "versionSatisfied": pip_runner.is_satisfied(name, ""),
        # ... and the import is not.
        "importError": pip_runner.import_failures([name]).get(name),
    }), 200


def _drop_from_import_path(path: str) -> None:
    """Take *path* back off ``sys.path`` and ``PYTHONPATH``."""
    import os
    import sys

    while path in sys.path:
        sys.path.remove(path)
    existing = os.environ.get("PYTHONPATH")
    if existing:
        # Empty entries are preserved: CPython reads one as the launch cwd, so
        # dropping it would quietly change what every child can import - a
        # side effect of a teardown, felt only by whatever runs next.
        kept = [p for p in existing.split(os.pathsep) if p != path]
        if any(kept):
            os.environ["PYTHONPATH"] = os.pathsep.join(kept)
        else:
            os.environ.pop("PYTHONPATH", None)


#: Saved on the first override so ``normal`` can put them back. Module-level
#: because the override outlives the request that set it — that is the point:
#: the install it has to affect happens in a LATER request.
_PIP_ORIGINALS: dict = {}

#: What each mode makes pip do. The messages are fixed so a test can assert on
#: them without depending on an index, a network or a pip version.
_PIP_MODES = ("normal", "install-error", "spec-error", "probe-error")


@testing_bp.route("/pip-behaviour", methods=["POST"])
def pip_behaviour():
    """Make this backend's pip fail on purpose, deterministically.

    The install seam has three answers, and only one of them can be staged from
    outside the server. "The library installed and does not import" has
    ``/api/testing/broken-library``; "pip itself failed" and "the probe could
    not run" have nothing, because both live in a subprocess the backend spawns
    and neither can be provoked offline — an unreachable index produces a
    different message every time, and on a machine with a warm wheel cache it
    may not fail at all.

    So they are staged here, in the process that owns them, for the same reason
    ``dataset-paths`` and ``package-store`` resolve here: a pytest process (or
    one talking to a container) cannot reach into this one.

    Body: ``{"mode": "normal" | "install-error" | "spec-error" | "probe-error"}``

      * ``install-error`` — ``install_python_deps`` raises ``PipInstallError``,
        the shape of pip exiting non-zero.
      * ``spec-error`` — it raises ``PipSpecError``, the shape of a requirement
        pip's grammar rejects. A different answer from the caller's side (400
        rather than 502), which is the distinction worth holding.
      * ``probe-error`` — both import probes raise, so the diagnostic is the
        thing that is broken. The install must still succeed and must not
        report a clean bill of health it did not earn.
      * ``normal`` — put the real functions back.

    Overriding is idempotent and always restores from the ORIGINALS captured on
    the first call, so repeated or interleaved modes cannot stack wrappers.
    """
    from utk_curio.backend.app.packages.infrastructure import pip_runner

    body = request.get_json(silent=True) or {}
    mode = (body.get("mode") or "normal").strip()
    if mode not in _PIP_MODES:
        return jsonify({"error": f"mode must be one of {list(_PIP_MODES)}"}), 400

    if not _PIP_ORIGINALS:
        _PIP_ORIGINALS.update({
            "install_python_deps": pip_runner.install_python_deps,
            "import_failures": pip_runner.import_failures,
            "import_failures_in": pip_runner.import_failures_in,
        })

    for name, original in _PIP_ORIGINALS.items():
        setattr(pip_runner, name, original)

    if mode == "install-error":
        def _fail(deps, on_line=None):
            raise pip_runner.PipInstallError(
                "ERROR: Could not find a version that satisfies the requirement")
        pip_runner.install_python_deps = _fail
    elif mode == "spec-error":
        def _bad_spec(deps, on_line=None):
            raise pip_runner.PipSpecError(
                "'>= 1.26' is not a valid version constraint for 'numpy'")
        pip_runner.install_python_deps = _bad_spec
    elif mode == "probe-error":
        def _no_probe(*a, **kw):
            raise OSError("no subprocesses here")
        pip_runner.import_failures = _no_probe
        pip_runner.import_failures_in = _no_probe

    pip_runner.forget_import_probes()
    return jsonify({"mode": mode}), 200


@testing_bp.route("/package-store", methods=["POST"])
def package_store():
    """Read or perturb one file in a user's package store.

    For the #194 delivery regression. A fix can ship inside a package at an
    unchanged version, and the question that test asks is whether an existing
    install picks it up — which means the test has to make a store copy stale
    and then read it back. Neither is possible from the pytest process when the
    stack runs in a container, because it does not share that filesystem. So it
    happens here, in the process that does, for the same reason ``dataset-paths``
    resolves paths here rather than in the harness.

    Body (JSON):
      * ``username`` – required; whose store to act on.
      * ``dirName``  – required; ``<packageId>@<major>``, validated.
      * ``action``   – ``"hash"`` reads, ``"stale"`` perturbs.
      * ``path``     – file inside the package, POSIX-relative.
                       Defaults to ``manifest.json``.

    ``hash`` answers ``{"sha256": "...", "catalog_sha256": "..."}`` so a caller
    can compare the store copy against the catalog it came from in one call.
    ``stale`` appends a marker byte to the file and records the result as the
    copy the catalog installed, then answers the same shape, after which the
    two hashes differ.

    Every action runs under the store lock the seeder swaps under, so a seeding
    pass lands before or after it and the answer describes the copy the action
    left.
    """
    import hashlib

    from utk_curio.backend.app.packages.infrastructure.locks import package_seed_lock
    from utk_curio.backend.app.packages.repositories import seed_state
    from utk_curio.backend.app.packages.repositories.catalog_dir import catalog_root as _catalog_root
    from utk_curio.backend.app.packages.service import (
        PACKAGE_DIR_RE,
        package_dir,
    )
    from utk_curio.backend.app.projects.services import _user_dir_key

    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    dir_name = (body.get("dirName") or "").strip()
    action = (body.get("action") or "hash").strip()
    rel = (body.get("path") or "manifest.json").strip()

    if not username or not dir_name:
        return jsonify({"error": "username and dirName are required"}), 400
    if not PACKAGE_DIR_RE.match(dir_name):
        return jsonify({"error": f"invalid dirName: {dir_name!r}"}), 400
    if action not in ("hash", "stale", "reset"):
        return jsonify({"error": "action must be 'hash', 'stale' or 'reset'"}), 400
    # Narrow the writable surface by hand: this route can only ever touch a
    # file INSIDE one validated package directory.
    if not rel or rel.startswith("/") or ".." in rel.split("/"):
        return jsonify({"error": f"invalid path: {rel!r}"}), 400

    user = user_repo.user_by_identifier(username)
    if user is None:
        return jsonify({"error": f"no such user: {username}"}), 404

    store_key = _user_dir_key(user)
    try:
        store_root = package_dir(store_key, dir_name)
    except Exception as exc:  # noqa: BLE001 — traversal guard etc.
        return jsonify({"error": str(exc)}), 400

    def _sha256(path):
        h = hashlib.sha256()
        h.update(path.read_bytes())
        return h.hexdigest()

    # The lock every other reader and writer of the store holds (memo dev/99).
    # The page's own requests run seeding passes: one landing between the
    # plant's record and its read-back would refresh the planted copy and the
    # plant would answer the catalog's hash, and a read could fall between a
    # swap's two renames.
    with package_seed_lock(store_key):
        if action == "reset":
            # Drop the store copy so the next install is a true first install.
            #
            # A test cannot get this by using a fresh username. The store is keyed
            # by user ID, and the e2e harness truncates the ``user`` table between
            # tests, so SQLite reissues low ids and a brand-new account inherits
            # whatever the last occupant of that id left on disk, including, for
            # this test, a deliberately damaged file. That is the hazard the recheck
            # logged as F6; until it is fixed at the source, a test that needs a
            # known starting state has to say so explicitly.
            import shutil

            if store_root.is_dir():
                shutil.rmtree(store_root, ignore_errors=True)
            seed_state.clear(store_key, dir_name)
            return jsonify({"reset": dir_name, "present": store_root.is_dir()}), 200

        target = store_root / rel
        if not target.is_file():
            return jsonify({"error": f"not in the store: {dir_name}/{rel}"}), 404

        if action == "stale":
            from utk_curio.backend.app.packages.repositories.archive import refresh_package_integrity

            # A marker byte rather than a rewrite: the file stays valid for anything
            # that only parses it, so the ONLY thing this changes is the hash.
            with open(target, "ab") as fh:
                fh.write(b"\n// stale-marker\n")
            # ...and then rewrite the store copy's own integrity.json to match.
            #
            # This is what makes it an UPGRADE rather than a corruption, and the
            # distinction is the whole point. A real upgrade leaves the user's copy
            # internally consistent: its files and its integrity map agree, they
            # are simply an older pair than the catalog's. Perturbing the file alone
            # leaves the store's map still quoting the original hash, so it matches
            # the catalog's map and the refresh correctly declines to act: the copy
            # is damaged, not out of date, and repairing damage is a different job
            # (`_package_is_healthy`). Skipping this step made the first version of
            # this endpoint simulate the wrong thing entirely.
            #
            # ...and record that older pair as the copy the catalog installed,
            # which is what an upgrade leaves behind. Clearing the record instead
            # made the copy look like one from before the record existed, and a
            # copy recorded as the user's own is never refreshed at all (#564).
            integrity = refresh_package_integrity(store_root)
            seed_state.mark_installed(
                store_key, dir_name, catalog_copy=seed_state.copy_digest(integrity),
            )

        catalog_file = _catalog_root() / dir_name / rel
        answer = {
            "sha256": _sha256(target),
            "catalog_sha256": _sha256(catalog_file) if catalog_file.is_file() else None,
            "path": rel,
            "dirName": dir_name,
        }
    return jsonify(answer), 200


#: The pip settings ``wheelhouse`` overrides, with the values they had before
#: the first stage, so ``restore`` puts back exactly what was there: a variable
#: that was unset is removed again, not left empty. Module level, like
#: ``_PIP_ORIGINALS``: the install it has to reach happens in a LATER request.
_WHEELHOUSE_ENV_KEYS = ("PIP_NO_INDEX", "PIP_FIND_LINKS", "PIP_DISABLE_PIP_VERSION_CHECK")
_WHEELHOUSE_ENV_ORIGINALS: dict = {}

#: Staging uninstalls the distributions it stages from the interpreter every
#: sandbox of the stack imports from, so only a test library's name may reach
#: it: ``curio-wheelhouse-<name>``, a name no index carries.
_WHEELHOUSE_DIST_RE = re.compile(r"curio[-_.]wheelhouse[-_.][a-z0-9][a-z0-9_.-]{0,40}", re.IGNORECASE)
_WHEEL_FILE_RE = re.compile(
    r"(?P<dist>[A-Za-z0-9][A-Za-z0-9_.]*)-(?P<version>[0-9][0-9A-Za-z.]*)-py3-none-any\.whl"
)
#: A test wheel is a few hundred bytes.
_WHEEL_MAX_BYTES = 64 * 1024


def _wheelhouse_root():
    """Where the staged wheels live: inside the test rig's state tree."""
    from utk_curio.backend.app.common.user_storage import curio_root

    return curio_root() / "test-wheelhouse"


def _staged_dists() -> list[str]:
    """The distributions of the wheels in the wheelhouse, as their files name them."""
    root = _wheelhouse_root()
    if not root.is_dir():
        return []
    dists = []
    for path in sorted(root.glob("*.whl")):
        match = _WHEEL_FILE_RE.fullmatch(path.name)
        if match:
            dists.append(match.group("dist"))
    return dists


def _installed_map(dists) -> dict:
    """Whether pip's metadata holds each distribution, asked afresh."""
    import importlib

    from utk_curio.backend.app.packages.infrastructure import pip_runner

    # The metadata finder caches directory listings, and pip ran in a child.
    importlib.invalidate_caches()
    pip_runner.forget_import_probes()
    return {dist: pip_runner.is_satisfied(dist, "") for dist in dists}


@testing_bp.route("/wheelhouse", methods=["POST"])
def wheelhouse():
    """Make this backend's pip install from a local wheelhouse, and from nothing else.

    A package declares its libraries, and Curio installs them when the package
    is added, when a dataflow whose lockfile names it is opened, and at launch.
    A test of those installs has to run the real pip and stay offline. pip
    reads both from its environment (``PIP_NO_INDEX`` with ``PIP_FIND_LINKS``,
    as ``test_backend_runtime.py`` sets them), and only this process's
    environment reaches the pip it spawns, so the wheelhouse is staged here,
    for the same reason ``broken-library`` and ``package-store`` act here.

    Body (JSON):
      * ``action`` - ``"stage"``, ``"status"`` or ``"restore"``.
      * ``wheels`` - stage: ``[{"filename", "content"}]``, the content in
        base64, each a ``curio-wheelhouse-*`` distribution.
      * ``names``  - status: the distributions to ask about.

    ``stage`` writes the wheels, points pip at them with no index, and
    uninstalls any copy of their distributions an earlier run left, so the
    install a test then sets off is a real one. ``status`` and ``stage`` answer
    ``installed``, per distribution. ``restore`` puts pip's settings back,
    removes the wheelhouse and uninstalls what it held.
    """
    import base64
    import binascii
    import os

    from utk_curio.backend.app.packages.infrastructure import pip_runner

    body = request.get_json(silent=True) or {}
    action = (body.get("action") or "").strip()
    if action not in ("stage", "status", "restore"):
        return jsonify({"error": "action must be 'stage', 'status' or 'restore'"}), 400

    if action == "status":
        names = body.get("names")
        if not isinstance(names, list) or not names or not all(
            isinstance(name, str) and _WHEELHOUSE_DIST_RE.fullmatch(name) for name in names
        ):
            return jsonify({"error": "names must list curio-wheelhouse-* distributions"}), 400
        return jsonify({"installed": _installed_map(names)}), 200

    root = _wheelhouse_root()
    if action == "restore":
        staged = _staged_dists()
        # Settings first: whatever the uninstall below answers, no later pip in
        # this process may be left reading only a wheelhouse.
        for key, value in _WHEELHOUSE_ENV_ORIGINALS.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        _WHEELHOUSE_ENV_ORIGINALS.clear()
        shutil.rmtree(root, ignore_errors=True)
        pip_runner.uninstall_python_deps(staged)
        return jsonify({"restored": True, "installed": _installed_map(staged)}), 200

    wheels = body.get("wheels")
    if not isinstance(wheels, list) or not wheels:
        return jsonify({"error": "wheels must be a non-empty list"}), 400
    decoded: dict[str, bytes] = {}
    for wheel in wheels:
        wheel = wheel if isinstance(wheel, dict) else {}
        filename = str(wheel.get("filename") or "")
        match = _WHEEL_FILE_RE.fullmatch(filename)
        if not match or not _WHEELHOUSE_DIST_RE.fullmatch(match.group("dist")):
            return jsonify({"error": f"not a curio-wheelhouse-* wheel: {filename!r}"}), 400
        try:
            data = base64.b64decode(str(wheel.get("content") or ""), validate=True)
        except (binascii.Error, ValueError):
            return jsonify({"error": f"{filename}: the content is not base64"}), 400
        if not data or len(data) > _WHEEL_MAX_BYTES:
            return jsonify({"error": f"{filename}: {len(data)} bytes is not a test wheel"}), 400
        decoded[filename] = data

    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    for filename, data in decoded.items():
        (root / filename).write_bytes(data)
    dists = _staged_dists()
    # A copy an earlier run left would make pip answer "already satisfied", and
    # a test would pass over an install that never ran.
    pip_runner.uninstall_python_deps(dists)

    if not _WHEELHOUSE_ENV_ORIGINALS:
        _WHEELHOUSE_ENV_ORIGINALS.update({key: os.environ.get(key) for key in _WHEELHOUSE_ENV_KEYS})
    os.environ["PIP_NO_INDEX"] = "1"
    os.environ["PIP_FIND_LINKS"] = str(root)
    os.environ["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    return jsonify({
        "wheelhouse": str(root),
        "wheels": sorted(decoded),
        "installed": _installed_map(dists),
    }), 200


#: Only a test package may be planted in the shared catalog or removed from it
#: through here, so no test can replace or delete a package Curio ships.
_TEST_PACKAGE_DIR_RE = re.compile(r"test\.[a-z][a-z0-9-]{0,62}@(?:0|[1-9][0-9]{0,3})")
#: A test package is a manifest and a starter or two.
_TEST_PACKAGE_MAX_FILES = 16
_TEST_PACKAGE_MAX_BYTES = 256 * 1024


@testing_bp.route("/catalog-package", methods=["POST"])
def catalog_package():
    """Put a test package in this backend's shared catalog, or take it out.

    Adding a package copies it from the shared catalog (``catalog_root()``)
    into the user's store and installs the libraries its manifest declares. A
    test of that install needs a package only the test has, in the catalog, and
    not yet in the user's store: a store copy is answered as already added and
    installs nothing. The catalog is in the stack's own filesystem, which a
    pytest process talking to a container cannot write, so it is written here.
    Each e2e shard has its own catalog (``tests/shards.py``).

    Body (JSON):
      * ``action``      - ``"plant"`` or ``"remove"``.
      * ``dirName``     - ``test.<name>@<major>``; nothing else passes.
      * ``files``       - plant: ``{relative path: text}``, with ``manifest.json``.
      * ``binaryFiles`` - plant, optional: ``{relative path: base64}`` under
        ``models/``, a test model package's weights.

    ``plant`` replaces any earlier copy and writes its ``integrity.json``;
    ``remove`` deletes the folder. Neither touches a user's store.
    """
    import base64 as _base64
    import binascii as _binascii
    import json as _json

    from utk_curio.backend.app.packages.repositories.archive import refresh_package_integrity
    from utk_curio.backend.app.packages.repositories.catalog_dir import catalog_root as _catalog_root

    body = request.get_json(silent=True) or {}
    action = (body.get("action") or "").strip()
    dir_name = (body.get("dirName") or "").strip()
    if action not in ("plant", "remove"):
        return jsonify({"error": "action must be 'plant' or 'remove'"}), 400
    if not _TEST_PACKAGE_DIR_RE.fullmatch(dir_name):
        return jsonify({"error": f"not a test package: {dir_name!r}"}), 400

    target = _catalog_root() / dir_name
    if action == "remove":
        shutil.rmtree(target, ignore_errors=True)
        return jsonify({"removed": dir_name, "present": target.exists()}), 200

    def _safe(rel) -> bool:
        return (isinstance(rel, str) and bool(rel) and not rel.startswith("/") and "\\" not in rel
                and ".." not in rel.split("/") and rel != "integrity.json")

    files = body.get("files")
    if not isinstance(files, dict) or "manifest.json" not in files:
        return jsonify({"error": "files must map relative paths to text, with manifest.json"}), 400
    binary_files = body.get("binaryFiles") or {}
    if not isinstance(binary_files, dict):
        return jsonify({"error": "binaryFiles must map paths under models/ to base64"}), 400
    weights: dict[str, bytes] = {}
    for rel, encoded in binary_files.items():
        if not _safe(rel) or not rel.startswith("models/") or rel in files or not isinstance(encoded, str):
            return jsonify({"error": f"invalid weights file: {rel!r}"}), 400
        try:
            weights[rel] = _base64.b64decode(encoded, validate=True)
        except (_binascii.Error, ValueError):
            return jsonify({"error": f"{rel!r} is not base64"}), 400
    size = sum(len(str(t)) for t in files.values()) + sum(len(b) for b in weights.values())
    if len(files) + len(weights) > _TEST_PACKAGE_MAX_FILES or size > _TEST_PACKAGE_MAX_BYTES:
        return jsonify({"error": "a test package is a manifest and a few small files"}), 400
    for rel, text in files.items():
        if not _safe(rel) or not isinstance(text, str):
            return jsonify({"error": f"invalid file: {rel!r}"}), 400
    try:
        manifest = _json.loads(files["manifest.json"])
    except ValueError:
        return jsonify({"error": "manifest.json is not JSON"}), 400
    declared = f"{manifest.get('id')}@{(manifest.get('compatibility') or {}).get('major')}"
    if declared != dir_name:
        return jsonify({"error": f"manifest.json declares {declared}, not {dir_name}"}), 400

    shutil.rmtree(target, ignore_errors=True)
    for rel, text in files.items():
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    for rel, data in weights.items():
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    refresh_package_integrity(target)
    return jsonify({"planted": dir_name, "files": sorted([*files, *weights])}), 200
