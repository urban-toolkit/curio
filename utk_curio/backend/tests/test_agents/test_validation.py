"""dev/67-7 — deterministic validation verdicts over the headless runner."""

from __future__ import annotations

from utk_curio.backend.app.agents import validation

KEY = "4242"
PID = "p-validate"


def _node(node_id, node_type="curio.builtin/computation-analysis", content="x()", goal=None):
    return {"id": node_id, "type": node_type, "content": content,
            "goal": goal or f"goal {node_id}"}


def _spec(nodes, edges):
    return {"dataflow": {"nodes": nodes, "edges": edges}}


def _exec(outcomes):
    """outcomes: marker substring → (path, dataType) | Exception."""

    def _fn(endpoint, payload):
        for marker, result in outcomes.items():
            if marker in payload["code"]:
                if isinstance(result, Exception):
                    raise result
                path, dtype = result
                return {"stdout": [], "stderr": "Traceback: boom" if not path else "",
                        "output": {"path": path, "dataType": dtype}}
        return {"stdout": [], "stderr": "",
                "output": {"path": "art", "dataType": "dataframe"}}

    return _fn


class TestValidateCandidate:
    def test_pass_with_output_evidence(self, tmp_curio):
        spec = _spec([_node("t", goal="compute stats")], [])
        result = validation.validate_candidate(
            KEY, PID, spec, "t", "print(1)", exec_fn=_exec({}),
        )
        assert result["verdict"] == "pass"
        assert result["evidence"]["kind"] == "executed"
        assert result["evidence"]["outputDataType"] == "dataframe"
        assert result["evidence"]["goal"] == "compute stats"

    def test_target_failure_is_execution_error(self, tmp_curio):
        spec = _spec([_node("t")], [])
        result = validation.validate_candidate(
            KEY, PID, spec, "t", "bad()", exec_fn=_exec({"bad()": ("", "str")}),
        )
        assert result["verdict"] == "fail"
        assert result["evidence"]["kind"] == "execution-error"
        assert "Traceback" in result["evidence"]["stderrTail"]

    def test_upstream_failure_names_the_blocker(self, tmp_curio):
        spec = _spec(
            [_node("up", content="up_code()", goal="Load CSV"), _node("t")],
            [{"id": "e1", "source": "up", "target": "t"}],
        )
        result = validation.validate_candidate(
            KEY, PID, spec, "t", "fine()", exec_fn=_exec({"up_code()": ("", "str")}),
        )
        assert result["verdict"] == "fail"
        assert result["evidence"]["kind"] == "upstream-blocker"
        assert result["evidence"]["blocker"] == "up"
        assert result["evidence"]["blockerLabel"] == "Load CSV"

    def test_consumer_type_mismatch_is_named(self, tmp_curio):
        spec = _spec(
            [_node("t"), _node("viz", "curio.builtin/vis-vega", "", goal="Chart it")],
            [{"id": "e1", "source": "t", "target": "viz"}],
        )
        available = {"curio.builtin/vis-vega": {
            "inputs": [{"types": ["JSON"], "min": 1, "max": 1}],
        }}
        result = validation.validate_candidate(
            KEY, PID, spec, "t", "x()", exec_fn=_exec({}),
            available_templates=available,
        )
        assert result["verdict"] == "fail"
        assert result["evidence"]["kind"] == "type-mismatch"
        assert "'Chart it'" in result["evidence"]["detail"]
        # Fail-open: no arity metadata → no mismatch claims.
        result = validation.validate_candidate(
            KEY, PID, spec, "t", "x()", exec_fn=_exec({}), available_templates=None,
        )
        assert result["verdict"] == "pass"

    def test_infrastructure_is_never_a_content_failure(self, tmp_curio):
        spec = _spec([_node("t")], [])
        result = validation.validate_candidate(
            KEY, PID, spec, "t", "x()",
            exec_fn=_exec({"x()": ConnectionError("down")}),
        )
        assert result["verdict"] == "infrastructure"
        assert result["evidence"]["kind"] == "infrastructure"
