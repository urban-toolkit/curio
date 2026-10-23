"""Tests for the built-in agent roster: two internal agents made of modes, the
P5 composites (memo dev/48), the authored evaluator, and the two cards that
took other agents over and run their prompts as modes."""

from __future__ import annotations

from utk_curio.backend.app.agents.domain import agent_text, builtin
from utk_curio.backend.app.agents.domain.manifest import AgentManifest
from utk_curio.backend.tests._support.prompt_files import prompt_folders, prompt_path


def _file(asset) -> str:
    """The file name of a prompt asset, as the agent's bundle holds it."""
    return asset.file.rsplit("/", 1)[-1]


def _by_id() -> dict[str, AgentManifest]:
    return {m.agent_id: m for m in builtin.list_builtin_manifests()}


def _modes(m: AgentManifest) -> list:
    """The capabilities of *m* that are modes: each with an instruction of its own."""
    return [c for c in m.capabilities if c.instruction]


#: Every built-in, in roster order (the catalog lists the cards in this
#: order): the instruction its chat runs, which for an internal agent is its
#: first mode's, and its capabilities in order.
_ROSTER = {
    "agent.curio.researcher": ("researcher_instruction.md", ["research.notes.compose", "research.verify"]),
    "agent.curio.dataflow-planner": ("new_subtasks_prompt.md", [
        "workflow.plan.create", "execution.followup.plan", "workflow.plan.refresh",
        "workflow.coherence.validate", "workflow.keyword.bind", "workflow.keywords.extract",
    ]),
    "agent.curio.dataflow-reader": ("explanation_prompt.md", ["dataflow.explain", "workflow.suggest"]),
    "agent.curio.node-builder": ("node_build_instruction.md", [
        "node.build", "dataset.fetch.author", "node.content.generate",
        "package.recommend", "package.build", "package.extend", "node.kind.author",
    ]),
    "agent.curio.dataset-finder": ("discovery_instruction.md", ["dataset.discover", "dataset.select"]),
    "agent.curio.dataflow-builder": ("orchestration_instruction.md", ["dataflow.orchestrate"]),
    "agent.curio.generated-content-evaluator": (
        "evaluate_generated_content_prompt.md", ["content.quality.evaluate"],
    ),
}

#: The merged agents: each capability is a mode that runs its own instruction.
#: The planning and keyword agents became the Dataflow Planner, and the two
#: dataflow readers the Dataflow Reader.
_MODES = {
    "agent.curio.dataflow-planner": {
        "workflow.plan.create": "new_subtasks_prompt.md",
        "execution.followup.plan": "new_subtask_from_exec_prompt.md",
        "workflow.plan.refresh": "task_refresh_prompt.md",
        "workflow.coherence.validate": "evaluate_coherence_subtasks_prompt.md",
        "workflow.keyword.bind": "keywords_binding_prompt.md",
        "workflow.keywords.extract": "syntax_analysis_prompt.md",
    },
    "agent.curio.dataflow-reader": {
        "dataflow.explain": "explanation_prompt.md",
        "workflow.suggest": "workflow_suggestions_prompt.md",
    },
}

#: The cards that took other agents over: each keeps its own instruction for
#: its chat and runs each absorbed prompt as a mode. The Node Builder writes
#: node content, recommends packages and writes packages (one prompt for the
#: three writing capabilities); the Researcher composes notes from search
#: results and checks a fact.
_CARD_MODES = {
    "agent.curio.node-builder": {
        "node.content.generate": "new_content_prompt.md",
        "package.recommend": "package_recommendation_instruction.md",
        "package.build": "package_build_instruction.md",
        "package.extend": "package_build_instruction.md",
        "node.kind.author": "package_build_instruction.md",
    },
    "agent.curio.researcher": {
        "research.notes.compose": "researcher_notes_instruction.md",
        "research.verify": "research_instruction.md",
    },
}

#: What each parent may delegate: the "who asks" of every mode. The Node
#: Builder asks its own modes for node content and for a package to be
#: written, and recommends packages in its own chat; the Researcher asks the
#: Node Builder to write a package; only the Dataflow Builder asks for a
#: recommendation and for notes.
_DELEGABLE = {
    "agent.curio.node-builder": {
        "content.quality.evaluate", "dataset.discover", "dataset.select",
        "execution.followup.plan", "node.content.generate", "node.kind.author",
        "package.build", "package.extend", "research.verify",
    },
    "agent.curio.dataset-finder": {
        "dataset.fetch.author", "node.build", "research.verify",
        "workflow.keyword.bind", "workflow.suggest",
    },
    "agent.curio.dataflow-builder": {
        "content.quality.evaluate", "dataflow.explain",
        "dataset.discover", "dataset.fetch.author", "dataset.select",
        "node.build", "node.content.generate",
        "node.kind.author", "package.build", "package.extend",
        "package.recommend", "research.notes.compose",
        "research.verify", "workflow.suggest",
    },
    "agent.curio.researcher": {"node.kind.author", "package.build", "package.extend"},
}


def _instructions():
    """Every instruction a built-in can run, as ``(agent id, prompt key, text)``:
    the agent's own and each mode's, one entry per file."""
    out = []
    for m in builtin.list_builtin_manifests():
        coord = f"{m.agent_id}@1"
        seen = set()
        for key, asset in m.prompts.items():
            filename = _file(asset)
            if key == "system" or filename in seen:
                continue
            seen.add(filename)
            out.append((m.agent_id, key, builtin.read_prompt_text(coord, key)))
    return out


#: The catalog cards, pinned by id rather than recomputed from the rule they
#: follow, which would only restate it. A card acts on the project (P1), has a
#: capability whose input or reply the runtime treats as structure (P2), or is
#: the only agent for a canvas target (P3).
_CARDS = {
    "agent.curio.dataflow-builder", "agent.curio.dataset-finder", "agent.curio.node-builder",
    "agent.curio.researcher",
}


