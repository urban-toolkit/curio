"""dev/67-7 — the promoted headless runner: ancestor slice, candidate
overlay, honest failure accumulation, journal writes."""

from __future__ import annotations

import pytest

from utk_curio.backend.app.execution import runner, runtime_journal

KEY = "4242"
PID = "p-runner"


def _node(node_id, node_type="curio.builtin/computation-analysis", content=None):
    return {"id": node_id, "type": node_type,
            "content": content if content is not None else f"{node_id}_code()",
            "goal": f"goal {node_id}"}


def _spec(nodes, edges):
    return {"dataflow": {"nodes": nodes, "edges": edges}}


def _chain_spec(ids):
    nodes = [_node(i) for i in ids]
    edges = [
        {"id": f"e{i}", "source": ids[i], "target": ids[i + 1]}
        for i in range(len(ids) - 1)
    ]
    return _spec(nodes, edges)


class _RecordingExec:
    def __init__(self, fail_for=(), raise_transport=False):
        self.calls: list[tuple[str, dict]] = []
        self.fail_for = set(fail_for)
        self.raise_transport = raise_transport

    def __call__(self, endpoint, payload):
        self.calls.append((endpoint, payload))
        if self.raise_transport:
            raise ConnectionError("sandbox is down")
        node_marker = next(
            (m for m in self.fail_for if m in payload["code"]), None
        )
        if node_marker:
            return {"stdout": [], "stderr": "Traceback: KeyError boom",
                    "output": {"path": "", "dataType": "str"}}
        return {"stdout": ["ran"], "stderr": "",
                "output": {"path": f"art-{len(self.calls)}", "dataType": "dataframe"}}


