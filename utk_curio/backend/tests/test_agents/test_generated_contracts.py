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

from utk_curio.backend.app.agents.domain import contracts

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
        assert (REPO_ROOT / relative.replace(".md", ".template.md")).is_file()


def test_every_prompt_template_is_registered():
    # A template no entry renders is a prompt nobody regenerates.
    registered = {r for r in contracts.GENERATED_OUTPUTS if r.startswith(contracts.PROMPTS_DIR)}
    templates = sorted((REPO_ROOT / contracts.PROMPTS_DIR).glob("*.template.md"))
    assert len(templates) == len(contracts.PROMPT_TEMPLATES)
    for path in templates:
        output = f"{contracts.PROMPTS_DIR}/{path.name.replace('.template.md', '.md')}"
        assert output in registered, f"{path.name} has no entry in GENERATED_OUTPUTS"


class TestRenderPrompt:
    """A template's markers are filled from ``PROMPT_FIELDS`` alone, and no
    marker ever reaches the model."""

    def test_an_unknown_marker_raises(self):
        with pytest.raises(contracts.PromptTemplateError, match="no.such.field"):
            contracts.render_template("Before {{no.such.field}} after.")

    def test_a_marker_the_pattern_does_not_read_is_left_and_raises(self):
        with pytest.raises(contracts.PromptTemplateError, match="still holds"):
            contracts.render_template("Before {{ Agent Name }} after.")

    def test_a_value_that_leaves_a_marker_raises(self, monkeypatch):
        monkeypatch.setitem(
            contracts.PROMPT_FIELDS, "test.leftover", contracts.PromptField(lambda src: "{{x")
        )
        with pytest.raises(contracts.PromptTemplateError, match="still holds"):
            contracts.render_template("Before {{test.leftover}} after.")

    def test_an_argument_must_fit_its_field(self):
        with pytest.raises(contracts.PromptTemplateError, match="takes an argument"):
            contracts.render_template("{{agent.name}}")
        with pytest.raises(contracts.PromptTemplateError, match="takes no argument"):
            contracts.render_template("{{note.palette:yellow}}")

    def test_text_without_a_marker_is_unchanged(self):
        assert contracts.render_template('No field here: {"a": {"b": 1}}.') == 'No field here: {"a": {"b": 1}}.'

    def test_a_marker_ends_at_the_first_closing_pair(self):
        # In the backend contract, JSON closes right after a marker.
        from utk_curio.backend.app.packages.domain.backend_contract import TIMEOUT_CLASSES

        text = contracts.render_template('{"timeoutClass": {{backend.timeout_classes}}}]}')
        assert text == '{"timeoutClass": ' + "|".join(f'"{c}"' for c in TIMEOUT_CLASSES) + "}]}"

    def test_an_agent_name_follows_BUILTIN_AGENTS(self):
        from utk_curio.backend.app.agents.domain import builtin

        for spec in builtin.BUILTIN_AGENTS:
            assert contracts.render_template("{{agent.name:" + spec.agent_id + "}}") == spec.name

    def test_a_renamed_agent_is_renamed_in_every_prompt_that_names_it(self, monkeypatch):
        import dataclasses

        from utk_curio.backend.app.agents.domain import builtin

        renamed = tuple(
            dataclasses.replace(s, name="Flow Architect") if s.agent_id == "agent.dataflow-builder" else s
            for s in builtin.BUILTIN_AGENTS
        )
        monkeypatch.setattr(builtin, "BUILTIN_AGENTS", renamed)
        assert contracts.render_prompt("orchestration_instruction").startswith("You are the Flow Architect: ")
        chat = contracts.render_prompt("chat_prompt")
        assert "the Flow Architect plans and builds a whole dataflow" in chat
        assert "Dataflow Builder" not in chat

    def test_an_unknown_agent_raises(self):
        with pytest.raises(contracts.PromptTemplateError, match="agent.nobody"):
            contracts.render_template("{{agent.name:agent.nobody}}")

    def test_a_template_label_follows_the_manifest(self):
        manifest = _manifest()
        package = manifest["id"].split("@")[0]
        for template in manifest["templates"]:
            marker = "{{template.label:" + f"{package}/{template['id']}" + "}}"
            assert contracts.render_template(marker) == template["label"]
        with pytest.raises(contracts.PromptTemplateError, match="no-such-node"):
            contracts.render_template("{{template.label:curio.builtin/no-such-node}}")