class TestRoster:
    def test_seven_agents(self):
        # The 2 agents merged from 8 + the three composites (dev/48, dev/50,
        # dev/52) + the authored evaluator (DEC-055, dev/85/86) + the
        # Researcher (dev/90). The chat agent, the node researcher and the
        # notes run in the Researcher; the content builder, the connection
        # builder and both package agents in the Node Builder.
        assert len(builtin.list_builtin_manifests()) == 7

    def test_the_four_cards_and_the_rest_internal(self):
        manifests = builtin.list_builtin_manifests()
        cards = {m.agent_id for m in manifests if m.catalog.listed}
        assert cards == _CARDS
        assert builtin.internal_agent_ids() == {m.agent_id for m in manifests} - _CARDS

    def test_every_card_meets_the_rule(self):
        from utk_curio.backend.app.agents.domain import content
        from utk_curio.backend.app.agents.application import tool_rounds as services

        mutate = set(services.MUTATE_PROPOSAL_TOOLS)
        structured = set(content.STRUCTURED_CAPABILITIES)
        manifests = builtin.list_builtin_manifests()
        for m in manifests:
            if not m.catalog.listed:
                continue
            acts = bool(mutate & {t.id for t in m.tools})
            understood = bool(structured & set(m.capability_ids))
            others = [o for o in manifests if o.agent_id != m.agent_id]
            owns_target = any(
                kind not in {t.kind for o in others for t in o.compatible_targets}
                for kind in (t.kind for t in m.compatible_targets)
            )
            assert acts or understood or owns_target, m.agent_id

    def test_no_internal_agent_meets_the_rule(self):
        # Otherwise it would be a card.
        from utk_curio.backend.app.agents.domain import content
        from utk_curio.backend.app.agents.application import tool_rounds as services

        mutate = set(services.MUTATE_PROPOSAL_TOOLS)
        structured = set(content.STRUCTURED_CAPABILITIES)
        for m in builtin.list_builtin_manifests():
            if m.catalog.listed:
                continue
            assert not mutate & {t.id for t in m.tools}, m.agent_id
            assert not structured & set(m.capability_ids), m.agent_id

    def test_internal_agents_are_known_by_coordinate(self):
        assert builtin.is_internal("agent.curio.dataflow-planner")
        assert builtin.is_internal("agent.curio.dataflow-planner@1")
        # The owner's own definition under the same id is not the built-in.
        assert not builtin.is_internal("agent.curio.dataflow-planner@2")
        assert not builtin.is_internal("agent.curio.researcher@1")

    def test_evaluator_authored_under_dec055(self):
        # OQ-007 resolved by dev/85 (DEC-055): the evaluator exists as a
        # net-new AUTHORED built-in — no longer excluded, never a fabricated
        # migration (its roster comment + docstring carry the decision).
        ids = set(_by_id())
        assert "agent.curio.generated-content-evaluator" in ids

    def test_matches_the_roster(self):
        manifests = builtin.list_builtin_manifests()
        got = {
            m.agent_id: (_file(m.prompts["instruction"]), list(m.capability_ids))
            for m in manifests
        }
        assert got == _ROSTER
        # In this order: the catalog lists the cards as the roster does, the
        # agent you talk to about anything first.
        assert [m.agent_id for m in manifests] == list(_ROSTER)
        modes = {
            m.agent_id: {c.id: _file(m.prompts[c.instruction]) for c in _modes(m)}
            for m in manifests
            if _modes(m)
        }
        assert modes == {**_MODES, **_CARD_MODES}
        # The rest run one instruction for everything.
        single = {m.agent_id for m in manifests} - set(_MODES) - set(_CARD_MODES)
        assert single == {"agent.curio.dataset-finder", "agent.curio.dataflow-builder",
                          "agent.curio.generated-content-evaluator"}

    def test_a_card_with_a_mode_keeps_its_own_chat_instruction(self):
        """A card that took another agent over is a card still: its chat runs
        its own instruction and reads its own context, and each absorbed
        prompt is a mode beside it (not the ``_merged`` shape, whose default
        is its first mode)."""
        chats = {
            "agent.curio.node-builder": "node_build_instruction.md",
            "agent.curio.researcher": "researcher_instruction.md",
        }
        assert set(chats) == set(_CARD_MODES)
        for agent_id, modes in _CARD_MODES.items():
            m = builtin.get_builtin_manifest(f"{agent_id}@1")
            assert m.catalog.listed, agent_id
            assert _file(m.prompts["instruction"]) == chats[agent_id], agent_id
            assert _file(m.prompts["instruction"]) not in modes.values(), agent_id
            for capability in modes:
                assert capability in m.capability_ids, (agent_id, capability)
            mode_reads = {r for c in _modes(m) for r in c.reads}
            assert not mode_reads <= set(m.inputs_reads), agent_id
        # The package recommendation is listed before the writing
        # capabilities, so reuse stays ahead of writing.
        caps = builtin.get_builtin_manifest("agent.curio.node-builder@1").capability_ids
        for writing in ("package.build", "package.extend", "node.kind.author"):
            assert caps.index("package.recommend") < caps.index(writing), writing

    def test_only_the_node_builder_hands_work_to_its_own_mode(self):
        # Its chat asks for node content and for a package to be written
        # through the entry naming itself, first in its preference order and
        # scoped to those modes; it recommends packages in its own chat, with
        # its catalog tools. The Researcher composes notes and checks facts in
        # its own chat, so it names no entry for itself.
        selves = {
            m.agent_id: m.delegate_scopes.get(m.agent_id)
            for m in builtin.list_builtin_manifests()
            if m.agent_id in m.delegates_to
        }
        assert selves == {"agent.curio.node-builder": (
            "node.content.generate", "package.build", "package.extend", "node.kind.author",
        )}
        nb = builtin.get_builtin_manifest("agent.curio.node-builder@1")
        assert nb.delegates_to[0] == "agent.curio.node-builder"

    def test_no_card_chat_carries_a_json_only_delegate_section(self):
        """A chat runs with its tools and answers the user. The JSON-only
        reply a delegated call owes its caller lives in the mode that call
        runs, never in a card's chat instruction."""
        for m in builtin.list_builtin_manifests():
            if not m.catalog.listed:
                continue
            chat = builtin.read_prompt_text(f"{m.agent_id}@1", "instruction")
            low = chat.lower()
            assert "delegated task from" not in low, m.agent_id
            assert "exactly one json object" not in low, m.agent_id
            assert "as a delegate" not in low, m.agent_id
        # The modes that answer in JSON say so.
        for agent_id, capability in (("agent.curio.researcher", "research.notes.compose"),
                                     ("agent.curio.node-builder", "package.build")):
            mode = builtin.read_prompt_text(f"{agent_id}@1", capability)
            assert mode, (agent_id, capability)
            assert "EXACTLY ONE JSON object" in mode, (agent_id, capability)
            assert "delegated task from" in mode.lower(), (agent_id, capability)

    def test_every_prompt_file_exists(self):
        for m in builtin.list_builtin_manifests():
            for asset in m.prompts.values():
                path = (
                    agent_text.page_file(asset.shared) if asset.shared
                    else builtin.agents_dir() / m.dir_name / asset.path
                )
                assert path.is_file(), _file(asset)

    def test_a_merged_agent_is_internal_and_its_default_is_its_first_mode(self):
        for agent_id, modes in _MODES.items():
            m = builtin.get_builtin_manifest(f"{agent_id}@1")
            assert not m.catalog.listed, agent_id
            assert _file(m.prompts["instruction"]) == next(iter(modes.values()))
            assert tuple(m.capability_ids) == tuple(modes)
            # Its reads are every mode's.
            assert set(m.inputs_reads) == {r for c in _modes(m) for r in c.reads}

    def test_the_keyword_modes_read_the_keyword_types(self):
        planner = builtin.get_builtin_manifest("agent.curio.dataflow-planner@1")
        reading = {c.id for c in planner.capabilities if "keywordTypes" in c.required_config}
        assert reading == {
            "workflow.keywords.extract", "workflow.keyword.bind", "workflow.plan.refresh",
        }
        assert planner.capability("workflow.keywords.extract").reads == ("workflowGoal",)

    def test_each_parent_delegates_what_the_merges_left_it(self):
        by_id = _by_id()
        got = {}
        for agent_id_of_parent in by_id:
            m = builtin.get_builtin_manifest(f"{agent_id_of_parent}@1")
            caps = {
                cap
                for agent_id in m.delegates_to
                for cap in by_id[agent_id].capability_ids
                if m.delegates(agent_id, cap)
            }
            if caps:
                got[agent_id_of_parent] = caps
        assert got == _DELEGABLE


