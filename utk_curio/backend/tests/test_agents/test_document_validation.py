"""dev/129: validating what the sandbox cannot run.

The two documents below are the owner's, from dataflow `00708324` — the Vega
spec Solve wrote and called *solved* (invalid: `'else'` inside an encoding
condition) and the AUTK grammar written beside it, unread.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from utk_curio.backend.app.agents.domain import document_validation as dv

VEGA = "curio.builtin/vis-vega"
AUTK = "curio.builtin/autk-grammar"
REPO_ROOT = Path(__file__).resolve().parents[4]

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
    """Against the grammar's own JSON Schema, vendored from autk-grammar, plus
    the one rule no schema form states: the document must run something."""

    def test_the_owners_grammar_is_valid(self):
        # Also the canary for open additional properties: its "initialView" is
        # a key the schema does not name.
        assert dv.validate(AUTK, OWNERS_AUTK) == {"status": dv.STATUS_VALID}

    def test_a_document_naming_nothing_is_invalid(self):
        for grammar in ({}, {"layers": []}, {"compute": []}, {"data": []}):
            verdict = dv.validate(AUTK, json.dumps(grammar))
            assert verdict["status"] == dv.STATUS_INVALID, grammar
            assert '"map"' in verdict["detail"]
            assert "layerRefs" in verdict["detail"] and "dataRef" in verdict["detail"]

    def test_a_map_with_no_layers_renders_nothing_and_is_invalid(self):
        for grammar in ({"map": {}}, {"map": {"layerRefs": []}},
                        {"map": [{"layerRefs": []}]}):
            verdict = dv.validate(AUTK, json.dumps(grammar))
            assert verdict["status"] == dv.STATUS_INVALID, grammar
            assert "layerRefs" in verdict["detail"]

    def test_a_layer_without_a_dataref_is_invalid(self):
        verdict = dv.validate(AUTK, json.dumps({"map": {"layerRefs": [{"style": {}}]}}))
        assert verdict["status"] == dv.STATUS_INVALID
        assert "dataRef" in verdict["detail"]

    def test_a_missing_field_is_named_where_it_belongs(self):
        verdict = dv.validate(AUTK, json.dumps({"map": {}}))
        assert verdict["detail"].startswith('map: missing "layerRefs"')
        verdict = dv.validate(AUTK, json.dumps({"map": {"layerRefs": [{}]}}))
        assert verdict["detail"].startswith('map.layerRefs[0]: missing "dataRef"')

    @pytest.mark.parametrize("grammar", [
        {"map": [{"layerRefs": [{"dataRef": "input_0"}]}]},
        {"plot": {"dataRef": "input_0", "mark": "bar", "axis": ["name", "value"]}},
        {"compute": [{"dataRef": "input_0", "attributes": {"h": "properties.height"},
                      "wglsFunction": "return h * 2.0;", "outputColumnName": "h2"}]},
        {"data": [{"type": "csv", "csvFileUrl": "a.csv", "outputTableName": "t"}]},
    ], ids=["map-list", "plot", "compute", "data"])
    def test_one_document_per_family_is_valid(self, grammar):
        assert dv.validate(AUTK, json.dumps(grammar)) == {"status": dv.STATUS_VALID}

    @pytest.mark.parametrize("grammar,named", [
        ({"plot": {"dataRef": "input_0", "mark": "pie", "axis": ["a"]}}, "pie"),
        ({"plot": {"dataRef": "input_0", "mark": "bar", "axis": []}}, "plot.axis"),
        ({"compute": [{"dataRef": "input_0", "attributes": {},
                       "wglsFunction": "return 1.0;"}]}, "outputColumnName"),
        # A heatmap once validated as a csv source; the type now selects its fields.
        ({"data": [{"type": "heatmap", "outputTableName": "x"}]}, "tableJoinName"),
    ], ids=["plot-mark", "plot-axis", "compute-output", "data-type"])
    def test_one_document_per_family_is_invalid_and_says_why(self, grammar, named):
        verdict = dv.validate(AUTK, json.dumps(grammar))
        assert verdict["status"] == dv.STATUS_INVALID
        assert named in verdict["detail"]

    def test_the_widened_compute_forms_are_valid(self):
        grammar = {"compute": [{
            "dataRef": "input_0",
            "attributes": {"h": "properties.height"},
            "wglsFunction": ["let x = h;", "// a comment", "return x;"],
            "uniforms": {"sun": {"fromFeature": {"layer": "sun", "path": "properties.alt",
                                                 "iterate": "batched"}, "default": 0}},
            "uniformMatrices": {"box": {"fromFeature": {"layer": "zones", "path": "geometry"},
                                        "cols": 2}},
            "outputColumnName": "shade",
        }]}
        assert dv.validate(AUTK, json.dumps(grammar)) == {"status": dv.STATUS_VALID}

    def test_keys_the_schema_does_not_name_are_allowed(self):
        grammar = {"note": "x", "map": {"layerRefs": [{"dataRef": "t", "custom": 1}],
                                        "initialView": {"zoom": 3}}}
        assert dv.validate(AUTK, json.dumps(grammar)) == {"status": dv.STATUS_VALID}

    def test_at_most_five_complaints_are_reported(self):
        grammar = {"map": {"layerRefs": [{} for _ in range(8)]}}
        detail = dv.validate(AUTK, json.dumps(grammar))["detail"]
        assert detail.count('missing "dataRef"') == dv._MAX_SCHEMA_ERRORS

    def test_jsonschema_missing_degrades_to_unchecked(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def _no_jsonschema(name, *a, **k):
            if name == "jsonschema":
                raise ImportError("no jsonschema here")
            return real_import(name, *a, **k)

        dv.validate(AUTK, OWNERS_AUTK)  # anything cached is already warm
        monkeypatch.setattr(builtins, "__import__", _no_jsonschema)
        verdict = dv.validate(AUTK, OWNERS_AUTK)
        assert verdict["status"] == dv.STATUS_UNCHECKED
        assert "jsonschema is unavailable" in verdict["why"]

    def test_an_unreadable_schema_degrades_to_unchecked(self, monkeypatch):
        from utk_curio.backend.app.agents.domain import contracts

        def _missing():
            raise FileNotFoundError("autk-grammar.v1.json")

        monkeypatch.setattr(contracts, "load_autk_schema", _missing)
        verdict = dv.validate(AUTK, OWNERS_AUTK)
        assert verdict["status"] == dv.STATUS_UNCHECKED
        assert "could not be read" in verdict["why"]


#: What an Autark node's error says of a document with more than one map
#: (``src/tests/adapters/node/autkOneMap.test.tsx``).
ONE_MAP = ("An Autark node draws one map. Put each map in its own Autark node, "
           "and link them with interaction edges.")
A_MAP = {"layerRefs": [{"dataRef": "input_0"}]}


class TestOneMapPerNode:
    """An Autark node draws one map, so a document that lists more is refused
    before it is written, with the words the node's own error says."""

    @pytest.mark.parametrize("count", [2, 3])
    def test_a_document_with_several_maps_is_refused_with_the_fix(self, count):
        verdict = dv.validate(AUTK, json.dumps({"map": [A_MAP] * count}))
        assert verdict == {"status": dv.STATUS_INVALID, "detail": ONE_MAP}

    def test_the_maps_are_counted_before_the_schema_is_applied(self):
        # The fix is to split the document, so its maps' own errors wait.
        grammar = {"map": [A_MAP, {"layerRefs": [{}]}]}
        assert dv.validate(AUTK, json.dumps(grammar)) == {"status": dv.STATUS_INVALID, "detail": ONE_MAP}

    def test_one_map_and_a_list_of_one_map_are_valid(self):
        for grammar in ({"map": A_MAP}, {"map": [A_MAP]}):
            assert dv.validate(AUTK, json.dumps(grammar)) == {"status": dv.STATUS_VALID}, grammar

    def test_the_refusal_says_the_fix_in_its_own_sentence(self):
        verdict = dv.validate(AUTK, json.dumps({"map": [A_MAP, A_MAP]}))
        text = dv.refusal_text(AUTK, verdict)
        assert f"does not validate: {ONE_MAP.removesuffix('.')}. Fix exactly that" in text


