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
