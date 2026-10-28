"""What an agent is told it may do, the code that handles it does.

Each prompt is read as a run reads it (``builtin.read_prompt_text``), and each
case names the code that refuses what the deleted text promised, or does not
do it.
"""
from __future__ import annotations

import re

DATAFLOW_BUILDER = "agent.curio.dataflow-builder@1"
NODE_BUILDER = "agent.curio.node-builder@1"
DATASET_FINDER = "agent.curio.dataset-finder@1"
RESEARCHER = "agent.curio.researcher@1"


def _prompt(coord: str, key: str = "instruction") -> str:
    from utk_curio.backend.app.agents.domain import builtin

    text = builtin.read_prompt_text(coord, key)
    assert text, f"{coord} has no {key} prompt"
    return text


def _held(coord: str) -> str:
    """What *coord*'s chat holds of its agent text beyond the preamble, on the
    canvas: the skills it is handed, among them the procedures its
    instruction names, then its instruction."""
    from utk_curio.backend.app.agents.application import skill_runs
    from utk_curio.backend.app.agents.domain import builtin

    m = builtin.get_builtin_manifest(coord)
    run = skill_runs.for_chat("4242", "p", m, None, {"kind": "canvas"}, builtin.read_prompt_text(coord, "system"), [])
    return f"{skill_runs.skills_text(run) or ''}\n\n{_prompt(coord)}"


def _sentence(text: str, words: str) -> str:
    """The sentence of *text* that holds *words*."""
    found = [s for s in re.split(r"(?<=[.!?])\s+", text) if words in s]
    assert found, f"no sentence holds {words!r}"
    return found[0]


def test_the_dataflow_builder_is_never_told_a_plan_may_carry_code():
    """``_mint_dataflow_plan`` (``proposals/plans.py``) refuses every plan node
    that carries content: plans describe intent, and Solve writes each node's
    content after the plan is applied. So no case lets the plan carry it."""
    instruction = _prompt(DATAFLOW_BUILDER)
    assert "unless a node's code is trivial" not in instruction
    assert "unless asked" not in instruction


def test_the_dataflow_builder_is_not_offered_a_decomposition_that_only_rewords_goals():
    """``workflow.plan.create`` runs the Dataflow Planner's
    ``new_subtasks_prompt.md``, which rewrites the goals of the nodes a
    dataflow already has and adds none."""
    assert '"workflow.plan.create"' not in _prompt(DATAFLOW_BUILDER)


def test_the_dataflow_builder_is_told_every_applied_plan_ends_with_a_topology_verdict():
    """Every way a plan is applied ends its result with the verdict: Apply plan
    (``plans._log_plan_applied``), and the row or Connect all that completes a
    plan applied a part at a time, which writes it through the same function.
    ``test_routes_proposals.py::TestPlansAppliedRowByRow`` checks the last
    row's result and Connect all's, word for word as Apply plan's, and
    ``test_routes_solve.py::TestSimulationDriver::test_auto_removes_what_the_plan_removes_and_the_stream_carries_it``
    Simulation Mode's."""
    assert (
        "After the user applies a plan, the applied result names what changed and ends with a Topology verdict"
        in _prompt(DATAFLOW_BUILDER)
    )


def test_the_node_builder_names_the_new_nodes_type_when_it_delegates_its_content():
    """A ``node.content.generate`` delegation that names a ``nodeType`` and no
    ``nodeId`` writes a new node of that template, wherever the agent is
    attached (``delegates._delegate_target_node_id``): its content returns to
    the run for its ``node.create``, and the node the agent is attached to is
    offered no change. ``test_delegation.py::TestChatContentReviewMint::test_content_for_a_new_node_returns_to_the_run_for_its_node_create``
    checks it from a node's Node Builder, and
    ``test_source_grounding_routes.py::TestContentForANewNode`` that the content
    is grounded as that template's."""
    step = _sentence(_prompt(NODE_BUILDER), "put the returned content in the node.create request's params.content")
    assert "attached to the canvas" not in step
    assert '"nodeType"' in step


def test_the_node_builder_is_not_told_its_chat_starts_discovery():
    """Only Solve asks the Dataset Finder for a node's candidates
    (``grounding._source_resolver``, which calls ``dataset_resolution.initiate``,
    from ``solve/batch.py``, ``node_solve.py`` and ``validate.py``); a chat run
    that cannot ground a source starts none. The chat reads it from its
    instruction and the data-sources skill it is handed."""
    held = _held(NODE_BUILDER)
    assert '"dataset.discover"' in held, "the chat is no longer told how it asks for candidates"
    assert "the runtime initiates that discovery itself" not in held


