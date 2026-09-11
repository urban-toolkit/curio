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

    def test_an_ABSENT_output_is_a_mismatch_and_names_the_decline(self, tmp_curio):
        """dev/138, from the owner's `edd71e67`: the node's code ended in
        `return None`, the sandbox typed the artifact "null", and this check
        took its "unmapped runtime type: fail open" path — so a node that
        produced nothing was written and called solved."""
        spec = _spec(
            [_node("t"), _node("pool", "curio.builtin/data-pool", "", goal="Neighborhood Pool")],
            [{"id": "e1", "source": "t", "target": "pool"}],
        )
        available = {"curio.builtin/data-pool": {
            "inputs": [{"types": ["DATAFRAME", "GEODATAFRAME"], "min": 1, "max": 1}],
        }}
        result = validation.validate_candidate(
            KEY, PID, spec, "t", "return None",
            exec_fn=_exec({"None": ("art-null", "null")}),
            available_templates=available,
        )
        assert result["verdict"] == "fail"
        assert result["evidence"]["kind"] == "type-mismatch"
        detail = result["evidence"]["detail"]
        assert "returned no output (None)" in detail
        assert "'Neighborhood Pool'" in detail
        assert "DATAFRAME, GEODATAFRAME" in detail
        # The honest alternative is named, because it exists (dev/115).
        assert "say so in one line instead of returning code" in detail

    def test_an_output_type_this_build_does_not_know_still_fails_open(self, tmp_curio):
        """The distinction dev/138 rests on: 'absent' is not 'unknown'."""
        spec = _spec(
            [_node("t"), _node("pool", "curio.builtin/data-pool", "", goal="Pool")],
            [{"id": "e1", "source": "t", "target": "pool"}],
        )
        available = {"curio.builtin/data-pool": {
            "inputs": [{"types": ["DATAFRAME"], "min": 1, "max": 1}],
        }}
        result = validation.validate_candidate(
            KEY, PID, spec, "t", "return tensor()",
            exec_fn=_exec({"tensor": ("art-9", "tensor")}),
            available_templates=available,
        )
        assert result["verdict"] == "pass"

    def test_an_absent_output_with_no_consumer_is_not_a_mismatch(self, tmp_curio):
        # Nothing downstream declares anything, so there is nothing to violate;
        # the journal still records the run as a failure (its own test).
        spec = _spec([_node("t")], [])
        result = validation.validate_candidate(
            KEY, PID, spec, "t", "return None",
            exec_fn=_exec({"None": ("art-null", "null")}),
            available_templates={"curio.builtin/computation-analysis": {"inputs": []}},
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


class TestDev115Passthrough:
    def test_dataset_paths_and_user_key_reach_the_runner_and_duration_is_evidence(self, tmp_curio):
        seen = {}

        def _fn(endpoint, payload):
            seen.update(payload)
            return {"stdout": [], "stderr": "", "output": {"path": "art", "dataType": "dataframe"}}

        spec = _spec([_node("t", node_type="curio.builtin/data-loading",
                            content='p = curio_dataset_path("imported.x@1")')], [])
        result = validation.validate_candidate(
            KEY, PID, spec, "t", 'p = curio_dataset_path("imported.x@1")\nreturn p',
            exec_fn=_fn, dataset_paths={"imported.x@1": "/store/x.csv"}, exec_user_key="4242",
            secrets={"census": "k3y-v4lue-9876"},
        )
        assert seen["dataset_paths"] == {"imported.x@1": "/store/x.csv"}
        assert seen["user_key"] == "4242"
        assert seen["secrets"] == {"census": "k3y-v4lue-9876"}  # dev/116 passthrough
        assert result["verdict"] == "pass"
        assert isinstance(result["evidence"]["durationMs"], int)


class TestNotExecutable:
    """dev/118 (DEC-075): the fourth verdict — a browser-rendered kind is
    neither a pass nor a content failure."""

    def test_browser_rendered_target_is_not_executable(self, tmp_curio):
        calls = []

        def _fn(endpoint, payload):
            calls.append(payload)
            return {"stdout": [], "stderr": "", "output": {"path": "art", "dataType": "dataframe"}}

        spec = _spec([_node("a"), _node("v", node_type="curio.builtin/vis-vega", content="{}", goal="plot it")],
                     [{"id": "e1", "source": "a", "target": "v"}])
        result = validation.validate_candidate(KEY, PID, spec, "v", '{"mark": "bar"}', exec_fn=_fn)
        assert result["verdict"] == "not-executable"
        assert result["evidence"]["kind"] == "not-executable"
        assert "no code the sandbox could run" in result["evidence"]["detail"]
        assert result["evidence"]["goal"] == "plot it"
        assert result["evidence"]["executedNodes"] == [] and calls == []


class TestPriorOutputs:
    def test_reused_nodes_and_the_output_record_ride_the_evidence(self, tmp_curio):
        payloads = []

        def _fn(endpoint, payload):
            payloads.append(payload)
            return {"stdout": [], "stderr": "", "output": {"path": "art-t", "dataType": "dataframe"}}

        spec = _spec([_node("a"), _node("t")], [{"id": "e1", "source": "a", "target": "t"}])
        result = validation.validate_candidate(
            KEY, PID, spec, "t", "df = arg[0]\nreturn df", exec_fn=_fn,
            prior_outputs={"a": {"path": "art-a", "dataType": "dataframe"}},
        )
        assert result["verdict"] == "pass"
        assert result["evidence"]["reusedNodes"] == ["a"]
        assert result["evidence"]["executedNodes"] == ["t"]
        assert result["evidence"]["output"] == {"path": "art-t", "dataType": "dataframe"}
        assert payloads[0]["file_path"] == "art-a"


class TestEmptyUpstream:
    def test_empty_upstream_is_an_upstream_blocker_flagged_empty(self, tmp_curio):
        spec = _spec([_node("a", content="", goal="load the tracts"), _node("t")],
                     [{"id": "e1", "source": "a", "target": "t"}])
        result = validation.validate_candidate(KEY, PID, spec, "t", "return arg", exec_fn=lambda e, p: {"stdout": [], "stderr": "", "output": {"path": "x", "dataType": "dataframe"}})
        assert result["verdict"] == "fail"
        assert result["evidence"]["kind"] == "upstream-blocker" and result["evidence"]["upstreamEmpty"] is True
        assert result["evidence"]["blocker"] == "a" and result["evidence"]["blockerLabel"] == "load the tracts"
        assert result["evidence"]["executedNodes"] == []
