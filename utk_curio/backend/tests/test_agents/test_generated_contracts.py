"""Every fact the agents' text states from code is read from that code.

The pages and prompts in ``agents/`` and the skills in ``skills/`` state
facts the code owns through markers that ``contracts.PROMPT_FIELDS`` fills
when the backend renders them (``agent_text``). These tests read each one as
written and as an agent reads it (``prompt_text``). The tables the frontend
shares, which several markers read, are held to their files in
``test_shared_constants.py``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from utk_curio.backend.app.agents.domain import agent_text, contracts
from utk_curio.backend.tests._support.prompt_files import prompt_files, prompt_name, prompt_path, prompt_text

REPO_ROOT = Path(__file__).resolve().parents[4]


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

    def test_an_agent_name_follows_the_shipped_manifests(self):
        from utk_curio.backend.app.agents.domain import builtin

        manifests = builtin.list_builtin_manifests()
        assert len(manifests) == 7
        for m in manifests:
            assert contracts.render_template("{{agent.name:" + m.agent_id + "}}") == m.name

    def test_a_renamed_agent_is_renamed_in_every_prompt_that_names_it(self, monkeypatch):
        import dataclasses

        from utk_curio.backend.app.agents.domain import builtin

        renamed = [
            dataclasses.replace(m, name="Flow Architect") if m.agent_id == "agent.curio.dataflow-builder" else m
            for m in builtin.list_builtin_manifests()
        ]
        monkeypatch.setattr(builtin, "list_builtin_manifests", lambda: renamed)
        assert agent_text.render(prompt_path("orchestration_instruction.md")).startswith(
            "# Flow Architect\n\nYou are the Flow Architect: "
        )
        # Every other page or prompt that names it follows too, and none
        # keeps the old name.
        marker = "{{agent.name:agent.curio.dataflow-builder}}"
        naming = [path for path in prompt_files() if marker in path.read_text(encoding="utf-8")]
        assert len(naming) >= 2, naming
        rendered = {prompt_name(path): agent_text.render(path) for path in naming}
        for name, text in rendered.items():
            assert "Flow Architect" in text and "Dataflow Builder" not in text, name
        assert any(
            "the Flow Architect plans and builds a whole dataflow" in text for text in rendered.values()
        )

    def test_an_unknown_agent_raises(self):
        with pytest.raises(contracts.PromptTemplateError, match="agent.test.nobody"):
            contracts.render_template("{{agent.name:agent.test.nobody}}")

    def test_a_template_label_follows_the_manifest(self):
        manifest = _manifest()
        package = manifest["id"].split("@")[0]
        for template in manifest["templates"]:
            marker = "{{template.label:" + f"{package}/{template['id']}" + "}}"
            assert contracts.render_template(marker) == template["label"]
        with pytest.raises(contracts.PromptTemplateError, match="no-such-node"):
            contracts.render_template("{{template.label:curio.builtin/no-such-node}}")

    def test_a_shipped_packages_template_label_follows_its_manifest(self):
        """A prompt names a template of a package Curio ships as its manifest
        labels it, as it names a built-in one: Scout's nodes."""
        manifest = json.loads((REPO_ROOT / "packages" / "curio.scout@1" / "manifest.json").read_text(
            encoding="utf-8"))
        assert len(manifest["templates"]) == 17
        for template in manifest["templates"]:
            marker = "{{template.label:" + f"curio.scout/{template['id']}" + "}}"
            assert contracts.render_template(marker) == template["label"]
        with pytest.raises(contracts.PromptTemplateError, match="no-such-chart"):
            contracts.render_template("{{template.label:curio.scout/no-such-chart}}")
        with pytest.raises(contracts.PromptTemplateError, match="no.such.package"):
            contracts.render_template("{{template.label:no.such.package/chart}}")

    def test_the_scenarios_skill_compares_scenarios_with_curios_nodes_and_scouts_templates_say_how_they_do(self):
        """Its Scenarios section says how scenarios are compared with Curio's
        own nodes: a Vega-Lite spec reading every input stacked, as the dataset
        its chip names, ``[!! inputs !!]``, never by the bare name, and a
        Python node for two tables' or layers' difference. It names no
        package's template: Scout's fifteen charts, the package's templates
        that draw with Vega-Lite, each say in their own description that they
        take one input per scenario, and its Raster Calculator says in its own
        how it takes two rasters' difference, with absolute=True for its size.
        A run that writes one of them reads that description and its starter
        in the dataflow block (``test_dataflow_block.py``). Compare Scenarios
        is gone, and the section names it nowhere. The section is the
        scenarios skill, which the chats that build list and a run reading a
        dataflow with scenario boxes is handed (``test_skill_listing.py``),
        read here as written."""
        assert "scenarios" in json.loads(
            (REPO_ROOT / "agents" / "agent.curio.dataflow-builder@1" / "manifest.json").read_text(encoding="utf-8")
        )["skills"]
        template = prompt_path("scenarios/SKILL.md").read_text(encoding="utf-8")
        section = template.split("## Scenarios", 1)[1]
        manifest = json.loads((REPO_ROOT / "packages" / "curio.scout@1" / "manifest.json").read_text(
            encoding="utf-8"))
        assert "compare-scenarios" not in section and "Compare Scenarios" not in section
        for named in ("curio.builtin/vis-vega", "curio.builtin/computation-analysis"):
            assert "{{template.label:" + named + "}}" in section, named
        assert set(re.findall(r"\{\{template\.label:([^/{}]+)/", section)) == {"curio.builtin"}
        assert "curio.scout" not in section
        charts = [t for t in manifest["templates"] if t.get("grammarId") == "vega-lite"]
        assert [chart["id"] for chart in charts] == [
            "lines-with-band", "curves-by-group", "bars-with-error-bars", "ensemble-strips",
            "stacked-bars-with-totals", "donuts", "weighted-matrix", "dots-with-a-range",
            "bars", "grouped-bars", "lines", "points", "pie", "lollipops", "table",
        ]
        for chart in charts:
            assert chart["description"].startswith("One input per scenario"), chart["id"]
        calculator = next(t for t in manifest["templates"] if t["id"] == "raster-calculator")
        assert "subtract" in calculator["description"] and "absolute=True" in calculator["description"]
        starter = (REPO_ROOT / "packages" / "curio.scout@1" / calculator["source"]).read_text(encoding="utf-8")
        assert 'raster_calculate("subtract", [input_1, input_0], absolute=True' in starter
        assert "{{inputs.stacked}}" in section
        assert '"inputs"' not in section, "the section names the dataset bare"
        scenarios = prompt_text("scenarios/SKILL.md").split("## Scenarios", 1)[1]
        assert '"data": {"name": "[!! inputs !!]"}' in scenarios