class TestManifests:
    def test_all_validate(self):
        manifests = builtin.list_builtin_manifests()
        assert len(manifests) == 7
        assert all(isinstance(m, AgentManifest) for m in manifests)

    def test_coords_and_capabilities(self):
        by_id = {m.agent_id: m for m in builtin.list_builtin_manifests()}
        assert set(by_id) == set(_ROSTER)
        for agent_id, (_, caps) in _ROSTER.items():
            m = by_id[agent_id]
            assert m.dir_name == f"{agent_id}@1"
            assert m.capability_ids == caps
            assert m.provenance.trust == "built-in"

    def test_a_mode_names_its_own_prompt(self):
        m = builtin.get_builtin_manifest("agent.curio.dataflow-planner@1")
        for capability, filename in _MODES["agent.curio.dataflow-planner"].items():
            declared = m.capability(capability)
            assert declared.instruction == capability
            assert m.prompts[capability].path == f"prompts/{filename}"
        # So does a card's mode, beside the card's own chat instruction, which
        # is no mode's file. A capability that is not a mode runs the chat
        # instruction. Every capability of the Researcher is a mode other
        # agents ask for, so its chat is its instruction alone.
        for agent_id, modes in _CARD_MODES.items():
            card = builtin.get_builtin_manifest(f"{agent_id}@1")
            for capability, filename in modes.items():
                assert card.capability(capability).instruction == capability, agent_id
                assert card.prompts[capability].path == f"prompts/{filename}", agent_id
            chat = card.prompts["instruction"].path
            assert chat not in {card.prompts[c].path for c in modes}, agent_id
            others = [c for c in card.capabilities if c.id not in modes]
            assert all(c.instruction is None for c in others), agent_id
        nb = builtin.get_builtin_manifest("agent.curio.node-builder@1")
        assert [c.id for c in nb.capabilities if c.instruction is None] == [
            "node.build", "dataset.fetch.author",
        ]
        # A single-instruction agent declares no modes.
        for agent_id in ("agent.curio.dataset-finder", "agent.curio.dataflow-builder"):
            single = builtin.get_builtin_manifest(f"{agent_id}@1")
            assert all(c.instruction is None for c in single.capabilities), agent_id

    def test_get_by_coord(self):
        m = builtin.get_builtin_manifest("agent.curio.researcher@1")
        assert m is not None and m.agent_id == "agent.curio.researcher"
        assert builtin.get_builtin_manifest("agent.curio.researcher@9") is None
        assert builtin.get_builtin_manifest("curio.builtin@1") is None


class TestPreambleAndInputs:
    """The dev/05 roster's System-file column + grounded inputs (dev/06 parity):
    every built-in manifest carries its preamble asset and non-empty reads."""

    def test_every_builtin_declares_system_asset_and_reads(self):
        from utk_curio.backend.app.agents.domain import builtin

        for m in builtin.list_builtin_manifests():
            assert "system" in m.prompts, m.agent_id
            # A shared preamble is carried as prompts/<file> by an export and an install.
            assert m.prompts["system"].file.startswith("prompts/"), m.agent_id
            assert m.inputs_reads, f"{m.agent_id} has no inputs.reads"

    def test_every_builtin_shares_the_one_preamble(self):
        from utk_curio.backend.app.agents.domain import builtin

        for m in builtin.list_builtin_manifests():
            assert m.prompts["system"].path == "curio:default_preamble.md", m.agent_id
            assert m.prompts["system"].file == "prompts/default_preamble.md", m.agent_id
        for folder in prompt_folders():
            assert not (folder / "syntax_analysis_preamble.md").exists(), folder

    def test_prompt_text_is_read_by_key(self):
        coord = "agent.curio.dataflow-planner@1"
        bind = builtin.read_prompt_text(coord, "workflow.keyword.bind")
        assert bind == agent_text.render(prompt_path("keywords_binding_prompt.md"))
        # An undeclared key reads nothing, not the preamble.
        assert builtin.read_prompt_text(coord, "workflow.nope") is None
        assert builtin.read_prompt_text("agent.curio.researcher@1", "dataflow.explain") is None

    def test_preamble_exemplars_never_read_a_bare_filename(self):
        # dev/114: the shared preamble's worked dataflow was the ONLY data-
        # loading exemplar every agent saw, and all three of its loaders read
        # bare filenames — the pattern #298's bras_ibge_data.csv reproduced.
        # The exemplars are now the worked examples (the "Used" dataflows of
        # the base entry's examples.md), so the same rule holds for them.
        import json
        import re

        from utk_curio.backend.app.agents.application.turns import examples

        used = [entry for entry in examples.read_index() if entry.section == examples.USED]
        assert used, "the index lists no Used dataflow; this test would be vacuous"
        text = "\n".join(
            node.get("content") or ""
            for entry in used
            for node in json.loads(entry.path.read_text(encoding="utf-8"))["dataflow"]["nodes"]
        )
        assert not re.search(r"""read_csv\(f?['"][^'"]+\.csv""", text)
        assert not re.search(r"""read_file\(f?['"][^'"]+\.shp""", text)
        assert not re.search(r"""rasterio\.open\(f?['"]""", text)
        # Their loaders resolve their datasets by id.
        assert len(re.findall(r"curio_(?:load_data|data_path)\(", text)) >= 3
        # And every run that is shown them is told so.
        assert "never a guessed filename" in examples.heading()

    def test_preamble_text_readable_for_all_builtins(self):
        from utk_curio.backend.app.agents.domain import builtin

        for m in builtin.list_builtin_manifests():
            coord = f"{m.agent_id}@1"
            assert builtin.read_prompt_text(coord, "system"), coord
            assert builtin.read_prompt_text(coord, "instruction"), coord

    def test_every_builtin_instruction_is_distinct(self):
        """No two built-ins may share instruction bytes.

        This is what keeps the per-agent E2E claim from being vacuous.
        ``test_frontend/test_agent_runs_e2e.py`` proves a given agent ran by
        asserting its OWN instruction composed the system turn - the scripted
        reply is identical for every agent and can prove nothing. If two agents
        shared a prompt file, that assertion would pass for either one and the
        "every agent is covered" claim would quietly cover one less than it
        says.

        Two agents legitimately sharing a *preamble* is fine and expected
        (``default_preamble.md``); it is the instruction that identifies.
        """
        by_text: dict[str, list[str]] = {}
        for agent_id, key, text in _instructions():
            assert text, (agent_id, key)
            by_text.setdefault(text.strip(), []).append(f"{agent_id}:{key}")

        collisions = {
            ids[0]: ids for ids in by_text.values() if len(ids) > 1
        }
        assert not collisions, (
            "these built-ins share instruction bytes, so no test can tell which "
            f"of them actually ran: {list(collisions.values())}"
        )

    def test_no_instruction_is_a_substring_of_another(self):
        """A containment collision defeats the same assertion as an exact one.

        The E2E check is ``instruction in system_prompt``, so if agent A's
        instruction were wholly contained in agent B's, a run of B would satisfy
        A's assertion too. Distinctness alone does not rule that out.
        """
        texts = {f"{agent_id}:{key}": text.strip() for agent_id, key, text in _instructions()}
        contained = [
            (inner_id, outer_id)
            for inner_id, inner in texts.items()
            for outer_id, outer in texts.items()
            if inner_id != outer_id and inner in outer
        ]
        assert not contained, (
            "one built-in's instruction is contained in another's, so a run of "
            f"the outer would satisfy the inner's assertion: {contained}"
        )


