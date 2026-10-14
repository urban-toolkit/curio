"""Published dashboards: the owner publishes a dataflow, and whoever holds the
link runs it with their own values for its pinned widgets.

The sandbox is faked (``test_run_routes.FakeSandbox``): each node's artifact is
named after it, and the request body it was sent is kept, so a test reads
which values reached the code and under which session the run wrote.
"""
from __future__ import annotations

import json

import pytest

from utk_curio.backend.tests.test_runs.test_run_routes import (
    CODE,
    FakeSandbox,
    _auth,
    _create,
    _edge,
)

WIDGETS = [
    {"name": "weight", "type": "slider", "label": "Rain weight", "default": 0.5,
     "options": {"min": 0, "max": 1, "step": 0.1}},
    {"name": "mode", "type": "choice", "label": "Mode", "default": "fast",
     "options": {"choices": ["fast", "safe"]}},
]


def _param_node():
    # The marker names the node in the sandbox request (FakeSandbox).
    return {
        "id": "p", "type": CODE, "dashboardPinned": True,
        "content": "# node p\nreturn [[!! weight !!], [!! mode !!]]",
        "metadata": {"widgets": [dict(w) for w in WIDGETS]},
    }


def _chart_node():
    return {"id": "c", "type": CODE, "dashboardPinned": True, "content": "# node c\nreturn input_0"}


@pytest.fixture()
def sandbox(monkeypatch):
    from utk_curio.backend import config
    from utk_curio.backend.app.published import service

    monkeypatch.setattr(config, "CURIO_DEFAULT_SAVE_NODE_OUTPUT", False)
    service.reset_for_tests()
    fake = FakeSandbox()
    monkeypatch.setattr("utk_curio.backend.app.execution.node_exec.sandbox_request", fake)
    yield fake
    fake.release()
    service.reset_for_tests()