class TestRunThroughNode:
    def test_only_the_ancestor_slice_executes(self, tmp_curio):
        spec = _chain_spec(["a", "b", "c"])
        spec["dataflow"]["nodes"].append(_node("unrelated"))
        exec_fn = _RecordingExec()
        report = runner.run_through_node(KEY, PID, spec, "b", exec_fn=exec_fn)
        assert report["ok"] is True
        assert report["order"] == ["a", "b"]  # c and unrelated never run
        assert len(exec_fn.calls) == 2

    def test_candidate_overlays_without_mutating_the_spec(self, tmp_curio):
        spec = _chain_spec(["a", "b"])
        exec_fn = _RecordingExec()
        report = runner.run_through_node(
            KEY, PID, spec, "b", candidate_content="print('candidate')",
            exec_fn=exec_fn,
        )
        assert report["ok"] is True
        assert "print('candidate')" in exec_fn.calls[1][1]["code"]
        # The spec dict is untouched — only an approved Apply writes.
        node_b = next(n for n in spec["dataflow"]["nodes"] if n["id"] == "b")
        assert node_b["content"] == "b_code()"

    def test_upstream_blocker_stops_and_is_named(self, tmp_curio):
        spec = _chain_spec(["a", "b"])
        exec_fn = _RecordingExec(fail_for={"a_code"})
        report = runner.run_through_node(KEY, PID, spec, "b", exec_fn=exec_fn)
        assert report["ok"] is False
        assert report["blocker"] == "a"
        assert "upstream" in report["error"]
        assert len(exec_fn.calls) == 1  # b never executed against broken input
        assert "KeyError" in report["nodes"]["a"]["stderrTail"]

    def test_transport_failure_is_infrastructure_not_a_node_error(self, tmp_curio):
        spec = _chain_spec(["a"])
        report = runner.run_through_node(
            KEY, PID, spec, "a", exec_fn=_RecordingExec(raise_transport=True),
        )
        assert report["ok"] is False
        assert report["blocker"] is None
        assert "sandbox unreachable" in report["error"]
        assert report["infrastructure"]

    def test_cycles_and_bounds_refuse_honestly(self, tmp_curio):
        cyclic = _spec(
            [_node("a"), _node("b")],
            [{"id": "e1", "source": "a", "target": "b"},
             {"id": "e2", "source": "b", "target": "a"}],
        )
        report = runner.run_through_node(KEY, PID, cyclic, "b", exec_fn=_RecordingExec())
        assert report["ok"] is False and "cycle" in report["error"]
        big = _chain_spec([f"n{i}" for i in range(6)])
        report = runner.run_through_node(
            KEY, PID, big, "n5", exec_fn=_RecordingExec(), node_limit=3,
        )
        assert report["ok"] is False and "validation bound" in report["error"]

    def test_ancestors_that_reuse_an_output_do_not_count_toward_the_bound(self, tmp_curio):
        """#467: a node 29 steps down a chain whose ancestors already passed in
        this batch runs 5 nodes, not 30, so the bound of 25 must not refuse it."""
        ids = [f"n{i}" for i in range(30)]
        spec = _chain_spec(ids)
        prior = {i: {"path": f"art-{i}", "dataType": "dataframe"} for i in ids[:25]}
        exec_fn = _RecordingExec()
        report = runner.run_through_node(KEY, PID, spec, "n29", exec_fn=exec_fn, prior_outputs=prior)
        assert report["error"] is None, report["error"]
        assert report["ok"] is True
        assert len(exec_fn.calls) == 5

    def test_the_bound_counts_the_nodes_that_would_run(self, tmp_curio):
        ids = [f"n{i}" for i in range(30)]
        prior = {i: {"path": f"art-{i}", "dataType": "dataframe"} for i in ids[:20]}
        report = runner.run_through_node(
            KEY, PID, _chain_spec(ids), "n29", exec_fn=_RecordingExec(), prior_outputs=prior, node_limit=5,
        )
        assert report["ok"] is False
        assert "10 nodes to run" in report["error"] and "validation bound 5" in report["error"]

    def test_the_bound_is_the_validation_node_limit_setting(self, tmp_curio, monkeypatch):
        """#467: the bound is an operator setting (``--validation-node-limit``)."""
        monkeypatch.setenv("CURIO_VALIDATION_NODE_LIMIT", "40")
        ids = [f"n{i}" for i in range(30)]
        report = runner.run_through_node(KEY, PID, _chain_spec(ids), "n29", exec_fn=_RecordingExec())
        assert report["error"] is None, report["error"]
        assert report["ok"] is True

    def test_a_node_with_several_inputs_receives_them_in_circle_order(self, tmp_curio):
        """#662: fan-in goes straight into the node that reads it, one circle per
        edge, and ``arg`` is assembled in circle order. ``a``'s edge kept the id
        it had on circle 2 before the canvas renumbered it onto ``in``: the
        handle, not the id, says which circle it feeds."""
        import ast

        spec = _spec(
            [_node("a"), _node("b"), _node("c", content="return [!! input 1 !!]")],
            [{"id": "reactflow__edge-aout-cin_2", "source": "a", "target": "c",
              "targetHandle": "in"},
             {"id": "reactflow__edge-bout-cin_1", "source": "b", "target": "c",
              "targetHandle": "in_1"}],
        )
        exec_fn = _RecordingExec()
        report = runner.run_through_node(KEY, PID, spec, "c", exec_fn=exec_fn)
        assert report["ok"] is True, report
        assert all(record["executed"] for record in report["nodes"].values()), report["nodes"]
        c_payload = exec_fn.calls[-1][1]
        assert c_payload["dataType"] == "outputs"
        assert [ref["path"] for ref in ast.literal_eval(c_payload["file_path"])] == [
            report["nodes"]["a"]["output"]["path"],
            report["nodes"]["b"]["output"]["path"],
        ], c_payload["file_path"]
        # The chip names circle 1, which is b's: arg[1] in the sent code.
        assert "return arg[1]" in c_payload["code"] and "[!!" not in c_payload["code"]

    def test_a_pass_through_node_with_several_inputs_forwards_them_in_circle_order(self, tmp_curio):
        """A Data Pool (or a Vega-Lite chart) takes any number of inputs and runs
        nothing: what it hands down is the bundle of its inputs, in circle order."""
        import ast

        spec = _spec(
            [_node("a"), _node("b"), _node("pool", "curio.builtin/data-pool", ""),
             _node("c")],
            [{"id": "e2", "source": "a", "target": "pool", "targetHandle": "in"},
             {"id": "e1", "source": "b", "target": "pool", "targetHandle": "in_1"},
             {"id": "e3", "source": "pool", "target": "c", "targetHandle": "in"}],
        )
        exec_fn = _RecordingExec()
        report = runner.run_through_node(KEY, PID, spec, "c", exec_fn=exec_fn)
        assert report["ok"] is True, report
        assert report["nodes"]["pool"] == {"status": "pass-through", "executed": False}
        c_payload = exec_fn.calls[-1][1]
        assert c_payload["dataType"] == "outputs"
        assert [ref["path"] for ref in ast.literal_eval(c_payload["file_path"])] == [
            report["nodes"]["a"]["output"]["path"],
            report["nodes"]["b"]["output"]["path"],
        ], c_payload["file_path"]

    def test_the_multi_input_example_runs_both_loaders_into_one_node(self, tmp_curio):
        """The shipped example that replaced Merge.json: two loaders feed the
        computation node directly on circles ``in`` and ``in_1``, and the node
        below it reads ``arg`` as the frame that node returned."""
        import ast
        import json
        from pathlib import Path

        from utk_curio.backend.app.execution.workflow_spec import parse_workflow_dict

        path = Path(__file__).resolve().parents[4] / "docs" / "examples" / "dataflows" / "MultiInput.json"
        spec = json.loads(path.read_text(encoding="utf-8"))
        assert [n["type"] for n in spec["dataflow"]["nodes"]] == (
            ["curio.builtin/data-loading"] * 2 + ["curio.builtin/computation-analysis"] * 2
        )
        first, second, both, last = (n["id"] for n in spec["dataflow"]["nodes"])
        parsed = parse_workflow_dict(spec)
        assert parsed.upstream_nodes(both) == [first, second]
        assert parsed.input_slots(both) == [0, 1]

        exec_fn = _RecordingExec()
        report = runner.run_through_node(KEY, PID, spec, last, exec_fn=exec_fn)
        assert report["ok"] is True, report
        assert all(record["executed"] for record in report["nodes"].values()), report["nodes"]
        payloads = {node_id: payload for node_id, payload in zip(report["order"], (c[1] for c in exec_fn.calls))}
        assert payloads[both]["dataType"] == "outputs"
        assert [ref["path"] for ref in ast.literal_eval(payloads[both]["file_path"])] == [
            report["nodes"][first]["output"]["path"],
            report["nodes"][second]["output"]["path"],
        ], payloads[both]["file_path"]
        assert payloads[last]["file_path"] == report["nodes"][both]["output"]["path"]

    def test_executions_journal_as_validation(self, tmp_curio):
        spec = _chain_spec(["a"])
        runner.run_through_node(KEY, PID, spec, "a", exec_fn=_RecordingExec())
        record = runtime_journal.read_record(KEY, PID, "a")
        assert record["validation"] is True and record["status"] == "ok"

    def test_validation_never_saves_datasets(self, tmp_curio):
        spec = _chain_spec(["a"])
        exec_fn = _RecordingExec()
        runner.run_through_node(KEY, PID, spec, "a", exec_fn=exec_fn)
        assert exec_fn.calls[0][1]["save_dataset"] is False


