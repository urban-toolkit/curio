"""dev/133: the loop's empty-result round, and the owner's join.

`e72c7080` is the shape: two frames whose key sets are disjoint by
construction, a merge that runs clean, and a dataflow built on nothing. The
loop must call that a failed round, tell the child what the inputs actually
hold, and write nothing when no round can produce rows.
"""

from __future__ import annotations

from utk_curio.backend.app.agents import services as services_mod
from utk_curio.backend.tests.test_agents.test_verified_rounds import CA, _Exec, _rounds

BOUNDARIES = {
    "kind": "geotable", "rowCount": 2,
    "columns": [{"name": "community", "dtype": "str"},
                {"name": "area_numbe", "dtype": "int"}],
    "sampleRows": [{"community": "Loop", "area_numbe": 32}],
}
POPULATION = {
    "kind": "table", "rowCount": 3,
    "columns": [{"name": "tract_id", "dtype": "str"},
                {"name": "population", "dtype": "int"}],
    "sampleRows": [{"tract_id": "17031010100", "population": 4521}],
}
UPSTREAMS = [
    {"goal": "Chicago Boundaries", "argIndex": 0, "outputDataType": "geodataframe",
     "schema": BOUNDARIES},
    {"goal": "Population Data", "argIndex": 1, "outputDataType": "dataframe",
     "schema": POPULATION},
]

#: The owner's join, verbatim in shape: the keys cannot match.
BAD_JOIN = ("joined = arg[0].merge(arg[1], left_on='area_numbe', "
            "right_on='tract_id')\nreturn joined")
#: A join on values of the same kind.
GOOD_JOIN = ("joined = arg[0].merge(arg[1], left_on='community', "
             "right_on='community')\nreturn joined")


def _summaries(empty_markers=("area_numbe", )):
    """Describe an artifact as EMPTY when the code that produced it joined on
    the mismatched key — the sandbox stores one artifact per call, so the fake
    keys off the call order the loop makes."""
    produced: list = []

    class _Exec2(_Exec):
        def __call__(self, endpoint, payload):
            code = payload["code"]
            produced.append(any(m in code for m in empty_markers))
            return {"stdout": [], "stderr": "",
                    "output": {"path": f"art-{len(produced)}", "dataType": "geodataframe"}}

    def _summary(artifact_id: str):
        index = int(str(artifact_id).rsplit("-", 1)[-1]) - 1
        was_empty = produced[index] if 0 <= index < len(produced) else False
        return {
            "kind": "geotable",
            "rowCount": 0 if was_empty else 2,
            "columns": [{"name": "community", "dtype": "str"}],
            "sampleRows": [] if was_empty else [{"community": "Loop"}],
        }

    return _Exec2(), _summary


class TestAnEmptyResultIsAFailedRound:
    def _node(self, content=""):
        return {"id": "n1", "type": CA, "goal": "Join density to geo", "content": content}

    def test_the_owners_join_fails_the_round_and_the_diagnosis_reaches_the_child(
        self, app, tmp_curio
    ):
        exec_fn, summary_fn = _summaries()
        events, outcome, inputs = _rounds(
            app, self._node(), replies=[BAD_JOIN, GOOD_JOIN], exec_fn=exec_fn,
            result_summary_fn=summary_fn,
            extra_inputs={"upstreamOutputs": UPSTREAMS},
        )
        kinds = [a["kind"] for a in outcome["attempts"]]
        assert kinds[0] == "empty-result"
        assert outcome["verdict"] == "pass"        # the second join produced rows
        assert outcome["candidate"] == GOOD_JOIN
        # The child was told what the inputs hold, with their VALUES.
        error = inputs[1]["validationError"]
        assert "EMPTY result" in error
        assert "area_numbe int e.g. 32" in error
        assert "tract_id str e.g. '17031010100'" in error
        assert inputs[1]["previousAttempt"].startswith("joined = arg[0].merge")

    def test_when_no_round_produces_rows_nothing_is_written(self, app, tmp_curio):
        exec_fn, summary_fn = _summaries()
        events, outcome, inputs = _rounds(
            app, self._node(),
            # Every candidate joins on the mismatched key (the suite pins the
            # attempt ceiling to three).
            replies=[BAD_JOIN, BAD_JOIN.replace("joined", "j2"),
                     BAD_JOIN.replace("joined", "j3")],
            exec_fn=exec_fn, result_summary_fn=summary_fn,
            extra_inputs={"upstreamOutputs": UPSTREAMS},
        )
        assert outcome["verdict"] == "fail"
        assert {a["kind"] for a in outcome["attempts"]} == {"empty-result"}
        assert outcome["candidate"] != ""  # the last candidate is reported…
        assert all(a["verdict"] == "fail" for a in outcome["attempts"])  # …never as a pass

    def test_a_result_with_rows_costs_no_extra_round(self, app, tmp_curio):
        exec_fn, summary_fn = _summaries()
        events, outcome, inputs = _rounds(
            app, self._node(), replies=[GOOD_JOIN], exec_fn=exec_fn,
            result_summary_fn=summary_fn,
            extra_inputs={"upstreamOutputs": UPSTREAMS},
        )
        assert outcome["verdict"] == "pass" and outcome["rounds"] == 1
        assert [a["kind"] for a in outcome["attempts"]] == ["executed"]

    def test_an_empty_INPUT_never_blames_this_node(self, app, tmp_curio):
        exec_fn, summary_fn = _summaries()
        upstreams = [
            dict(UPSTREAMS[0], schema={**BOUNDARIES, "rowCount": 0, "sampleRows": []}),
            UPSTREAMS[1],
        ]
        events, outcome, inputs = _rounds(
            app, self._node(), replies=[BAD_JOIN], exec_fn=exec_fn,
            result_summary_fn=summary_fn,
            extra_inputs={"upstreamOutputs": upstreams},
        )
        # Nothing this node could do would produce rows: dev/118 reports the
        # upstream, and this node is not corrected for someone else's failure.
        assert outcome["verdict"] == "pass"
        assert [a["kind"] for a in outcome["attempts"]] == ["executed"]

    def test_an_undescribable_artifact_leaves_the_verdict_alone(self, app, tmp_curio):
        exec_fn, _ = _summaries()
        events, outcome, inputs = _rounds(
            app, self._node(), replies=[BAD_JOIN], exec_fn=exec_fn,
            result_summary_fn=lambda artifact_id: None,   # no preview, no claim
            extra_inputs={"upstreamOutputs": UPSTREAMS},
        )
        assert outcome["verdict"] == "pass"

    def test_without_a_summary_reader_the_loop_is_exactly_as_before(self, app, tmp_curio):
        exec_fn, _ = _summaries()
        events, outcome, inputs = _rounds(
            app, self._node(), replies=[BAD_JOIN], exec_fn=exec_fn,
            extra_inputs={"upstreamOutputs": UPSTREAMS},
        )
        assert outcome["verdict"] == "pass"

    def test_the_check_is_carried_forward_as_the_error_not_as_code_to_ignore(
        self, app, tmp_curio
    ):
        """dev/131's carry-forward and dev/133's verdict compose: an empty
        result IS about the code, so a later pass starts from it."""
        carry = services_mod._carry_forward_error({
            "attempts": [{"verdict": "fail", "kind": "empty-result",
                          "detail": "the code ran but produced an EMPTY result — 0 rows",
                          "code": BAD_JOIN}],
        })
        assert carry is not None
        assert carry["kind"] == "empty-result"
        assert carry["code"] == BAD_JOIN