def test_no_agent_is_told_to_declare_a_synthetic_flag_the_gate_ignores():
    """``source_grounding.synthetic_requested`` reads only the user's own words;
    a ``"synthetic": true`` param changes nothing. Neither the Node Builder nor a
    source refusal's list of allowed sources asks for one."""
    from utk_curio.backend.app.agents.application.turns import grounding

    held = _held(NODE_BUILDER)
    assert "synthetic data ONLY when the user explicitly asked for made-up data in their own words" in held
    assert '"synthetic": true' not in held
    base = {"catalog_paths": {}, "catalog_ids": {}, "verified": {}, "secrets": {}, "texts": []}
    ctx = grounding._grounding_context("4242", "p-1", {}, node_type="curio.builtin/data-loading", base=base)
    assert not any('"synthetic"' in hint for hint in ctx.hints), ctx.hints
    assert any("in their own words" in hint for hint in ctx.hints), ctx.hints


def test_the_content_mode_is_not_offered_a_model_search_it_cannot_run():
    """The Node Builder's content mode runs as a delegate with no tools
    (``delegation`` pins ``"tools": []``), so it never calls models.search."""
    assert "models.search" not in _prompt(NODE_BUILDER, "node.content.generate")


def test_the_content_mode_promises_a_one_line_conclusion_on_every_node():
    """Solve takes a one-line conclusion in place of code on every node whose
    content is code: the loop reads it before any gate or the sandbox
    (``verified_loop._one_line_answer``), which
    ``test_verified_rounds.TestOneLineAnswers`` proves on a join that loads no
    data. So the content mode offers it to every node, not only to one that
    loads data."""
    sentence = _sentence(_prompt(NODE_BUILDER, "node.content.generate"), "state that conclusion as your WHOLE reply")
    assert "in one line, with no code at all" in sentence
    assert "loads data" not in sentence


def _absent_output_a_consumer_refuses() -> str:
    """The refusal a validation round sends for code that returns nothing to a
    node that declares what it takes (``validation._consumer_type_mismatch``)."""
    from utk_curio.backend.app.agents.domain import validation

    spec = {"dataflow": {
        "nodes": [{"id": "n1", "type": "curio.builtin/computation-analysis"},
                  {"id": "n2", "type": "curio.builtin/vis-vega", "goal": "Trips chart"}],
        "edges": [{"id": "e1", "source": "n1", "target": "n2"}],
    }}
    available = {"curio.builtin/vis-vega": {"inputs": [{"types": ["DATAFRAME"]}]}}
    text = validation._consumer_type_mismatch(spec, "n1", "null", available)
    assert text, "no refusal for an absent output"
    return text


def test_solves_refusals_offer_a_one_line_answer_on_every_node():
    """Each refusal a Solve round sends back offers the one-line answer
    without narrowing it to a node that loads data. Only the verified loop
    sends them (``result_shape``'s from its stages, ``validation``'s from
    ``validate_candidate``), and the loop reads the answer on every node whose
    content is code (``verified_loop._one_line_answer``;
    ``test_verified_rounds.TestOneLineAnswers``)."""
    from utk_curio.backend.app.agents.domain import result_shape as rs

    nulls = {"kind": "geotable", "rowCount": 2, "columns": [{"name": "population", "dtype": "unknown"}],
             "sampleRows": [{"population": None}, {"population": None}]}
    conclusion = "# A join is not possible with the provided columns.\nreturn None"
    offers = {
        "no output": (rs.absent_output_refusal(code="return None"), "say so in one line with no code"),
        "no output, its own conclusion": (rs.absent_output_refusal(code=conclusion), "with no code at all"),
        "rows that hold nothing": (rs.null_refusal_text(columns=["population"], summary=nulls),
                                   "say so in one line and return no code"),
        "no rows": (rs.refusal_text(summary={"kind": "table", "rowCount": 0}, upstream_outputs=None),
                    "Either join on columns whose values are the same kind of thing"),
        "no output a consumer takes": (_absent_output_a_consumer_refuses(),
                                       "say so in one line instead of returning code"),
    }
    for name, (text, words) in offers.items():
        assert "loads data" not in _sentence(text, words), name


#: Words that tell a model to load a skill: the tool, by its id or its native
#: name, or a verb of loading and a skill in one sentence.
_LOADS_A_SKILL = re.compile(r"skill\.read|skill__read|\bload(?:s|ed|ing)?\b[^.;\n]*\bskills?\b", re.IGNORECASE)


def _loads(text: str) -> list[str]:
    """The sentences of *text* that tell a model to load a skill."""
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n", text or "") if _LOADS_A_SKILL.search(s)]


