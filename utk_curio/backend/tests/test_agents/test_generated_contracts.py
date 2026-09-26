"""Every generated contract output matches a fresh render of its source.

``contracts.py`` is the one definition of each contract; the files listed in
``contracts.GENERATED_OUTPUTS`` are copies written by
``scripts/generate_contracts.py``. A hand edit to a copy, or a change to the
source that was never regenerated, is exactly the drift the module exists to
prevent, so it fails here.
"""

from __future__ import annotations

import difflib
from pathlib import Path

import pytest

from utk_curio.backend.app.agents import contracts

REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize("relative", sorted(contracts.GENERATED_OUTPUTS))
def test_the_committed_output_matches_its_source(relative):
    path = REPO_ROOT / relative
    expected = contracts.GENERATED_OUTPUTS[relative]()
    assert path.is_file(), (
        f"{relative} is missing: run python {contracts.GENERATOR}"
    )
    actual = path.read_text(encoding="utf-8")
    if actual != expected:
        diff = "".join(difflib.unified_diff(
            expected.splitlines(keepends=True), actual.splitlines(keepends=True),
            fromfile="rendered", tofile=relative,
        ))
        pytest.fail(
            f"{relative} is out of date with {contracts.SOURCE_MODULE}: run "
            f"python {contracts.GENERATOR}\n{diff}"
        )


def test_the_check_and_the_registry_agree():
    assert contracts.stale_outputs(REPO_ROOT) == []


def test_every_code_output_names_its_generator_and_source():
    for relative, render in contracts.GENERATED_OUTPUTS.items():
        if relative.startswith(contracts.PROMPTS_DIR):
            continue  # sent to the model verbatim, so it carries no header
        head = render()[:400]
        assert contracts.GENERATOR in head
        assert contracts.SOURCE_MODULE in head
        assert "Do not edit by hand" in head


def test_every_generated_prompt_has_its_template_beside_it():
    prompts = [r for r in contracts.GENERATED_OUTPUTS if r.startswith(contracts.PROMPTS_DIR)]
    assert prompts
    for relative in prompts:
        assert (REPO_ROOT / relative.replace(".txt", ".template.txt")).is_file()


class TestTheRenderCauseTable:
    def test_the_cause_names_and_their_order(self):
        assert contracts.EMPTY_RENDER_CAUSES == (
            "no-layers", "no-input-rows", "nothing-drawn", "empty-source",
        )

    def test_only_no_input_rows_spares_the_document(self):
        at_fault = {c.name: c.document_at_fault for c in contracts.RENDER_CAUSES}
        assert at_fault == {
            "no-layers": True, "no-input-rows": False,
            "nothing-drawn": True, "empty-source": True,
        }

    def test_an_unknown_cause_is_still_the_documents_fault(self):
        assert contracts.is_document_at_fault("teleported") is True
        assert contracts.is_document_at_fault("") is True
        assert contracts.is_document_at_fault(None) is True

    def test_every_cause_is_described_in_one_line(self):
        for cause in contracts.RENDER_CAUSES:
            assert cause.description and "\n" not in cause.description


class TestTheAutarkRenderers:
    """The schema is rendered twice: a one-line shape for refusals and a
    preamble region. Both read the vendored file, never a hand-kept copy."""

    def test_the_shape_names_every_family_and_fits_a_refusal_whole(self):
        from utk_curio.backend.app.agents import document_validation as dv

        schema = contracts.load_autk_schema()
        shape = contracts.render_autk_shape(schema)
        assert "\n" not in shape
        for family in contracts.autk_families(schema):
            assert f'"{family}"' in shape
        assert f'"dataRef": "{contracts.AUTK_UPSTREAM_LAYER}"' in shape
        # The whole shape survives the refusal's 600-character cut.
        assert shape in dv.validate(contracts.AUTK_TEMPLATE, "not controllable")["detail"]

    def test_the_region_names_what_the_schema_requires(self):
        schema = contracts.load_autk_schema()
        region = contracts.render_autk_region(schema, "Autark")
        assert schema["$id"] in region
        assert contracts.AUTK_TEMPLATE in region
        assert f'"{contracts.AUTK_UPSTREAM_LAYER}"' in region
        for union, key in (("DataSourceSpec", "type"), ("PlotSpec", "mark")):
            for values, _ in contracts._variants(schema, union, key):
                for value in values:
                    assert f'"{value}"' in region, (union, value)

    def test_the_preamble_fills_every_field_and_names_no_retired_node(self):
        text = contracts.render_default_preamble()
        assert "{{" not in text
        assert "AUTK_MAP" not in text
        assert "initialView" not in text


def _manifest() -> dict:
    import json

    return json.loads((REPO_ROOT / contracts.BUILTIN_MANIFEST).read_text(encoding="utf-8"))


def _trill() -> dict:
    import json

    return json.loads((REPO_ROOT / contracts.TRILL_SCHEMA).read_text(encoding="utf-8"))


#: The node vocabulary the preamble used before its lists were generated. No
#: prompt names a node by it any more.
_LEGACY_NAMES = (
    "DATA_LOADING", "DATA_EXPORT", "DATA_TRANSFORMATION", "COMPUTATION_ANALYSIS",
    "VIS_VEGA", "VIS_SIMPLE", "DATA_POOL", "MERGE_FLOW", "AUTK_GRAMMAR",
)