class TestNodeBuilderComposite:
    """The dev/48 roster entry, spec per dev/15 §3.4 minus recorded
    deviations. It also writes node content, suggests nodes for a connection,
    and installs or writes node packages."""

    COORD = "agent.curio.node-builder@1"

    def test_manifest_surface(self):
        m = builtin.get_builtin_manifest(self.COORD)
        assert m is not None
        assert m.capability_ids == [
            "node.build", "dataset.fetch.author", "node.content.generate",
            "package.recommend", "package.build", "package.extend", "node.kind.author",
        ]
        assert m.delegates_to == [
            "agent.curio.node-builder",  # its own content and package-writing modes
            "agent.curio.dataflow-planner",  # its follow-up planning only
            "agent.curio.researcher",  # dev/67-4: chainable verification, its mode only
            "agent.curio.generated-content-evaluator",  # dev/86: advisory semantic check
            "agent.curio.dataset-finder",  # dev/114 (DEC-072): source resolution for data-loading nodes
        ]
        assert m.delegate_scopes == {
            "agent.curio.node-builder": (
                "node.content.generate", "package.build", "package.extend", "node.kind.author",
            ),
            "agent.curio.dataflow-planner": ("execution.followup.plan",),
            "agent.curio.researcher": ("research.verify",),
        }
        # dev/67-6 lifts the dev/48 canvas-only limitation: modify-existing
        # attaches to the node it modifies. On a connection it suggests what
        # could go there.
        assert [t.kind for t in m.compatible_targets] == ["canvas", "node", "connection"]
        assert [t.id for t in m.tools] == [
            "dataflow.read",
            "node.read",  # the content mode's own read, kept by the merge
            "node.create",  # a node type is made only by a package draft
            "node.runtime.read",  # dev/67-2: diagnose before regenerating
            "node.content.write",  # dev/67-6: modify-existing, reviewed
            "catalog.search",  # dev/114 (DEC-072): the only source of a real local path
            "models.search",  # the Model Catalog: a model this account can run
            "packages.catalog", "packages.resolve",  # dev/84: what exists, what it needs
            "package.install",  # dev/84: the reviewed install lane
            "package.draft.apply",  # dev/89: a written package's reviewed draft
        ]
        assert m.provenance.trust == "built-in"

    def test_its_chat_and_each_mode_read_their_own_prompt(self):
        # The prompt keys a run selects: the chat its instruction, a
        # node.content.generate run the content prompt (an Autark document
        # under the reply schema the Autark prompt), a recommendation its own
        # prompt, and the three package-writing capabilities one prompt.
        nb = builtin.get_builtin_manifest(self.COORD)
        assert {key: _file(asset) for key, asset in nb.prompts.items()} == {
            "system": "default_preamble.md",
            "instruction": "node_build_instruction.md",
            "node.content.generate": "new_content_prompt.md",
            "autk-grammar": "new_content_autk_prompt.md",
            "package.recommend": "package_recommendation_instruction.md",
            "package.build": "package_build_instruction.md",
            "package.extend": "package_build_instruction.md",
            "node.kind.author": "package_build_instruction.md",
        }
        m = builtin.get_builtin_manifest(self.COORD)
        assert m.capability("node.content.generate").reads == (
            "dataflowContext", "nodeId", "subtask", "workflowGoal",
        )
        assert m.capability("package.recommend").reads == (
            "mission", "targetContext", "existingPackages",
        )
        for writing in ("package.build", "package.extend", "node.kind.author"):
            assert m.capability(writing).reads == (
                "packageIntent", "targetContext", "existingPackages",
            ), writing
        # Worked examples under its chat and its content mode; the package
        # modes take none.
        assert builtin.gets_worked_examples(self.COORD)
        assert builtin.gets_worked_examples(self.COORD, "node.content.generate")
        for capability in ("package.recommend", "package.build", "package.extend", "node.kind.author"):
            assert not builtin.gets_worked_examples(self.COORD, capability), capability

    def test_review_policy_and_the_shipped_file_is_what_runs(self):
        # The composite declares review-before-apply; every agent that is not
        # a composite declares no delegatesTo and a report-only runtime. Each
        # agent runs exactly its shipped file: the manifest the roster serves
        # is that file parsed, and every prompt a run reads is the file its
        # folder holds, rendered, or the page Curio shares (``curio:``).
        import json
        from pathlib import Path

        from utk_curio.backend.app.agents.domain.manifest import parse_agent_manifest

        agents = Path(__file__).resolve().parents[4] / "agents"
        shared = agents / "agent.curio.builtin@1"

        def shipped(coord: str) -> dict:
            return json.loads((agents / coord / "manifest.json").read_text(encoding="utf-8"))

        nb = shipped(self.COORD)
        assert nb["runtime"] == {"execution": "foreground", "reviewPolicy": "review-before-apply"}
        assert nb["delegatesTo"] == [
            {"id": "agent.curio.node-builder", "capabilities": [
                "node.content.generate", "package.build", "package.extend", "node.kind.author",
            ]},
            {"id": "agent.curio.dataflow-planner", "capabilities": ["execution.followup.plan"]},
            {"id": "agent.curio.researcher", "capabilities": ["research.verify"]},
            "agent.curio.generated-content-evaluator",
            "agent.curio.dataset-finder",  # dev/114
        ]
        composites = {"agent.curio.node-builder", "agent.curio.dataset-finder", "agent.curio.dataflow-builder",
                      "agent.curio.researcher"}  # dev/90: asserted in its class
        manifests = builtin.list_builtin_manifests()
        assert len(manifests) == 7
        for m in manifests:
            raw = shipped(m.dir_name)
            assert m == parse_agent_manifest(raw), m.agent_id
            for key, asset in m.prompts.items():
                file = (
                    shared / asset.path.removeprefix("curio:") if asset.path.startswith("curio:")
                    else agents / m.dir_name / asset.path
                )
                assert builtin.read_prompt_text(m.dir_name, key) == agent_text.render(file), (
                    m.agent_id, key,
                )
            if m.agent_id in composites:
                continue
            assert "delegatesTo" not in raw, m.agent_id
            assert raw["runtime"] == {"execution": "foreground", "reviewPolicy": "report-only"}
            # requires stays empty for every migrated agent (dev/50 parity).
            assert all(t["requires"] == [] for t in raw["compatibleTargets"]), m.agent_id

    def test_net_new_instruction_resolves(self):
        # Net-new asset (dev/15 §3.3: no migrated source), read from the
        # agent's folder as every other prompt of it is.
        text = builtin.read_prompt_text(self.COORD, "instruction")
        assert text and "Reuse first" in text
        assert builtin.read_prompt_text(self.COORD, "system")  # default preamble

    def test_instruction_teaches_the_source_ladder(self):
        # dev/114 (DEC-072): the ladder the runtime gate enforces — user path,
        # catalog.search loader line, runtime-verified URL via dataset.discover,
        # synthetic only when asked — and the two-turn rule.
        text = builtin.read_prompt_text(self.COORD, "instruction")
        assert "catalog.search" in text
        assert 'curio_data_path("<id>")' in text
        assert '"dataset.discover"' in text
        assert "do not propose in that same turn" in text
        assert "synthetic data ONLY when the user explicitly asked for made-up data in their own words" in text
        assert "Never invent a filename" in text
        assert "ask the user for a path or URL instead of proposing" in text

    def test_instruction_sends_code_through_params_not_the_reply(self):
        # #245: the runtime now recovers a misplaced request, but the cheapest
        # fix is the model never misplacing it. Both the direct and the
        # delegated create paths must name params.content as the code channel.
        text = builtin.read_prompt_text(self.COORD, "instruction")
        assert "params.content" in text
        assert "code in your reply is not a node" in text

    def test_on_a_connection_it_suggests_nodes_and_never_wires_them(self):
        """Attached to a connection it is told which end is which (the
        ``connectionSide`` read, composed only for a connection), and its chat
        suggests up to three nodes in prose, specific to the dataflow, then
        creates the one the user picks. The user wires it."""
        m = builtin.get_builtin_manifest(self.COORD)
        assert "connectionSide" in m.inputs_reads
        text = builtin.read_prompt_text(self.COORD, "instruction")
        section = text.split("## On a connection", 1)[1].split("\n## ", 1)[0]
        low = section.lower()
        assert "or the user asks what could come before or after a node" in low
        assert "suggest up to three nodes, in prose" in low
        assert "a node for the input side is a step that can run before the node and feed it" in low
        assert "a node for the output side is a next step that uses the node's output" in low
        assert "in at most 50 words" in low
        assert '"transform the data to required format"' in low
        assert "never repeating the connected node's goal or node type" in low
        assert "include a visualization whenever one fits" in low
        assert "one node.create tool request" in low
        assert "you never wire connections" in low