def test_a_run_with_no_tools_is_never_told_to_load_a_skill(tmp_curio):
    """A mode runs as a delegated call with no tools (``delegation`` pins
    ``"tools": []``), and so does every Solve round: neither can call
    skill.read, so each is handed the skills it needs
    (``skill_runs.for_delegated``). So no mode's prompt, no message a check
    sends back, and no skill a tool-less run is handed tells a model to load
    a skill. Only skill.read's own answers, which a chat that holds the tool
    reads, and the catalog's instruction, which only such a chat is given,
    name it."""
    from utk_curio.backend.app.agents.application import skill_runs
    from utk_curio.backend.app.agents.domain import agent_text, builtin

    assert _loads("When a task matches, call the skill.read tool.") and _loads("Load the widgets skill first.")
    assert not _loads("A widget is a value the node's code reads. Load the dataset by its id.")
    told = []
    for m in builtin.list_builtin_manifests():
        for capability in m.capabilities:
            if capability.instruction:
                told += [(m.dir_name, capability.id, said)
                         for said in _loads(builtin.read_prompt_text(m.dir_name, capability.instruction))]
    page = agent_text.MESSAGES_PAGE
    for name, text in agent_text.split_sections(agent_text.page_text(page), page).items():
        if not name.startswith("skills."):
            told += [(page, name, said) for said in _loads(text)]
    preamble = builtin.read_page("default_preamble.md", wanted_by="the test")
    told += [("default_preamble.md", "", said) for said in _loads(preamble)]
    for node_type in ("curio.builtin/computation-analysis", "curio.builtin/vis-vega", "curio.builtin/autk-grammar"):
        run = skill_runs.for_delegated("4242", "p", builtin.get_builtin_manifest(NODE_BUILDER), "node.content.generate",
                                       {"nodeType": node_type}, None, preamble, refused="document-invalid")
        assert run.handed, node_type
        told += [(node_type, "handed", said) for said in _loads(skill_runs.skills_text(run))]
    assert not told, f"these tell a run with no tools to load a skill: {told}"
    assert _loads(agent_text.section(builtin.FRAMES_FILE, skill_runs.CATALOG_SECTION))


def test_a_research_check_is_told_which_inputs_the_runtime_probes():
    """``delegates._enriched_delegate_inputs`` probes the delegation's ``url``
    or ``endpoint`` input; a URL anywhere else in its inputs is not probed."""
    text = _prompt(RESEARCHER, "research.verify")
    assert "When you were given a URL or an endpoint" not in text
    assert 'When your inputs carry a "url" or an "endpoint"' in text


def test_the_dataset_finder_is_not_told_a_confirmed_fetchable_row_is_being_built():
    """A confirmed row Curio downloads is downloaded first, and its builder
    starts only when it lands within the confirmation's wait
    (``acquire._DISCOVERY_APPLY_WAIT_S``); a node with no builder, or a Solve
    already running, starts none (``dataset_selection._delegate_confirmed_fetch``)."""
    text = _prompt(DATASET_FINDER)
    for promise in ("DELEGATES automatically", "the delegation has already started", "writing the loader now"):
        assert promise not in text, promise


def test_the_dataset_finder_is_not_told_its_rows_come_in_two_kinds():
    """A row's access verdict is fetchable, manual-download or unknown
    (``verify.ACCESS_UNKNOWN`` among them)."""
    assert "TWO kinds" not in _prompt(DATASET_FINDER)


def test_the_dataset_finder_is_not_told_a_fetch_author_delegation_proposes_an_install():
    """An install proposal is minted only when the project lacks the agent that
    declares the capability (``delegates``, a ``not-installed`` resolution); an
    installed Node Builder runs the request, and nothing reaches the user to
    apply."""
    assert "so an install proposal reaches the user" not in _prompt(DATASET_FINDER)


#: A sentence that tells an agent to keep a spec as it is.
_KEEPS_A_SPEC = re.compile(r"\bspecs?\b[^.;]*\bas it is\b", re.IGNORECASE)
#: A sentence that tells an agent to set widgets: ``set``, then a widget in
#: the same clause. A user who "sets" a value, and a widget that "is set",
#: name no step of the agent's.
_SETS_WIDGETS = re.compile(r"\bset\b[^.;]*\bwidgets?\b", re.IGNORECASE)
#: The sentence #1070 narrowed, as the preamble said it of Scout's charts.
_NARROWED = (
    "Each is a Vega-Lite node whose spec is its template's: in a plan, set the columns it plots in its "
    "widgets, and its Combine widget, where it has one, to the Vega-Lite aggregate it combines a "
    "scenario's rows with (mean, sum, median, min, max or count), and leave its spec as it is."
)


