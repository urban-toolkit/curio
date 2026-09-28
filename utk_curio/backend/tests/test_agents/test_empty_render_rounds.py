"""dev/136: a valid document that drew nothing is a failed round.

The owner's report — *"Vega-Lite and Autark nodes render empty plots. Curio
must properly detect empty output so the harness can validate and fix it
accordingly."* The harness half: a grammar node's round 0 validates the
document that is already there, and an empty-rendering document VALIDATES — so
the round passed, the loop stopped, and the chart the user was looking at
stayed empty.
"""

from __future__ import annotations

import json

from utk_curio.backend.app.agents import result_shape as rs
from utk_curio.backend.app.execution import runtime_journal
from utk_curio.backend.tests.test_agents.test_verified_rounds import _Exec, _rounds

VEGA = "curio.builtin/vis-vega"
VALID_DOC = json.dumps({
    "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
    "mark": "bar",
    "encoding": {"x": {"field": "density", "type": "quantitative"}},
})
FIXED_DOC = json.dumps({
    "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
    "mark": "bar",
    "encoding": {"x": {"field": "community", "type": "nominal"}},
})
DREW_NOTHING = (
    "rendered nothing — 12 rows arrived and no mark was drawn: an encoding, a "
    "transform or a scale domain removed every row."
)
NO_ROWS = (
    "rendered nothing — 0 rows arrived at this node, so there was nothing to "
    "draw. The upstream node that feeds it is what must change; this document "
    "is not at fault."
)
#: The columns the chart's input actually has — dev/134's field check reads
#: these, so the document below is genuinely VALID and its emptiness is the
#: only thing wrong with it (rows whose `density` is null, say).
UPSTREAM = [{
    "goal": "Chicago Data Pool", "argIndex": 0, "outputDataType": "dataframe",
    "schema": {"kind": "table", "rowCount": 12,
               "columns": [{"name": "community", "dtype": "str"},
                           {"name": "density", "dtype": "float"}],
               "sampleRows": [{"community": "Loop", "density": 1.5}]},
}]


def _recorded(message: str, cause: str, content: str = VALID_DOC) -> dict:
    """The journal record dev/135's reporter leaves for an empty render."""
    return {
        "codeSha256": runtime_journal.normalized_code_sha256(content),
        "stderr": message,
        "ranAt": "2026-09-10T23:10:00Z",
        "origin": "browser",
        "kind": f"empty-render:{cause}",
    }


class TestTheCauseDecidesWhoIsAtFault:
    def test_the_cause_is_read_from_the_kind_not_from_the_prose(self):
        assert rs.empty_render_cause("empty-render:nothing-drawn") == "nothing-drawn"
        assert rs.empty_render_cause("empty-render:no-layers") == "no-layers"
        assert rs.empty_render_cause("empty-render:no-input-rows") == "no-input-rows"
        # An empty render whose reason this build does not know: still an empty
        # render, reason unknown.
        assert rs.empty_render_cause("empty-render:teleported") == ""
        assert rs.empty_render_cause("empty-render") == ""
        # And anything else is not an empty render at all.
        assert rs.empty_render_cause("execution-error") is None
        assert rs.empty_render_cause(None) is None

    def test_only_no_input_rows_spares_the_document(self):
        assert rs.is_document_at_fault("nothing-drawn") is True
        assert rs.is_document_at_fault("no-layers") is True
        assert rs.is_document_at_fault("") is True     # unknown: ask for a fix
        assert rs.is_document_at_fault("no-input-rows") is False

    def test_the_refusal_leads_with_the_renderers_own_sentence(self):
        text = rs.empty_render_refusal(
            message=DREW_NOTHING, cause="nothing-drawn", upstream_outputs=UPSTREAM,
        )
        assert text.startswith("the document is valid and its last render drew NOTHING")
        assert "12 rows arrived" in text                      # the counts
        assert "community str e.g. 'Loop'" in text            # what it HAS
        assert "return the whole document" in text
        assert len(text) <= 900

    def test_an_upstream_fault_does_not_lecture_about_the_encoding(self):
        text = rs.empty_render_refusal(
            message=NO_ROWS, cause="no-input-rows", upstream_outputs=UPSTREAM,
        )
        assert "0 rows arrived" in text
        assert "Encode fields that exist" not in text   # not this document's job


