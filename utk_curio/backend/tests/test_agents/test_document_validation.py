"""dev/129: validating what the sandbox cannot run.

The two documents below are the owner's, from dataflow `00708324` — the Vega
spec Solve wrote and called *solved* (invalid: `'else'` inside an encoding
condition) and the AUTK grammar written beside it, unread.
"""

from __future__ import annotations

import json

from utk_curio.backend.app.agents import document_validation as dv

VEGA = "curio.builtin/vis-vega"
AUTK = "curio.builtin/autk-grammar"

OWNERS_VEGA = json.dumps({
    "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
    "mark": {"type": "bar"},
    "encoding": {
        "x": {"field": "density", "type": "quantitative"},
        "color": {
            "field": "interacted", "type": "nominal",
            # The defect: `else` is not part of a condition object.
            "condition": {"test": "datum.interacted === '1'", "value": "red",
                          "else": "steelblue"},
        },
    },
})

FIXED_VEGA = json.dumps({
    "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
    "mark": {"type": "bar"},
    "encoding": {
        "x": {"field": "density", "type": "quantitative"},
        "color": {
            "condition": {"test": "datum.interacted === '1'", "value": "red"},
            "value": "steelblue",
        },
    },
})

OWNERS_AUTK = json.dumps({
    "map": {
        "layerRefs": [{"dataRef": "population_density",
                       "style": {"opacity": 0.8, "fill": True}}],
        "initialView": {"center": [-87.6298, 41.8781], "zoom": 11},
    }
})