class TestDev115RunnerContract:
    """dev/115: the validation runner runs a node the way Play does — the
    dataset-path mapping and the user key ride the payload, a hang is the
    node's failure (never infrastructure), the timeout is one env-driven
    constant aligned to the sandbox wall clock, and durations are measured."""

    def test_dataset_paths_and_user_key_ride_the_payload_when_given(self, tmp_curio):
        rec = _RecordingExec()
        runner.run_through_node(
            KEY, PID, _chain_spec(["a"]), "a", exec_fn=rec,
            dataset_paths={"imported.x@1": "/store/x.csv"}, exec_user_key="4242",
        )
        payload = rec.calls[0][1]
        assert payload["dataset_paths"] == {"imported.x@1": "/store/x.csv"}
        assert payload["user_key"] == "4242"

    def test_payload_is_byte_compatible_without_them(self, tmp_curio):
        rec = _RecordingExec()
        runner.run_through_node(KEY, PID, _chain_spec(["a"]), "a", exec_fn=rec)
        payload = rec.calls[0][1]
        assert "dataset_paths" not in payload and "user_key" not in payload

    def test_execution_timeout_is_the_nodes_failure(self, tmp_curio):
        def _hang(endpoint, payload):
            raise runner.ExecutionTimeout(300)

        report = runner.run_through_node(KEY, PID, _chain_spec(["a"]), "a", exec_fn=_hang)
        assert report["ok"] is False
        assert report["infrastructure"] is None  # NOT a transport failure
        assert report["blocker"] == "a"
        record = report["nodes"]["a"]
        assert record["status"] == "error"
        assert "did not finish within 300 s" in record["stderrTail"]
        assert "add one and bound the fetch" in record["stderrTail"]
        # The journal saw a real, failed execution.
        journal = runtime_journal.read_record(KEY, PID, "a")
        assert journal["status"] == "error"

    def test_duration_is_measured(self, tmp_curio):
        rec = _RecordingExec()
        report = runner.run_through_node(KEY, PID, _chain_spec(["a"]), "a", exec_fn=rec)
        assert isinstance(report["nodes"]["a"]["durationMs"], int)
        assert report["nodes"]["a"]["durationMs"] >= 0

    def test_exec_timeout_env_override_and_fallback(self, monkeypatch):
        monkeypatch.delenv("CURIO_VALIDATION_EXEC_TIMEOUT", raising=False)
        assert runner.exec_timeout_s() == runner.DEFAULT_EXEC_TIMEOUT_S == 300
        monkeypatch.setenv("CURIO_VALIDATION_EXEC_TIMEOUT", "45")
        assert runner.exec_timeout_s() == 45
        monkeypatch.setenv("CURIO_VALIDATION_EXEC_TIMEOUT", "soon")
        assert runner.exec_timeout_s() == 300
        monkeypatch.setenv("CURIO_VALIDATION_EXEC_TIMEOUT", "0")
        assert runner.exec_timeout_s() == 300

    def test_http_exec_maps_requests_timeout(self, monkeypatch):
        import requests

        class _Session:
            @staticmethod
            def post(url, json=None, timeout=None, headers=None):
                assert timeout == (runner.SANDBOX_CONNECT_TIMEOUT_S, 300)
                raise requests.exceptions.ReadTimeout("slow")

        monkeypatch.delenv("CURIO_VALIDATION_EXEC_TIMEOUT", raising=False)
        monkeypatch.setattr(requests, "post", _Session.post)
        try:
            runner._http_exec("/exec", {"code": "x"})
        except runner.ExecutionTimeout as exc:
            assert exc.seconds == 300
        else:
            raise AssertionError("expected ExecutionTimeout")