def _claims(text: str) -> list[str]:
    """The sentences of *text* that tell an agent to keep a spec as it is or
    to set widgets, each sentence and each line on its own."""
    return [
        sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+|\n", text)
        if _KEEPS_A_SPEC.search(sentence) or _SETS_WIDGETS.search(sentence)
    ]


def _what_agents_read() -> list[tuple[str, str]]:
    """Every text an agent can read, with where it is: each page of the base
    entry and each prompt of each agent Curio ships, rendered as a run reads
    them, and the description and the starter of each template of each
    package Curio ships, which a run's dataflow block shows (a model
    package's template without a source starts with its model's cell)."""
    from pathlib import Path

    from utk_curio.backend.app.agents.domain import agent_text
    from utk_curio.backend.app.packages.application.model_packages import model_default_cell
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest

    repo = Path(__file__).resolve().parents[4]
    texts = [(file.relative_to(repo).as_posix(), agent_text.render(file)) for file in agent_text.shipped_files()]
    for folder in sorted(path.parent for path in (repo / "packages").glob("*/manifest.json")):
        manifest = load_package_manifest(folder)
        for template in manifest.templates:
            where = f"{manifest.package_id}/{template.template_id}"
            texts.append((f"{where}, its description", template.description or ""))
            if template.source:
                texts.append((f"{where}, its starter", (folder / template.source).read_text(encoding="utf-8")))
            elif manifest.kind == "model" and manifest.model is not None:
                texts.append((f"{where}, its starter", model_default_cell(manifest, folder)))
    return texts


#: Where a template's starter and widgets are set: the words each claim says it in.
_IN_BOTH = "in a plan or a node.create"
#: The sentence #1070 narrowed, as it reads once it holds in both.
_WIDENED = _NARROWED.replace("in a plan, set", f"{_IN_BOTH}, set")


def _tool_section(text: str, tool: str) -> str:
    """The ``## <tool>`` section of the rendered ``tools.md``."""
    sections = re.split(r"^## ", text, flags=re.MULTILINE)
    found = [s for s in sections if s.split("\n", 1)[0].strip() == tool]
    assert found, f"tools.md has no section {tool}"
    return found[0]


def test_a_spec_is_kept_as_it_is_and_a_templates_widgets_set_in_a_plan_or_a_node_create():
    """A plan and a ``node.create`` both start a node of a template whose
    starter is its whole content from that starter, and set the template's
    widgets by name (``plans._content_starters`` and the node.create mint,
    both through ``plan_scenarios._set_over``); ``node.content.write`` carries
    no widgets. ``test_routes_starter_templates.py::TestACreatedTemplateStartsFromItsStarter``
    checks the node.create half, and ``TestAPlannedTemplateKeepsItsStarter``
    the plan's. So a sentence that tells an agent to keep a spec as it is, or
    to set a template's widgets, says it holds in a plan or a node.create,
    wherever an agent reads it: every page and prompt, and every template's
    description and starter. The two tools that place a node say it, where a
    run reads each of them."""
    # The check finds the widened sentence, and holds a sentence to both: one
    # that names only the plan, as #1070 left it, no longer passes.
    assert _claims(_WIDENED) == [_WIDENED]
    assert _claims(_NARROWED) == [_NARROWED] and _IN_BOTH not in _NARROWED
    for innocent in ("A widget is a value a node's code reads that the user sets in the node's Widgets tab.",
                     "A copy whose height factor widget is set to 2.", "Keep your answers specific."):
        assert _claims(innocent) == [], innocent

    texts = _what_agents_read()
    places = [where for where, _text in texts]
    assert any(place.endswith("default_preamble.md") for place in places), places
    assert any(place.endswith("orchestration_instruction.md") for place in places), places
    charts = [(where, text) for where, text in texts
              if where.startswith("curio.scout/") and where.endswith(", its description")]
    assert len(charts) >= 15, charts
    unsaid = [(where, claim) for where, text in texts for claim in _claims(text) if _IN_BOTH not in claim]
    assert not unsaid, (
        "these tell an agent to keep a spec as it is or to set a template's widgets, which a plan and a "
        f"node.create do, and do not say where: {unsaid}"
    )
    assert not [(where, claim) for where, text in charts for claim in _claims(text) if _IN_BOTH not in claim]
    (tools_page,) = [text for where, text in texts if where.endswith("agent.curio.builtin@1/tools.md")]
    for tool in ("dataflow.plan.write", "node.create"):
        said = _claims(_tool_section(tools_page, tool))
        assert said and all(_IN_BOTH in claim for claim in said), (tool, said)