class TestVegaLite:
    def test_the_owners_spec_is_invalid_and_the_message_names_the_property(self):
        verdict = dv.validate(VEGA, OWNERS_VEGA)
        assert verdict["status"] == dv.STATUS_INVALID
        assert "'else' was unexpected" in verdict["detail"]

    def test_the_corrected_spec_is_valid(self):
        assert dv.validate(VEGA, FIXED_VEGA) == {"status": dv.STATUS_VALID}

    def test_a_spec_without_data_is_correct_here(self):
        # Curio injects the node's input at render time, so the schema's
        # "data is required" must not be reported as the author's error.
        assert dv.validate(VEGA, FIXED_VEGA)["status"] == dv.STATUS_VALID
        assert '"data"' not in FIXED_VEGA

    def test_an_authors_own_data_block_is_kept(self):
        spec = json.loads(FIXED_VEGA)
        spec["data"] = {"values": [{"density": 1, "interacted": "0"}]}
        assert dv.validate(VEGA, json.dumps(spec))["status"] == dv.STATUS_VALID

    def test_a_parse_error_is_invalid_with_its_position(self):
        verdict = dv.validate(VEGA, '{"mark": "bar",}')
        assert verdict["status"] == dv.STATUS_INVALID
        assert "not valid JSON" in verdict["detail"]
        assert "line" in verdict["detail"] or "char" in verdict["detail"]

    def test_a_non_object_document_is_invalid(self):
        assert dv.validate(VEGA, "[1, 2]")["status"] == dv.STATUS_INVALID

    def test_altair_missing_degrades_to_unchecked(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def _no_altair(name, *a, **k):
            if name == "altair":
                raise ImportError("no altair here")
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", _no_altair)
        verdict = dv.validate(VEGA, FIXED_VEGA)
        assert verdict["status"] == dv.STATUS_UNCHECKED
        assert "altair is unavailable" in verdict["why"]


class TestAutkGrammar:
    def test_the_owners_grammar_is_valid(self):
        assert dv.validate(AUTK, OWNERS_AUTK) == {"status": dv.STATUS_VALID}

    def test_a_document_without_a_map_is_invalid(self):
        verdict = dv.validate(AUTK, json.dumps({"layers": []}))
        assert verdict["status"] == dv.STATUS_INVALID
        assert '"map"' in verdict["detail"]

    def test_a_map_with_no_layers_renders_nothing_and_is_invalid(self):
        for grammar in ({"map": {}}, {"map": {"layerRefs": []}}):
            verdict = dv.validate(AUTK, json.dumps(grammar))
            assert verdict["status"] == dv.STATUS_INVALID
            assert "layerRefs" in verdict["detail"]

    def test_a_layer_without_a_dataref_is_invalid(self):
        verdict = dv.validate(AUTK, json.dumps({"map": {"layerRefs": [{"style": {}}]}}))
        assert verdict["status"] == dv.STATUS_INVALID
        assert "dataRef" in verdict["detail"]

    def test_a_malformed_initial_view_is_invalid(self):
        verdict = dv.validate(AUTK, json.dumps({
            "map": {"layerRefs": [{"dataRef": "x"}], "initialView": {"center": [1]}},
        }))
        assert verdict["status"] == dv.STATUS_INVALID
        assert "longitude" in verdict["detail"]

    def test_an_absent_initial_view_is_fine(self):
        assert dv.validate(AUTK, json.dumps({"map": {"layerRefs": [{"dataRef": "x"}]}})) == {
            "status": dv.STATUS_VALID
        }


class TestRouting:
    def test_a_passive_boxes_marker_is_nothing_to_write(self):
        for kind in ("curio.builtin/merge-flow", "curio.builtin/data-pool",
                     "curio.builtin/vis-simple"):
            verdict = dv.validate(kind, "not controllable")
            assert verdict["status"] == dv.STATUS_UNCHECKED
            assert verdict["passive"] is True

    def test_an_empty_document_is_nothing_to_write(self):
        assert dv.validate(VEGA, "")["status"] == dv.STATUS_UNCHECKED
        assert dv.validate(VEGA, None)["status"] == dv.STATUS_UNCHECKED

    def test_a_kind_with_no_validator_says_so(self):
        verdict = dv.validate("curio.builtin/data-loading", "print(1)")
        assert verdict["status"] == dv.STATUS_UNCHECKED
        assert "no document validator exists for data-loading" in verdict["why"]

    def test_versioned_and_legacy_kind_spellings_route(self):
        assert dv.validate("curio.builtin/vis-vega@2", OWNERS_VEGA)["status"] == dv.STATUS_INVALID
        assert dv.validate("VIS_VEGA", OWNERS_VEGA)["status"] == dv.STATUS_INVALID
        assert dv.canonical_suffix("pkg/autk-grammar@1") == "autk-grammar"

    def test_the_refusal_names_the_document_kind_and_the_rule(self):
        verdict = dv.validate(VEGA, OWNERS_VEGA)
        text = dv.refusal_text(VEGA, verdict)
        assert text.startswith("document refused")
        assert "Vega-Lite document" in text
        assert "'else' was unexpected" in text
        assert "nothing is written to the node until it validates" in text


class TestTheWriteGateInTheLoop:
    """dev/129: an invalid document is a ROUND, a valid one is written with a
    stronger claim, and one nothing can check is NOT written."""

    def _rounds(self, app, node_type, replies, **kw):
        from utk_curio.backend.tests.test_agents.test_verified_rounds import _Exec, _rounds

        node = {"id": "n1", "type": node_type, "goal": "Density chart", "content": ""}
        spec = {"dataflow": {"nodes": [node], "edges": [], "name": "wf", "task": "t"}}
        return _rounds(app, node, replies=replies, exec_fn=kw.pop("exec_fn", None) or _Exec(),
                       spec=spec, **kw)

    def test_an_invalid_vega_document_is_corrected_within_the_loop(self, app, tmp_curio):
        events, outcome, inputs = self._rounds(
            app, VEGA, [OWNERS_VEGA, FIXED_VEGA],
        )
        kinds = [a["kind"] for a in outcome["attempts"]]
        assert kinds[0] == "document-invalid"
        assert outcome["verdict"] == "not-executable"
        assert (outcome["evidence"] or {}).get("documentValidated") == "vis-vega"
        assert outcome["candidate"] == FIXED_VEGA
        # The refused document rides the trail with the validator's complaint.
        assert "'else' was unexpected" in outcome["attempts"][0]["detail"]
        assert outcome["attempts"][0]["code"] == OWNERS_VEGA
        # And the correction was told exactly what to fix.
        assert "document refused" in inputs[1]["validationError"]

    def test_a_kind_with_no_validator_is_reported_unchecked(self, app, tmp_curio):
        events, outcome, inputs = self._rounds(
            app, "curio.builtin/some-package-grammar", ['{"whatever": 1}'],
        )
        assert outcome["verdict"] == "not-executable"
        assert "no document validator exists" in (outcome["evidence"] or {}).get(
            "documentUnchecked", ""
        )
        assert (outcome["evidence"] or {}).get("documentPassive") is False

    def test_a_passive_box_marker_stays_passive(self, app, tmp_curio):
        events, outcome, inputs = self._rounds(
            app, "curio.builtin/merge-flow", ["not controllable"],
        )
        assert (outcome["evidence"] or {}).get("documentPassive") is True

    def test_an_invalid_autk_grammar_is_corrected_too(self, app, tmp_curio):
        events, outcome, inputs = self._rounds(
            app, AUTK, ['{"map": {"layerRefs": []}}', OWNERS_AUTK],
        )
        assert [a["kind"] for a in outcome["attempts"]][0] == "document-invalid"
        assert (outcome["evidence"] or {}).get("documentValidated") == "autk-grammar"
        assert outcome["candidate"] == OWNERS_AUTK