def _shipped_autk_documents() -> list:
    """Every Autark node's content in the shipped examples, as (where, content).

    A dataflow's node is read as a run reads it, with its references resolved
    (#662): a spec that places a widget as a value, ``"height_factor":
    [!! height_factor !!]``, is not JSON until a run gives it the widget's value.
    """
    from utk_curio.backend.app.execution.workflow_spec import parse_workflow_dict

    found = []

    def _resolver(doc):
        flow = doc.get("dataflow") if isinstance(doc, dict) else None
        if not isinstance(flow, dict) or not isinstance(flow.get("nodes"), list):
            return {}
        spec = parse_workflow_dict(doc)
        return {node.id: (lambda node=node: spec.node_code(node, "json")) for node in spec.nodes}

    def _walk(value, where, resolve):
        if isinstance(value, dict):
            if value.get("type") in ("AUTK_GRAMMAR", AUTK) and isinstance(value.get("content"), str):
                read = resolve.get(value.get("id"))
                found.append((f"{where}#{value.get('id')}", read() if read else value["content"]))
            for child in value.values():
                _walk(child, where, resolve)
        elif isinstance(value, list):
            for child in value:
                _walk(child, where, resolve)

    for path in sorted((REPO_ROOT / "docs" / "examples").rglob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        _walk(doc, path.relative_to(REPO_ROOT), _resolver(doc))
    return found


def _draws_a_legend(ref: dict) -> bool:
    """Whether a map layer shows a legend: autk-grammar turns the legend on for a
    layer that colours by a column (``getFnv``) or names a scheme
    (``colorMapInterpolator``), and ``"isColorMap": false`` hides it
    (``recolorRasters`` keeps it hidden on a raster)."""
    if ref.get("isColorMap") is False:
        return False
    return bool(ref.get("getFnv") or ref.get("colorMapInterpolator") or ref.get("isColorMap"))


class TestShippedAutarkDocuments:
    def test_every_shipped_document_is_valid(self):
        documents = _shipped_autk_documents()
        assert len(documents) >= 28
        refused = {where: verdict for where, content in documents
                   if (verdict := dv.validate(AUTK, content))["status"] != dv.STATUS_VALID}
        assert refused == {}

    def test_every_shipped_legend_names_what_it_shows(self):
        """#771: autk-map titles a legend with its layer's table, so a map of a
        node's input read ``input_0`` and an OpenStreetMap layer its table
        (``table_osm_roads``). Every shipped layer that shows a legend names
        it with ``legendTitle`` (#747)."""
        untitled, legends = [], 0
        for where, content in _shipped_autk_documents():
            maps = json.loads(content).get("map") or []
            for map_spec in maps if isinstance(maps, list) else [maps]:
                for ref in map_spec.get("layerRefs") or []:
                    if not _draws_a_legend(ref):
                        continue
                    legends += 1
                    title = ref.get("legendTitle")
                    if not isinstance(title, str) or not title.strip() or re.fullmatch(r"input_\d+", title.strip()):
                        untitled.append(f"{where} {ref.get('dataRef')} (colours by {ref.get('getFnv')!r})")
        assert legends >= 23
        assert untitled == [], "map layers whose legend has no title:\n  " + "\n  ".join(untitled)


class TestRouting:
    def test_a_passive_boxes_marker_is_nothing_to_write(self):
        for kind in ("curio.builtin/data-export", "curio.builtin/data-pool",
                     "curio.builtin/vis-simple"):
            verdict = dv.validate(kind, "not controllable")
            assert verdict["status"] == dv.STATUS_UNCHECKED
            assert verdict["passive"] is True

    def test_passive_is_the_rosters_content_kind(self):
        # A template that authors nothing is passive, whatever its name.
        assert dv.validate("acme.flows/fan-in", "not controllable",
                           content_kind="none")["passive"] is True
        # And the roster's kind wins over the offline tables, which call a
        # data-pool passive.
        assert dv.validate("curio.builtin/data-pool", "not controllable",
                           content_kind="note")["passive"] is False

    def test_an_empty_document_is_now_refused_for_a_grammar_kind(self):
        # dev/134 corrects dev/129 here: for a kind that HAS a validator, "no
        # document" is not "cannot be checked" — it is a refusal the loop must
        # correct, because the node needs a document and nothing is written
        # until one arrives. See TestProseIsARefusalNotAnUnchecked below.
        assert dv.validate(VEGA, "")["status"] == dv.STATUS_INVALID
        assert dv.validate(VEGA, None)["status"] == dv.STATUS_INVALID

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
            app, "curio.builtin/vis-simple", ["not controllable"],
        )
        assert (outcome["evidence"] or {}).get("documentPassive") is True

    def test_an_invalid_autk_grammar_is_corrected_too(self, app, tmp_curio):
        events, outcome, inputs = self._rounds(
            app, AUTK, ['{"map": {"layerRefs": []}}', OWNERS_AUTK],
        )
        assert [a["kind"] for a in outcome["attempts"]][0] == "document-invalid"
        assert (outcome["evidence"] or {}).get("documentValidated") == "autk-grammar"
        assert outcome["candidate"] == OWNERS_AUTK

    # #662: a document is checked as it is drawn, its references resolved.
    _WITH_WIDGET = (
        '{"$schema": "https://vega.github.io/schema/vega-lite/v6.json", '
        '"mark": {"type": "bar", "opacity": [!! opacity !!]}, '
        '"title": "Season: [!! season !!]", '
        '"encoding": {"x": {"field": "density", "type": "quantitative"}}}'
    )

    def _widget_rounds(self, app, replies):
        from utk_curio.backend.tests.test_agents.test_verified_rounds import _Exec, _rounds

        node = {
            "id": "n1", "type": VEGA, "goal": "Density chart", "content": "",
            "metadata": {"widgets": [
                {"name": "opacity", "type": "slider", "default": 0.5, "options": {"min": 0, "max": 1}},
                {"name": "season", "type": "text", "default": "winter"},
            ]},
        }
        spec = {"dataflow": {"nodes": [node], "edges": [], "name": "wf", "task": "t"}}
        return _rounds(app, node, replies=replies, exec_fn=_Exec(), spec=spec)

    def test_a_document_that_places_its_widgets_is_checked_with_their_values(self, app, tmp_curio):
        """Unresolved, a bare reference is not JSON and the document was refused;
        resolved, it is the document the canvas draws, and it is valid. What is
        written keeps the references, so the Widgets tab still sets them."""
        events, outcome, inputs = self._widget_rounds(app, [self._WITH_WIDGET])
        assert "document-invalid" not in [a.get("kind") for a in outcome["attempts"]]
        assert len(inputs) == 1, "the first document was accepted: no correction round"
        assert (outcome["evidence"] or {}).get("documentValidated") == "vis-vega"
        assert outcome["candidate"] == self._WITH_WIDGET

    def test_a_reference_the_node_cannot_resolve_is_a_round_naming_it(self, app, tmp_curio):
        broken = self._WITH_WIDGET.replace("[!! opacity !!]", "[!! alpha !!]")
        events, outcome, inputs = self._widget_rounds(app, [broken, self._WITH_WIDGET])
        assert [a["kind"] for a in outcome["attempts"]][0] == "document-invalid"
        assert "this node has no widget named alpha" in outcome["attempts"][0]["detail"]
        assert "this node has no widget named alpha" in inputs[1]["validationError"]
        assert outcome["candidate"] == self._WITH_WIDGET