class TestTheLoopCorrectsAnEmptyRender:
    def _node(self, content=VALID_DOC):
        return {"id": "n1", "type": VEGA, "goal": "Density chart", "content": content}

    def test_a_valid_document_that_drew_nothing_is_a_FAILED_round(self, app, tmp_curio):
        events, outcome, inputs = _rounds(
            app, self._node(), replies=[FIXED_DOC], exec_fn=_Exec(),
            start_from_current=True,
            recorded_failure=_recorded(DREW_NOTHING, "nothing-drawn"),
            extra_inputs={"upstreamOutputs": UPSTREAM},
        )
        kinds = [a["kind"] for a in outcome["attempts"]]
        assert kinds[0] == "empty-render"           # round 0 no longer passes
        # The correction was asked for, with the renderer's sentence as the error.
        assert inputs, "the loop asked for a new document"
        assert "drew NOTHING" in inputs[0]["validationError"]
        assert "12 rows arrived" in inputs[0]["validationError"]
        assert inputs[0]["previousAttempt"] == VALID_DOC
        # And the corrected document validates, so it is written.
        assert outcome["verdict"] == "not-executable"
        assert outcome["candidate"] == FIXED_DOC
        assert outcome["evidence"].get("documentValidated") == "vis-vega"

    def test_an_empty_INPUT_leaves_the_document_alone_and_waits(self, app, tmp_curio):
        empty_upstream = [dict(UPSTREAM[0], schema={
            "kind": "table", "rowCount": 0, "columns": [], "sampleRows": [],
        })]
        events, outcome, inputs = _rounds(
            app, self._node(), replies=[FIXED_DOC], exec_fn=_Exec(),
            start_from_current=True,
            recorded_failure=_recorded(NO_ROWS, "no-input-rows"),
            extra_inputs={"upstreamOutputs": empty_upstream},
        )
        # dev/133's rule, applied to a picture: nothing arrived, so no document
        # could have drawn anything — the node waits on its upstream.
        assert inputs == [], "no correction was asked for"
        assert outcome["evidence"]["upstreamEmpty"] is True
        assert outcome["evidence"]["kind"] == "empty-render"
        assert outcome["candidate"] == VALID_DOC          # untouched
        assert "0 rows arrived" in outcome["evidence"]["detail"]

    def test_an_INVALID_document_is_still_fixed_first(self, app, tmp_curio):
        """An invalid document cannot draw at all, so its invalidity is the
        first thing to correct — the empty render is not consulted."""
        invalid = '{"mark": "bar", "encoding": {"x": {"field": "d", "condition": {"else": 1}}}}'
        events, outcome, inputs = _rounds(
            app, self._node(invalid), replies=[FIXED_DOC], exec_fn=_Exec(),
            start_from_current=True,
            recorded_failure=_recorded(DREW_NOTHING, "nothing-drawn", content=invalid),
            extra_inputs={"upstreamOutputs": UPSTREAM},
        )
        assert outcome["attempts"][0]["kind"] == "document-invalid"
        assert "drew NOTHING" not in json.dumps(outcome["attempts"][0])

    def test_a_render_failure_that_is_NOT_empty_is_unchanged(self, app, tmp_curio):
        """A render that threw is dev/135's ordinary failure: the document is
        regenerated from its message, and no empty-render branch fires."""
        events, outcome, inputs = _rounds(
            app, self._node(), replies=[FIXED_DOC], exec_fn=_Exec(),
            start_from_current=True,
            recorded_failure={
                "codeSha256": runtime_journal.normalized_code_sha256(VALID_DOC),
                "stderr": "outputs is not a valid input type for the 2D Plot (Vega-Lite)",
                "ranAt": "2026-09-10T23:10:00Z", "origin": "browser",
            },
            extra_inputs={"upstreamOutputs": UPSTREAM},
        )
        kinds = [a["kind"] for a in outcome["attempts"]]
        assert "empty-render" not in kinds
        assert outcome["verdict"] == "not-executable"   # the document validates

    def test_without_a_recorded_render_nothing_changes(self, app, tmp_curio):
        events, outcome, inputs = _rounds(
            app, self._node(), replies=[], exec_fn=_Exec(), start_from_current=True,
            extra_inputs={"upstreamOutputs": UPSTREAM},
        )
        assert inputs == []                              # the document validates
        assert outcome["verdict"] == "not-executable"
        assert outcome["evidence"].get("documentValidated") == "vis-vega"