@pytest.fixture()
def published(client, user_and_token, sandbox):
    _user, token = user_and_token
    project_id, _rev = _create(client, token, [_param_node(), _chart_node()], [_edge("p", "c")], name="Published")
    resp = client.put(f"/api/projects/{project_id}/publish", data=json.dumps({"access": "link"}), headers=_auth(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return project_id, resp.get_json()["published"]


def _run(client, link, inputs=None, headers=None):
    return client.post(
        f"/api/published/{link}/runs",
        data=json.dumps({"inputs": inputs} if inputs is not None else {}),
        headers=headers or {"Content-Type": "application/json"},
    )


def _wait(run_id):
    from utk_curio.backend.app.published.service import PUBLISHED_REGISTRY

    job = PUBLISHED_REGISTRY.get_job(run_id)
    assert job is not None
    job.thread.join(timeout=30)
    assert not job.thread.is_alive()


def _events(client, run_id, key):
    resp = client.get(f"/api/published/runs/{run_id}/stream?key={key}")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    events = []
    for block in resp.get_data(as_text=True).strip().split("\n\n"):
        kind = block.split("\n", 1)[0].removeprefix("event: ")
        events.append((kind, json.loads(block.split("data: ", 1)[1])))
    return events


# ---------------------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------------------

class TestPublishing:
    def test_the_owner_publishes_and_the_link_lists_the_pinned_widgets(self, client, published):
        project_id, pub = published
        assert pub["access"] == "link" and len(pub["token"]) >= 30
        assert [(i["nodeId"], i["name"], i["type"]) for i in pub["inputs"]] == [
            ("p", "weight", "slider"), ("p", "mode", "choice"),
        ]
        described = client.get(f"/api/published/{pub['token']}").get_json()
        assert described["projectId"] == project_id
        assert described["inputs"] == pub["inputs"]

    def test_publishing_again_keeps_the_link_and_unpublishing_ends_it(self, client, user_and_token, published):
        _user, token = user_and_token
        project_id, pub = published
        again = client.put(f"/api/projects/{project_id}/publish", data=json.dumps({"access": "signed-in"}), headers=_auth(token))
        assert again.get_json()["published"]["token"] == pub["token"]
        assert again.get_json()["published"]["access"] == "signed-in"

        assert client.delete(f"/api/projects/{project_id}/publish", headers=_auth(token)).status_code == 204
        assert client.get(f"/api/published/{pub['token']}").status_code == 404
        assert client.get(f"/api/projects/{project_id}/publish", headers=_auth(token)).get_json()["published"] is None

    def test_only_the_owner_publishes(self, client, published, guest_user_and_token):
        project_id, _pub = published
        _guest, guest_token = guest_user_and_token
        resp = client.put(f"/api/projects/{project_id}/publish", data="{}", headers=_auth(guest_token))
        assert resp.status_code in (403, 404)

    def test_a_dashboard_with_nothing_pinned_is_refused(self, client, user_and_token, sandbox):
        _user, token = user_and_token
        project_id, _ = _create(client, token, [{"id": "a", "type": CODE, "content": "# node a\nreturn 1"}])
        resp = client.put(f"/api/projects/{project_id}/publish", data="{}", headers=_auth(token))
        assert resp.status_code == 422 and "Pin at least one node" in resp.get_json()["error"]

    def test_a_dataflow_that_saves_files_is_refused(self, client, user_and_token, sandbox):
        _user, token = user_and_token
        node = {**_chart_node(), "content": "# node c\ncurio_save_folder('tiles')\nreturn 1"}
        project_id, _ = _create(client, token, [node])
        resp = client.put(f"/api/projects/{project_id}/publish", data="{}", headers=_auth(token))
        assert resp.status_code == 422 and "saves files" in resp.get_json()["error"]

    def test_an_unknown_link_is_not_found(self, client, sandbox):
        assert client.get("/api/published/not-a-link").status_code == 404
        assert _run(client, "not-a-link").status_code == 404


# ---------------------------------------------------------------------------
# Running from the link
# ---------------------------------------------------------------------------

class TestRunningFromTheLink:
    def test_a_visitor_runs_it_with_their_values_as_the_owner_saving_nothing(self, client, published, sandbox, monkeypatch):
        from utk_curio.backend.app.execution import node_exec

        recorded = []
        monkeypatch.setattr(node_exec, "record_runtime_outcome", lambda *a, **k: recorded.append(k))
        monkeypatch.setattr(node_exec, "install_saved_files", lambda *a, **k: recorded.append("saved"))
        _project_id, pub = published

        resp = _run(client, pub["token"], {"p": {"weight": 0.9, "mode": "safe"}})
        assert resp.status_code == 202, resp.get_data(as_text=True)
        started = resp.get_json()
        assert started["cached"] is False
        _wait(started["runId"])

        # The viewer's values reached the code, and nothing was recorded.
        assert "return [0.9, \"safe\"]" in sandbox.bodies["p"]["code"]
        assert sandbox.bodies["p"]["save_dataset"] is False
        assert sandbox.bodies["p"]["session_id"] == started["key"]
        assert recorded == []

        events = _events(client, started["runId"], started["key"])
        kinds = [k for k, _ in events]
        assert kinds[0] == "run" and kinds[-1] == "run_finished"
        finished = [p for k, p in events if k == "step_finished"]
        assert {p["nodeId"]: p["status"] for p in finished} == {"p": "ok", "c": "ok"}
        # Outputs reach the viewer; logs do not.
        for payload in finished:
            assert "stdoutTail" not in payload and "stderrTail" not in payload
            assert payload["reply"]["stdout"] == []
        run = client.get(f"/api/published/runs/{started['runId']}?key={started['key']}").get_json()
        assert run["status"] == "succeeded"

    def test_the_same_values_reuse_the_last_run(self, client, published, sandbox):
        _pid, pub = published
        first = _run(client, pub["token"], {"p": {"weight": 0.2}}).get_json()
        _wait(first["runId"])
        again = _run(client, pub["token"], {"p": {"weight": 0.2}}).get_json()
        assert again == {**first, "cached": True}
        other = _run(client, pub["token"], {"p": {"weight": 0.3}}).get_json()
        assert other["runId"] != first["runId"] and other["cached"] is False
        _wait(other["runId"])

    @pytest.mark.parametrize("inputs, message", [
        ({"p": {"weight": 2}}, "within its range"),
        ({"p": {"weight": "0.5"}}, "a number"),
        ({"p": {"mode": "reckless"}}, "one of its choices"),
        ({"p": {"code": "import os"}}, "not an input"),
        ({"c": {"weight": 0.1}}, "not an input"),
        ({"p": "weight=1"}, "must map"),
    ])
    def test_values_a_widget_could_not_hold_are_refused(self, client, published, inputs, message):
        _pid, pub = published
        resp = _run(client, pub["token"], inputs)
        assert resp.status_code == 422 and message in resp.get_json()["error"]

    def test_signed_in_only_needs_a_signed_in_account(self, client, user_and_token, published, sandbox):
        _user, token = user_and_token
        project_id, pub = published
        client.put(f"/api/projects/{project_id}/publish", data=json.dumps({"access": "signed-in"}), headers=_auth(token))
        assert _run(client, pub["token"]).status_code == 401
        signed_in = _run(client, pub["token"], headers=_auth(token))
        assert signed_in.status_code == 202
        _wait(signed_in.get_json()["runId"])

    def test_one_address_is_rate_limited(self, client, published, sandbox, monkeypatch):
        from utk_curio.backend.app.published import service

        monkeypatch.setattr(service, "ADDRESS_BURST", 2)
        _pid, pub = published
        statuses = []
        for weight in (0.1, 0.2, 0.3):
            resp = _run(client, pub["token"], {"p": {"weight": weight}})
            statuses.append(resp.status_code)
            if resp.status_code == 202:
                _wait(resp.get_json()["runId"])
        assert statuses == [202, 202, 429]

    def test_a_run_needs_its_key(self, client, published, sandbox):
        _pid, pub = published
        started = _run(client, pub["token"]).get_json()
        _wait(started["runId"])
        assert client.get(f"/api/published/runs/{started['runId']}?key=wrong").status_code == 404
        assert client.get(f"/api/published/runs/{started['runId']}/stream").status_code == 404


class TestArtifacts:
    def test_only_the_runs_own_artifacts_are_served_under_its_key(self, client, published, sandbox, monkeypatch):
        from utk_curio.backend.app.api import routes as api_routes

        asked = []

        class Reply:
            ok = True
            status_code = 200
            content = b'{"dataType": "dataframe", "data": {}}'
            headers = {"Content-Type": "application/json"}

            def json(self):
                return json.loads(self.content)

        def fake_call(method, path, **kwargs):
            asked.append(kwargs["params"])
            return Reply()

        monkeypatch.setattr(api_routes, "_sandbox_call", fake_call)
        _pid, pub = published
        started = _run(client, pub["token"]).get_json()
        _wait(started["runId"])
        base = f"/api/published/runs/{started['runId']}"

        ok = client.get(f"{base}/get?key={started['key']}&fileName=art-c")
        assert ok.status_code == 200
        assert asked == [{"fileName": "art-c", "sessionId": started["key"]}]
        # Another run's, or anyone else's, artifact is not.
        assert client.get(f"{base}/get?key={started['key']}&fileName=someone-elses").status_code == 404
        assert client.get(f"{base}/get?key=wrong&fileName=art-c").status_code == 404

    def test_a_bundles_parts_may_be_read_once_the_bundle_was(self, client, published, sandbox, monkeypatch):
        from utk_curio.backend.app.api import routes as api_routes

        class Reply:
            ok = True
            status_code = 200
            headers = {"Content-Type": "application/json"}

            def __init__(self, body):
                self.content = json.dumps(body).encode()

            def json(self):
                return json.loads(self.content)

        def fake_call(method, path, **kwargs):
            if kwargs["params"]["fileName"] == "art-c":
                return Reply({"dataType": "outputs", "data": [{"path": "part-1"}, {"path": "part-2"}]})
            return Reply({"dataType": "dataframe", "data": {}})

        monkeypatch.setattr(api_routes, "_sandbox_call", fake_call)
        _pid, pub = published
        started = _run(client, pub["token"]).get_json()
        _wait(started["runId"])
        base = f"/api/published/runs/{started['runId']}"
        assert client.get(f"{base}/get?key={started['key']}&fileName=part-1").status_code == 404
        assert client.get(f"{base}/get?key={started['key']}&fileName=art-c").status_code == 200
        assert client.get(f"{base}/get?key={started['key']}&fileName=part-1").status_code == 200


class TestCheckingValues:
    @pytest.mark.parametrize("widget, value, ok", [
        ({"type": "number", "options": {}}, 3, True),
        ({"type": "number", "options": {}}, True, False),
        ({"type": "slider", "options": {"min": 0, "max": 1}}, 1.5, False),
        ({"type": "checkbox"}, False, True),
        ({"type": "text"}, "x" * 3000, False),
        ({"type": "checkbox-group", "options": {"choices": ["a", "b"]}}, ["a"], True),
        ({"type": "checkbox-group", "options": {"choices": ["a", "b"]}}, ["c"], False),
        ({"type": "datetime"}, "2025-07-06T00:00", True),
        ({"type": "datetime"}, "tomorrow", False),
        ({"type": "location"}, {"lat": 41.9, "lon": -87.6}, True),
        ({"type": "location"}, {"lat": 141.9, "lon": -87.6}, False),
        ({"type": "range", "options": {"min": 0, "max": 10}}, [2, 5], True),
        ({"type": "range", "options": {"min": 0, "max": 10}}, [5, 2], False),
        ({"type": "file"}, "/etc/passwd", False),
    ])
    def test_each_kind(self, widget, value, ok):
        from utk_curio.backend.app.published.service import value_problem

        assert (value_problem(widget, value) is None) is ok
