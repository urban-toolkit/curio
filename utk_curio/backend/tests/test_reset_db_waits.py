"""``reset-db`` waits for the requests in flight, and refuses new ones meanwhile.

The e2e harness resets the database between tests (``POST
/api/testing/reset-db``). A test's page can still have requests running on the
server when it closes, and the reset deleted their user under them. A request
that then committed and read its user back answered 500 with
``ObjectDeletedError``: 1 to 4 times in each Full stack build's server logs, in
``list_projects``, the dataset catalog and the Discovery media routes.

A listing is held here inside ``list_projects`` with events, after it has
loaded its user, while a reset arrives. The database is a file, so each thread
has its own connection, as on the server. Nothing opens a socket: every
request goes through Flask's test client.

A test can also leave an agent job running: a Solve session keeps making
passes until its deadline. The reset stops it and waits for it the same way.
"""
from __future__ import annotations

import contextlib
import logging
import threading
import time

import pytest
from sqlalchemy import event, text

from utk_curio.backend.app import create_app
from utk_curio.backend.app.agents.application.solve import session as solve_session
from utk_curio.backend.app.agents.infrastructure import agent_jobs
from utk_curio.backend.app.projects import seed
from utk_curio.backend.app.projects import services as project_services
from utk_curio.backend.app.testing import routes as testing_routes
from utk_curio.backend.app.testing.in_flight import REFUSAL
from utk_curio.backend.extensions import db as _db
from utk_curio.backend.tests._unit_fixtures import TestConfig, tmp_curio  # noqa: F401
from utk_curio.backend.tests.test_datasets.test_save_lock_order import (
    HOLD_SECONDS,
    STEP_SECONDS,
    _release_and_join,
    _start,
)

TOKEN = "reset-waits-token"
HELD = "GET /api/projects"
ROUTES_LOGGER = "utk_curio.backend.app.testing.routes"


@pytest.fixture()
def app(tmp_curio, tmp_path):  # noqa: F811
    """The app on a SQLite file, so each thread gets its own connection."""
    class FileTestConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'reset.db'}"

    application = create_app(FileTestConfig)
    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()
        _db.engine.dispose()


@pytest.fixture()
def user_id(app):
    """Rita and her session token."""
    from utk_curio.backend.app.users.models import User, UserSession

    user = User(username="rita", name="Rita", email="rita@test.com")
    _db.session.add(user)
    _db.session.flush()
    _db.session.add(UserSession(user_id=user.id, token=TOKEN))
    _db.session.commit()
    return user.id


class _ResetSignals:
    """``waits``: a reset said it waits for requests in flight. ``settled``:
    that, or the reset is done, whichever came first."""

    def __init__(self) -> None:
        self.waits = threading.Event()
        self.settled = threading.Event()


@pytest.fixture()
def signals():
    """Watches the testing routes' log for a reset that waits."""
    found = _ResetSignals()

    class _Watch(logging.Handler):
        def emit(self, record):
            if record.getMessage().startswith("reset-db waits for"):
                found.waits.set()
                found.settled.set()

    logger = logging.getLogger(ROUTES_LOGGER)
    handler = _Watch(level=logging.INFO)
    previous = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    yield found
    logger.removeHandler(handler)
    logger.setLevel(previous)


def _list(application):
    return application.test_client().get(
        "/api/projects", headers={"Authorization": f"Bearer {TOKEN}"},
    )


def _reset(application, found: _ResetSignals | None = None):
    try:
        return application.test_client().post(
            "/api/testing/reset-db", data="{}", content_type="application/json",
        )
    finally:
        if found is not None:
            found.settled.set()


def _hold_the_listing(monkeypatch, thread_name: str):
    """Hold *thread_name*'s listing inside ``list_projects``: it has loaded its
    user and read nothing for it yet. Returns the (reached, release) events and
    the names of the threads whose listing got that far."""
    reached, release = threading.Event(), threading.Event()
    entered: list = []
    real = seed.ensure_user_examples_seeded

    def held(user):
        name = threading.current_thread().name
        entered.append(name)
        if name == thread_name and not reached.is_set():
            reached.set()
            release.wait(timeout=HOLD_SECONDS)
        return real(user)

    # list_projects imports it at call time, so the module attribute is what it gets.
    monkeypatch.setattr(seed, "ensure_user_examples_seeded", held)
    return reached, release, entered


