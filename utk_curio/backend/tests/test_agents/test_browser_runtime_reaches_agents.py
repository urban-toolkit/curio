"""dev/135: the owner's `a29d1ad8`, end to end.

A Vega-Lite node fails to render in the BROWSER; the client reports it; and
every agent path that asks about that node is then told what happened. This is
the test that fails before dev/135 — the journal had three writers and all
three were the sandbox, so the Node Builder attached to a visibly red node
answered *"since the node has never been executed, there are no runtime errors
to diagnose"*.
"""

from __future__ import annotations

import json

from utk_curio.backend.app.agents import node_context
from utk_curio.backend.app.execution import runtime_journal
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.tests.test_agents import test_routes as _tr

_auth = _tr._auth

VEGA = "curio.builtin/vis-vega"
POOL = "curio.builtin/data-pool"
VEGA_ERROR = "outputs is not a valid input type for the 2D Plot (Vega-Lite)"
GRAMMAR = '{"$schema": "https://vega.github.io/schema/vega-lite/v6.json", "mark": "bar"}'


def _project_with_a_failing_chart(client, token):
    """A pool feeding a Vega node — the owner's shape, minus the dataflow."""
    spec = {"dataflow": {"nodes": [
        {"id": "pool-1", "type": POOL, "goal": "Chicago Data Pool", "content": "",
         "x": 0, "y": 0},
        {"id": "vega-1", "type": VEGA, "goal": "Density Ranking Chart",
         "content": GRAMMAR, "x": 100, "y": 0},
    ], "edges": [
        {"id": "e1", "source": "pool-1", "target": "vega-1"},
    ], "packages": []}}
    body = {"name": "p", "spec": spec, "outputs": []}
    return client.post("/api/projects", json=body, headers=_auth(token)).get_json()["id"]


def _report(client, token, pid, node_id, **body):
    return client.post("/nodeRuntime", json={
        "dataflowId": pid, "nodeId": node_id, **body,
    }, headers=_auth(token))


class TestABrowserFailureReachesEveryAgentPath:
    def test_the_node_context_a_delegated_child_reads_carries_the_message(
        self, client, user_and_token, tmp_curio
    ):
        user, token = user_and_token
        pid = _project_with_a_failing_chart(client, token)
        key = _user_dir_key(user)

        # Before the report: exactly what the owner's agent was told.
        before = node_context.compose_node_context(key, pid, _spec(client, token, pid), "vega-1")
        assert before["runtimeStatus"] == "never-executed"
        assert before["runtime"] == {"status": "never-executed"}

        # The node reports its own render failure, as the client now does.
        assert _report(client, token, pid, "vega-1", status="error",
                       message=VEGA_ERROR, durationMs=9, code=GRAMMAR).status_code == 204

        after = node_context.compose_node_context(key, pid, _spec(client, token, pid), "vega-1")
        assert after["runtimeStatus"] == "error"
        assert after["runtime"]["message"] == VEGA_ERROR
        assert after["runtime"]["origin"] == "browser"
        # The context a delegated node.content.generate receives is this same
        # composition, so the child can no longer be told the node never ran.
        assert "never-executed" not in json.dumps(after["runtime"])

    def test_the_repair_loop_can_start_from_it(self, client, user_and_token, tmp_curio):
        """dev/129 F2 / dev/131 F3: a session can now repair a browser-side
        failure, because `last_failure` sees one and digest-matches the content
        the node still holds."""
        user, token = user_and_token
        pid = _project_with_a_failing_chart(client, token)
        key = _user_dir_key(user)
        _report(client, token, pid, "vega-1", status="error", message=VEGA_ERROR,
                code=GRAMMAR)
        failure = runtime_journal.last_failure(key, pid, "vega-1")
        assert failure["origin"] == "browser"
        assert failure["stderr"] == VEGA_ERROR
        assert runtime_journal.failure_matches(failure, GRAMMAR) is True
        # And a node whose grammar was edited since is NOT repaired from a
        # failure about code that is gone.
        assert runtime_journal.failure_matches(failure, GRAMMAR + "\n") is True
        assert runtime_journal.failure_matches(failure, '{"mark": "line"}') is False

    def test_a_failed_UPSTREAM_travels_with_the_node(self, client, user_and_token, tmp_curio):
        user, token = user_and_token
        pid = _project_with_a_failing_chart(client, token)
        key = _user_dir_key(user)
        _report(client, token, pid, "pool-1", status="error",
                message="Nothing to display — this input is not tabular data")
        ctx = node_context.compose_node_context(key, pid, _spec(client, token, pid), "vega-1")
        upstream = ctx["upstream"][0]
        assert upstream["id"] == "pool-1"
        assert "not tabular data" in upstream["runtime"]["message"]

    def test_a_successful_render_stops_saying_never_executed(
        self, client, user_and_token, tmp_curio
    ):
        user, token = user_and_token
        pid = _project_with_a_failing_chart(client, token)
        key = _user_dir_key(user)
        _report(client, token, pid, "vega-1", status="ok", outputType="dataframe")
        ctx = node_context.compose_node_context(key, pid, _spec(client, token, pid), "vega-1")
        assert ctx["runtime"]["status"] == "ok"
        assert ctx["runtime"]["outputType"] == "dataframe"
        # A render produces no artifact, and the record says so honestly.
        assert runtime_journal.read_record(key, pid, "vega-1")["output"]["path"] == ""

    def test_the_agent_tool_reads_it_too(self, client, user_and_token, tmp_curio):
        """`node.runtime.read` is the model-chosen reader — same record, so it
        needed no change at all."""
        from utk_curio.backend.app.agents import tools

        user, token = user_and_token
        pid = _project_with_a_failing_chart(client, token)
        key = _user_dir_key(user)
        _report(client, token, pid, "vega-1", status="error", message=VEGA_ERROR)
        status, text = tools.execute_read_tool(
            "node.runtime.read", user_key=key, project_id=pid,
            target={"kind": "node", "targetId": "vega-1"}, params={},
        )
        assert status == "ok"
        assert VEGA_ERROR in text
        assert '"origin": "browser"' in text or "browser" in text


def _spec(client, token, pid):
    return client.get(f"/api/projects/{pid}", headers=_auth(token)).get_json()["spec"]
