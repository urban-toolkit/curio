"""dev/67-7 — the promoted headless runner: ancestor slice, candidate
overlay, honest failure accumulation, journal writes."""

from __future__ import annotations

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
