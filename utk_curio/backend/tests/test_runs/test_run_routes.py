"""Runs on the server through their routes: a run goes on with no browser
following it, records what each node did, and is refused where a save would be.

The sandbox is a fake behind ``node_exec.sandbox_request``; a gate can hold a
node open so a test can act while the run is going. ``runs`` is imported inside
each test, so a checkout without it fails each test on its own.
"""
from __future__ import annotations

import json
import threading

import pytest

CODE = "curio.builtin/computation-analysis"


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _node(node_id, node_type=CODE, **fields):
    # The marker names the node in the sandbox request, which carries no id.
    return {"id": node_id, "type": node_type, "content": f"# node {node_id}\nreturn arg", **fields}


def _edge(source, target):
    return {"id": f"{source}-{target}", "source": source, "target": target}


def _create(client, token, nodes, edges=(), name="Run routes"):
    resp = client.post("/api/projects", data=json.dumps({
        "name": name,
        "spec": {"dataflow": {"name": name, "nodes": list(nodes), "edges": list(edges)}},
        "outputs": [],
    }), headers=_auth(token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"], resp.get_json()["spec_revision"]


class FakeSandbox:
    """Answers ``/exec`` with an artifact named after the node; *hold* keeps
    the named nodes running until :meth:`release`."""

    def __init__(self, hold=(), fail=()):
        self.hold = set(hold)
        self.fail = set(fail)
        self.gate = threading.Event()
        self.started = threading.Event()
        self.bodies = {}

    def release(self):
        self.gate.set()

    def __call__(self, method, path, **kwargs):
        body = json.loads(kwargs["data"])
        node_id = body["code"].split("# node ", 1)[1].split("\n", 1)[0]
        self.bodies[node_id] = body
        self.started.set()
        if node_id in self.hold:
            assert self.gate.wait(timeout=30), "the test never released the gate"

        class Reply:
            status_code = 200
            text = ""

            def json(_self):
                if node_id in self.fail:
                    return {"stdout": [], "stderr": "Traceback: boom", "output": {"path": "", "dataType": "str"}}
                return {"stdout": [f"ran {node_id}"], "stderr": "",
                        "output": {"path": f"art-{node_id}", "dataType": "dataframe"}}

        return Reply()


@pytest.fixture()
def sandbox(monkeypatch):
    from utk_curio.backend import config
    from utk_curio.backend.app.runs import jobs

    # Nothing is installed unless a test says so: the fake artifacts are not files.
    monkeypatch.setattr(config, "CURIO_DEFAULT_SAVE_NODE_OUTPUT", False)
    jobs.REGISTRY.reset()
    fake = FakeSandbox()
    monkeypatch.setattr("utk_curio.backend.app.execution.node_exec.sandbox_request", fake)
    yield fake
    fake.release()


def _start(client, token, project_id, **body):
    return client.post(f"/api/projects/{project_id}/runs", data=json.dumps(body), headers=_auth(token))


def _wait(run_id):
    from utk_curio.backend.app.runs import jobs
    from utk_curio.backend.extensions import db

    job = jobs.REGISTRY.get_job(run_id)
    assert job is not None
    job.thread.join(timeout=30)
    assert not job.thread.is_alive()
    # End this thread's read, so it sees what the run's threads committed.
    db.session.rollback()
    return job


def _get(client, token, run_id):
    resp = client.get(f"/api/runs/{run_id}", headers=_auth(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


def _events(client, token, run_id):
    resp = client.get(f"/api/runs/{run_id}/stream", headers=_auth(token))
    assert resp.status_code == 200
    events = []
    for block in resp.get_data(as_text=True).strip().split("\n\n"):
        kind = block.split("\n", 1)[0].removeprefix("event: ")
        data = json.loads(block.split("data: ", 1)[1])
        events.append((kind, data))
    return events


class TestARunGoesOnWithNoBrowser:
    def test_it_runs_every_node_and_records_each_step(self, client, user_and_token, sandbox):
        user, token = user_and_token
        project_id, revision = _create(client, token, [_node("a"), _node("b")], [_edge("a", "b")])

        started = _start(client, token, project_id, specRevision=revision)
        assert started.status_code == 202, started.get_data(as_text=True)
        run_id = started.get_json()["id"]
        assert [s["nodeId"] for s in started.get_json()["steps"]] == ["a", "b"]
        _wait(run_id)

        run = _get(client, token, run_id)
        assert run["status"] == "succeeded" and run["wholeDataflow"] is True
        assert run["counts"] == {"ok": 2, "failed": 0, "skipped": 0, "waiting": 0}
        steps = {s["nodeId"]: s for s in run["steps"]}
        assert steps["b"]["status"] == "ok" and steps["b"]["outputPath"] == "art-b"
        assert steps["b"]["stdoutTail"] == "ran b" and steps["b"]["codeSha256"]
        # b read a's output, as Play would have sent it.
        assert sandbox.bodies["b"]["file_path"] == "art-a"

    def test_its_artifacts_carry_the_starting_session_and_nothing_stores_it(self, client, db, user_and_token, sandbox):
        from utk_curio.backend.app.runs import jobs
        from utk_curio.backend.app.runs.models import DataflowRun, DataflowRunStep

        user, token = user_and_token
        project_id, _ = _create(client, token, [_node("a")])
        run_id = _start(client, token, project_id).get_json()["id"]
        job = _wait(run_id)

        assert sandbox.bodies["a"]["session_id"] == token
        rows = db.session.query(DataflowRun).all() + db.session.query(DataflowRunStep).all()
        stored = repr([{c.name: getattr(r, c.name) for c in r.__table__.columns} for r in rows])
        assert token not in stored
        assert token not in json.dumps(list(job.events), default=str)
        assert token not in json.dumps(_events(client, token, run_id))

    def test_closing_the_stream_does_not_stop_the_run(self, client, user_and_token, sandbox):
        from utk_curio.backend.app.runs import jobs

        user, token = user_and_token
        sandbox.hold = {"a"}
        project_id, _ = _create(client, token, [_node("a"), _node("b")], [_edge("a", "b")])
        run_id = _start(client, token, project_id).get_json()["id"]
        follower = jobs.REGISTRY.subscribe(jobs.REGISTRY.get_job(run_id))
        assert next(follower)[0] == "run_started"
        follower.close()  # the browser went away

        sandbox.release()
        _wait(run_id)
        run = _get(client, token, run_id)
        assert run["status"] == "succeeded"
        assert {s["status"] for s in run["steps"]} == {"ok"}

    def test_the_stream_replays_the_run_in_order_held_or_not(self, client, user_and_token, sandbox):
        from utk_curio.backend.app.runs import jobs

        user, token = user_and_token
        project_id, _ = _create(client, token, [_node("a"), _node("b")], [_edge("a", "b")])
        run_id = _start(client, token, project_id).get_json()["id"]
        _wait(run_id)

        live = _events(client, token, run_id)
        assert live[0][0] == "run" and live[0][1]["id"] == run_id
        assert [k for k, _ in live[1:]] == [
            "run_started", "step_started", "step_finished", "step_started", "step_finished", "run_finished",
        ]
        assert [p["nodeId"] for k, p in live if k == "step_finished"] == ["a", "b"]

        jobs.REGISTRY.reset()  # the process no longer holds it: rebuilt from the steps
        rebuilt = _events(client, token, run_id)
        assert [k for k, _ in rebuilt] == ["run", "run_started", "step_finished", "step_finished", "run_finished"]
        assert rebuilt[-1][1]["status"] == "succeeded"


class TestRefusals:
    def test_a_second_start_while_it_runs_names_the_running_run(self, client, user_and_token, sandbox):
        user, token = user_and_token
        sandbox.hold = {"a"}
        project_id, _ = _create(client, token, [_node("a")])
        first = _start(client, token, project_id).get_json()["id"]
        assert sandbox.started.wait(timeout=10)

        second = _start(client, token, project_id)
        assert second.status_code == 409
        assert second.get_json()["runId"] == first
        sandbox.release()
        _wait(first)

    def test_an_account_runs_at_most_two_dataflows_at_once(self, client, user_and_token, sandbox):
        user, token = user_and_token
        sandbox.hold = {"a"}
        held = [_create(client, token, [_node("a")], name=f"Held {i}")[0] for i in range(2)]
        runs = [_start(client, token, pid).get_json()["id"] for pid in held]
        third, _ = _create(client, token, [_node("b")], name="Third")

        assert _start(client, token, third).status_code == 429
        sandbox.release()
        for run_id in runs:
            _wait(run_id)

    def test_a_revision_that_is_not_the_saved_one_is_refused(self, client, user_and_token, sandbox):
        user, token = user_and_token
        project_id, revision = _create(client, token, [_node("a")])
        resp = _start(client, token, project_id, specRevision=revision + 7)
        assert resp.status_code == 409 and resp.get_json()["specRevision"] == revision

    def test_another_users_runs_and_dataflows_are_not_found(self, client, db, user_and_token, sandbox):
        from utk_curio.backend.app.users.models import User, UserSession

        user, token = user_and_token
        project_id, _ = _create(client, token, [_node("a")])
        run_id = _start(client, token, project_id).get_json()["id"]
        _wait(run_id)
        other = User(username="bob", name="Bob", email="bob@test.com")
        db.session.add(other)
        db.session.flush()
        db.session.add(UserSession(user_id=other.id, token="bob-token"))
        db.session.commit()

        assert client.get(f"/api/runs/{run_id}", headers=_auth("bob-token")).status_code == 404
        assert client.get(f"/api/runs/{run_id}/stream", headers=_auth("bob-token")).status_code == 404
        assert _start(client, "bob-token", project_id).status_code == 404
        assert client.get("/api/runs", headers=_auth("bob-token")).get_json()["runs"] == []

    def test_a_hosted_guest_runs_in_the_browser(self, client, guest_user_and_token, sandbox, monkeypatch):
        from utk_curio.backend import config

        monkeypatch.setattr(config, "CURIO_NO_AUTH", False)
        _, token = guest_user_and_token
        resp = _start(client, token, "any-dataflow")
        assert resp.status_code == 403 and "guest" in resp.get_json()["error"]


class TestRunningUpToANode:
    def test_only_the_node_and_the_ancestors_not_reused_run(self, client, user_and_token, sandbox):
        user, token = user_and_token
        project_id, _ = _create(
            client, token, [_node("a"), _node("b"), _node("c")], [_edge("a", "b"), _edge("b", "c")],
        )
        run_id = _start(
            client, token, project_id,
            target="b", reuse={"a": {"path": "art-a-kept", "dataType": "dataframe"}},
        ).get_json()["id"]
        _wait(run_id)

        run = _get(client, token, run_id)
        assert run["trigger"] == "node" and run["targetNodeId"] == "b" and run["wholeDataflow"] is False
        assert [s["nodeId"] for s in run["steps"]] == ["b"]
        assert sandbox.bodies["b"]["file_path"] == "art-a-kept"
        assert set(sandbox.bodies) == {"b"}

    def test_run_again_repeats_what_the_run_ran(self, client, user_and_token, sandbox):
        user, token = user_and_token
        project_id, _ = _create(client, token, [_node("a"), _node("b")], [_edge("a", "b")])
        first = _start(client, token, project_id, target="b").get_json()["id"]
        _wait(first)

        again = client.post(f"/api/runs/{first}/rerun", headers=_auth(token))
        assert again.status_code == 202
        body = again.get_json()
        assert body["rerunOf"] == first and body["trigger"] == "rerun" and body["targetNodeId"] == "b"
        _wait(body["id"])


class TestCancel:
    def test_cancel_stops_before_the_next_node(self, client, user_and_token, sandbox):
        user, token = user_and_token
        sandbox.hold = {"a"}
        project_id, _ = _create(client, token, [_node("a"), _node("b")], [_edge("a", "b")])
        run_id = _start(client, token, project_id).get_json()["id"]
        assert sandbox.started.wait(timeout=10)

        assert client.post(f"/api/runs/{run_id}/cancel", headers=_auth(token)).status_code == 202
        sandbox.release()
        _wait(run_id)

        run = _get(client, token, run_id)
        assert run["status"] == "cancelled"
        assert {s["nodeId"]: s["status"] for s in run["steps"]} == {"a": "cancelled", "b": "cancelled"}
        assert "b" not in sandbox.bodies
        assert client.post(f"/api/runs/{run_id}/cancel", headers=_auth(token)).status_code == 409


class TestRestarts:
    def test_a_run_an_earlier_process_left_going_is_interrupted(self, client, db, user_and_token, sandbox):
        from utk_curio.backend.app.runs import repositories as runs

        user, token = user_and_token
        project_id, _ = _create(client, token, [_node("a"), _node("b")])
        run = runs.create_run(
            project_id=project_id, user_id=user.id, trigger="all", boot_id="an-earlier-process",
            steps=[{"node_id": "a"}, {"node_id": "b"}],
        )
        runs.update_run(run.id, status="running")
        runs.update_step(run.id, "a", status="ok")

        body = _get(client, token, run.id)
        assert body["status"] == "interrupted" and body["error"]
        assert {s["nodeId"]: s["status"] for s in body["steps"]} == {"a": "ok", "b": "interrupted"}


class TestWhatARunSaves:
    def test_outputs_are_installed_and_recorded_as_the_canvas_would(self, client, user_and_token, sandbox, monkeypatch):
        from utk_curio.backend.app.datasets.application import auto_install
        from utk_curio.backend.app.projects import services as project_services

        monkeypatch.setattr(
            auto_install, "auto_install_node_output",
            lambda **kwargs: {"status": "skipped", "nodeId": kwargs.get("node_id")},
        )
        recorded = []
        monkeypatch.setattr(
            project_services, "record_node_outputs",
            lambda user, project_id, outputs: recorded.extend(o.node_id for o in outputs) or [],
        )
        user, token = user_and_token
        project_id, _ = _create(client, token, [
            _node("kept", saveOutputDataset=True),
            _node("plain"),
            _node("feeds", saveOutputDataset=False),
            {"id": "tile", "type": "curio.builtin/vis-vega", "content": "{}", "dashboardPinned": True},
        ], [_edge("feeds", "tile")])
        run_id = _start(client, token, project_id).get_json()["id"]
        _wait(run_id)

        assert sandbox.bodies["kept"]["save_dataset"] is True
        assert sandbox.bodies["plain"]["save_dataset"] is False
        assert sandbox.bodies["feeds"]["save_dataset"] is True  # a pinned tile reads it
        assert sorted(recorded) == ["feeds", "kept"]


class TestNodesTheBrowserRuns:
    def test_a_tab_finishes_what_waited_for_it(self, client, user_and_token, sandbox):
        user, token = user_and_token
        osm = {"id": "osm", "type": "curio.builtin/autk-grammar",
               "content": json.dumps({"data": [{"type": "osm"}]})}
        project_id, _ = _create(client, token, [osm, _node("count")], [_edge("osm", "count")])
        run_id = _start(client, token, project_id).get_json()["id"]
        _wait(run_id)
        assert _get(client, token, run_id)["status"] == "needs_canvas"

        def report(node_id, status):
            return client.post(
                f"/api/runs/{run_id}/steps/{node_id}",
                data=json.dumps({"status": status}), headers=_auth(token),
            )

        assert report("osm", "ok").status_code == 200
        done = report("count", "ok").get_json()
        assert done["status"] == "succeeded" and done["counts"]["waiting"] == 0

    def test_a_report_waits_for_the_servers_part_to_end(self, client, user_and_token, sandbox):
        # The run's own outcome is written when it ends; a report before that
        # would be overwritten by it.
        user, token = user_and_token
        sandbox.hold = {"slow"}
        osm = {"id": "osm", "type": "curio.builtin/autk-grammar",
               "content": json.dumps({"data": [{"type": "osm"}]})}
        project_id, _ = _create(client, token, [osm, _node("slow")])
        run_id = _start(client, token, project_id).get_json()["id"]
        assert sandbox.started.wait(timeout=10)

        early = client.post(
            f"/api/runs/{run_id}/steps/osm", data=json.dumps({"status": "ok"}), headers=_auth(token),
        )
        assert early.status_code == 409
        sandbox.release()
        _wait(run_id)
