"""The test-only routes act on every backend process of a start.

``curio.py start --backend-processes N`` runs N backends behind nginx. A
testing route names no dataflow, so nginx sends it to the home process, while
what it changes lives in each process's memory: the record clock, Curio's LLM
endpoints, the run hold, pip's behaviour and settings, the import path, and the
door a reset closes. So the process a call reaches makes the change and sends
it to every other process of the start over 127.0.0.1, signed with the start's
secret, and the call fails, naming the process, when one did not take it. A
reset closes every process's door before it deletes anything, and opens every
one after. With one process nothing is sent.

Here this app is the home process of two. Both processes' ports are servers in
the test (``_support/backend_group_fakes.AnotherBackend``): the other process
answers each call as a backend does, and this process's own port must get
none. The last tests send such a call to this app as the other process. New
names are imported in each test, so a checkout without them fails test by test.
"""
from __future__ import annotations

import base64
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import event, text

from utk_curio.backend.app import create_app
from utk_curio.backend.extensions import db as _db
from utk_curio.backend.tests._support.backend_group_fakes import AnotherBackend
from utk_curio.backend.tests._support.offline_wheels import WheelLibrary, build_wheel, wheel_file_name
from utk_curio.backend.tests._unit_fixtures import TestConfig, tmp_curio  # noqa: F401
from utk_curio.backend.tests.test_collaboration._processes import as_process, as_the_one_process

#: The secret the start's backends show each other, and the header it travels in.
SECRET = "the start's own secret"
TOKEN_HEADER = "X-Curio-Backend-Token"
TOKEN = "every-process-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
#: pip's settings the wheelhouse points every process at.
PIP_KEYS = ("PIP_NO_INDEX", "PIP_FIND_LINKS", "PIP_DISABLE_PIP_VERSION_CHECK")
LIB = WheelLibrary(dist="curio-wheelhouse-forks", version="1.0.0", module="curio_wheelhouse_forks",
                   message="curio-wheelhouse-forks 1.0.0 from the test wheelhouse")
#: An endpoint file, with a key that is no one's.
ENDPOINT_FILE = "[Gateway]\napi_key = not-a-real-key\nmodels = model-a, model-b\n"
#: What a process that closed its door for a reset answers: it waited for
#: nothing and left nothing going.
CLOSED = {"waited_for": [], "waited_seconds": 0.0, "still_running": [], "agent_jobs": [],
          "agent_jobs_still_running": [], "runs": [], "runs_still_going": []}


@pytest.fixture()
def app(tmp_curio, tmp_path):  # noqa: F811
    """The app on a SQLite file, so each thread gets its own connection."""
    class FileTestConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'every-process.db'}"

    application = create_app(FileTestConfig)
    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()
        _db.engine.dispose()


@pytest.fixture()
def user_id(app):
    """Rita, with a session."""
    from utk_curio.backend.app.users.models import User, UserSession

    user = User(username="rita", name="Rita", email="rita@test.com")
    _db.session.add(user)
    _db.session.flush()
    _db.session.add(UserSession(user_id=user.id, token=TOKEN))
    _db.session.commit()
    return user.id


@pytest.fixture()
def start(monkeypatch):
    """This app as the home process of a start of two; ``itself`` is a server
    at this process's own port, which must get no call, and ``other`` the
    other process."""
    with AnotherBackend() as itself, AnotherBackend() as other:
        as_process(monkeypatch, 0)
        monkeypatch.setenv("CURIO_BACKEND_PORTS", f"{itself.port},{other.port}")
        monkeypatch.setenv("CURIO_BACKEND_TOKEN", SECRET)
        other.results.update({
            "run-hold": lambda arguments: {"held": bool(arguments.get("hold")), "waiting": 0},
            "reset.close": dict(CLOSED),
        })
        yield SimpleNamespace(itself=itself, other=other)