@contextlib.contextmanager
def _watch_user_delete(on_delete):
    """Call *on_delete* when anything deletes the ``user`` table's rows."""
    def observe(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.strip().upper() == 'DELETE FROM "USER"':
            on_delete()

    engine = _db.engine
    event.listen(engine, "before_cursor_execute", observe)
    try:
        yield
    finally:
        event.remove(engine, "before_cursor_execute", observe)


def _users() -> int:
    return _db.session.execute(text('SELECT COUNT(*) FROM "user"')).scalar()


def test_a_reset_waits_for_a_request_in_flight(app, user_id, signals, monkeypatch):
    """Rita's first listing is held after it has loaded her, and a reset
    arrives. The reset must wait for the listing and delete nothing until it is
    done.

    The first listing seeds her examples, which commits and so expires the user
    it loaded. Reading her back is where a reset that ran under the listing
    failed it with ``ObjectDeletedError``."""
    monkeypatch.setenv("CURIO_SEED_EXAMPLES", "1")
    reached, release, _entered = _hold_the_listing(monkeypatch, "listing")
    deleted = threading.Event()

    threads: list = []
    with _watch_user_delete(deleted.set):
        try:
            listing = _start(threads, "listing", lambda: _list(app))
            assert reached.wait(STEP_SECONDS), "the listing never reached list_projects"
            reset = _start(threads, "reset", lambda: _reset(app, signals))
            assert signals.settled.wait(STEP_SECONDS), "the reset neither waited nor finished"
            deleted_while_held = deleted.is_set()
        finally:
            _release_and_join(threads, release)

    assert "error" not in listing, repr(listing.get("error"))
    response = listing["value"]
    assert response.status_code == 200, (
        f"the listing answered {response.status_code}: {response.get_data(as_text=True)[:300]}"
    )
    assert response.get_json(), "the listing found none of Rita's examples"
    assert not deleted_while_held, f"the reset deleted users while {HELD} was still running"
    assert signals.waits.is_set(), f"the reset never said it waits for {HELD}"
    assert "error" not in reset, repr(reset.get("error"))
    assert reset["value"].status_code == 200, reset["value"].get_data(as_text=True)
    assert reset["value"].get_json().get("waited_for") == [HELD]
    assert deleted.is_set(), "the reset never deleted the users"
    assert _users() == 0


def test_a_request_that_arrives_during_a_reset_is_refused_before_it_starts(
    app, user_id, signals, monkeypatch,
):
    """While a reset waits for a held listing, another listing arrives. It must
    be refused at once, without reaching its route, and the reset must still
    wait for the first one."""
    reached, release, entered = _hold_the_listing(monkeypatch, "listing")

    threads: list = []
    try:
        listing = _start(threads, "listing", lambda: _list(app))
        assert reached.wait(STEP_SECONDS), "the listing never reached list_projects"
        reset = _start(threads, "reset", lambda: _reset(app, signals))
        assert signals.settled.wait(STEP_SECONDS), "the reset neither waited nor finished"
        assert signals.waits.is_set(), f"the reset did not wait for {HELD}"
        started = time.monotonic()
        late = _list(app)
        late_took = time.monotonic() - started
    finally:
        _release_and_join(threads, release)

    assert late.status_code == 503, (
        f"a listing sent during the reset answered {late.status_code}: "
        f"{late.get_data(as_text=True)[:300]}"
    )
    assert "reset" in late.get_json()["error"]
    assert late_took < STEP_SECONDS
    assert entered == ["listing"], f"listings that reached list_projects: {entered}"
    assert listing["value"].status_code == 200, listing["value"].get_data(as_text=True)
    assert reset["value"].status_code == 200, reset["value"].get_data(as_text=True)
    assert _users() == 0


def test_the_liveness_probe_answers_while_a_reset_waits(app, user_id, signals, monkeypatch):
    """A backend that is resetting is up: ``/live`` answers while a reset
    waits, and a listing sent in the same wait is still refused.

    Each e2e shard resets its own database between its tests while the other
    shards run theirs. The shard isolation e2e asked a sibling's ``/live`` in
    the middle of such a reset, got 503, and called that shard down (#1171)."""
    reached, release, _entered = _hold_the_listing(monkeypatch, "listing")

    threads: list = []
    try:
        _start(threads, "listing", lambda: _list(app))
        assert reached.wait(STEP_SECONDS), "the listing never reached list_projects"
        reset = _start(threads, "reset", lambda: _reset(app, signals))
        assert signals.settled.wait(STEP_SECONDS), "the reset neither waited nor finished"
        assert signals.waits.is_set(), f"the reset did not wait for {HELD}"
        probe = app.test_client().get("/live")
        late = _list(app)
    finally:
        _release_and_join(threads, release)

    assert probe.status_code == 200, (
        f"/live answered {probe.status_code} while a reset waited for {HELD}: "
        f"{probe.get_data(as_text=True)[:300]}"
    )
    assert late.status_code == 503, (
        f"a listing sent during the reset answered {late.status_code}: "
        f"{late.get_data(as_text=True)[:300]}"
    )
    # What the shard isolation e2e asks again on.
    assert late.get_json()["error"] == REFUSAL
    assert reset["value"].status_code == 200, reset["value"].get_data(as_text=True)
    assert _users() == 0


def test_a_request_past_the_bound_is_named_and_waited_for_once(app, user_id, monkeypatch):
    """A request that never finishes holds a reset for the bound only. The
    reset then goes ahead, names it, and the next reset does not wait for it."""
    bound = 0.5
    # raising=False: the bound is part of what this pins.
    monkeypatch.setattr(testing_routes, "RESET_WAIT_SECONDS", bound, raising=False)
    reached, release, _entered = _hold_the_listing(monkeypatch, "listing")

    threads: list = []
    try:
        _start(threads, "listing", lambda: _list(app))
        assert reached.wait(STEP_SECONDS), "the listing never reached list_projects"
        started = time.monotonic()
        first = _reset(app)
        first_took = time.monotonic() - started
        second = _reset(app)
    finally:
        _release_and_join(threads, release)

    assert first.status_code == 200, first.get_data(as_text=True)
    assert second.status_code == 200, second.get_data(as_text=True)
    answer = first.get_json()
    assert answer.get("waited_for") == [HELD], answer
    assert answer.get("still_running") == [HELD], answer
    assert bound * 0.9 <= first_took < STEP_SECONDS, f"the first reset took {first_took:.2f} s"
    again = second.get_json()
    assert again.get("waited_for") == [] and again.get("still_running") == [], again
    assert _users() == 0


def test_a_reset_with_nothing_in_flight_does_not_wait(app, user_id, monkeypatch):
    """Guard: requests that came and went, however they ended, leave nothing
    for a reset to wait for."""
    client = app.test_client()
    auth = {"Authorization": f"Bearer {TOKEN}"}
    assert client.get("/api/projects", headers=auth).status_code == 200
    assert client.get("/api/projects").status_code == 401
    assert client.get("/api/no-such-route").status_code == 404

    def fails(*_args, **_kwargs):
        raise RuntimeError("a route that fails")

    monkeypatch.setattr(project_services, "list_projects", fails)
    assert client.get("/api/projects", headers=auth).status_code == 500

    started = time.monotonic()
    response = _reset(app)
    took = time.monotonic() - started
    assert response.status_code == 200, response.get_data(as_text=True)
    assert took < 2.0, f"a reset with nothing in flight took {took:.1f} s"
    assert response.get_json().get("waited_for", []) == []
    assert _users() == 0


@pytest.fixture()
def fresh_agent_jobs():
    """No agent job from another test, and none left for the next one."""
    agent_jobs.reset_registry()
    yield
    agent_jobs.reset_registry()


def _left_running(monkeypatch, execution_id: str):
    """A Solve session the last test left running, as a batch runs one: an
    agent job that makes passes until its stop event is set (dev/131).
    Returns the job and that event."""
    stop = threading.Event()
    monkeypatch.setitem(solve_session._SOLVE_CANCEL_EVENTS, execution_id, stop)

    def passes():
        stop.wait(timeout=HOLD_SECONDS)
        yield "done", {}

    job = agent_jobs.start_job(
        user_key="rita", project_id="p1", attachment_id="a1",
        kind="solve-batch", job_id=execution_id, events=passes(),
    )
    return job, stop


def test_a_reset_stops_a_solve_the_last_test_left_running(
    app, user_id, monkeypatch, fresh_agent_jobs,
):
    """A Solve session keeps making passes until its deadline (dev/131), so the
    test that starts one can end with it still running. Its later calls took
    the replies the next test scripted for the model: the Map Editor agent e2e
    failed 3 of 10 repeats, each time right after the Solve e2e. A reset stops
    it as the user's Stop does, waits for it to end, and only then deletes the
    users whose files it writes."""
    job, stop = _left_running(monkeypatch, "left-running")
    live_at_delete: list = []

    try:
        with _watch_user_delete(lambda: live_at_delete.append(job.live)):
            response = _reset(app)
        stopped_by_the_reset, live_after = stop.is_set(), job.live
    finally:
        stop.set()
        job.thread.join(timeout=STEP_SECONDS)

    assert response.status_code == 200, response.get_data(as_text=True)
    assert stopped_by_the_reset, "the reset left the Solve running"
    assert not live_after, "the reset answered with the Solve still running"
    assert live_at_delete == [False], (
        f"whether the Solve was running when the users were deleted: {live_at_delete}"
    )
    answer = response.get_json()
    assert answer.get("agent_jobs") == ["solve-batch left-running"], answer
    assert answer.get("agent_jobs_still_running") == [], answer
    assert _users() == 0


def test_an_agent_job_past_the_bound_is_named_and_the_reset_goes_ahead(
    app, user_id, monkeypatch, fresh_agent_jobs,
):
    """A per-node Solve has no stop: it ends after its rounds. One that outlasts
    the bound holds a reset for the bound only, as a request does: the reset
    then names it and goes ahead."""
    bound = 0.5
    # raising=False: the bound is part of what this pins.
    monkeypatch.setattr(testing_routes, "RESET_WAIT_SECONDS", bound, raising=False)
    release = threading.Event()

    def rounds():
        release.wait(timeout=HOLD_SECONDS)
        yield "done", {}

    job = agent_jobs.start_job(
        user_key="rita", project_id="p1", attachment_id="a2",
        kind="solve-node", job_id="node-rounds", events=rounds(),
    )
    try:
        started = time.monotonic()
        response = _reset(app)
        took = time.monotonic() - started
    finally:
        release.set()
        job.thread.join(timeout=STEP_SECONDS)

    assert response.status_code == 200, response.get_data(as_text=True)
    answer = response.get_json()
    assert answer.get("agent_jobs") == ["solve-node node-rounds"], answer
    assert answer.get("agent_jobs_still_running") == ["solve-node node-rounds"], answer
    assert bound * 0.9 <= took < STEP_SECONDS, f"the reset took {took:.2f} s"
    assert _users() == 0


def test_only_a_test_rig_counts_its_requests(tmp_curio, monkeypatch):  # noqa: F811
    """Guard: an app built without ``CURIO_TESTING`` (a developer's own
    ``curio.py start``, where ``CURIO_ENV`` defaults to dev and so mounts the
    testing routes) gets no part of the request count."""
    rig = create_app(TestConfig)
    monkeypatch.setattr(testing_routes, "_is_testing", lambda: False)
    plain = create_app(TestConfig)

    count_in = getattr(testing_routes, "_count_request_in", None)
    count_out = getattr(testing_routes, "_count_request_out", None)
    assert count_in is not None and count_in in rig.before_request_funcs.get(None, [])
    assert count_out is not None and count_out in rig.teardown_request_funcs.get(None, [])
    assert count_in not in plain.before_request_funcs.get(None, [])
    assert count_out not in plain.teardown_request_funcs.get(None, [])
