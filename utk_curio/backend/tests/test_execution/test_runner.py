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

    def test_merge_pass_through_assembles_fan_in(self, tmp_curio):
        spec = _spec(
            [_node("a"), _node("b"), _node("m", "curio.builtin/merge-flow", ""),
             _node("c")],
            [{"id": "e-a-in_0", "source": "a", "target": "m"},
             {"id": "e-b-in_1", "source": "b", "target": "m"},
             {"id": "e3", "source": "m", "target": "c"}],
        )
        exec_fn = _RecordingExec()
        report = runner.run_through_node(KEY, PID, spec, "c", exec_fn=exec_fn)
        assert report["ok"] is True
        assert report["nodes"]["m"] == {"status": "pass-through", "executed": False}
        # The consumer receives the assembled outputs list.
        c_payload = exec_fn.calls[-1][1]
        assert c_payload["dataType"] == "outputs"
        assert "art-1" in c_payload["file_path"] and "art-2" in c_payload["file_path"]

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
        from utk_curio.backend.app.api import routes
        from utk_curio.backend.app.execution import sandbox_auth

        assert routes._sandbox_headers is sandbox_auth.sandbox_headers
        assert routes.SANDBOX_TOKEN_HEADER == sandbox_auth.SANDBOX_TOKEN_HEADER


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
                     "curio.builtin/js-computation", "DATA_LOADING", "curio.builtin/data-export@1"):
            assert is_executable_kind(kind) is True, kind
        for kind in ("curio.builtin/vis-vega", "curio.builtin/autk-grammar@1", "curio.builtin/data-pool",
                     "curio.builtin/merge-flow", "curio.builtin/vis-simple", "some.pkg/custom-node@1", "", None):
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
        assert "runs in the browser" in report["error"] and "'v'" in report["error"]
        assert rec.calls == []  # not even the upstream ran
        assert report["order"] == [] and report["nodes"] == {}

    def test_an_upstream_pass_through_node_still_forwards(self, tmp_curio):
        # The refusal is about the TARGET only: a merge upstream of a code
        # target keeps its pass-through forwarding.
        rec = _RecordingExec()
        spec = _spec(
            [_node("a"), _node("m", node_type="curio.builtin/merge-flow", content=""), _node("c")],
            [{"id": "e1", "source": "a", "target": "m"}, {"id": "e2", "source": "m", "target": "c"}],
        )
        report = runner.run_through_node(KEY, PID, spec, "c", exec_fn=rec)
        assert report["ok"] is True and report["notExecutable"] is False
        assert report["nodes"]["m"]["status"] == "pass-through"
        assert [c[1]["nodeType"] for c in rec.calls] == ["curio.builtin/computation-analysis"] * 2


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