class TestThePreambleVocabulary:
    def test_every_list_names_every_template_by_label(self):
        manifest = _manifest()
        lists = contracts.builtin_lists(manifest)
        labels = [t["label"] for t in manifest["templates"]]
        for key in ("builtin.nodes", "builtin.control", "builtin.inputs", "builtin.outputs"):
            assert [line.split(":", 1)[0] for line in lists[key].splitlines()] == [f"- {l}" for l in labels], key

    def test_each_row_reads_its_template(self):
        manifest = _manifest()
        lists = contracts.builtin_lists(manifest)
        by_label = {t["label"]: t for t in manifest["templates"]}
        vega, loading = by_label["Vega-Lite"], by_label["Data Loading"]
        assert f"- Vega-Lite: {vega['description']}" in lists["builtin.nodes"].splitlines()
        assert "- Vega-Lite: controllable through grammar." in lists["builtin.control"]
        assert "- JS Computation: controllable through JavaScript code." in lists["builtin.control"]
        assert "- Data Loading: no input supported" in lists["builtin.inputs"]
        # Vega-Lite takes a GeoDataFrame, which the hand-kept list said it did not.
        assert "- Vega-Lite: DATAFRAME, GEODATAFRAME" in lists["builtin.inputs"]
        assert not any(line.startswith("- Data Loading:") for line in lists["builtin.input_count"].splitlines())
        assert lists["builtin.interaction"].splitlines() == [
            f"- {t['label']}" for t in manifest["templates"] if t.get("bidirectional")
        ]
        assert loading["outputPorts"][0]["cardinality"] in lists["builtin.output_count"]

    def test_an_input_count_is_the_connections_a_node_accepts(self):
        # The declared "[1,n]" of a port is not what the canvas holds: one edge
        # per input socket, and the Merge Flow's slots (maxIncomingEdges).
        from utk_curio.backend.app.packages.services import input_capacity

        lists = contracts.builtin_lists(_manifest())
        counts = dict(line[2:].split(": ", 1) for line in lists["builtin.input_count"].splitlines())
        assert counts["Python Computation"] == "1"
        assert counts["Spatial Join"] == "2"
        assert counts["Merge Flow"] == str(input_capacity(contracts.MERGE_TEMPLATE, 1))
        slots = input_capacity(contracts.MERGE_TEMPLATE, 1)
        assert lists["builtin.merge_slots"].endswith(f'or "in_{slots - 1}"')

    def test_the_lists_name_no_template_id(self):
        # The run's roster is the authority on ids; a list to copy them from
        # is how a Dataflow Builder once looped on a refused id.
        for text in contracts.builtin_lists(_manifest()).values():
            assert "curio.builtin/" not in text

    def test_no_prompt_names_a_node_by_its_legacy_name(self):
        import re

        from utk_curio.backend.app.agents import builtin

        for path in sorted(builtin.PROMPT_SOURCE_DIR.glob("*.txt")):
            found = re.findall(r"\b(" + "|".join(_LEGACY_NAMES) + r")\b", path.read_text(encoding="utf-8"))
            assert not found, f"{path.name} names {sorted(set(found))}"


class TestTheTrillBlock:
    def test_it_is_the_schemas_shape_for_the_fields_agents_use(self):
        import json

        block = json.loads(contracts.render_trill_block(_trill()))
        dataflow = block["properties"]["dataflow"]
        assert list(dataflow["properties"]) == list(contracts.TRILL_PROMPT_FIELDS["dataflowBase"])
        node = dataflow["properties"]["nodes"]["items"]
        edge = dataflow["properties"]["edges"]["items"]
        assert list(node["properties"]) == list(contracts.TRILL_PROMPT_FIELDS["node"])
        assert list(edge["properties"]) == list(contracts.TRILL_PROMPT_FIELDS["edge"])
        assert node["required"] == ["id", "type", "x", "y"]
        # A node's type is a template id, in the schema's own grammar.
        assert node["properties"]["type"]["pattern"] == _trill()["$defs"]["nodeTypeRef"]["pattern"]
        assert edge["properties"]["type"]["enum"] == ["Interaction"]

    def test_it_carries_no_field_the_format_does_not_have(self):
        text = contracts.render_trill_block(_trill())
        for phantom in ('"output"', '"annotations"', '"Data"', '"warnings"'):
            assert phantom not in text, phantom
        assert "description" not in text

    def test_the_preamble_carries_it(self):
        assert contracts.render_trill_block(_trill()) in contracts.render_default_preamble()

    def test_the_preambles_example_dataflow_is_valid_trill(self):
        # The example teaches the format, so it has to satisfy the block the
        # preamble shows just above it.
        import json

        from jsonschema import Draft202012Validator

        text = contracts.render_default_preamble()
        start = text.index("An example of a dataflow:\n\n") + len("An example of a dataflow:\n\n")
        example = json.loads(text[start:text.index("\nAttention:", start)])
        block = json.loads(contracts.render_trill_block(_trill()))
        assert [e.message for e in Draft202012Validator(block).iter_errors(example)] == []
        merge_edges = [e for e in example["dataflow"]["edges"] if e["target"] in ("node3", "node6")]
        assert merge_edges and all(e["targetHandle"].startswith("in_") for e in merge_edges)