class TestCatalogReadGrants:
    """Which built-ins hold the catalog read tools that no other agent needs."""

    @staticmethod
    def _holders(tool_id: str) -> set[str]:
        return {m.agent_id for m in builtin.list_builtin_manifests() if tool_id in [t.id for t in m.tools]}

    @staticmethod
    def _granted(agent_id: str) -> list[str]:
        from utk_curio.backend.app.agents.application import tools

        return tools.resolve_grants(builtin.get_builtin_manifest(f"{agent_id}@1").tools)

    def test_the_agents_that_write_node_code_search_the_model_catalog(self):
        # The Node Builder, in its chat and in its content mode.
        writers = {"agent.curio.node-builder"}
        assert self._holders("models.search") == writers
        for agent_id in writers:
            assert "models.search" in self._granted(agent_id), agent_id

    def test_the_dataflow_builder_reads_the_worked_examples(self):
        assert self._holders("examples.read") == {"agent.curio.dataflow-builder"}
        assert "examples.read" in self._granted("agent.curio.dataflow-builder")

    def test_only_the_node_builder_reads_the_node_catalog(self):
        # It recommends and installs packages in its chat.
        for tool in ("packages.catalog", "packages.resolve"):
            assert self._holders(tool) == {"agent.curio.node-builder"}, tool
            assert tool in self._granted("agent.curio.node-builder"), tool


class TestDatasetFinderComposite:
    """The dev/50 roster entry — spec per dev/15 §3.4 + docs/06, minus
    recorded deviations."""

    COORD = "agent.curio.dataset-finder@1"

    def test_manifest_surface(self):
        m = builtin.get_builtin_manifest(self.COORD)
        assert m is not None
        assert m.capability_ids == ["dataset.discover", "dataset.select"]
        assert m.delegates_to == [
            "agent.curio.node-builder",
            "agent.curio.dataflow-reader",
            "agent.curio.dataflow-planner",
            "agent.curio.researcher",
        ]
        assert m.delegate_scopes == {
            # Building the node, never its content mode.
            "agent.curio.node-builder": ("node.build", "dataset.fetch.author"),
            "agent.curio.dataflow-reader": ("workflow.suggest",),
            "agent.curio.dataflow-planner": ("workflow.keyword.bind",),
            # Checking a fact, never composing notes.
            "agent.curio.researcher": ("research.verify",),
        }
        by_kind = {t.kind: t for t in m.compatible_targets}
        assert set(by_kind) == {"node", "canvas"}
        # The docs/06 Data-Load gate: requires rides the node target only, and
        # names the template flag a node that loads a dataset declares.
        assert by_kind["node"].requires == ["loadsDataset"]
        assert by_kind["canvas"].requires == []
        assert [t.id for t in m.tools] == [
            "catalog.search",
            # The external lane used to dead-end: it could name a portal
            # dataset and nothing could act on it. These three make it
            # actionable - roster, live search, reviewed download.
            "discovery.sources", "discovery.search", "discovery.acquire",
            "dataset.install", "dataflow.read",
        ]
        assert m.provenance.trust == "built-in"

    def test_handoff_card_carries_the_verdict(self):
        # dev/114: the DEC-047 hand-off is a "handoff" card whose lines carry
        # the runtime's verification verdict; Node Builder re-probes anyway.
        text = builtin.read_prompt_text(self.COORD, "instruction")
        assert 'kind "handoff"' in text
        assert "verification verdict" in text
        assert "never as usable" in text

    def test_net_new_instruction_resolves(self):
        text = builtin.read_prompt_text(self.COORD, "instruction")
        assert text and "two lanes" in text.lower()
        assert "never author" in text.lower() or "never authors" in text.lower()
        assert builtin.read_prompt_text(self.COORD, "system")  # default preamble


class TestBackgroundExecutionRoster:
    """dev/115 (DEC-073): the Dataflow Builder alone declares
    ``runtime.execution: "background"`` — its Solve outlives the request as a
    detached job; every other built-in stays foreground byte-identically."""

    def test_only_the_dataflow_builder_is_background(self):
        manifests = builtin.list_builtin_manifests()
        background = [m.agent_id for m in manifests if m.execution == "background"]
        assert background == ["agent.curio.dataflow-builder"]
        dfb = builtin.manifest_dict("agent.curio.dataflow-builder@1")
        assert dfb["runtime"] == {"execution": "background", "reviewPolicy": "review-before-apply"}
        for m in manifests:
            if m.agent_id != "agent.curio.dataflow-builder":
                assert builtin.manifest_dict(m.dir_name)["runtime"]["execution"] == "foreground"
        # And the field parses through the manifest contract.
        assert builtin.get_builtin_manifest("agent.curio.dataflow-builder@1") is not None


class TestRequiresAgentsRoster:
    """dev/106 roster-wide invariant: hard dependencies are declared delegates
    and resolve to a roster agent."""

    def test_requires_subset_of_delegates_and_visible(self):
        ids = {m.agent_id for m in builtin.list_builtin_manifests()}
        for m in builtin.list_builtin_manifests():
            for r in m.requires_agents:
                assert r in m.delegates_to, (m.agent_id, r)
                assert r in ids, (m.agent_id, r)

    def test_only_the_two_composites_require(self):
        # dev/126: the Node Builder joins the Dataflow Builder — a data-loading
        # node's source resolution delegates dataset.discover from a server
        # path. Every other built-in keeps an empty requiresAgents, so no
        # install fans out across the roster.
        requiring = sorted(
            m.agent_id for m in builtin.list_builtin_manifests() if m.requires_agents
        )
        assert requiring == ["agent.curio.dataflow-builder", "agent.curio.node-builder"]


class TestDataflowBuilderComposite:
    """The dev/52 roster entry — spec per dev/15 §3.4 minus recorded deviations."""

    COORD = "agent.curio.dataflow-builder@1"

    def test_manifest_surface(self):
        m = builtin.get_builtin_manifest(self.COORD)
        assert m is not None
        assert m.capability_ids == ["dataflow.orchestrate"]
        assert m.delegates_to == [
            "agent.curio.dataset-finder",
            # dev/73: chat-path content updates; dev/84 Recommend packages,
            # dev/89 package-scale steps: its modes.
            "agent.curio.node-builder",
            # Not the Dataflow Planner: what its modes answer changes no node.
            "agent.curio.dataflow-reader",
            "agent.curio.generated-content-evaluator",  # dev/86: advisory semantic check
            "agent.curio.researcher",  # dev/95 (Follow-up D) reviewed notes, dev/67-4 verification
        ]
        # The Researcher is asked for its two modes, never its chat.
        assert m.delegate_scopes["agent.curio.researcher"] == ("research.notes.compose", "research.verify")
        assert [t.kind for t in m.compatible_targets] == ["canvas"]
        # dev/95: node.create is the reviewed lane the delegated Researcher's
        # note proposals mint on (grant-gated at the parent).
        # #917: package.draft.apply is the one a package the Node Builder's
        # writing mode drafts for it mints on, grant-gated the same way.
        assert [t.id for t in m.tools] == [
            "dataflow.read", "dataflow.plan.write", "node.runtime.read",
            "node.create",
            "examples.read",  # any worked example, beside the ones a run is given
            "package.draft.apply",
        ]
        assert m.provenance.trust == "built-in"

    def test_requires_the_two_server_invoked_specialists(self):
        # dev/106: Solve/Validate hard-invoke node.content.generate, the Node
        # Builder's mode. dev/126: resolution hard-invokes dataset.discover,
        # and every plan-created node is given a Node Builder at the user's
        # Apply: server paths, so both are required. The other delegates stay
        # optional (no install fan-out).
        m = builtin.get_builtin_manifest(self.COORD)
        assert m.requires_agents == ["agent.curio.dataset-finder", "agent.curio.node-builder"]

    def test_net_new_instruction_resolves(self):
        text = builtin.read_prompt_text(self.COORD, "instruction")
        assert text and "dataflowPlan" in text
        # dev/59: removals exist but only on explicit request.
        assert "Never remove uninvited" in text
        assert builtin.read_prompt_text(self.COORD, "system")  # default preamble