@pytest.fixture()
def as_the_other(monkeypatch):
    """This app as process 1 of 2. The home process's port is a server in the
    test, which must get no call: a change another process sent is made here
    alone."""
    with AnotherBackend() as home:
        as_process(monkeypatch, 1)
        monkeypatch.setenv("CURIO_BACKEND_PORTS", f"{home.port},{home.port + 1}")
        monkeypatch.setenv("CURIO_BACKEND_TOKEN", SECRET)
        yield home


@pytest.fixture()
def import_path_put_back(monkeypatch):
    """``sys.path`` and ``PYTHONPATH`` back as they were after the test,
    whatever it left on them."""
    monkeypatch.setattr(sys, "path", list(sys.path))
    if "PYTHONPATH" in os.environ:
        monkeypatch.setenv("PYTHONPATH", os.environ["PYTHONPATH"])
    else:
        monkeypatch.delenv("PYTHONPATH", raising=False)


def _post(client, route: str, body: dict | None = None):
    return client.post(f"/api/testing/{route}", data=json.dumps(body or {}), content_type="application/json")


def _sent_here(client, step: str, arguments: dict, token: str | None = SECRET):
    """A step another backend process of the start sends this one."""
    return client.post(f"/internal/testing/{step}", data=json.dumps({"arguments": arguments}),
                       content_type="application/json", headers={TOKEN_HEADER: token} if token else {})


def _signed(backend: AnotherBackend) -> None:
    assert backend.calls and {call["token"] for call in backend.calls} == {SECRET}, (
        f"a change reached another process without the start's secret: {backend.calls}"
    )


def _users() -> int:
    return _db.session.execute(text('SELECT COUNT(*) FROM "user"')).scalar()