class TestAJoinThatProducedNullsIsEmptyToo:
    """dev/137: the owner's `7a27b702`, end to end in the loop.

    Its transformation node said out loud what it did — *"The current datasets
    have mismatched keys… To allow the dataflow to proceed and be tested, we
    perform a join… this will likely result in an empty GDF"* — and used
    ``how="left"``, so two rows of nulls passed dev/133's row count and both
    plots below were empty.
    """

    LEFT_JOIN = ("joined = arg[0].merge(arg[1], left_on='area_numbe', "
                 "right_on='tract_id', how='left')\nreturn joined")
    REAL_JOIN = ("joined = arg[0].merge(arg[1], left_on='community', "
                 "right_on='community')\nreturn joined")

    def _summaries(self):
        """A fake sandbox + describer: the left join yields rows of NULLS, the
        real one yields rows with values."""
        produced: list = []

        class _Exec2(_Exec):
            def __call__(self, endpoint, payload):
                produced.append("how='left'" in payload["code"])
                return {"stdout": [], "stderr": "",
                        "output": {"path": f"art-{len(produced)}", "dataType": "geodataframe"}}

        def _summary(artifact_id: str):
            index = int(str(artifact_id).rsplit("-", 1)[-1]) - 1
            nulls = produced[index] if 0 <= index < len(produced) else False
            return {
                "kind": "geotable", "rowCount": 2,
                "columns": [{"name": "community", "dtype": "str"},
                            {"name": "population", "dtype": "unknown" if nulls else "int"}],
                "sampleRows": [
                    {"community": "Loop", "population": None if nulls else 4521},
                    {"community": "Hyde Park", "population": None if nulls else 3890},
                ],
            }

        return _Exec2(), _summary

    def test_rows_of_nulls_fail_the_round_and_name_the_columns(self, app, tmp_curio):
        exec_fn, summary_fn = self._summaries()
        events, outcome, inputs = _rounds(
            app, {"id": "n1", "type": CA, "goal": "Join density", "content": ""},
            replies=[self.LEFT_JOIN, self.REAL_JOIN], exec_fn=exec_fn,
            result_summary_fn=summary_fn,
            extra_inputs={"upstreamOutputs": UPSTREAMS},
        )
        assert outcome["attempts"][0]["kind"] == "empty-result"
        error = inputs[1]["validationError"]
        assert "every sampled value of population is NULL" in error
        assert 'how="left"' in error
        assert "say so in one line and return no code" in error
        # The real join has values, so it passes and is written.
        assert outcome["verdict"] == "pass"
        assert outcome["candidate"] == self.REAL_JOIN

    def test_a_column_that_arrived_null_is_not_this_nodes_fault(self, app, tmp_curio):
        exec_fn, summary_fn = self._summaries()
        upstream_nulls = [
            UPSTREAMS[0],
            {"goal": "Population Data", "argIndex": 1, "schema": {
                "kind": "table", "rowCount": 3,
                "columns": [{"name": "population", "dtype": "unknown"}],
                "sampleRows": [{"population": None}],
            }},
        ]
        events, outcome, inputs = _rounds(
            app, {"id": "n1", "type": CA, "goal": "Join density", "content": ""},
            replies=[self.LEFT_JOIN], exec_fn=exec_fn, result_summary_fn=summary_fn,
            extra_inputs={"upstreamOutputs": upstream_nulls},
        )
        # `population` came in null: dev/133's attribution rule says the blame
        # is upstream, so this node is not corrected for it.
        assert outcome["verdict"] == "pass"
        assert [a["kind"] for a in outcome["attempts"]] == ["executed"]