class TestNodeBuilderPackages:
    """The dev/84 recommendation (spec per dev/16 / DEC-035) and the dev/89
    package writing, in the Node Builder. Its chat installs a package that
    already fits, with its catalog tools, and climbs the node type ladder; its
    package-writing mode drafts a new or extended package for its chat, the
    Researcher and the Dataflow Builder, and its recommendation mode answers
    the Dataflow Builder. Both modes are delegated calls with no tools."""

    COORD = "agent.curio.node-builder@1"

    def test_the_recommendation_mode(self):
        m = builtin.get_builtin_manifest(self.COORD)
        recommend = m.capability("package.recommend")
        assert recommend.instruction == "package.recommend"
        assert recommend.reads == ("mission", "targetContext", "existingPackages")
        assert m.prompts["package.recommend"].path == "prompts/package_recommendation_instruction.md"
        # The install lane and the catalog reads it grounds on, in its chat.
        for tool in ("packages.catalog", "packages.resolve", "package.install"):
            assert tool in [t.id for t in m.tools], tool

    def test_every_tool_it_declares_is_granted(self):
        from utk_curio.backend.app.agents.application import tools

        m = builtin.get_builtin_manifest(self.COORD)
        # dev/89 commit 8 registered the package.draft.apply ToolContract
        # (mutate, grantable for proposal purposes only, DEC-017).
        granted = tools.resolve_grants(m.tools)
        assert granted == [t.id for t in m.tools]
        for tool in ("packages.catalog", "packages.resolve", "package.install", "package.draft.apply"):
            assert tool in granted, tool

    def test_no_card_ships_in_the_package_category(self):
        # The category stays: it is the frontend's fallback colour key.
        from utk_curio.backend.app.agents.domain.manifest import AGENT_CATEGORIES

        assert "package" in AGENT_CATEGORIES
        assert [m.agent_id for m in builtin.list_builtin_manifests() if m.category == "package"] == []
        raw = builtin.manifest_dict(self.COORD)
        assert raw["category"] == "node"

    def test_the_mode_recommends_from_its_evidence_and_the_chat_proposes_installs(self):
        text = builtin.read_prompt_text(self.COORD, "package.recommend")
        assert text and '"existingPackages"' in text
        low = text.lower()
        assert "never install, author, or publish" in low
        assert "delegated task from" in low
        assert "a need no row meets is a finding" in low
        chat = builtin.read_prompt_text(self.COORD, "instruction")
        assert "packages.catalog" in chat and "package.install" in chat
        assert builtin.read_prompt_text(self.COORD, "system")  # default preamble

    def test_delegation_wiring(self):
        # dev/89 topology: the Node Builder's chat, the Researcher's notes
        # ladder and the Dataflow Builder's package-scale plan steps resolve
        # the package.create-or-extend intent to the Node Builder's writing
        # mode. Only the Dataflow Builder asks it which packages a task needs:
        # the Node Builder recommends in its own chat. Reuse (the
        # recommendation) stays ahead of writing in its capability order.
        nb = builtin.get_builtin_manifest(self.COORD)
        rs = builtin.get_builtin_manifest("agent.curio.researcher@1")
        dfb = builtin.get_builtin_manifest("agent.curio.dataflow-builder@1")
        for parent in (nb, rs, dfb):
            assert "agent.curio.node-builder" in parent.delegates_to, parent.agent_id
            for capability in ("package.build", "package.extend", "node.kind.author"):
                assert parent.delegates("agent.curio.node-builder", capability), (parent.agent_id, capability)
        assert dfb.delegates("agent.curio.node-builder", "package.recommend")
        assert not nb.delegates("agent.curio.node-builder", "package.recommend")
        assert not rs.delegates("agent.curio.node-builder", "package.recommend")
        caps = nb.capability_ids
        for writing in ("package.build", "package.extend", "node.kind.author"):
            assert caps.index("package.recommend") < caps.index(writing)

    def test_the_writing_mode_carries_the_contract(self):
        text = builtin.read_prompt_text(self.COORD, "package.build")
        assert text
        low = text.lower()
        # Reuse-first posture and the two ways to write a package.
        assert "reuse first" in low
        assert "CREATE" in text and "EXTEND" in text
        # The never-rules: no self-install or publish, no read-only mutation.
        assert "never install" in low
        assert "read-only" in low
        # Backend generation stays out of scope (dev/89 Follow-up A).
        assert "backend sandbox" in low
        # The three writing capabilities read the one prompt.
        for capability in ("package.extend", "node.kind.author"):
            assert builtin.read_prompt_text(self.COORD, capability) == text, capability
        # The draft reaches review through the chat's one draft tool, and the
        # chat never pretends a package was built before then.
        chat = builtin.read_prompt_text(self.COORD, "instruction")
        assert "package.draft.apply" in chat
        assert "never pretend" in chat.lower()

    def test_its_chat_proposes_installing_a_package_that_fits(self):
        # The dev/84 install rules, on the ladder's second rung: a fitting
        # package is proposed for install there, not only named.
        text = builtin.read_prompt_text(self.COORD, "instruction")
        rungs = text.split("## Node types and packages", 1)[1].split("\n## ", 1)[0]
        low = rungs.lower()
        assert "proposed for install, not only named" in low
        assert "one package.install tool request per package" in low
        assert "dirname from the packages.catalog results" in low
        assert "is stated, not proposed" in low
        assert "builtin are always present" in low
        assert "packages.resolve" in rungs and "never force-resolve" in low
        assert "never present an install as done" in low

    def test_its_chat_climbs_the_node_type_ladder_in_order(self):
        # An existing template, a catalog package to install, and only then a
        # package written by its writing mode: the one way it makes a node
        # type, with the justification the user judges.
        text = builtin.read_prompt_text(self.COORD, "instruction")
        rungs = text.split("## Node types and packages", 1)[1].split("\n## ", 1)[0]
        starts = [rungs.index(f"\n{n}. ") for n in (1, 2, 3)]
        assert starts == sorted(starts)
        assert "\n4. " not in rungs
        one, rest = rungs.split("\n2. ", 1)
        two, three = rest.split("\n3. ", 1)
        assert "Available node templates" in one
        assert "packages.catalog" in two and "package.install" in two
        assert '"node.kind.author"' in three and "package.draft.apply" in three
        assert "for any new node type" in three
        assert "the closest listed templates you considered and why each is inadequate" in three
        assert "the user judges the justification" in three
        assert "node.template.create" not in text
        # The procedure sends the model to the ladder.
        procedure = text.split("## Procedure", 1)[1].split("\n## ", 1)[0]
        assert "node type ladder" in procedure

    def test_the_writing_mode_justifies_each_node_type_it_adds(self):
        # The delegate writes the draft, so it is taught the justification
        # and the label rule both in its prompt and in the build-request
        # contract it is handed.
        from utk_curio.backend.app.agents.application.turns.delegates import _build_request_contract

        text = builtin.read_prompt_text(self.COORD, "package.build")
        low = text.lower()
        assert '"justification" beside "mode"' in text
        assert "the closest existing templates you considered" in low
        assert "why each is inadequate" in low
        assert "a label no existing template has" in low
        contract = _build_request_contract()
        assert "justification" in contract["shape"]
        assert any("justification" in rule and "a label no existing template has" in rule
                   for rule in contract["rules"])

    def test_the_writing_mode_teaches_the_generic_authoring_contract(self):
        # dev/90 commit 2: ONE authoring contract for every custom look:
        # hook shape, registration, externals, safe rendering, appearance,
        # self-containment, with the gates named as the enforcement.
        text = builtin.read_prompt_text(self.COORD, "package.build")
        low = text.lower()
        assert "registerBehavior" in text
        assert "contentComponent" in text
        assert "(data, nodeState)" in text
        assert "dangerouslySetInnerHTML" in text and "never" in low
        assert "never bundled" in low  # react/react-dom/reactflow → host copies
        assert "appearance.backgroundColor" in text
        for color in ("yellow", "pink", "blue", "green", "orange", "lavender"):
            assert color in low
        assert "preview sandbox" in low  # enforcement, not advice
        # dev/90 A5: dependency-minimal authoring is the default: write it
        # yourself before importing it through a supply chain.
        assert "ZERO JavaScript dependencies" in text
        assert "markdown-lite" in low
        # dev/90 A7: the delegate posture: a tool-less call replies with ONE
        # JSON build request, never a tool request it cannot execute.
        assert "DELEGATE" in text
        assert "delegated task from" in low
        assert "EXACTLY ONE JSON object" in text
        # dev/90 A8: the schema arrives as a runtime-supplied input: the
        # prompt points at it and bans the observed invented keys.
        assert "buildRequestContract" in text
        assert "behaviorKey" in text
        # No scenario content: looks come from CALLERS (dev/90: the post-it
        # recipe lives with the Researcher, never with the writing mode).
        assert "post-it" not in low
        assert "carr" in low and "no built-in looks" in low