class TestThePromptFacts:
    """Each fact a prompt states from code is read from that code."""

    def test_the_coherence_check_skips_every_template_not_controlled_through_code(self):
        control = contracts.builtin_lists(_manifest())["builtin.control"].splitlines()
        expected = [
            line.split(":", 1)[0] for line in control
            if not line.endswith((": controllable through python code.",
                                  ": controllable through JavaScript code."))
        ]
        text = prompt_text("evaluate_coherence_subtasks_prompt.md")
        head = "Do not generate warnings for nodes made from these templates:\n\n"
        skipped = text.split(head, 1)[1].split("\n\n", 1)[0].splitlines()
        assert skipped == expected
        # The three the hand-written list named that still ship stay, beside
        # the other templates with no code; a code node is never skipped, and
        # the Merge Flow left the manifest (#662).
        assert {"- Data Pool", "- Simple View", "- Vega-Lite", "- Autark"} <= set(skipped)
        assert "- JS Computation" not in skipped
        assert "- Merge Flow" not in skipped
        # A Data Export's code writes its file: it is checked as code.
        assert "- Data Export" not in skipped

    def test_the_input_handles_and_the_input_chips_come_from_the_runtime(self):
        """The circles an edge names and the chips code reads its inputs by
        are the runtime's own (``slot_handle_id``, ``reference_text``), and
        the prompts that state them say exactly that. Successor of the Merge
        Flow's slot names (#662)."""
        from utk_curio.backend.app.execution.code_references import (
            input_reference_inner,
            reference_text,
        )
        from utk_curio.backend.app.execution.workflow_spec import slot_handle_id

        handles = contracts.render_template("{{inputs.handles}}")
        assert handles == ", ".join(f'"{slot_handle_id(k)}"' for k in range(3)) + ", ..."
        assert handles == '"in", "in_1", "in_2", ...'
        chip0 = contracts.render_template("{{inputs.chip:0}}")
        assert chip0 == reference_text(input_reference_inner(0)) == "[!! input_0 !!]"
        assert contracts.render_template("{{inputs.chip:1}}") == "[!! input_1 !!]"
        column = contracts.render_template("{{inputs.chip:0.population}}")
        assert column == reference_text(input_reference_inner(0, "population"))
        assert column == "[!! input_0.population !!]"
        with pytest.raises(contracts.PromptTemplateError, match="circle number"):
            contracts.render_template("{{inputs.chip:population}}")
        preamble = prompt_text("default_preamble.md")
        assert f'"targetHandle": {handles}, circle 0 first.' in preamble
        assert f"`{chip0}` is the input on circle 0" in preamble
        assert f"`{column}`" in preamble
        orchestration = prompt_text("orchestration_instruction.md")
        assert f'"toHandle" ({handles})' in orchestration
        assert f"`{chip0}`, `[!! input_1 !!]`, ..." in orchestration
        lists = contracts.builtin_lists(_manifest())
        assert "builtin.merge_slots" not in lists

    def test_the_stacked_dataset_chip_comes_from_the_runtime(self):
        """The chip a Vega-Lite spec names its inputs stacked by is the
        runtime's own (``STACKED_DATASET``, ``reference_text``), and the
        scenarios skill says exactly that."""
        from utk_curio.backend.app.execution.code_references import STACKED_DATASET, reference_text

        chip = contracts.render_template("{{inputs.stacked}}")
        assert chip == reference_text(STACKED_DATASET) == "[!! inputs !!]"
        assert f'"data": {{"name": "{chip}"}}' in prompt_text("scenarios/SKILL.md")

    def test_the_orchestration_rule_links_two_views_directly_and_names_the_four_pool_cases(self):
        """An interaction edge carries selections, never data. Two views link
        directly, and a Data Pool goes between them only when a Simple View
        shows the selection, when selections are merged, when a Vega-Lite
        chart colors its own selection through ``interacted``, or when three
        or more views share one selection (owner, 10-21). The node names are
        the manifest's labels."""
        def label(template_id: str) -> str:
            return contracts.render_template("{{template.label:curio.builtin/" + template_id + "}}")

        rule = prompt_text("orchestration_instruction.md")
        assert "carries selections, never data" in rule
        assert "Link two views with one interaction edge between them" in rule
        assert f"Put a {label('data-pool')} between views only when" in rule
        for case in (
            f"a {label('vis-simple')} must show the selection",
            "selections are merged (AND or OR)",
            f"a {label('vis-vega')} chart colors its own selection",
            "three or more views share one selection",
        ):
            assert case in rule, case
        assert "never valid into a transformation or analysis node" in rule
        assert "ONE legitimate feedback link" not in rule
        assert "feed back into the pool" not in rule

    def test_the_widget_facts_come_from_the_runtime(self):
        """#662: the kinds a widget takes and the reference code places one by
        are the runtime's own (``WIDGET_KINDS``, ``reference_text``), and the
        prompts that teach widgets and scenarios to the node-writing agents say
        exactly that. A value several nodes read is a widget on one Python node
        that returns it, wired into each reader."""
        from utk_curio.backend.app.execution.code_references import (
            WIDGET_KINDS,
            reference_text,
        )

        kinds = contracts.render_template("{{widgets.kinds}}")
        assert kinds == ", ".join(WIDGET_KINDS[:-1]) + " or " + WIDGET_KINDS[-1]
        factor = contracts.render_template("{{widgets.reference:factor}}")
        assert factor == reference_text("factor") == "[!! factor !!]"
        with pytest.raises(contracts.PromptTemplateError, match="not a widget name"):
            contracts.render_template("{{widgets.reference:2x}}")
        python = contracts.render_template("{{template.label:curio.builtin/computation-analysis}}")
        widgets = prompt_text("widgets/SKILL.md")
        assert f'a "type" ({kinds})' in widgets
        assert "`[!! threshold !!]` for the widget named threshold" in widgets
        assert (
            f"A value several nodes read is a widget on one {python} node that returns it, wired into each reader."
            in widgets
        )
        scenarios = prompt_text("scenarios/SKILL.md")
        assert "## Scenarios" in scenarios and '"metadata"."copiedFrom"' in scenarios
        orchestration = prompt_text("orchestration_instruction.md")
        assert f"`{factor}` for the widget named factor" in orchestration
        assert "A value several nodes read is a widget on one Python node that returns it, wired into each reader." in (
            orchestration
        )
        assert '"duplicateOf"' in orchestration and '"copies"' in orchestration and '"values"' in orchestration
        content = prompt_text("new_content_prompt.md")
        assert f"`{factor}` for the widget named factor" in content
        assert "`[!! threshold !!]` for the widget named threshold" in prompt_text("node_build_instruction.md")
        # No page or prompt teaches the old marker form, or a shared tag, any more.
        for path in prompt_files():
            name = prompt_name(path)
            assert "$TYPE$" not in prompt_text(name), name
            assert "[!! @" not in prompt_text(name), name
            assert '"sharedTags"' not in prompt_text(name), name

    def test_no_marker_names_a_shared_tag(self):
        """A widget's value reaches another node by an edge, so no prompt field
        writes a shared tag's reference."""
        with pytest.raises(contracts.PromptTemplateError, match="which no prompt field defines"):
            contracts.render_template("{{widgets.shared:season}}")

    def test_no_page_names_the_parameter_template(self):
        """Builtin holds no Parameter template, so a page naming its label
        would stop the backend's start; every page renders without it."""
        with pytest.raises(contracts.PromptTemplateError, match="has no labelled template 'curio.builtin/parameter'"):
            contracts.render_template("{{template.label:curio.builtin/parameter}}")
        for path in prompt_files():
            assert "curio.builtin/parameter" not in path.read_text(encoding="utf-8"), prompt_name(path)

    def test_a_widget_name_that_ends_in_a_line_break_is_refused(self):
        """A marker's argument may hold a line break, and a widget name is read
        whole, as the Widgets tab reads it (``widgetChecks.cases.json``).
        Python's ``re.match`` lets a final line break through."""
        for marker in ("{{widgets.reference:factor\n}}", "{{selections.reference:picked\n}}"):
            with pytest.raises(contracts.PromptTemplateError, match="not a widget name"):
                contracts.render_template(marker)

    def test_the_note_palette_is_the_named_colors(self):
        from utk_curio.backend.app.packages.application.note_palette import NOTE_PALETTE

        palette = ", ".join(NOTE_PALETTE.colors)
        # The package-writing mode, and the post-it look the Researcher's chat
        # asks for when it has a notes package written.
        for name in ("package_build_instruction.md", "researcher_instruction.md"):
            assert f"a palette name ({palette})" in prompt_text(name), name

    def test_the_web_call_budget_is_the_egress_policys(self):
        from utk_curio.backend.app.common.egress_policy import MAX_CALLS_PER_RUN

        # The Researcher's chat, and the fact-checking skill its chat and its
        # checking mode are handed; the notes mode makes no web call of its own.
        for name in ("researcher_instruction.md", "fact-checking/SKILL.md"):
            assert f"at most {MAX_CALLS_PER_RUN} web calls per run" in prompt_text(name), name

    def test_the_rows_per_lane_are_the_candidate_cards(self):
        from utk_curio.backend.app.agents.domain import content

        rows = content._CANDIDATES_MAX_ROWS_PER_LANE
        assert f"two lanes, at most {rows} rows each" in prompt_text("discovery_instruction.md")

    def test_the_node_context_fields_are_the_composers(self):
        from utk_curio.backend.app.agents.domain import input_contract, node_context
        from utk_curio.backend.app.agents.domain.document_validation import RUNTIME_FIELDS

        text = prompt_text("new_content_prompt.md")
        assert "{" + ", ".join(node_context.RUNTIME_BLOCK_KEYS) + "}" in text
        assert f'If its "kind" is "{input_contract.KIND_SEVERAL}", ' in text
        assert f'If its "kind" is "{input_contract.KIND_GATHERED}", ' in text
        assert f'If its "kind" is "{input_contract.KIND_SINGLE}", ' in text
        # A field Curio adds to the rows is named here, so a new one fails
        # until the prompt says what it holds.
        for name in RUNTIME_FIELDS:
            assert f'"{name}"' in text, name
        with pytest.raises(contracts.PromptTemplateError, match="not_a_field"):
            contracts.render_template("{{vega.runtime_field:not_a_field}}")

    def test_the_input_kinds_and_names_are_the_runtimes(self):
        """A node reads circle k as ``input_k``: the prompt states the three
        input kinds, and no prompt teaches ``arg`` or the old chip spelling."""
        from utk_curio.backend.app.agents.domain import input_contract

        text = prompt_text("new_content_prompt.md")
        for kind in (input_contract.KIND_SINGLE, input_contract.KIND_SEVERAL, input_contract.KIND_GATHERED):
            assert f'If its "kind" is "{kind}", ' in text, kind
        assert 'If its "kind" is "list"' not in text
        # Every page and prompt, as written and as an agent reads it.
        files = prompt_files("*.md")
        texts = {}
        for path in files:
            texts[f"{prompt_name(path)}, as written"] = path.read_text(encoding="utf-8")
            texts[f"{prompt_name(path)}, as read"] = prompt_text(prompt_name(path))
        assert files and len(texts) == 2 * len(files)
        for name, rendered in texts.items():
            assert not re.search(r"(?<![\w.$])arg(?![\w$])", rendered), name
            assert not re.search(r"\[!!\s*input\s+[\d?]", rendered), name

    def test_the_package_contract_is_the_backend_contracts(self):
        from utk_curio.backend.app.packages.domain import backend_contract as bc

        fragment = prompt_text("package-contract/SKILL.md")
        assert f'"name": "<a name matching {bc.HANDLER_NAME_RE.pattern}>"' in fragment
        assert '"timeoutClass": ' + "|".join(f'"{c}"' for c in bc.TIMEOUT_CLASSES) + "}]}" in fragment
        assert f"the '{bc.PERMISSION_SERVER_CODE}' permission" in fragment
        assert f"(add '{bc.PERMISSION_SERVER_NETWORK}' if and only if" in fragment
        assert f"rides the {bc.DATA_DIR_ENV} env var" in fragment

    def test_every_package_writing_run_is_handed_the_contract_whole(self):
        """The contract is the skill ``package-contract``: each package-writing
        mode's run is handed it whole, wrapped as a skill, and its prompt no
        longer carries it."""
        from utk_curio.backend.app.agents.application import skill_runs
        from utk_curio.backend.app.agents.domain import builtin

        fragment = prompt_text("package-contract/SKILL.md")
        assert fragment.endswith(".\n") and not fragment.endswith("\n\n")
        assert fragment.startswith("## Backend contract\n\nServer-side compute follows ONE backend contract")
        coord = builtin.builtin_coord("agent.curio.node-builder")
        manifest = builtin.get_builtin_manifest(coord)
        preamble = builtin.read_prompt_text(coord, "system")
        for capability in ("package.build", "package.extend", "node.kind.author"):
            run = skill_runs.for_delegated("4242", "p", manifest, capability, {}, None, preamble)
            held = skill_runs.skills_text(run) or ""
            assert ('<skill_content name="package-contract">\n' + fragment.rstrip("\n") + "\n</skill_content>"
                    in held), capability
            assert fragment.rstrip("\n") not in builtin.read_prompt_text(coord, capability), capability
        assert "{{include:" not in prompt_path("package_build_instruction.md").read_text(encoding="utf-8")

    def test_every_vega_lite_schema_url_is_the_one_the_frontend_writes(self):
        import re

        assert contracts.render_template("{{vega.schema_url}}") == contracts.VEGA_SCHEMA_URL
        urls = re.findall(r"https://vega\.github\.io/schema/vega-lite/[^\"\\\s]+", prompt_text("default_preamble.md"))
        assert urls and set(urls) == {contracts.VEGA_SCHEMA_URL}
        # No page, prompt or skill writes the URL by hand, the skills the
        # preamble places among them: each names it by its marker.
        written = [prompt_name(path) for path in prompt_files("*.md")
                   if "vega.github.io/schema" in path.read_text(encoding="utf-8")]
        assert not written, written
        assert "{{vega.schema_url}}" in prompt_path("node-control/SKILL.md").read_text(encoding="utf-8")

    @pytest.mark.parametrize("field, ladder, skill", [
        ("vega.starter_ladder", "VEGA_STARTER_LADDER", "vega-lite-starter"),
        ("autk.starter_ladder", "AUTK_STARTER_LADDER", "autark-starter"),
    ])
    def test_a_starter_ladder_is_its_table_in_order(self, field, ladder, skill):
        rules = getattr(contracts, ladder)
        text = contracts.render_template("{{" + field + "}}")
        lines = text.splitlines()
        assert len(lines) == len(rules)
        for line, rule in zip(lines, rules):
            assert line.startswith("- ")
            condition, result = line[2:].split(" -> ", 1)
            assert result == f"{rule.produces}: {rule.description}"
            terms = condition.split(" + ")
            if rule.layers:
                layers = terms.pop(0)
                assert layers.endswith(" layer" if rule.layers.most == 1 else " layers")
                assert ("or more" in layers) == (rule.layers.most is None)
            assert [term.split()[-1] for term in terms] == [role for role, _ in rule.columns]
            for term, (role, count) in zip(terms, rule.columns):
                # A bare role is at least one column; anything else is spelt out.
                assert (term == role) == (count.least == 1 and count.most is None)
                assert term.startswith("exactly ") == (count.most == count.least)
        assert text in prompt_text(f"{skill}/SKILL.md")

    def test_the_dtype_roles_are_the_table_in_order(self):
        import re

        text = contracts.render_template("{{starter.dtype_roles}}")
        parts = text.split("; ")
        assert len(parts) == len(contracts.DTYPE_ROLES)
        for part, entry in zip(parts, contracts.DTYPE_ROLES):
            assert part.endswith(f" {entry.role}")
            assert re.findall(r"`([^`]+)`", part) == [*entry.names, *entry.prefixes]
            assert ("starts with" in part) == bool(entry.prefixes)
        assert text in prompt_text("vega-lite-starter/SKILL.md")

    def test_the_image_facts_are_the_tables(self):
        import re

        columns = contracts.render_template("{{image.columns}}")
        assert re.findall(r'"([^"]+)"', columns) == list(contracts.IMAGE_COLUMNS)
        assert columns.endswith(f' or "{contracts.IMAGE_COLUMNS[-1]}"')
        extensions = contracts.render_template("{{image.extensions}}")
        assert re.findall(r"\.([a-z0-9]+)", extensions) == list(contracts.IMAGE_EXTENSIONS)
        threshold = contracts.render_template("{{image.threshold}}")
        assert threshold == f"{round(contracts.IMAGE_MATCH_THRESHOLD * 100)}%"
        for name in contracts.IMAGE_COLUMNS:
            assert contracts.render_template("{{image.column:" + name + "}}") == f'"{name}"'
        with pytest.raises(contracts.PromptTemplateError, match="not_a_column"):
            contracts.render_template("{{image.column:not_a_column}}")

    def test_the_simple_view_paragraph_states_the_image_rule_the_frontend_applies(self):
        text = prompt_text("default_preamble.md")
        columns = contracts.render_template("{{image.columns}}")
        threshold = contracts.render_template("{{image.threshold}}")
        extensions = contracts.render_template("{{image.extensions}}")
        thumbnail = contracts.render_template("{{image.column:thumbnail}}")
        image_url = contracts.render_template("{{image.column:image_url}}")
        paragraphs = [p for p in text.split("\n\n") if columns in p]
        assert len(paragraphs) == 1
        paragraph = paragraphs[0]
        assert f"at least {threshold} of its non-empty values are images" in paragraph
        assert f"({extensions})" in paragraph
        assert f"{image_url} is left out when {thumbnail} holds images" in paragraph
        # Every named column takes the same values: Base64 is not one column's.
        assert "or bare Base64 image bytes" in paragraph
        assert '"image_content" is raw Base64' not in text


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
        assert f'"dataRef": "{contracts.input_table_name(0)}"' in shape
        # The whole shape survives the refusal's 600-character cut.
        assert shape in dv.validate(contracts.AUTK_TEMPLATE, "not controllable")["detail"]

    def test_the_region_names_what_the_schema_requires(self):
        schema = contracts.load_autk_schema()
        region = contracts.render_autk_region(schema, "Autark")
        assert schema["$id"] in region
        assert contracts.AUTK_TEMPLATE in region
        assert f'"{contracts.input_table_name(0)}"' in region
        for union, key in (("DataSourceSpec", "type"), ("PlotSpec", "mark")):
            for values, _ in contracts._variants(schema, union, key):
                for value in values:
                    assert f'"{value}"' in region, (union, value)

    def test_the_region_says_a_node_draws_one_view(self):
        schema = contracts.load_autk_schema()
        region = contracts.render_autk_region(schema, "Autark")
        one_view = ("An Autark node draws one view: one map or one plot. Put each in its own "
                    "Autark node, and link them with interaction edges.")
        [map_line] = [row for row in region.splitlines() if row.startswith('- "map":')]
        [plot_line] = [row for row in region.splitlines() if row.startswith('- "plot":')]
        assert map_line.startswith(f'- "map": {one_view} Requires "layerRefs"')
        assert plot_line.startswith(f'- "plot": {one_view} Every plot requires')
        autark = prompt_text("autark/SKILL.md")
        for line in (map_line, plot_line):
            assert "several" not in line
            assert line in autark

    def test_the_preamble_fills_every_field_and_names_no_retired_node(self):
        text = prompt_text("default_preamble.md")
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
        assert "- Data Export: controllable through python code." in lists["builtin.control"]
        # A loader can read values from the nodes wired into it, so it takes
        # every kind; a Note takes none.
        assert "- Data Loading: DATAFRAME, GEODATAFRAME, VALUE, LIST, JSON, RASTER" in lists["builtin.inputs"]
        assert "- Note: no input supported" in lists["builtin.inputs"]
        # Vega-Lite takes a GeoDataFrame, which the hand-kept list said it did not.
        assert "- Vega-Lite: DATAFRAME, GEODATAFRAME" in lists["builtin.inputs"]
        assert "- Data Loading: any number" in lists["builtin.input_count"].splitlines()
        assert not any(line.startswith("- Note:") for line in lists["builtin.input_count"].splitlines())
        assert lists["builtin.interaction"].splitlines() == [
            f"- {t['label']}" for t in manifest["templates"] if t.get("bidirectional")
        ]
        assert loading["outputPorts"][0]["cardinality"] in lists["builtin.output_count"]

    def test_an_input_count_is_the_connections_a_node_accepts(self):
        # One input port takes its declared maximum: a "[1,n]" port grows a
        # circle per edge on the canvas, up to a bounded "[1,k]" port's k.
        # Named ports take one edge each. No template is special-cased by id
        # any more: the Merge Flow and its slots left with #662.
        from utk_curio.backend.app.packages.application.templates import input_capacity

        lists = contracts.builtin_lists(_manifest())
        counts = dict(line[2:].split(": ", 1) for line in lists["builtin.input_count"].splitlines())
        assert counts["Python Computation"] == "any number"
        assert counts["JS Computation"] == "any number"
        assert counts["Vega-Lite"] == "any number"
        assert counts["Autark"] == "any number"
        assert counts["Data Summary"] == "1"
        assert counts["Spatial Join"] == "2"
        assert "Merge Flow" not in counts
        assert input_capacity(1, "[1,n]") is None
        assert input_capacity(1, "[1,2]") == 2
        assert input_capacity(1, "1") == 1
        assert input_capacity(2) == 2
        assert input_capacity(2, None) == 2

    def test_the_lists_name_no_template_id(self):
        # The run's roster is the authority on ids; a list to copy them from
        # is how a Dataflow Builder once looped on a refused id.
        for text in contracts.builtin_lists(_manifest()).values():
            assert "curio.builtin/" not in text

    def test_no_prompt_names_a_node_by_its_legacy_name(self):
        import re

        # Every page and prompt, as written and as an agent reads it.
        files = prompt_files("*.md")
        assert files
        for path in files:
            name = prompt_name(path)
            for how, text in (("as written", path.read_text(encoding="utf-8")), ("as read", prompt_text(name))):
                found = re.findall(r"\b(" + "|".join(_LEGACY_NAMES) + r")\b", text)
                assert not found, f"{name}, {how}, names {sorted(set(found))}"


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

    def test_a_scenario_shows_what_an_agent_reads_and_writes(self):
        # #662: not where its box sits on the canvas or where it came from.
        import json

        block = json.loads(contracts.render_trill_block(_trill()))
        scenario = block["properties"]["dataflow"]["properties"]["scenarios"]["items"]
        assert list(scenario["properties"]) == list(contracts.TRILL_PROMPT_FIELDS["scenario"])
        assert scenario["required"] == ["id", "name", "color", "nodes"]

    def test_a_nodes_widgets_and_lineage_show_what_an_agent_writes(self):
        # #662: the widgets a node declares, in the schema's own shape, and the
        # lineage a copy carries.
        import json

        from utk_curio.backend.app.execution.code_references import WIDGET_KINDS

        block = json.loads(contracts.render_trill_block(_trill()))
        node = block["properties"]["dataflow"]["properties"]["nodes"]["items"]
        metadata = node["properties"]["metadata"]
        assert list(metadata["properties"]) == list(contracts.TRILL_PROMPT_FIELDS["nodeMetadata"])
        widget = metadata["properties"]["widgets"]["items"]
        assert list(widget["properties"]) == list(_trill()["$defs"]["widget"]["properties"])
        assert widget["properties"]["type"]["enum"] == list(WIDGET_KINDS)
        assert widget["required"] == ["name", "type"]
        assert metadata["properties"]["copiedFrom"] == {"type": "array", "items": {"type": "string"}}

    def test_it_carries_no_field_the_format_does_not_have(self):
        import json

        text = contracts.render_trill_block(_trill())
        for phantom in ('"annotations"', '"Data"', '"warnings"'):
            assert phantom not in text, phantom
        # "output" is a field of a Spatial Join's setting, and of nothing else.
        block = json.loads(text)
        metadata = block["properties"]["dataflow"]["properties"]["nodes"]["items"]["properties"]["metadata"]
        spatial_join = metadata["properties"].pop("spatialJoin")
        assert list(spatial_join["properties"]) == ["predicate", "output"]
        assert '"output"' not in json.dumps(block)
        assert "description" not in text

    def test_the_preamble_carries_it(self):
        assert contracts.render_trill_block(_trill()) in prompt_text("default_preamble.md")

    def test_the_worked_examples_are_valid_trill(self):
        # The worked examples teach the format, so each has to satisfy the
        # block the preamble shows, and wire several inputs into one node the
        # way the preamble says to: each edge on its own input circle, "in",
        # "in_1", ... in connection order, with no Merge Flow between (#662).
        import json
        import re

        from jsonschema import Draft202012Validator

        from utk_curio.backend.app.agents.application.turns import examples
        from utk_curio.backend.app.execution.workflow_spec import slot_handle_id

        package = _manifest()["id"].split("@")[0]
        one_port = {
            f"{package}/{t['id']}" for t in _manifest()["templates"]
            if len(t.get("inputPorts") or []) == 1
        }
        block = json.loads(contracts.render_trill_block(_trill()))
        used = [entry for entry in examples.read_index() if entry.section == examples.USED]
        assert used, "the index lists no Used dataflow; this test would be vacuous"
        fan_in_edges = []
        for entry in used:
            example = json.loads(entry.path.read_text(encoding="utf-8"))
            assert [e.message for e in Draft202012Validator(block).iter_errors(example)] == [], entry.target
            types = {n["id"]: re.sub(r"@\d+$", "", n["type"]) for n in example["dataflow"]["nodes"]}
            assert "curio.builtin/merge-flow" not in types.values(), entry.target
            into: dict[str, list[dict]] = {}
            for e in example["dataflow"]["edges"]:
                if e.get("type") != "Interaction":
                    into.setdefault(e["target"], []).append(e)
            for target, edges in into.items():
                if len(edges) < 2 or types.get(target) not in one_port:
                    continue
                handles = sorted(str(e.get("targetHandle")) for e in edges)
                assert handles == sorted(slot_handle_id(k) for k in range(len(edges))), (entry.target, target, handles)
                fan_in_edges += edges
        assert fan_in_edges, "no Used example wires several inputs into one node"
