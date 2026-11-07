"""``reset-db`` stops the server runs a test left going, and waits for them.

The e2e harness resets the database between tests (``POST
/api/testing/reset-db``). A test can end while its run on the server is still
going. In job 128307293769 (run 42340566115, test-gpu shard 4), run fff306f0
was still in example 09's UTCI node when the next test's reset came at
05:24:46. The node ended at 05:24:54, and the run then failed on the emptied
tables (``NotFoundError: run ... has no step for node ea821796``). Until then
the node held its shard's sandbox, which runs one Python node at a time
without isolation, so the next test's nodes waited behind it.

The sandbox here is a fake behind ``node_exec.sandbox_request`` whose node
sleeps. Like a real node, it runs on whatever happens to its run, so a reset
can only stop the run's next nodes and wait for the one running. The database
is a file, so each thread has its own connection. Nothing opens a socket.
"""
from __future__ import annotations

import contextlib
import json
import logging
import threading
import time

import pytest
from sqlalchemy import event, text

CODE = "curio.builtin/python-computation"
#: How long the node a reset finds running sleeps: well inside the reset's
#: bound, and long past the reset on a checkout whose reset does not wait.
SLOW_SECONDS = 5.0
#: The longest a test waits for a node to reach the sandbox.
STEP_SECONDS = 15.0
#: The longest a test waits for a run's thread to end.
JOIN_SECONDS = 60.0
ROUTES_LOGGER = "utk_curio.backend.app.testing.routes"


class SleepingSandbox:
    """Answers ``/exec`` with an artifact named after the node, once the node
    has slept its seconds (*sleeps*) or, for a node with a gate, once the test
    opens it. It runs any number of nodes at once and records, for each node,
    how many others were running when it came: the sandbox without isolation
    runs one Python node at a time, so a node that finds another there waits
    for it."""

    def __init__(self):
        self.sleeps: dict[str, float] = {}
        self.found_running: dict[str, int] = {}
        self._gates: dict[str, threading.Event] = {}
        self._started: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._running = 0

    def started(self, node_id: str) -> threading.Event:
        """Set once *node_id* has reached the sandbox."""
        with self._lock:
            return self._started.setdefault(node_id, threading.Event())

    def gate(self, node_id: str) -> threading.Event:
        """Keep *node_id* running in the sandbox until the returned gate opens."""
        with self._lock:
            return self._gates.setdefault(node_id, threading.Event())

    def open_gates(self) -> None:
        with self._lock:
            gates = list(self._gates.values())
        for gate in gates:
            gate.set()

    def __call__(self, method, path, **kwargs):
        body = json.loads(kwargs["data"])
        # The marker names the node in the request, which carries no id.
        node_id = body["code"].split("# node ", 1)[1].split("\n", 1)[0]
        with self._lock:
            self.found_running[node_id] = self._running
            self._running += 1
            started = self._started.setdefault(node_id, threading.Event())
            gate = self._gates.get(node_id)
        started.set()
        try:
            if gate is not None:
                assert gate.wait(timeout=JOIN_SECONDS), "the test never opened the gate"
            else:
                time.sleep(self.sleeps.get(node_id, 0.0))
        finally:
            with self._lock:
                self._running -= 1

        class Reply:
            status_code = 200
            text = ""

            def json(self):
                return {"stdout": [f"ran {node_id}"], "stderr": "",
                        "output": {"path": f"art-{node_id}", "dataType": "dataframe"}}

        return Reply()


@pytest.fixture()
def sandbox(monkeypatch):
    from utk_curio.backend import config
    from utk_curio.backend.app.runs import jobs, viewer

    # Nothing is installed: the fake artifacts are not files.
    monkeypatch.setattr(config, "CURIO_DEFAULT_SAVE_NODE_OUTPUT", False)
    # No run of another test for a reset here to find.
    jobs.REGISTRY.reset()
    viewer.reset()
    fake = SleepingSandbox()
    monkeypatch.setattr("utk_curio.backend.app.execution.node_exec.sandbox_request", fake)
    yield fake
    fake.open_gates()
    jobs.REGISTRY.reset()
    viewer.reset()