class TestGeneratedContentEvaluator:
    """The DEC-055 authored built-in (dev/85 §4 contract; impl dev/86)."""

    COORD = "agent.curio.generated-content-evaluator@1"

    def test_manifest_surface(self):
        m = builtin.get_builtin_manifest(self.COORD)
        assert m is not None
        assert m.capability_ids == ["content.quality.evaluate"]
        assert [t.kind for t in m.compatible_targets] == ["node", "canvas"]
        # Read-only evidence tools; no mutate contract anywhere near it.
        assert [t.id for t in m.tools] == ["node.read", "node.runtime.read", "dataflow.read"]
        # Advisory by construction: report-only, delegates-free — the same
        # shape as the migrated manifests (the byte-parity loop covers it).
        assert m.delegates_to == []
        assert m.provenance.trust == "built-in"

    def test_report_only_runtime(self):
        raw = builtin.manifest_dict(self.COORD)
        assert raw["runtime"] == {"execution": "foreground", "reviewPolicy": "report-only"}
        assert "delegatesTo" not in raw

    def test_net_new_instruction_carries_the_contract(self):
        text = builtin.read_prompt_text(self.COORD, "instruction")
        assert text
        # The dev/85 §4 verdict vocabulary, strictly findings-derived.
        for verdict in ("fits", "fits-with-warnings", "does-not-fit"):
            assert verdict in text
        for severity in ("[blocker]", "[warn]", "[note]"):
            assert severity in text
        # The advisory + honesty rules.
        assert "advisory" in text.lower()
        assert "never approves" in text.lower() or "never approve" in text.lower()
        assert "never-executed" in text
        assert builtin.read_prompt_text(self.COORD, "system")  # default preamble