class TestThePromptFacts:
    """Each fact a prompt states from code is read from that code."""

    def test_the_coherence_check_skips_every_template_not_controlled_through_python(self):
        control = contracts.builtin_lists(_manifest())["builtin.control"].splitlines()
        expected = [
            line.split(":", 1)[0] for line in control
            if not line.endswith(": controllable through python code.")
        ]
        text = contracts.render_prompt("evaluate_coherence_subtasks_prompt")
        head = "Do not generate warnings for nodes made from these templates:\n\n"
        assert text.split(head, 1)[1].split("\n\n", 1)[0].splitlines() == expected

    def test_the_merge_range_and_the_merge_slots_agree(self):
        slots = contracts.merge_slot_names()
        assert f'("{slots[0]}".."{slots[-1]}")' in contracts.render_prompt("orchestration_instruction")
        assert contracts.builtin_lists(_manifest())["builtin.merge_slots"].endswith(f'or "{slots[-1]}"')

    def test_the_note_palette_is_the_named_colors(self):
        from utk_curio.backend.app.packages.domain.node_appearance import NAMED_COLORS

        palette = ", ".join(NAMED_COLORS)
        for stem in ("package_build_instruction", "researcher_notes_instruction"):
            assert f"a palette name ({palette})" in contracts.render_prompt(stem), stem

    def test_the_web_call_budget_is_the_egress_policys(self):
        from utk_curio.backend.app.common.egress_policy import MAX_CALLS_PER_RUN

        for stem in ("research_instruction", "researcher_notes_instruction"):
            assert f"at most {MAX_CALLS_PER_RUN} web calls per run" in contracts.render_prompt(stem), stem

    def test_the_rows_per_lane_are_the_candidate_cards(self):
        from utk_curio.backend.app.agents.domain import content

        rows = content._CANDIDATES_MAX_ROWS_PER_LANE
        assert f"two lanes, at most {rows} rows each" in contracts.render_prompt("discovery_instruction")

    def test_the_node_context_fields_are_the_composers(self):
        from utk_curio.backend.app.agents.domain import input_contract, node_context
        from utk_curio.backend.app.agents.domain.document_validation import RUNTIME_FIELDS

        text = contracts.render_prompt("new_content_prompt")
        assert "{" + ", ".join(node_context.RUNTIME_BLOCK_KEYS) + "}" in text
        assert f'If its "kind" is "{input_contract.KIND_LIST}", ' in text
        assert f'If its "kind" is "{input_contract.KIND_SINGLE}", ' in text
        # A field Curio adds to every row is named here, so a new one fails
        # until the prompt says what it holds.
        for name in RUNTIME_FIELDS:
            assert f'"{name}"' in text, name
        with pytest.raises(contracts.PromptTemplateError, match="not_a_field"):
            contracts.render_template("{{vega.runtime_field:not_a_field}}")

    def test_the_package_contract_is_the_backend_contracts(self):
        from utk_curio.backend.app.packages.domain import backend_contract as bc

        fragment = contracts.render_prompt(contracts.PACKAGE_CONTRACT)
        assert f'"name": "<a name matching {bc.HANDLER_NAME_RE.pattern}>"' in fragment
        assert '"timeoutClass": ' + "|".join(f'"{c}"' for c in bc.TIMEOUT_CLASSES) + "}]}" in fragment
        assert f"the '{bc.PERMISSION_SERVER_CODE}' permission" in fragment
        assert f"(add '{bc.PERMISSION_SERVER_NETWORK}' if and only if" in fragment
        assert f"rides the {bc.DATA_DIR_ENV} env var" in fragment

    def test_the_package_builder_includes_the_contract_whole(self):
        fragment = contracts.render_prompt(contracts.PACKAGE_CONTRACT)
        assert fragment.endswith(".\n") and not fragment.endswith("\n\n")
        instruction = contracts.render_prompt("package_build_instruction")
        assert "\n\n" + fragment.rstrip("\n") + "\n\n" in instruction


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
        from utk_curio.backend.app.agents.domain import document_validation as dv

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
        from utk_curio.backend.app.packages.application.templates import input_capacity

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

        from utk_curio.backend.app.agents.domain import builtin

        for path in sorted(builtin.PROMPT_SOURCE_DIR.glob("*.md")):
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