class TestProseIsARefusalNotAnUnchecked:
    """dev/134, from `e72c7080`: the child replied the sentence "not
    controllable" for an autk-grammar node and it was WRITTEN as the grammar.
    For a kind with a validator that reply is a refusal — the loop asks again
    with the shape named — and nothing is written until a document arrives."""

    def test_the_not_controllable_marker_is_refused_for_a_grammar_kind(self):
        verdict = dv.validate("curio.builtin/autk-grammar", "not controllable")
        assert verdict["status"] == dv.STATUS_INVALID
        assert "no document here at all" in verdict["detail"]
        assert "layerRefs" in verdict["detail"]  # the shape is named
        assert "dataRef" in verdict["detail"]

    def test_the_attempt_trail_keeps_the_map_example(self):
        # The trail cuts each detail shorter than the refusal itself.
        from utk_curio.backend.app.agents.application.solve import budgets as services

        verdict = dv.validate(AUTK, "not controllable")
        head = dv.refusal_text(AUTK, verdict)[:services._ATTEMPT_DETAIL_CHARS]
        assert '"layerRefs"' in head and '"dataRef"' in head

    def test_empty_content_is_refused_for_a_grammar_kind(self):
        verdict = dv.validate("curio.builtin/vis-vega", "   ")
        assert verdict["status"] == dv.STATUS_INVALID
        assert "$schema" in verdict["detail"]
        # And the Vega contract the runtime imposes is stated, not implied.
        assert "Curio injects this node's input as the data" in verdict["detail"]

    def test_prose_is_refused_with_what_was_expected(self):
        verdict = dv.validate(
            "curio.builtin/vis-vega",
            "I cannot produce a chart without knowing the columns.",
        )
        assert verdict["status"] == dv.STATUS_INVALID
        assert "prose, not a document" in verdict["detail"]
        assert "I cannot produce a chart" in verdict["detail"]

    def test_a_wired_kind_keeps_its_unchecked_and_passive_answer(self):
        # vis-simple/data-pool have no validator: "unchecked" keeps its narrow
        # meaning, and dev/134 stops them being asked at all.
        for node_type in ("curio.builtin/vis-simple", "curio.builtin/data-pool"):
            verdict = dv.validate(node_type, "not controllable")
            assert verdict["status"] == dv.STATUS_UNCHECKED
            assert verdict["passive"] is True

    def test_a_grammar_with_no_validator_is_unchecked_not_refused(self):
        verdict = dv.validate("pkg.custom/plotly-view", '{"data": []}',
                              grammar_id="plotly")
        assert verdict["status"] == dv.STATUS_UNCHECKED
        assert "plotly" in verdict["why"]


