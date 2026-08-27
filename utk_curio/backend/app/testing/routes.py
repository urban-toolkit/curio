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
environment (``CURIO_ENV != 'prod'``, see ``backend/config.py::_is_dev``).
``CURIO_TESTING=1`` is **not** required for the stub-login/stub-project
endpoints to work; that flag only controls whether the backend uses a
dedicated test DB or the default one. The ``agent-script`` routes are the
exception - they 404 without it, because unlike the others they read prompt
text back out of the process.
"""

from __future__ import annotations

from flask import Blueprint, abort, jsonify, request

from utk_curio.backend.config import _is_dev
from utk_curio.backend.app.agents import testing_provider
from utk_curio.backend.extensions import db
from utk_curio.backend.app.users import repositories as user_repo
from utk_curio.backend.app.users import security
from utk_curio.backend.app.projects import services as project_services
from utk_curio.backend.app.projects.schemas import ProjectCreate


testing_bp = Blueprint("testing", __name__, url_prefix="/api/testing")


def _guard() -> None:
    """Abort with 404 in production.

    Belt-and-braces: ``create_app`` already gates blueprint registration on
    ``_is_dev()``, but we also refuse at request time in case the env
    changes mid-session (e.g. by a restart that reused the port).
    """
    if not _is_dev():
        abort(404)


def _empty_spec() -> dict:
    """Default workflow spec used when a stub request omits ``spec``.

    Shape matches what ``FlowProvider`` / ``save_project`` expects when a
    brand-new workflow is persisted: an empty dataflow with no nodes or
    edges. Good enough for "/projects lists this project" assertions.
    """
    return {
        "name": "StubbedWorkflow",
        "dataflow": {"nodes": [], "edges": []},
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
      * ``password`` – optional; when provided the hash is (re)stored so
        the normal ``/api/auth/signin`` form keeps working for the same
        account in follow-up test steps.
      * ``email`` – optional.

    Response: same shape as ``/api/auth/signup`` / ``/api/auth/signin``
    (``{"user": {...}, "token": "..."}``). Callers install ``token`` as the
    ``session_token`` cookie and the SPA is immediately authenticated.
    """
    _guard()
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
    elif password:
        user.password_hash = security.hash_password(password)
        db.session.commit()

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


@testing_bp.route("/reset-db", methods=["POST"])
def reset_db():
    """Truncate mutable tables so the next test starts with a clean slate.

    Called by the ``e2e_clean_db`` fixture over HTTP when the test process
    cannot reach the backend's sqlite file directly (e.g.
    ``CURIO_E2E_USE_EXISTING=1`` pointing at a separately-started server
    whose DB path differs from what ``conftest.py`` resolves).

    Body (JSON, all optional):
      * ``tables`` – list of table names to truncate.  Defaults to the
        standard mutable set (user, user_session, project, auth_attempt,
        exec_cache_entry).

    Response: ``{"truncated": [...table names...]}``
    """
    _guard()
    default_tables = [
        "exec_cache_entry",
        "project",
        "auth_attempt",
        "user_session",
        "user",
    ]
    body = request.get_json(silent=True) or {}
    tables = body.get("tables") or default_tables

    truncated = []
    for table in tables:
        try:
            db.session.execute(db.text(f'DELETE FROM "{table}"'))
            truncated.append(table)
        except Exception:
            pass
    db.session.commit()
    return jsonify({"truncated": truncated}), 200


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
    _guard()
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

    Deliberately not ``abort(404)`` like :func:`_guard`. ``create_app`` installs
    an ``@app.errorhandler(Exception)`` that catches ``HTTPException`` too and
    rewrites it to a 500, so an aborting guard here would answer 500 and the
    refusal would read as a server fault. Returning the response walks past that
    handler and says what it means.
    """
    if not _is_dev() or not testing_provider.enabled():
        return jsonify({"error": "not found"}), 404
    return None


@testing_bp.route("/agent-script", methods=["POST"])
def agent_script_push():
    """Queue scripted replies for the next agent turns.

    Body (JSON):
      * ``replies`` - list of reply strings, consumed in order, one per
        provider call. A multi-round run (a toolRequest and its follow-up)
        needs one entry per round.
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
    if not isinstance(replies, list) or not all(isinstance(r, str) for r in replies):
        return jsonify({"error": "'replies' must be a list of strings"}), 400
    if body.get("reset", True):
        testing_provider.reset()
    testing_provider.push_replies(*replies)
    return jsonify({"pending": testing_provider.pending()}), 200


@testing_bp.route("/agent-script", methods=["GET"])
def agent_script_read():
    """What the scripted provider was asked, and what is still queued.

    ``captured`` is one entry per provider call since the last reset, each the
    OpenAI-style ``[{"role", "content"}, ...]`` list the run composed. A
    per-agent test asserts against it that the system turn really carried that
    agent's own instruction bytes - which a reply, being scripted, can never
    show.

    Response: ``{"pending": n, "captured": [[{role, content}, ...], ...]}``
    """
    denied = _scripted_guard()
    if denied is not None:
        return denied
    return (
        jsonify(
            {
                "pending": testing_provider.pending(),
                "captured": testing_provider.captured(),
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