class _UserDelete:
    """Calls *on_delete* when anything deletes the ``user`` table's rows."""

    def __init__(self, on_delete):
        self._on_delete = on_delete

    def _observe(self, _conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.strip().upper() == 'DELETE FROM "USER"':
            self._on_delete()

    def __enter__(self):
        event.listen(_db.engine, "before_cursor_execute", self._observe)
        return self

    def __exit__(self, *_exc):
        event.remove(_db.engine, "before_cursor_execute", self._observe)
        return False


# ---------------------------------------------------------------------------
# A change is made in every process
# ---------------------------------------------------------------------------

def test_the_record_clock_is_set_in_every_process_and_put_back_in_every_one(app, start, monkeypatch):
    """A catalog capture dates the records it makes on the test's own date,
    whichever process makes them. With one process nothing is sent."""
    from utk_curio.backend.app.common import record_clock

    client = app.test_client()
    moment = datetime(2026, 10, 24, 6, 0, tzinfo=timezone.utc)
    try:
        set_it = _post(client, "clock", {"now": moment.isoformat()})
        here = record_clock.utc_now()
        put_back = client.delete("/api/testing/clock")
        back_here = record_clock.utc_now()
        sent_by_two = start.other.steps()
        as_the_one_process(monkeypatch)
        alone = _post(client, "clock", {"now": moment.isoformat()})
    finally:
        record_clock.set_now(None)

    assert (set_it.status_code, put_back.status_code, alone.status_code) == (200, 200, 200), (
        set_it.get_data(as_text=True), put_back.get_data(as_text=True), alone.get_data(as_text=True))
    assert abs((here - moment).total_seconds()) < 60, f"this process's record clock read {here}"
    assert abs((back_here - datetime.now(timezone.utc)).total_seconds()) < 60, back_here
    assert [call["path"] for call in start.other.calls] == ["/internal/testing/clock"] * 2, start.other.calls
    _signed(start.other)
    (_, sent), (_, back) = sent_by_two
    other_reads = datetime.now(timezone.utc) + timedelta(microseconds=sent["offsetMicroseconds"])
    assert abs((other_reads - moment).total_seconds()) < 60, f"the other process's clock would read {other_reads}"
    assert back == {"offsetMicroseconds": 0}, back
    assert start.other.steps() == sent_by_two, "a start of one process sent the clock on"
    assert start.itself.calls == [], "the process that made the change sent it to itself"


def test_curios_llm_endpoints_are_set_in_every_process_and_put_back_in_every_one(app, start):
    """The stress stage's agents and a guest's page read the scripted model,
    or a test's endpoint file, in whichever process serves them."""
    from utk_curio.backend import config as settings

    client = app.test_client()
    launch = tuple(settings.DEFAULT_LLM_ENDPOINTS)
    try:
        scripted = _post(client, "llm-deployment", {"scripted": True})
        offered = [endpoint.name for endpoint in settings.DEFAULT_LLM_ENDPOINTS]
        from_a_file = _post(client, "llm-deployment", {"file": ENDPOINT_FILE})
        put_back = client.delete("/api/testing/llm-deployment")
        back = tuple(settings.DEFAULT_LLM_ENDPOINTS)
    finally:
        settings.DEFAULT_LLM_ENDPOINTS = launch

    assert [answer.status_code for answer in (scripted, from_a_file, put_back)] == [200, 200, 200], (
        scripted.get_data(as_text=True), from_a_file.get_data(as_text=True))
    assert offered == ["Scripted"], offered
    assert back == launch, "the launch's endpoints did not come back here"
    assert start.other.steps() == [
        ("llm-deployment", {"scripted": True}),
        ("llm-deployment", {"file": ENDPOINT_FILE}),
        ("llm-deployment", {"restore": True}),
    ], start.other.calls
    _signed(start.other)


def test_runs_are_held_in_every_process_and_their_waiting_nodes_counted_together(app, start):
    """A run executes in its dataflow's process, so a hold holds every
    process, and the nodes waiting at it are those of every process."""
    from utk_curio.backend.app.runs import jobs as run_jobs

    start.other.results["run-hold"] = (
        lambda arguments: {"held": arguments["hold"], "waiting": 2} if "hold" in arguments
        else {"held": True, "waiting": 3})
    client = app.test_client()
    try:
        held = _post(client, "run-hold", {"hold": True})
        held_here = run_jobs.hold_state()["held"]
        read = client.get("/api/testing/run-hold")
        released = _post(client, "run-hold", {"hold": False})
    finally:
        run_jobs.set_hold(False)

    assert held.get_json() == {"held": True, "waiting": 2}, held.get_data(as_text=True)
    assert held_here is True, "this process did not hold its runs"
    assert read.get_json() == {"held": True, "waiting": 3}, read.get_data(as_text=True)
    assert released.get_json() == {"held": False, "waiting": 2}, released.get_data(as_text=True)
    assert start.other.steps() == [("run-hold", {"hold": True}), ("run-hold", {}), ("run-hold", {"hold": False})]
    _signed(start.other)


def test_pip_fails_on_purpose_in_every_process(app, start):
    """A package is added, and a dataflow's libraries installed, by
    whichever process the page reaches."""
    from utk_curio.backend.app.packages.infrastructure import pip_runner

    names = ("install_python_deps", "import_failures", "import_failures_in")
    real = {name: getattr(pip_runner, name) for name in names}
    client = app.test_client()
    try:
        failing = _post(client, "pip-behaviour", {"mode": "install-error"})
        fails_here = pip_runner.install_python_deps is not real["install_python_deps"]
        normal = _post(client, "pip-behaviour", {"mode": "normal"})
        normal_here = pip_runner.install_python_deps is real["install_python_deps"]
    finally:
        for name, function in real.items():
            setattr(pip_runner, name, function)

    assert (failing.status_code, normal.status_code) == (200, 200), failing.get_data(as_text=True)
    assert fails_here and normal_here
    assert start.other.steps() == [("pip-behaviour", {"mode": "install-error"}),
                                   ("pip-behaviour", {"mode": "normal"})]
    _signed(start.other)


def test_the_wheelhouse_is_written_once_and_every_process_installs_from_it(app, start, monkeypatch):
    """The wheels and the uninstall touch the one disk and interpreter, so
    the process the call reached does them; every process's pip then reads
    the wheelhouse, and on restore every process's settings go back before
    the uninstall."""
    from utk_curio.backend.app.packages.infrastructure import pip_runner

    for key in PIP_KEYS:
        monkeypatch.delenv(key, raising=False)
    happened: list = []
    monkeypatch.setattr(pip_runner, "uninstall_python_deps",
                        lambda dists, *args, **kwargs: happened.append(("uninstall", list(dists))))

    def other_process(arguments):
        if arguments.get("restore"):
            happened.append(("restored", None))
        else:
            happened.append(("pointed", sorted(path.name for path in Path(arguments["root"]).glob("*.whl"))))
        return {}

    start.other.results["wheelhouse"] = other_process
    wheel = {"filename": wheel_file_name(LIB), "content": base64.b64encode(build_wheel(LIB)).decode("ascii")}
    client = app.test_client()
    staged = _post(client, "wheelhouse", {"action": "stage", "wheels": [wheel]})
    settings_here = [os.environ.get(key) for key in PIP_KEYS]
    restored = _post(client, "wheelhouse", {"action": "restore"})

    assert (staged.status_code, restored.status_code) == (200, 200), staged.get_data(as_text=True)
    root = staged.get_json()["wheelhouse"]
    dist = "curio_wheelhouse_forks"
    assert settings_here == ["1", root, "1"], settings_here
    assert happened == [("uninstall", [dist]), ("pointed", [wheel_file_name(LIB)]),
                        ("restored", None), ("uninstall", [dist])], happened
    assert [key for key in PIP_KEYS if key in os.environ] == []
    assert start.other.steps() == [("wheelhouse", {"root": root}), ("wheelhouse", {"restore": True})]
    _signed(start.other)


def test_a_broken_library_is_written_once_and_put_on_every_processs_import_path(app, start, import_path_put_back):
    """pip's probe runs in a child of whichever process installs, so the fake
    is on every process's import path while it is staged."""
    client = app.test_client()
    installed = _post(client, "broken-library", {"action": "install", "name": "brokenforks"})
    path = (installed.get_json() or {}).get("path")
    on_path_here = path in sys.path
    removed = _post(client, "broken-library", {"action": "remove", "name": "brokenforks"})

    assert (installed.status_code, removed.status_code) == (200, 200), installed.get_data(as_text=True)
    assert on_path_here and path not in sys.path
    assert start.other.steps() == [("broken-library", {"path": path, "onPath": True}),
                                   ("broken-library", {"path": path, "onPath": False})]
    _signed(start.other)


def test_a_process_that_does_not_take_a_change_fails_the_call_and_is_named(app, start):
    from utk_curio.backend.app.common import record_clock

    start.other.failing["clock"] = "its clock would not move"
    client = app.test_client()
    try:
        answered = _post(client, "clock", {"now": "2026-10-24T06:00:00Z"})
    finally:
        record_clock.set_now(None)

    assert answered.status_code == 502, answered.get_data(as_text=True)
    error = answered.get_json()["error"]
    assert "backend process 1" in error and "its clock would not move" in error, error


# ---------------------------------------------------------------------------
# A reset closes every process before it deletes, and opens every one after
# ---------------------------------------------------------------------------

def test_a_reset_closes_every_process_before_it_deletes_and_opens_every_one_after(app, user_id, start):
    """Every process's requests, runs and agents are stopped and waited for
    before the rows are deleted: a request another process still served
    would write into the next test's tables."""
    order: list = []

    def closed(_arguments):
        order.append("closed")
        return {**CLOSED, "waited_for": ["GET /api/datasets"]}

    def opened(_arguments):
        order.append("opened")
        return {}

    start.other.results.update({"reset.close": closed, "reset.open": opened})
    with _UserDelete(lambda: order.append("deleted")):
        reset = app.test_client().post("/api/testing/reset-db", data="{}", content_type="application/json")

    assert reset.status_code == 200, reset.get_data(as_text=True)
    assert order == ["closed", "deleted", "opened"], order
    assert start.other.steps() == [("reset.close", {}), ("reset.open", {"restore": True})]
    assert reset.get_json()["waited_for"] == ["GET /api/datasets"], reset.get_json()
    assert _users() == 0
    _signed(start.other)


def test_a_run_still_going_in_another_process_keeps_every_row_and_opens_every_door(app, user_id, start):
    going = "run r1 of dataflow d1, running Loader (n1)"
    start.other.results["reset.close"] = {**CLOSED, "runs": ["run r1"], "runs_still_going": [going]}
    client = app.test_client()
    reset = client.post("/api/testing/reset-db", data="{}", content_type="application/json")
    late = client.get("/api/projects", headers=AUTH)

    assert reset.status_code == 409, reset.get_data(as_text=True)
    assert going in reset.get_json()["error"] and reset.get_json()["runs_still_going"] == [going]
    assert _users() == 1, "a reset deleted rows under a run another process still ran"
    assert start.other.steps() == [("reset.close", {}), ("reset.open", {"restore": False})]
    assert late.status_code == 200, f"this process's door stayed closed: {late.status_code}"


def test_a_process_that_cannot_close_for_a_reset_stops_it(app, user_id, start):
    start.other.failing["reset.close"] = "it could not stop its runs"
    client = app.test_client()
    reset = client.post("/api/testing/reset-db", data="{}", content_type="application/json")
    late = client.get("/api/projects", headers=AUTH)

    assert reset.status_code == 502, reset.get_data(as_text=True)
    error = reset.get_json()["error"]
    assert "backend process 1" in error and "it could not stop its runs" in error, error
    assert _users() == 1, "a reset deleted rows while another process still served"
    assert start.other.steps() == [("reset.close", {}), ("reset.open", {"restore": False})]
    assert late.status_code == 200, f"this process's door stayed closed: {late.status_code}"


# ---------------------------------------------------------------------------
# A change another process sends is made here
# ---------------------------------------------------------------------------

def test_a_change_another_process_sends_is_made_here_and_sent_nowhere(app, as_the_other):
    from utk_curio.backend import config as settings
    from utk_curio.backend.app.common import record_clock
    from utk_curio.backend.app.packages.infrastructure import pip_runner
    from utk_curio.backend.app.runs import jobs as run_jobs

    client = app.test_client()
    launch = tuple(settings.DEFAULT_LLM_ENDPOINTS)
    real_install = pip_runner.install_python_deps
    five_days = -5 * 24 * 3600 * 1_000_000
    try:
        clock = _sent_here(client, "clock", {"offsetMicroseconds": five_days})
        clock_here = record_clock.utc_now()
        scripted = _sent_here(client, "llm-deployment", {"scripted": True})
        offered = [endpoint.name for endpoint in settings.DEFAULT_LLM_ENDPOINTS]
        put_back = _sent_here(client, "llm-deployment", {"restore": True})
        back = tuple(settings.DEFAULT_LLM_ENDPOINTS)
        held = _sent_here(client, "run-hold", {"hold": True})
        held_here = run_jobs.hold_state()["held"]
        read = _sent_here(client, "run-hold", {})
        failing = _sent_here(client, "pip-behaviour", {"mode": "install-error"})
        fails_here = pip_runner.install_python_deps is not real_install
        normal = _sent_here(client, "pip-behaviour", {"mode": "normal"})
    finally:
        record_clock.set_now(None)
        settings.DEFAULT_LLM_ENDPOINTS = launch
        run_jobs.set_hold(False)
        pip_runner.install_python_deps = real_install

    answers = (clock, scripted, put_back, held, read, failing, normal)
    assert [answer.status_code for answer in answers] == [200] * len(answers), [
        answer.get_data(as_text=True) for answer in answers]
    assert all(answer.get_json()["ok"] is True for answer in answers), [answer.get_json() for answer in answers]
    expected = datetime.now(timezone.utc) - timedelta(days=5)
    assert abs((clock_here - expected).total_seconds()) < 60, f"this process's record clock read {clock_here}"
    assert offered == ["Scripted"] and back == launch, (offered, back)
    assert held_here is True and read.get_json()["result"]["held"] is True
    assert fails_here, "pip-behaviour was not staged here"
    assert as_the_other.calls == [], "a change another process sent was sent on again"


def test_the_wheelhouse_and_a_broken_library_another_process_wrote_are_read_here(
    app, as_the_other, tmp_path, monkeypatch, import_path_put_back,
):
    for key in PIP_KEYS:
        monkeypatch.delenv(key, raising=False)
    wheels, libs = tmp_path / "wheels", tmp_path / "broken-libs"
    wheels.mkdir()
    libs.mkdir()
    client = app.test_client()
    pointed = _sent_here(client, "wheelhouse", {"root": str(wheels)})
    settings_here = [os.environ.get(key) for key in PIP_KEYS]
    restored = _sent_here(client, "wheelhouse", {"restore": True})
    settings_after = [key for key in PIP_KEYS if key in os.environ]
    on = _sent_here(client, "broken-library", {"path": str(libs), "onPath": True})
    on_here = (str(libs) in sys.path, str(libs) in os.environ.get("PYTHONPATH", "").split(os.pathsep))
    off = _sent_here(client, "broken-library", {"path": str(libs), "onPath": False})
    off_here = (str(libs) in sys.path, str(libs) in os.environ.get("PYTHONPATH", "").split(os.pathsep))

    answers = (pointed, restored, on, off)
    assert [answer.status_code for answer in answers] == [200] * 4, [answer.get_data(as_text=True) for answer in answers]
    assert settings_here == ["1", str(wheels), "1"] and settings_after == [], (settings_here, settings_after)
    assert on_here == (True, True) and off_here == (False, False), (on_here, off_here)
    assert as_the_other.calls == []


def test_a_reset_another_process_sends_closes_this_processs_door_and_opens_it(app, user_id, as_the_other):
    """The call that opens the door is not refused at the door it opens."""
    from utk_curio.backend.app.testing.in_flight import REFUSAL

    client = app.test_client()
    closed = _sent_here(client, "reset.close", {})
    refused = client.get("/api/projects", headers=AUTH)
    opened = _sent_here(client, "reset.open", {"restore": True})
    served = client.get("/api/projects", headers=AUTH)

    assert closed.status_code == 200 and closed.get_json()["ok"] is True, closed.get_data(as_text=True)
    assert set(CLOSED) <= set(closed.get_json()["result"]), closed.get_json()
    assert refused.status_code == 503 and refused.get_json()["error"] == REFUSAL, refused.get_data(as_text=True)
    assert opened.status_code == 200, f"the call that opens the door answered {opened.status_code}"
    assert served.status_code == 200, served.get_data(as_text=True)
    assert _users() == 1, "a process that only closed for a reset deleted rows"
    assert as_the_other.calls == []


def test_only_the_starts_own_backends_reach_the_internal_route(app, as_the_other, monkeypatch):
    from utk_curio.backend.app.common import record_clock

    client = app.test_client()
    try:
        unsigned = _sent_here(client, "clock", {"offsetMicroseconds": 1}, token=None)
        wrong = _sent_here(client, "clock", {"offsetMicroseconds": 1}, token="another secret")
        unknown = _sent_here(client, "no-such-step", {})
        signed = _sent_here(client, "clock", {"offsetMicroseconds": 0})
        as_the_one_process(monkeypatch)
        alone = _sent_here(client, "clock", {"offsetMicroseconds": 1})
    finally:
        record_clock.set_now(None)

    assert (unsigned.status_code, wrong.status_code) == (403, 403), (unsigned.status_code, wrong.status_code)
    assert unknown.status_code == 404, unknown.get_data(as_text=True)
    assert signed.status_code == 200, signed.get_data(as_text=True)
    assert alone.status_code == 404, "a start of one process took a call from another"


def test_the_internal_route_is_closed_outside_a_test_rig(app, as_the_other, monkeypatch):
    from utk_curio.backend import config

    client = app.test_client()
    signed = _sent_here(client, "run-hold", {})
    monkeypatch.setattr(config, "_is_testing", lambda: False)
    outside = _sent_here(client, "run-hold", {})

    assert signed.status_code == 200, signed.get_data(as_text=True)
    assert outside.status_code == 404, outside.get_data(as_text=True)