class TestRoutingByGrammarId:
    def test_the_roster_grammar_routes_a_third_party_vega_node(self):
        spec = '{"mark": "bar", "encoding": {"x": {"field": "a", "type": "quantitative"}}}'
        assert dv.validate("pkg.custom/chart", spec, grammar_id="vega-lite")["status"] == dv.STATUS_VALID
        assert dv.grammar_of("pkg.custom/chart", "vega-lite") == "vega-lite"

    def test_the_suffix_is_the_offline_fallback(self):
        assert dv.grammar_of("curio.builtin/vis-vega@2") == "vega-lite"
        assert dv.grammar_of("curio.builtin/autk-grammar") == "autk-grammar"
        assert dv.grammar_of("curio.builtin/data-pool") is None

    def test_the_refusal_text_names_the_grammar(self):
        text = dv.refusal_text(
            "pkg.custom/chart", {"detail": "boom"}, grammar_id="vega-lite",
        )
        assert "Vega-Lite" in text and "boom" in text


class TestVegaFieldReferences:
    """dev/129 F3, closed. The owner's chart was schema-valid and plotted
    nothing: it encoded a column that does not exist."""

    COLUMNS = ["community", "area_numbe", "population", "density"]

    def _spec(self, y_field: str) -> str:
        import json as _json

        return _json.dumps({
            "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
            "mark": "bar",
            "encoding": {
                "x": {"field": "density", "type": "quantitative"},
                "y": {"field": y_field, "type": "nominal", "sort": "-x"},
            },
        })

    def test_an_unknown_field_is_invalid_and_the_columns_are_named(self):
        verdict = dv.validate(
            "curio.builtin/vis-vega", self._spec("neighborhood"), columns=self.COLUMNS,
        )
        assert verdict["status"] == dv.STATUS_INVALID
        assert "encoding.y.field reads 'neighborhood'" in verdict["detail"]
        assert "available columns: area_numbe, community, density, population" in verdict["detail"]

    def test_the_same_spec_with_a_real_column_is_valid(self):
        assert dv.validate(
            "curio.builtin/vis-vega", self._spec("community"), columns=self.COLUMNS,
        )["status"] == dv.STATUS_VALID

    def test_the_runtime_fields_curio_adds_are_allowed(self):
        import json as _json

        spec = _json.dumps({
            "mark": "bar",
            "encoding": {
                "x": {"field": "density", "type": "quantitative"},
                "color": {"field": "interacted", "type": "nominal"},
                "tooltip": [{"field": "__row_index__", "type": "quantitative"}],
            },
        })
        assert dv.validate("curio.builtin/vis-vega", spec, columns=self.COLUMNS)[
            "status"] == dv.STATUS_VALID

    def test_a_column_a_transform_creates_is_allowed(self):
        import json as _json

        spec = _json.dumps({
            "mark": "bar",
            "transform": [
                {"calculate": "datum.population / 1000", "as": "pop_k"},
                {"aggregate": [{"op": "mean", "field": "density", "as": "mean_density"}],
                 "groupby": ["community"]},
            ],
            "encoding": {
                "x": {"field": "mean_density", "type": "quantitative"},
                "y": {"field": "community", "type": "nominal"},
            },
        })
        assert dv.validate("curio.builtin/vis-vega", spec, columns=self.COLUMNS)[
            "status"] == dv.STATUS_VALID

    def test_a_transform_groupby_on_an_unknown_column_is_invalid(self):
        import json as _json

        spec = _json.dumps({
            "mark": "bar",
            "transform": [{"aggregate": [{"op": "mean", "field": "density", "as": "m"}],
                           "groupby": ["nabe"]}],
            "encoding": {"x": {"field": "m", "type": "quantitative"}},
        })
        verdict = dv.validate("curio.builtin/vis-vega", spec, columns=self.COLUMNS)
        assert verdict["status"] == dv.STATUS_INVALID
        assert "groupby[0] reads 'nabe'" in verdict["detail"]

    def test_a_layered_spec_is_walked(self):
        import json as _json

        spec = _json.dumps({
            "layer": [
                {"mark": "bar",
                 "encoding": {"x": {"field": "density", "type": "quantitative"}}},
                {"mark": "text",
                 "encoding": {"text": {"field": "ghost", "type": "nominal"}}},
            ],
        })
        verdict = dv.validate("curio.builtin/vis-vega", spec, columns=self.COLUMNS)
        assert verdict["status"] == dv.STATUS_INVALID
        assert "'ghost'" in verdict["detail"]

    def test_an_opaque_transform_skips_the_field_check(self):
        import json as _json

        spec = _json.dumps({
            "mark": "bar",
            "transform": [{"fold": ["population", "density"]}],
            "encoding": {"x": {"field": "key", "type": "nominal"},
                         "y": {"field": "value", "type": "quantitative"}},
        })
        # `fold` creates key/value columns this module cannot enumerate: the
        # schema still decides, and no field is refused on a guess.
        assert dv.validate("curio.builtin/vis-vega", spec, columns=self.COLUMNS)[
            "status"] == dv.STATUS_VALID

    def test_unknown_columns_skip_the_check_entirely(self):
        assert dv.validate(
            "curio.builtin/vis-vega", self._spec("neighborhood"), columns=None,
        )["status"] == dv.STATUS_VALID
        assert dv.validate(
            "curio.builtin/vis-vega", self._spec("neighborhood"), columns=[],
        )["status"] == dv.STATUS_VALID

    def test_a_repeat_spec_names_no_column_and_is_not_refused(self):
        import json as _json

        spec = _json.dumps({
            "repeat": {"column": ["density", "population"]},
            "spec": {"mark": "bar",
                     "encoding": {"x": {"field": {"repeat": "column"},
                                        "type": "quantitative"}}},
        })
        assert dv.validate("curio.builtin/vis-vega", spec, columns=self.COLUMNS)[
            "status"] == dv.STATUS_VALID