class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self.text = ""
        self._body = body if body is not None else {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(f"{self.status_code} Client Error")


class TestSandboxSharedSecret:
    """dev/115 field fix (live re-test 2026-09-08): under ``curio start`` the
    sandbox guards ``/exec`` and ``/get`` with ``CURIO_SANDBOX_TOKEN`` and the
    runner sent nothing, so every verified Solve round was an ``infrastructure``
    verdict reading ``401 Client Error: UNAUTHORIZED``. The runner now attaches
    the same header the API bridge does, and a 401 names the disagreement."""

    def _capture(self, monkeypatch, status=200, body=None):
        import requests

        seen = {}

        def _post(url, json=None, timeout=None, headers=None):
            seen["post"] = headers
            return _Resp(status, body)

        def _get(url, params=None, timeout=None, headers=None):
            seen["get"] = headers
            return _Resp(status, body)

        monkeypatch.setattr(requests, "post", _post)
        monkeypatch.setattr(requests, "get", _get)
        return seen

    def test_token_rides_exec_and_get_when_the_launcher_set_one(self, monkeypatch):
        monkeypatch.setenv("CURIO_SANDBOX_TOKEN", "launch-secret")
        seen = self._capture(monkeypatch, body={"ok": True})
        assert runner._http_exec("/exec", {"code": "x"}) == {"ok": True}
        assert seen["post"] == {"X-Curio-Sandbox-Token": "launch-secret"}
        runner.load_artifact_as_dict("art-1")
        assert seen["get"] == {"X-Curio-Sandbox-Token": "launch-secret"}

    def test_nothing_is_sent_without_a_token(self, monkeypatch):
        monkeypatch.delenv("CURIO_SANDBOX_TOKEN", raising=False)
        seen = self._capture(monkeypatch, body={})
        runner._http_exec("/exec", {"code": "x"})
        runner.load_artifact_as_dict("art-1")
        assert seen["post"] is None and seen["get"] is None

    def test_a_401_names_the_token_disagreement(self, monkeypatch):
        monkeypatch.setenv("CURIO_SANDBOX_TOKEN", "stale")
        self._capture(monkeypatch, status=401)
        with pytest.raises(RuntimeError) as exc:
            runner._http_exec("/exec", {"code": "x"})
        assert "CURIO_SANDBOX_TOKEN" in str(exc.value) and "/exec" in str(exc.value)
        with pytest.raises(RuntimeError) as exc:
            runner.load_artifact_as_dict("art-1")
        assert "/get" in str(exc.value)

    def test_the_bridge_and_the_runner_share_one_helper(self):
        from utk_curio.backend.app.execution import sandbox_auth, sandbox_client

        assert sandbox_client.sandbox_headers is sandbox_auth.sandbox_headers
        assert runner.sandbox_headers is sandbox_auth.sandbox_headers


class TestDev116SecretsPayload:
    """dev/116: connection-key values ride the /exec payload under ``secrets``
    exactly like ``dataset_paths`` — and are absent otherwise."""

    def test_secrets_ride_the_payload_when_given(self, tmp_curio):
        rec = _RecordingExec()
        runner.run_through_node(
            KEY, PID, _chain_spec(["a"]), "a", exec_fn=rec,
            secrets={"census": "k3y-v4lue-9876"},
        )
        assert rec.calls[0][1]["secrets"] == {"census": "k3y-v4lue-9876"}

    def test_payload_has_no_secrets_key_without_them(self, tmp_curio):
        rec = _RecordingExec()
        runner.run_through_node(KEY, PID, _chain_spec(["a"]), "a", exec_fn=rec, secrets={})
        assert "secrets" not in rec.calls[0][1]


class TestDev118NotExecutableTarget:
    """dev/118 (DEC-075): a browser-rendered TARGET is refused by name before
    anything runs — it used to fall into the pass-through branch and end
    ``ok: True`` with its candidate never sent, a pass on nothing."""

    def test_executable_kinds(self):
        from utk_curio.backend.app.execution.workflow_spec import is_executable_kind

        for kind in ("curio.builtin/data-loading", "curio.builtin/computation-analysis@1",
                     "curio.builtin/js-computation", "DATA_LOADING"):
            assert is_executable_kind(kind) is True, kind
        # Data Export is one Download button with no code (#226). Merge Flow is
        # gone (#662): an old spec that still names it must not run it either.
        for kind in ("curio.builtin/vis-vega", "curio.builtin/autk-grammar@1", "curio.builtin/data-pool",
                     "curio.builtin/merge-flow", "curio.builtin/vis-simple", "curio.builtin/data-export@1",
                     "some.pkg/custom-node@1", "", None):
            assert is_executable_kind(kind) is False, kind

    def test_a_browser_rendered_target_is_refused_before_anything_runs(self, tmp_curio):
        rec = _RecordingExec()
        spec = _spec(
            [_node("a"), _node("v", node_type="curio.builtin/vis-vega", content='{"mark": "bar"}')],
            [{"id": "e1", "source": "a", "target": "v"}],
        )
        report = runner.run_through_node(KEY, PID, spec, "v", exec_fn=rec, candidate_content='{"mark": "line"}')
        assert report["ok"] is False and report["notExecutable"] is True
        assert report["blocker"] is None and report["infrastructure"] is None
        assert "no code the sandbox could run" in report["error"] and "'v'" in report["error"]
        assert rec.calls == []  # not even the upstream ran
        assert report["order"] == [] and report["nodes"] == {}

    def test_an_upstream_pass_through_node_still_forwards(self, tmp_curio):
        # The refusal is about the TARGET only: a view upstream of a code
        # target keeps its pass-through forwarding.
        rec = _RecordingExec()
        spec = _spec(
            [_node("a"), _node("v", node_type="curio.builtin/vis-simple", content=""), _node("c")],
            [{"id": "e1", "source": "a", "target": "v"}, {"id": "e2", "source": "v", "target": "c"}],
        )
        report = runner.run_through_node(KEY, PID, spec, "c", exec_fn=rec)
        assert report["ok"] is True and report["notExecutable"] is False
        assert report["nodes"]["v"]["status"] == "pass-through"
        assert [c[1]["nodeType"] for c in rec.calls] == ["curio.builtin/computation-analysis"] * 2
        # What reaches c is a's own output, forwarded unchanged.
        assert rec.calls[-1][1]["file_path"] == report["nodes"]["a"]["output"]["path"]
        assert rec.calls[-1][1]["dataType"] == report["nodes"]["a"]["output"]["dataType"]


class TestDev118PriorOutputs:
    """dev/118 (DEC-075) commit 4: an ancestor that passed earlier in the batch
    stands in by its recorded output — the target always runs."""

    def test_reused_ancestors_are_not_re_executed_and_feed_the_target(self, tmp_curio):
        rec = _RecordingExec()
        spec = _chain_spec(["a", "b", "c"])
        report = runner.run_through_node(
            KEY, PID, spec, "c", exec_fn=rec,
            prior_outputs={"a": {"path": "art-a", "dataType": "dataframe"},
                           "b": {"path": "art-b", "dataType": "dataframe"},
                           "zzz": {"path": "ignored", "dataType": "x"}},
        )
        assert report["ok"] is True
        assert report["nodes"]["a"] == {"status": "reused", "executed": False, "output": {"path": "art-a", "dataType": "dataframe"}}
        assert report["nodes"]["b"]["status"] == "reused"
        assert [c[1]["nodeType"] for c in rec.calls] == ["curio.builtin/computation-analysis"]  # only c ran
        assert rec.calls[0][1]["file_path"] == "art-b" and rec.calls[0][1]["dataType"] == "dataframe"
        assert report["nodes"]["c"]["executed"] is True

    def test_the_target_itself_is_never_reused(self, tmp_curio):
        rec = _RecordingExec()
        report = runner.run_through_node(
            KEY, PID, _chain_spec(["a"]), "a", exec_fn=rec,
            prior_outputs={"a": {"path": "art-a", "dataType": "dataframe"}},
        )
        assert report["ok"] is True and report["nodes"]["a"]["executed"] is True
        assert len(rec.calls) == 1


class TestDev118EmptyUpstream:
    """dev/118 live fix: an upstream code node with no content is a blocker by
    name before anything runs — never a seed-only body handing None downstream."""

    def test_an_empty_upstream_blocks_before_execution(self, tmp_curio):
        rec = _RecordingExec()
        spec = _spec([_node("a", content=""), _node("t")], [{"id": "e1", "source": "a", "target": "t"}])
        report = runner.run_through_node(KEY, PID, spec, "t", exec_fn=rec, strict_upstream=True)
        assert report["ok"] is False and report["blocker"] == "a" and report["upstreamEmpty"] is True
        assert "has no content yet" in report["error"] and "'a'" in report["error"]
        assert report["nodes"]["a"] == {"status": "empty", "executed": False}
        assert rec.calls == []
        # A plain Run (dev/71) keeps Play's semantics and runs the empty body.
        rec_run = _RecordingExec()
        assert runner.run_through_node(KEY, PID, spec, "t", exec_fn=rec_run)["ok"] is True
        assert len(rec_run.calls) == 2

    def test_the_target_may_be_empty_only_through_its_candidate(self, tmp_curio):
        rec = _RecordingExec()
        spec = _spec([_node("a"), _node("t", content="")], [{"id": "e1", "source": "a", "target": "t"}])
        report = runner.run_through_node(KEY, PID, spec, "t", exec_fn=rec, candidate_content="return arg", strict_upstream=True)
        assert report["ok"] is True and "upstreamEmpty" not in {k for k, v in report.items() if v}
        # A reused empty upstream never reaches the check either.
        rec2 = _RecordingExec()
        spec2 = _spec([_node("a", content=""), _node("t")], [{"id": "e1", "source": "a", "target": "t"}])
        report2 = runner.run_through_node(KEY, PID, spec2, "t", exec_fn=rec2, strict_upstream=True,
                                          prior_outputs={"a": {"path": "art-a", "dataType": "dataframe"}})
        assert report2["ok"] is True and report2["nodes"]["a"]["status"] == "reused"


class TestDev119VersionedIds:
    """dev/119 hotfix: a palette-dragged node's versioned id classifies like
    its unversioned twin — the runner and the gate agree."""

    def test_normalize_type_strips_the_version(self):
        from utk_curio.backend.app.execution.workflow_spec import classify_node, normalize_type, parse_workflow_dict

        assert normalize_type("curio.builtin/data-loading@1") == "DATA_LOADING"
        assert normalize_type("curio.builtin/vis-vega@2") == "VIS_VEGA"
        assert normalize_type("some.pkg/custom@1") == "some.pkg/custom"
        assert classify_node(normalize_type("curio.builtin/js-computation@1")) == "code"
        wf = parse_workflow_dict({"dataflow": {"nodes": [
            {"id": "a", "type": "curio.builtin/data-loading@1", "content": "x"},
            {"id": "v", "type": "curio.builtin/vis-vega@1", "content": "{}"},
        ], "edges": []}})
        by_id = {n.id: n for n in wf.nodes}
        assert by_id["a"].category == "code" and by_id["a"].type == "DATA_LOADING"
        assert by_id["a"].raw_type == "curio.builtin/data-loading@1"  # the wire id survives for the sandbox
        assert by_id["v"].category == "grammar"

    def test_a_versioned_data_loading_target_executes(self, tmp_curio):
        rec = _RecordingExec()
        spec = _spec([_node("a", node_type="curio.builtin/data-loading@1", content="return 1")], [])
        report = runner.run_through_node(KEY, PID, spec, "a", exec_fn=rec)
        assert report["ok"] is True and report["notExecutable"] is False
        assert rec.calls[0][1]["nodeType"] == "curio.builtin/data-loading@1"


class TestDev119RosterClassification:
    """dev/119 (DEC-076): with a roster snapshot the template's own facts
    decide what the sandbox runs and on which engine; the legacy tables are
    only the offline fallback."""

    ROSTER = {
        "curio.builtin/data-loading": {"executable": True, "engine": "python"},
        "curio.builtin/computation-analysis": {"executable": True, "engine": "python"},
        "curio.builtin/spatial-join": {"executable": False, "engine": "python"},
        "some.pkg/custom-python": {"executable": True, "engine": "python"},
        "some.pkg/custom-js": {"executable": True, "engine": "javascript"},
        "some.pkg/surface": {"executable": False, "engine": "python"},
    }

    def test_parse_classifies_from_the_roster_with_legacy_fallback(self):
        from utk_curio.backend.app.execution.workflow_spec import is_executable_kind, parse_workflow_dict

        wf = parse_workflow_dict({"dataflow": {"nodes": [
            {"id": "p", "type": "some.pkg/custom-python@1", "content": "x"},
            {"id": "j", "type": "some.pkg/custom-js@2", "content": "x"},
            {"id": "s", "type": "some.pkg/surface@1", "content": "x"},
            {"id": "sj", "type": "curio.builtin/spatial-join@1", "content": ""},
            {"id": "v", "type": "curio.builtin/vis-vega@1", "content": "{}"},  # not in the roster → legacy
            {"id": "u", "type": "unknown.pkg/thing@1", "content": "x"},       # unknown → legacy passive
        ], "edges": []}}, templates=self.ROSTER)
        by_id = {n.id: n for n in wf.nodes}
        assert by_id["p"].category == "code" and by_id["p"].engine == "python"
        assert by_id["j"].category == "code" and by_id["j"].engine == "javascript"
        assert by_id["s"].category == "passive" and by_id["sj"].category == "passive"
        assert by_id["v"].category == "grammar" and by_id["u"].category == "passive"
        assert is_executable_kind("some.pkg/custom-python@1", self.ROSTER) is True
        assert is_executable_kind("some.pkg/custom-python@1") is False  # no roster: legacy has no such kind
        assert is_executable_kind("curio.builtin/spatial-join", self.ROSTER) is False

    def test_the_roster_overrides_a_legacy_code_name(self):
        # A template whose NAME the legacy table calls code but whose manifest
        # has no code: the roster wins — an impostor never reaches the sandbox.
        from utk_curio.backend.app.execution.workflow_spec import parse_workflow_dict

        roster = {"curio.builtin/data-loading": {"executable": False, "engine": "python"}}
        wf = parse_workflow_dict({"dataflow": {"nodes": [
            {"id": "a", "type": "curio.builtin/data-loading@1", "content": "x"}], "edges": []}}, templates=roster)
        assert wf.nodes[0].category == "passive"

    def test_a_package_python_kind_executes_and_a_js_kind_takes_the_js_endpoint(self, tmp_curio):
        rec = _RecordingExec()
        spec = _spec(
            [_node("p", node_type="some.pkg/custom-python@1", content="return 1"),
             _node("j", node_type="some.pkg/custom-js@2", content="return 2")],
            [{"id": "e1", "source": "p", "target": "j"}],
        )
        report = runner.run_through_node(KEY, PID, spec, "j", exec_fn=rec, templates=self.ROSTER)
        assert report["ok"] is True and report["notExecutable"] is False
        assert [(ep, c["nodeType"]) for ep, c in rec.calls] == [
            ("/exec", "some.pkg/custom-python@1"), ("/execJs", "some.pkg/custom-js@2")]
        # Without the roster the same kinds are unknown → the target is refused.
        rec2 = _RecordingExec()
        report = runner.run_through_node(KEY, PID, spec, "j", exec_fn=rec2)
        assert report["ok"] is False and report["notExecutable"] is True and rec2.calls == []

    def test_spatial_join_is_refused_by_the_roster_with_the_service_wording(self, tmp_curio):
        rec = _RecordingExec()
        spec = _spec(
            [_node("a", node_type="curio.builtin/data-loading@1", content="return 1"),
             _node("sj", node_type="curio.builtin/spatial-join@1", content="")],
            [{"id": "e1", "source": "a", "target": "sj"}],
        )
        report = runner.run_through_node(KEY, PID, spec, "sj", exec_fn=rec, templates=self.ROSTER)
        assert report["ok"] is False and report["notExecutable"] is True
        assert "no code the sandbox could run" in report["error"]
        assert "through its own service" in report["error"] and "Play the dataflow" in report["error"]
        assert rec.calls == []


class TestArtifactPreviewIsBounded:
    """dev/127: the backend describes an upstream frame without holding it.

    ``load_artifact_as_dict`` fetches a WHOLE artifact and its own comment
    records what that cost once (MemoryError on the largest example dataflow).
    The preview asks the sandbox for a row cap AND abandons the read past a
    byte cap, so an artifact too big to describe cheaply is reported as no
    schema rather than as a crash.
    """

    class _StreamResp:
        def __init__(self, body: bytes, status: int = 200):
            self._body = body
            self.status_code = status
            self.ok = 200 <= status < 300

        def iter_content(self, chunk_size=32_768):
            for i in range(0, len(self._body), chunk_size):
                yield self._body[i : i + chunk_size]

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def _patch(self, monkeypatch, resp, seen=None):
        import requests

        def _get(url, params=None, timeout=None, headers=None, stream=False):
            if seen is not None:
                seen.update({"url": url, "params": params, "stream": stream,
                             "headers": headers})
            return resp

        monkeypatch.setattr(requests, "get", _get)

    def test_the_row_cap_rides_the_request_and_the_payload_comes_back(self, monkeypatch):
        seen: dict = {}
        self._patch(
            monkeypatch,
            self._StreamResp(b'{"dataType": "dataframe", "data": {"a": [1]}}'),
            seen,
        )
        out = runner.load_artifact_preview("art-1")
        assert out == {"dataType": "dataframe", "data": {"a": [1]}}
        assert seen["params"] == {"fileName": "art-1", "maxRows": runner.ARTIFACT_PREVIEW_MAX_ROWS}
        assert seen["stream"] is True
        assert seen["url"].endswith("/get")

    def test_an_oversized_body_is_abandoned_and_reports_no_preview(self, monkeypatch):
        big = b'{"dataType": "geodataframe", "data": "' + b"x" * (
            runner.ARTIFACT_PREVIEW_MAX_BYTES + 10_000
        ) + b'"}'
        self._patch(monkeypatch, self._StreamResp(big))
        assert runner.load_artifact_preview("art-big") is None

    def test_an_error_status_is_no_preview_not_a_raise(self, monkeypatch):
        self._patch(monkeypatch, self._StreamResp(b"nope", status=500))
        assert runner.load_artifact_preview("art-1") is None
        self._patch(monkeypatch, self._StreamResp(b"", status=401))
        assert runner.load_artifact_preview("art-1") is None

    def test_a_body_that_is_not_json_is_no_preview(self, monkeypatch):
        self._patch(monkeypatch, self._StreamResp(b"<html>error</html>"))
        assert runner.load_artifact_preview("art-1") is None

    def test_an_unreachable_sandbox_is_no_preview(self, monkeypatch):
        import requests

        def _boom(*a, **k):
            raise requests.ConnectionError("refused")

        monkeypatch.setattr(requests, "get", _boom)
        assert runner.load_artifact_preview("art-1") is None


class TestInputSlotOrderIsTheHandle:
    """dev/128, from a field failure: dataflow `00708324` reported
    *"ed1a326f · solved · pass after 1 round"* and then failed on Play with
    ``KeyError: 'tract_id'``, because validation assembled ``arg`` as
    ``[population, boundaries]`` while the canvas assembles it as
    ``[boundaries, population]``.

    The cause was reading the slot from the edge's ID: the canvas encodes it
    there (`…78504in_1`), but an AGENT-APPLIED edge has a UUID id and carries
    the slot in ``targetHandle`` (dev/67-3). Both parsers also dropped the
    handle entirely, so a plan-created fan-in was ordered lexicographically by
    UUID. The handle is now the authority, the same one
    `inputSlots.inputSlotOf` reads for Play. Since #662 the fan-in goes
    straight into the node that reads it: circle 0 is ``in``, circle k is
    ``in_k``.
    """

    #: The owner's own edges: UUID ids, slots in targetHandle, and the id sort
    #: is the INVERSE of the handle sort.
    AGENT_SPEC = {
        "dataflow": {
            "nodes": [
                {"id": "b", "type": "curio.builtin/data-loading", "content": "return 1"},
                {"id": "p", "type": "curio.builtin/data-loading", "content": "return 2"},
                {"id": "t", "type": "curio.builtin/data-transformation", "content": "return arg"},
            ],
            "edges": [
                {"id": "b396ed2d-3679-4b38-bbf7-5829d1db082c", "source": "b",
                 "target": "t", "sourceHandle": "out", "targetHandle": "in"},
                {"id": "0c05b055-f50e-43f6-9a98-7f66d66e36d9", "source": "p",
                 "target": "t", "sourceHandle": "out", "targetHandle": "in_1"},
            ],
        }
    }

    def _spec(self, raw):
        from utk_curio.backend.app.execution.workflow_spec import parse_workflow_dict

        return parse_workflow_dict(raw)

    def test_an_agent_applied_fan_in_is_ordered_by_its_handles(self):
        spec = self._spec(self.AGENT_SPEC)
        assert spec.upstream_nodes("t") == ["b", "p"]
        assert spec.input_slots("t") == [0, 1]
        # The regression: sorted by id it would be ["p", "b"].
        assert sorted(
            e["id"] for e in spec.edges if e["target"] == "t"
        ) == ["0c05b055-f50e-43f6-9a98-7f66d66e36d9", "b396ed2d-3679-4b38-bbf7-5829d1db082c"]

    def test_the_canvas_legacy_id_encoding_still_works(self):
        raw = {"dataflow": {
            "nodes": self.AGENT_SPEC["dataflow"]["nodes"],
            "edges": [
                {"id": "reactflow__edge-p78504in_1", "source": "p", "target": "t"},
                {"id": "reactflow__edge-b78504in_0", "source": "b", "target": "t"},
            ],
        }}
        assert self._spec(raw).upstream_nodes("t") == ["b", "p"]

    def test_the_handle_wins_over_a_conflicting_id_suffix(self):
        raw = {"dataflow": {
            "nodes": self.AGENT_SPEC["dataflow"]["nodes"],
            "edges": [
                {"id": "x-in_1", "source": "b", "target": "t", "targetHandle": "in_0"},
                {"id": "y-in_0", "source": "p", "target": "t", "targetHandle": "in_1"},
            ],
        }}
        assert self._spec(raw).upstream_nodes("t") == ["b", "p"]

    def test_the_plain_in_handle_wins_over_a_conflicting_id_suffix(self):
        """``in`` is circle 0 even when the edge id still ends in the ``in_2``
        of the circle it fed before the canvas renumbered it."""
        raw = {"dataflow": {
            "nodes": self.AGENT_SPEC["dataflow"]["nodes"],
            "edges": [
                {"id": "x-in_2", "source": "b", "target": "t", "targetHandle": "in"},
                {"id": "y-in_0", "source": "p", "target": "t", "targetHandle": "in_1"},
            ],
        }}
        spec = self._spec(raw)
        assert spec.upstream_nodes("t") == ["b", "p"]
        assert spec.input_slots("t") == [0, 1]

    def test_the_handle_survives_the_projection(self):
        spec = self._spec(self.AGENT_SPEC)
        handles = {e["source"]: e.get("targetHandle") for e in spec.edges if e["target"] == "t"}
        assert handles == {"b": "in", "p": "in_1"}

    def test_named_input_slot_is_the_one_slot_reader(self):
        from utk_curio.backend.app.execution.workflow_spec import (
            input_slot,
            named_input_slot,
            slot_handle_id,
        )

        assert named_input_slot({"targetHandle": "in_2"}) == 2
        assert named_input_slot({"target_handle": "in_3"}) == 3
        assert named_input_slot({"id": "…78504in_4"}) == 4
        # The plain handle is circle 0, whatever the id says.
        assert named_input_slot({"targetHandle": "in", "id": "u"}) == 0
        assert named_input_slot({"targetHandle": "in", "id": "…78504in_4"}) == 0
        assert named_input_slot({"target_handle": "in"}) == 0
        assert named_input_slot({"targetHandle": "out_0"}) is None
        assert named_input_slot({}) is None
        assert named_input_slot(None) is None
        # The handle the canvas writes for circle k reads back as k.
        assert slot_handle_id(0) == "in" and slot_handle_id(3) == "in_3"
        for k in range(5):
            assert named_input_slot({"targetHandle": slot_handle_id(k)}) == k
        # No name at all is circle 0 for the ordering.
        assert input_slot({}) == 0 and input_slot({"targetHandle": "out_0"}) == 0

    def test_validation_hands_the_node_the_same_order_play_does(self, monkeypatch):
        """The end of the disagreement: the runner's own input assembly,
        driven through a fake sandbox, delivers circle order."""
        seen: list[dict] = []

        def _exec(endpoint, payload):
            seen.append(payload)
            code = payload["code"]
            if "return 1" in code:
                return {"stdout": [], "stderr": "", "output": {"path": "art-b", "dataType": "geodataframe"}}
            if "return 2" in code:
                return {"stdout": [], "stderr": "", "output": {"path": "art-p", "dataType": "dataframe"}}
            return {"stdout": [], "stderr": "", "output": {"path": "art-t", "dataType": "dataframe"}}

        monkeypatch.setattr(runner, "_http_exec", _exec)
        report = runner.run_through_node(
            "1", "p-1", self.AGENT_SPEC, "t", candidate_content="return arg",
        )
        assert report["ok"], report
        target = seen[-1]
        # The node's inputs ride its file_path as the stringified outputs
        # list the worker evals back, in circle order.
        assert target["dataType"] == "outputs"
        assert target["file_path"].index("art-b") < target["file_path"].index("art-p"), (
            target["file_path"]
        )