@pytest.fixture()
def errors_logged():
    """The messages the testing routes log at error level from now on."""
    messages: list[str] = []

    class _Keep(logging.Handler):
        def emit(self, record):
            messages.append(record.getMessage())

    logger = logging.getLogger(ROUTES_LOGGER)
    handler = _Keep(level=logging.ERROR)
    logger.addHandler(handler)
    yield messages
    logger.removeHandler(handler)


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _node(node_id):
    return {"id": node_id, "type": CODE, "content": f"# node {node_id}\nreturn input_0"}


def _edge(source, target):
    return {"id": f"{source}-{target}", "source": source, "target": target}


def _create(client, token, nodes, edges=()):
    resp = client.post("/api/projects", data=json.dumps({
        "name": "Reset stops runs",
        "spec": {"dataflow": {"name": "Reset stops runs", "nodes": list(nodes), "edges": list(edges)}},
        "outputs": [],
    }), headers=_auth(token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def _start(client, token, project_id):
    """Start a run of the whole dataflow and return the job that holds it."""
    from utk_curio.backend.app.runs import jobs

    resp = client.post(f"/api/projects/{project_id}/runs", data="{}", headers=_auth(token))
    assert resp.status_code == 202, resp.get_data(as_text=True)
    job = jobs.REGISTRY.get_job(resp.get_json()["id"])
    assert job is not None, "no job holds the run"
    return job


def _sign_in(client, username):
    """A new account's token, as the next test signs in after a reset."""
    resp = client.post("/api/testing/stub-login", data=json.dumps({"username": username}),
                       content_type="application/json")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()["token"]


def _reset(client):
    return client.post("/api/testing/reset-db", data="{}", content_type="application/json")


def _join(*jobs):
    """Wait for each run's thread to end, then end this thread's read so it
    sees what they committed."""
    from utk_curio.backend.extensions import db

    for job in jobs:
        if job.thread is not None:
            job.thread.join(timeout=JOIN_SECONDS)
    db.session.rollback()


def _count(table: str) -> int:
    from utk_curio.backend.extensions import db

    db.session.rollback()
    return db.session.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar()


class _AfterTheDelete:
    """What a run did once a reset emptied the run tables: whether its thread
    still ran at that moment, and each write of its record it made after."""

    def __init__(self, monkeypatch, job):
        from utk_curio.backend.app.runs import repositories as runs_repo

        self.job = job
        self.alive_at_delete = None
        self.writes: list = []
        self._deleted = threading.Event()
        for name in ("update_step", "update_run"):
            monkeypatch.setattr(runs_repo, name, self._recorded(name, getattr(runs_repo, name)))

    def _recorded(self, name, real):
        def recorded(run_id, *args, **fields):
            if run_id == self.job.job_id and self._deleted.is_set():
                self.writes.append((name, *args, fields.get("status")))
            return real(run_id, *args, **fields)
        return recorded

    @contextlib.contextmanager
    def watching(self):
        from utk_curio.backend.extensions import db

        def observe(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.strip().upper() == 'DELETE FROM "DATAFLOW_RUN_STEP"' and not self._deleted.is_set():
                self.alive_at_delete = self.job.thread.is_alive()
                self._deleted.set()

        engine = db.engine
        event.listen(engine, "before_cursor_execute", observe)
        try:
            yield self
        finally:
            event.remove(engine, "before_cursor_execute", observe)


def test_a_reset_stops_a_run_and_waits_for_its_node_before_it_deletes(
    client, user_and_token, sandbox, monkeypatch,
):
    """Alice's run is in its first node, which sleeps, when a reset comes.
    The reset must stop the run, so its next node never starts, and wait for
    the node running before it deletes anything: the run writes nothing of its
    record after the run tables are emptied, and it ends cancelled, not failed
    on tables that are gone."""
    _user, token = user_and_token
    sandbox.sleeps["slow"] = SLOW_SECONDS
    project_id = _create(client, token, [_node("slow"), _node("after")], [_edge("slow", "after")])
    job = _start(client, token, project_id)
    after_the_delete = _AfterTheDelete(monkeypatch, job)
    try:
        assert sandbox.started("slow").wait(STEP_SECONDS), "the run's first node never reached the sandbox"
        with after_the_delete.watching():
            response = _reset(client)
    finally:
        _join(job)

    assert response.status_code == 200, response.get_data(as_text=True)
    assert after_the_delete.alive_at_delete is False, (
        "the reset emptied the run tables while the run's thread still ran"
        if after_the_delete.alive_at_delete else "the reset never emptied the run tables"
    )
    assert after_the_delete.writes == [], f"the run wrote its record after the reset: {after_the_delete.writes}"
    assert "after" not in sandbox.found_running, "the run started its next node after the reset stopped it"
    events = list(job.events)
    assert job.status == "done", f"the run's thread ended {job.status}: {events[-1:]}"
    steps = {payload["nodeId"]: payload["status"] for kind, payload in events if kind == "step_finished"}
    assert steps == {"slow": "cancelled", "after": "cancelled"}, steps
    assert events[-1][0] == "run_finished" and events[-1][1]["status"] == "cancelled", events[-1]
    assert response.get_json().get("runs") == [f"run {job.job_id}"], response.get_json()


def test_the_next_run_after_a_reset_finds_the_sandbox_idle(client, user_and_token, sandbox):
    """After a reset, the next test signs in afresh and runs a dataflow of its
    own. Its node must find the sandbox idle, not still running a node of the
    run the last test left going."""
    _user, token = user_and_token
    sandbox.sleeps["slow"] = SLOW_SECONDS
    started = [_start(client, token, _create(client, token, [_node("slow")]))]
    try:
        assert sandbox.started("slow").wait(STEP_SECONDS), "the run's node never reached the sandbox"
        response = _reset(client)
        assert response.status_code == 200, response.get_data(as_text=True)
        bea = _sign_in(client, "bea")
        started.append(_start(client, bea, _create(client, bea, [_node("quick")])))
        assert sandbox.started("quick").wait(STEP_SECONDS), "the next run's node never reached the sandbox"
    finally:
        _join(*started)

    found = sandbox.found_running.get("quick")
    assert found == 0, (
        f"the next run's node found {found} node(s) of the last test's run still running in the sandbox"
    )


def test_a_run_still_going_past_the_bound_is_named_and_nothing_is_deleted(
    client, user_and_token, sandbox, monkeypatch, errors_logged,
):
    """A node that outlasts the reset's bound keeps its run going. The reset
    must not empty the tables under it: it refuses, naming the run and the
    node it runs, and logs that as an error. Once the run has ended, the next
    reset goes ahead."""
    from utk_curio.backend.app.testing import routes as testing_routes

    bound = 0.5
    # raising=False: the bound is part of what this pins.
    monkeypatch.setattr(testing_routes, "RESET_WAIT_SECONDS", bound, raising=False)
    _user, token = user_and_token
    gate = sandbox.gate("slow")
    job = _start(client, token, _create(client, token, [_node("slow")]))
    try:
        assert sandbox.started("slow").wait(STEP_SECONDS), "the run's node never reached the sandbox"
        began = time.monotonic()
        refused = _reset(client)
        took = time.monotonic() - began
        live_after = job.live
        left = _count("user"), _count("dataflow_run")
    finally:
        gate.set()
        _join(job)
    second = _reset(client)

    assert refused.status_code == 409, (
        f"the reset answered {refused.status_code} with run {job.job_id} still going: "
        f"{refused.get_data(as_text=True)[:500]}"
    )
    answer = refused.get_json()
    going = answer.get("runs_still_going") or []
    assert len(going) == 1 and going[0].startswith(f"run {job.job_id}") and "slow" in going[0], answer
    assert job.job_id in answer.get("error", ""), answer
    assert live_after, "the reset answered only once the run had ended"
    assert left == (1, 1), f"the reset deleted under a live run: {left[0]} user(s) and {left[1]} run(s) left"
    assert bound * 0.9 <= took < STEP_SECONDS, f"the reset took {took:.2f} s"
    assert any(job.job_id in message for message in errors_logged), (
        f"no error logged names the run: {errors_logged}"
    )
    assert second.status_code == 200, second.get_data(as_text=True)
    again = second.get_json()
    assert again.get("runs") == [] and again.get("runs_still_going") == [], again
    assert _count("user") == 0