class TestResearcher:
    """The dev/90 roster entry, the agent you talk to about a node or the
    whole dataflow. Its chat explains, debugs and helps define a task, answers
    a web question as post-it notes (reuse-first, package writing delegated to
    the Node Builder) and checks facts. Composing notes from search results
    and checking a fact are its modes, for other agents."""

    COORD = "agent.curio.researcher@1"

    # The Dataflow Builder's prompt is byte-pinned while the Researcher lands
    # (dev/90 §8 AC-2): a drive-by edit fails HERE, not in a downstream run.
    DATAFLOW_BUILDER_PROMPT_SHA256 = (
        # The plan is named, not called a block: on native tools it is the
        # dataflow.plan.write call, on the fenced protocol its block. It names
        # examples.read, for a worked example beyond the two a run is given.
        # #662: fan-in goes straight onto a node's input circles, read
        # through chips; no Merge Flow to route through.
        # #662, 2026-10-05: a planned node declares the widgets its code
        # reads, and a plan saves scenarios (selections and duplicates).
        # 2026-10-13: each input circle is its own variable, input_k, and its
        # chip is [!! input_k !!] (port of #819's input names).
        # 2026-10-14: the research examples are cool roofs, building heights
        # and street trees in Chicago, beside GTFS feeds (owner, 10-13).
        # 2026-10-15: the Node Builder writes new node types; its one-template
        # fallback is retired (plan a-few-things-snuggly-goblet, step 6).
        # 2026-10-22: two views link directly, and a Data Pool goes between
        # them only in its four cases (owner, 10-21; PR #1058).
        # 2026-10-22: a planned Spatial Join says how it joins in
        # "spatialJoin"; and the text that promised what the code refuses
        # goes: a plan carrying code, a Topology verdict ending every applied
        # result, and workflow.plan.create decomposing a task (plan step 11).
        # 2026-10-23: every applied plan ends with the Topology verdict again,
        # since one applied row by row or by Connect all now does; and the
        # Dataflow Planner leaves the Builder's delegations, so its coherence
        # check is no longer offered (proposal paths, step 2). A pool starts
        # at OVERWRITE and the plan sets its modes in "dataPool"; a Simple
        # View names its image column in "simpleVis" (step 3).
        "e6cdb1caee09f5743cf16a2d2a9732ddce1c548afa54ad28d259dbbface151db"
    )

    def test_manifest_surface(self):
        m = builtin.get_builtin_manifest(self.COORD)
        assert m is not None
        # Composing notes from search results and checking a fact: its modes.
        assert m.capability_ids == ["research.notes.compose", "research.verify"]
        # It delegates package writing only, to the Node Builder's mode.
        assert m.delegates_to == ["agent.curio.node-builder"]
        assert m.delegate_scopes == {
            "agent.curio.node-builder": ("package.build", "package.extend", "node.kind.author"),
        }
        assert [t.kind for t in m.compatible_targets] == ["node", "canvas"]
        # It reads the dataflow as it is on screen, unsaved edits included,
        # beside what it is attached to (on a node, that node's last run).
        assert list(m.inputs_reads) == [
            "mission", "targetContext", "installedTemplates", "dataflowContext",
        ]
        # dataflow.read, node.read and node.runtime.read answer about the
        # dataflow and a node's last run; web.search/web.fetch gather the
        # findings (dev/90 A1, the recording's question to web to post-it
        # loop); node.create carries notes onto an installed template;
        # package.install is the dev/93 D4 middle rung: it enlists a package
        # the user already owns, without which a notes package outside this
        # project's lockfile was unreachable and authoring a near-duplicate
        # was the only move left; package.draft.apply authorizes the dev/90
        # delegate-draft MINT only: the draft content always comes from the
        # Node Builder's writing mode.
        assert [t.id for t in m.tools] == [
            "dataflow.read", "node.read", "node.runtime.read", "web.search", "web.fetch",
            "node.create", "package.install", "package.draft.apply",
        ]
        assert m.provenance.trust == "built-in"

    def test_review_policy(self):
        raw = builtin.manifest_dict(self.COORD)
        assert raw["runtime"] == {"execution": "foreground", "reviewPolicy": "review-before-apply"}
        assert raw["category"] == "node"

    def test_its_chat_and_its_two_modes(self):
        # A message typed to it runs researcher_instruction.md. Delegated
        # research.verify (dev/67-4) runs research_instruction.md, delegated
        # research.notes.compose (dev/95) runs researcher_notes_instruction.md,
        # and capability-keyed resolution finds both on this one agent.
        m = builtin.get_builtin_manifest(self.COORD)
        assert m.prompts["instruction"].path == "prompts/researcher_instruction.md"
        assert m.capability("research.verify").instruction == "research.verify"
        assert m.capability("research.verify").reads == ("mission", "nodeContext")
        assert m.prompts["research.verify"].path == "prompts/research_instruction.md"
        notes = m.capability("research.notes.compose")
        assert notes.instruction == "research.notes.compose"
        assert notes.reads == ("question", "searchResults", "notesTemplates")
        assert m.prompts["research.notes.compose"].path == "prompts/researcher_notes_instruction.md"
        for capability in ("research.verify", "research.notes.compose"):
            holders = {o.agent_id for o in builtin.list_builtin_manifests() if capability in o.capability_ids}
            assert holders == {"agent.curio.researcher"}, capability
        # And the purpose line says what it does in chat.
        for words in ("a node or the whole dataflow", "diagnoses errors",
                      "define what to build", "as notes on the canvas", "checks facts"):
            assert words in m.purpose, words

    def test_dataflow_builder_prompt_stays_pinned_and_delegation_is_wired(self):
        # dev/90 Follow-up D DELIVERED by dev/95: the delegatesTo growth this
        # pin used to forbid is now the deliberate change (the dev/48 D4
        # precedent: a byte-pin updates WITH its memo, never incidentally).
        # The prompt sha updates only with the dev/95 prompt edit itself. It
        # covers the text the agent reads: its source, rendered.
        import hashlib

        prompt = builtin.read_prompt_text("agent.curio.dataflow-builder@1", "instruction").encode("utf-8")
        assert hashlib.sha256(prompt).hexdigest() == self.DATAFLOW_BUILDER_PROMPT_SHA256
        dfb = builtin.get_builtin_manifest("agent.curio.dataflow-builder@1")
        assert "agent.curio.researcher" in dfb.delegates_to  # dev/95 Follow-up D
        # It asks for the notes mode and the checking mode, never the chat.
        assert dfb.delegate_scopes["agent.curio.researcher"] == ("research.notes.compose", "research.verify")

    def test_its_chat_routes_what_the_user_wants(self):
        """The LLM picks what to do, in the call that answers: about the
        dataflow (explain, debug, define what to build) it answers from the
        dataflow and its read tools, with no web and no notes; a question the
        dataflow cannot answer is searched on the web, answered in prose and
        given notes; a fact to check gets labeled findings and no notes."""
        text = builtin.read_prompt_text(self.COORD, "instruction")
        low = text.lower()
        route = low.split("## what the user wants", 1)[1].split("\n## ", 1)[0]
        assert "explain it, debug it, or define what to build" in route
        assert "answer from the dataflow you were given and your read tools" in route
        assert "use no web tools and propose no notes" in route
        assert "a question the dataflow cannot answer" in route
        assert "search the web, answer in prose, and propose notes" in route
        assert "a fact to check" in route and "labeled findings" in route
        # The sections the routes name, in this order.
        headings = ["## explain", "## debug", "## define a task", "## gather findings",
                    "## check a fact", "## reuse first", "## notes", "## failures",
                    "## changes to the dataflow"]
        at = [low.index("\n" + heading + "\n") for heading in headings]
        assert at == sorted(at)
        # It reads the dataflow on screen and looks further with its tools.
        assert "unsaved edits included" in low
        for tool in ("dataflow.read", "node.read", "node.runtime.read"):
            assert tool in text, tool
        # A finished task definition ends in the fixed summary, and nothing
        # else in that reply.
        assert "Task:\n**{task}**\nIf you would like to change it let me know!" in text
        assert "output the summary in exactly this form, and nothing else in that reply" in low
        # Debugging reads the node's last run and states the cause, then the fix.
        assert "state the cause in one or two sentences, then the fix" in low
        # Explaining names nodes by title or type, never by internal ids.
        assert "never by internal ids" in low
        # Changes go to the agents that make them.
        changes = low.split("## changes to the dataflow", 1)[1]
        assert "the dataflow builder plans and builds a whole dataflow" in changes
        assert "the node builder creates or changes one node" in changes

    def test_its_chat_carries_the_recipe(self):
        text = builtin.read_prompt_text(self.COORD, "instruction")
        assert text
        low = text.lower()
        # The post-it recipe as REQUIREMENTS (dev/90 §3).
        assert "post-it" in low
        assert "reuse first" in low
        assert "node.create" in text
        assert "node.kind.author" in text
        # dev/93 D4: the ladder has three rungs in order, and the middle one
        # is what was missing — a package the user already owns is enlisted,
        # not re-authored. "Reuse first" alone let the model jump straight to
        # authoring the moment this project's roster came up empty.
        assert "package.install" in text
        assert "installed but not enlisted" in low
        assert "last resort" in low
        assert "never author a package whose job an already-installed one does" in low
        for color in ("yellow", "pink", "blue", "green", "orange", "lavender"):
            assert color in low
        assert "never raw html" in low
        assert 'editor "none"' in low
        # Ownership boundary + honesty rules.
        assert "never compose" in low
        assert "never claim" in low
        assert "never invent facts" in low
        # Checking a fact in its own chat (what the verification agent's chat
        # did): labeled findings in chat, no notes, and a finding checked
        # before it becomes a note.
        check = low.split("## check a fact", 1)[1].split("\n## ", 1)[0]
        assert "answer in chat with your findings, one per line, each labeled, and place no notes" in check
        assert "a finding that needs checking is checked before it becomes a note" in check
        for label in ("VERIFIED", "REPORTED", "UNVERIFIED"):
            assert label in text
        # The research examples (owner, 2026-10-13).
        for question in (
            "how much do cool roofs lower summer surface temperatures in chicago?",
            "which open datasets give building heights for downtown chicago?",
            "which cities publish their street trees as open data?",
            "which gtfs feeds cover this city?",
        ):
            assert question in low, question
        assert "paris" not in low and '"cool roofs in chicago"' in low
        # dev/90 A12: findings ride the delegation as DATA — a delegation
        # without notes places nothing; the runtime copies rows verbatim.
        assert '"notes"' in text
        assert "delegation without notes places nothing" in low
        assert "verbatim" in low
        # dev/90 A13: the reference recording's row — yellow question note
        # FIRST, then green answer note(s), content composed as markdown.
        assert "yellow note carrying the user's question" in low
        assert "green note per answer" in low
        assert "as clean markdown" in low
        # dev/105 D3/S1/S3: the live 2026-08-25 run. The ENLIST rung names the
        # exact dirName spelling (the model sent the bare id); a REFUSED
        # request is a correction to act on, distinct from a FAILED build
        # (the old single sentence taught "stop" for both); a refusal is never
        # evidence of absence (the model said "not in the catalog" — false);
        # a canvas node type is not a template choice; no mechanics narration.
        assert "the versioned dirname, e.g. curio.notes@1" in low
        assert "never the bare package id" in low
        assert "a correction, not a dead end" in low
        assert "a refused request is not evidence of absence" in low
        assert "is not a note template unless it appears there" in low
        assert "never narrate the request mechanics" in low
        # dev/105 A2: the REUSE rung names the exact node.create params — and
        # the tool contract the model reads at the tail admits every one of
        # them (the second live test's notes were white and headed "Note"
        # because the contract named only nodeType/content/goal).
        assert '"title": "<short header>"' in text
        assert '"appearance": {"backgroundColor"' in text
        # Its notes go on the built-in Note, which every dataflow can hold.
        reuse = low.split("1. reuse.", 1)[1].split("2. enlist.", 1)[0]
        assert '"nodetype": "curio.builtin/note"' in reuse
        # dev/105 A3: the ENLIST rung carries the findings like AUTHOR does, so
        # Apply on the install card proceeds to the notes without a second turn.
        assert 'an install request without "notes" enlists a package and places nothing' in low
        assert "you do not need a second turn" in low
        from utk_curio.backend.app.agents.application import tools as tools_mod

        contract = tools_mod.REGISTRY["node.create"].description
        for name in ('"title"', '"goal"', '"appearance": {"backgroundColor"'):
            assert name in contract
        assert "notes mirror the chat" in low
        # dev/90 A1: gather-first via the web tools, sources in the note,
        # honest stop when no provider is configured.
        assert "web.search" in text
        assert "gather your own findings" in low
        assert "https link" in low
        assert "never invent findings" in low
        assert builtin.read_prompt_text(self.COORD, "system")  # default preamble
