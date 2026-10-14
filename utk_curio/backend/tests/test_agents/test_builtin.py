"""Tests for the built-in agent roster: the prompt-agent migrations, two of
them merged agents with modes, the P5 composites (memo dev/48), and the three
cards that took another agent over and run its prompt as a mode."""

from __future__ import annotations

from utk_curio.backend.app.agents.domain import builtin
from utk_curio.backend.app.agents.domain.manifest import AgentManifest


# The dev/06 canonical map: agent id -> its prompt file and capabilities.
_EXPECTED = {
    # The chat agent explains and diagnoses as well as chatting.
    "agent.chat-agent": ("chat_prompt.md", ["conversation.respond", "attachment.refine",
                                             "node.explain", "code.debug.diagnose"]),
    "agent.connection-builder": ("new_connection_prompt.md", ["connection.propose"]),
}

#: The merged agents: each capability is a mode that runs its own instruction.
#: The planning and keyword agents became the Dataflow Planner, and the two
#: dataflow readers the Dataflow Reader.
_MODES = {
    "agent.dataflow-planner": {
        "workflow.plan.create": "new_subtasks_prompt.md",
        "execution.followup.plan": "new_subtask_from_exec_prompt.md",
        "workflow.plan.refresh": "task_refresh_prompt.md",
        "workflow.coherence.validate": "evaluate_coherence_subtasks_prompt.md",
        "workflow.keyword.bind": "keywords_binding_prompt.md",
        "workflow.keywords.extract": "syntax_analysis_prompt.md",
    },
    "agent.dataflow-reader": {
        "dataflow.explain": "explanation_prompt.md",
        "workflow.suggest": "workflow_suggestions_prompt.md",
    },
}

#: The cards that took another agent over (2026-10-14): each keeps its own
#: instruction for its chat and runs the absorbed prompt as a mode.
_CARD_MODES = {
    "agent.node-builder": {"node.content.generate": "new_content_prompt.md"},
    "agent.researcher": {"research.verify": "research_instruction.md"},
    "agent.package-builder": {"package.recommend": "package_recommendation_instruction.md"},
}

#: What each parent may delegate. The merges kept every set as it was, save
#: the syntax analysis the package recommender delegated expecting import
#: extraction, which it never did, and two capabilities no caller asked for
#: (research.summarize, package.identify). The Connection Builder delegates
#: only the recommendation; the Researcher checks facts itself, so it
#: delegates only package authoring.
_DELEGABLE = {
    "agent.connection-builder": {"package.recommend"},
    "agent.node-builder": {
        "content.quality.evaluate", "dataset.discover", "dataset.select",
        "execution.followup.plan", "node.content.generate", "node.kind.author",
        "package.build", "package.extend", "package.recommend", "research.verify",
    },
    "agent.dataset-finder": {
        "dataset.fetch.author", "node.build", "research.verify",
        "workflow.keyword.bind", "workflow.suggest",
    },
    "agent.dataflow-builder": {
        "connection.propose", "content.quality.evaluate", "dataflow.explain",
        "dataset.discover", "dataset.fetch.author", "dataset.select",
        "execution.followup.plan", "node.build", "node.content.generate",
        "node.kind.author", "package.build", "package.extend",
        "package.recommend", "research.notes.compose",
        "research.verify", "workflow.coherence.validate", "workflow.plan.create",
        "workflow.plan.refresh", "workflow.suggest",
    },
    "agent.researcher": {"node.kind.author", "package.build", "package.extend"},
}


def _instructions():
    """Every instruction a built-in can run, as ``(agent id, prompt key, text)``:
    the agent's own and each mode's, one entry per file."""
    out = []
    for spec in builtin.BUILTIN_AGENTS:
        coord = f"{spec.agent_id}@1.0.0"
        seen = set()
        for key, filename in spec.prompt_files().items():
            if key == "system" or filename in seen:
                continue
            seen.add(filename)
            out.append((spec.agent_id, key, builtin.read_prompt_text(coord, key)))
    return out


#: The catalog cards, pinned by id rather than recomputed from the rule they
#: follow, which would only restate it. A card acts on the project (P1), has a
#: capability whose input or reply the runtime treats as structure (P2), or is
#: the only agent for a canvas target (P3); the chat agent is the one
#: conversational surface.
_CARDS = {
    "agent.dataflow-builder", "agent.dataset-finder", "agent.node-builder",
    "agent.package-builder", "agent.researcher", "agent.connection-builder",
    "agent.chat-agent",
}


class TestRoster:
    def test_ten_agents(self):
        # 2 migrations and the 2 agents merged from 8 more + the three
        # composites (dev/48, dev/50, dev/52) + the authored evaluator
        # (DEC-055, dev/85/86) + the package builder (dev/89) + the notes
        # researcher (dev/90). The content builder, the node researcher and
        # the package recommender run as modes of three of them.
        assert len(builtin.BUILTIN_AGENTS) == 10

    def test_the_seven_cards_and_the_rest_internal(self):
        cards = {s.agent_id for s in builtin.BUILTIN_AGENTS if s.in_catalog}
        assert cards == _CARDS
        assert builtin.internal_agent_ids() == {
            s.agent_id for s in builtin.BUILTIN_AGENTS
        } - _CARDS

    def test_every_card_meets_the_rule(self):
        from utk_curio.backend.app.agents.domain import content
        from utk_curio.backend.app.agents.application import tool_rounds as services

        mutate = set(services.MUTATE_PROPOSAL_TOOLS)
        structured = set(content.STRUCTURED_CAPABILITIES)
        for spec in builtin.BUILTIN_AGENTS:
            if not spec.in_catalog:
                continue
            acts = bool(mutate & set(spec.tools))
            understood = bool(structured & set(spec.capabilities))
            others = [s for s in builtin.BUILTIN_AGENTS if s is not spec]
            owns_target = any(
                kind not in {k for o in others for k in o.target_kinds()}
                for kind in spec.target_kinds()
            )
            surface = spec.agent_id == "agent.chat-agent"
            assert acts or understood or owns_target or surface, spec.agent_id

    def test_no_internal_agent_meets_the_rule(self):
        # Otherwise it would be a card.
        from utk_curio.backend.app.agents.domain import content
        from utk_curio.backend.app.agents.application import tool_rounds as services

        mutate = set(services.MUTATE_PROPOSAL_TOOLS)
        structured = set(content.STRUCTURED_CAPABILITIES)
        for spec in builtin.BUILTIN_AGENTS:
            if spec.in_catalog:
                continue
            assert not mutate & set(spec.tools), spec.agent_id
            assert not structured & set(spec.capabilities), spec.agent_id

    def test_internal_agents_are_known_by_coordinate(self):
        assert builtin.is_internal("agent.dataflow-planner")
        assert builtin.is_internal("agent.dataflow-planner@1.0.0")
        # The owner's own definition under the same id is not the built-in.
        assert not builtin.is_internal("agent.dataflow-planner@2.0.0")
        assert not builtin.is_internal("agent.chat-agent@1.0.0")

    def test_evaluator_authored_under_dec055(self):
        # OQ-007 resolved by dev/85 (DEC-055): the evaluator exists as a
        # net-new AUTHORED built-in — no longer excluded, never a fabricated
        # migration (its roster comment + docstring carry the decision).
        ids = {s.agent_id for s in builtin.BUILTIN_AGENTS}
        assert "agent.generated-content-evaluator" in ids

    def test_matches_dev06_map(self):
        got = {
            s.agent_id: (s.prompt_file, list(s.capabilities))
            for s in builtin.BUILTIN_AGENTS
            if s.agent_id in _EXPECTED
        }
        assert got == _EXPECTED
        modes = {
            s.agent_id: {m.capability: m.prompt_file for m in s.modes}
            for s in builtin.BUILTIN_AGENTS
            if s.modes
        }
        assert modes == {**_MODES, **_CARD_MODES}
        # The composites are the only non-migration entries (dev/48, dev/50).
        extras = {s.agent_id for s in builtin.BUILTIN_AGENTS} - set(_EXPECTED) - set(_MODES)
        assert extras == {"agent.node-builder", "agent.dataset-finder",
                          "agent.dataflow-builder",
                          "agent.generated-content-evaluator",
                          "agent.package-builder",
                          "agent.researcher"}

    def test_a_card_with_a_mode_keeps_its_own_chat_instruction(self):
        """A card that took another agent over is a card still: its chat runs
        its own instruction and reads its own context, and the absorbed
        prompt is a mode beside it (not the ``_merged`` shape, whose default
        is its first mode)."""
        chats = {
            "agent.node-builder": "node_build_instruction.md",
            "agent.researcher": "researcher_notes_instruction.md",
            "agent.package-builder": "package_build_instruction.md",
        }
        assert set(chats) == set(_CARD_MODES)
        for agent_id, modes in _CARD_MODES.items():
            spec = builtin.get_builtin_spec(f"{agent_id}@1.0.0")
            assert spec.in_catalog, agent_id
            assert spec.prompt_file == chats[agent_id], agent_id
            assert spec.prompt_file not in modes.values(), agent_id
            for capability in modes:
                assert capability in spec.capabilities, (agent_id, capability)
            mode_reads = {r for m in spec.modes for r in m.reads}
            assert not mode_reads <= set(spec.reads), agent_id
        # The package recommendation is listed before the authoring
        # capabilities, so reuse stays ahead of authoring.
        pb = builtin.get_builtin_spec("agent.package-builder@1.0.0")
        assert pb.capabilities[0] == "package.recommend"

    def test_only_the_node_builder_hands_work_to_its_own_mode(self):
        # Its chat asks for node content through the entry naming itself,
        # first in its preference order and scoped to that mode. The
        # Researcher checks facts in its own chat, and the Package Builder
        # proposes installs in its own, so neither names itself.
        selves = {
            m.agent_id: m.delegate_scopes.get(m.agent_id)
            for m in builtin.list_builtin_manifests()
            if m.agent_id in m.delegates_to
        }
        assert selves == {"agent.node-builder": ("node.content.generate",)}
        nb = builtin.get_builtin_manifest("agent.node-builder@1.0.0")
        assert nb.delegates_to[0] == "agent.node-builder"

    def test_every_prompt_file_exists(self):
        for spec in builtin.BUILTIN_AGENTS:
            for filename in spec.prompt_files().values():
                assert (builtin.PROMPT_SOURCE_DIR / filename).is_file(), filename

    def test_a_merged_agent_is_internal_and_its_default_is_its_first_mode(self):
        for agent_id, modes in _MODES.items():
            spec = builtin.get_builtin_spec(f"{agent_id}@1.0.0")
            assert not spec.in_catalog, agent_id
            assert spec.prompt_file == next(iter(modes.values()))
            assert spec.capabilities == tuple(modes)
            # Its reads are every mode's.
            assert set(spec.reads) == {r for m in spec.modes for r in m.reads}

    def test_the_keyword_modes_read_the_keyword_types(self):
        planner = builtin.get_builtin_manifest("agent.dataflow-planner@1.0.0")
        reading = {c.id for c in planner.capabilities if "keywordTypes" in c.required_config}
        assert reading == {
            "workflow.keywords.extract", "workflow.keyword.bind", "workflow.plan.refresh",
        }
        assert planner.capability("workflow.keywords.extract").reads == ("workflowGoal",)

    def test_each_parent_delegates_what_the_merges_left_it(self):
        specs = {s.agent_id: s for s in builtin.BUILTIN_AGENTS}
        got = {}
        for spec in builtin.BUILTIN_AGENTS:
            m = builtin.get_builtin_manifest(f"{spec.agent_id}@1.0.0")
            caps = {
                cap
                for agent_id in m.delegates_to
                for cap in specs[agent_id].capabilities
                if m.delegates(agent_id, cap)
            }
            if caps:
                got[spec.agent_id] = caps
        assert got == _DELEGABLE


class TestManifests:
    def test_all_validate(self):
        manifests = builtin.list_builtin_manifests()
        assert len(manifests) == 10
        assert all(isinstance(m, AgentManifest) for m in manifests)

    def test_coords_and_capabilities(self):
        by_id = {m.agent_id: m for m in builtin.list_builtin_manifests()}
        expected = {**{a: caps for a, (_, caps) in _EXPECTED.items()},
                    **{a: list(modes) for a, modes in _MODES.items()}}
        for agent_id, caps in expected.items():
            m = by_id[agent_id]
            assert m.dir_name == f"{agent_id}@1.0.0"
            assert m.capability_ids == caps
            assert m.provenance.trust == "built-in"

    def test_a_mode_names_its_own_prompt(self):
        m = builtin.get_builtin_manifest("agent.dataflow-planner@1.0.0")
        for capability, filename in _MODES["agent.dataflow-planner"].items():
            declared = m.capability(capability)
            assert declared.instruction == capability
            assert m.prompts[capability].path == f"prompts/{filename}"
        # So does a card's mode, beside the card's own instruction.
        for agent_id, modes in _CARD_MODES.items():
            card = builtin.get_builtin_manifest(f"{agent_id}@1.0.0")
            for capability, filename in modes.items():
                assert card.capability(capability).instruction == capability, agent_id
                assert card.prompts[capability].path == f"prompts/{filename}", agent_id
            others = [c for c in card.capabilities if c.id not in modes]
            assert others and all(c.instruction is None for c in others), agent_id
        # A single-instruction agent declares no modes.
        chat = builtin.get_builtin_manifest("agent.chat-agent@1.0.0")
        assert all(c.instruction is None for c in chat.capabilities)

    def test_get_by_coord(self):
        m = builtin.get_builtin_manifest("agent.chat-agent@1.0.0")
        assert m is not None and m.agent_id == "agent.chat-agent"
        assert builtin.get_builtin_manifest("agent.chat-agent@9.9.9") is None
        assert builtin.get_builtin_manifest("curio.builtin@1") is None


class TestPreambleAndInputs:
    """The dev/05 roster's System-file column + grounded inputs (dev/06 parity):
    every built-in manifest carries its preamble asset and non-empty reads."""

    def test_every_builtin_declares_system_asset_and_reads(self):
        from utk_curio.backend.app.agents.domain import builtin

        for m in builtin.list_builtin_manifests():
            assert "system" in m.prompts, m.agent_id
            assert m.prompts["system"].path.startswith("prompts/"), m.agent_id
            assert m.inputs_reads, f"{m.agent_id} has no inputs.reads"

    def test_every_builtin_shares_the_one_preamble(self):
        from utk_curio.backend.app.agents.domain import builtin

        for m in builtin.list_builtin_manifests():
            assert m.prompts["system"].path == "prompts/default_preamble.md", m.agent_id
        assert not (builtin.PROMPT_SOURCE_DIR / "syntax_analysis_preamble.md").exists()

    def test_prompt_text_is_read_by_key(self):
        coord = "agent.dataflow-planner@1.0.0"
        bind = builtin.read_prompt_text(coord, "workflow.keyword.bind")
        assert bind == (builtin.PROMPT_SOURCE_DIR / "keywords_binding_prompt.md").read_text(encoding="utf-8")
        # An undeclared key reads nothing, not the preamble.
        assert builtin.read_prompt_text(coord, "workflow.nope") is None
        assert builtin.read_prompt_text("agent.chat-agent@1.0.0", "dataflow.explain") is None

    def test_preamble_exemplars_never_read_a_bare_filename(self):
        # dev/114: the shared preamble's worked dataflow was the ONLY data-
        # loading exemplar every agent saw, and all three of its loaders read
        # bare filenames — the pattern #298's bras_ibge_data.csv reproduced.
        # The exemplars are now the worked examples (the "Used" dataflows of
        # llm-prompts/examples.md), so the same rule holds for them.
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
        assert "never a guessed filename" in examples.HEADING

    def test_preamble_text_readable_for_all_builtins(self):
        from utk_curio.backend.app.agents.domain import builtin

        for spec in builtin.BUILTIN_AGENTS:
            coord = f"{spec.agent_id}@1.0.0"
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
    """The dev/48 roster entry — spec per dev/15 §3.4 minus recorded deviations."""

    COORD = "agent.node-builder@1.0.0"

    def test_manifest_surface(self):
        m = builtin.get_builtin_manifest(self.COORD)
        assert m is not None
        assert m.capability_ids == ["node.build", "dataset.fetch.author", "node.content.generate"]
        assert m.delegates_to == [
            "agent.node-builder",  # its own content mode
            "agent.dataflow-planner",  # its follow-up planning only
            "agent.researcher",  # dev/67-4: chainable verification, its mode only
            "agent.package-builder",  # dev/84 recommendation, then dev/89 authoring
            "agent.generated-content-evaluator",  # dev/86: advisory semantic check
            "agent.dataset-finder",  # dev/114 (DEC-072): source resolution for data-loading nodes
        ]
        assert m.delegate_scopes == {
            "agent.node-builder": ("node.content.generate",),
            "agent.dataflow-planner": ("execution.followup.plan",),
            "agent.researcher": ("research.verify",),
        }
        # dev/67-6 lifts the dev/48 canvas-only limitation: modify-existing
        # attaches to the node it modifies.
        assert [t.kind for t in m.compatible_targets] == ["canvas", "node"]
        assert [t.id for t in m.tools] == [
            "dataflow.read",
            "node.read",  # the content mode's own read, kept by the merge
            "node.create", "node.template.create",
            "node.runtime.read",  # dev/67-2: diagnose before regenerating
            "node.content.write",  # dev/67-6: modify-existing, reviewed
            "catalog.search",  # dev/114 (DEC-072): the only source of a real local path
            "models.search",  # the Model Catalog: a model this account can run
        ]
        assert m.provenance.trust == "built-in"

    def test_node_content_is_its_mode_with_the_autark_variant(self):
        # The prompt keys a run selects: the chat its instruction, a
        # node.content.generate run the content prompt, and an Autark
        # document under the reply schema the Autark prompt.
        spec = builtin.get_builtin_spec(self.COORD)
        assert spec.prompt_files() == {
            "system": "default_preamble.md",
            "instruction": "node_build_instruction.md",
            "node.content.generate": "new_content_prompt.md",
            "autk-grammar": "new_content_autk_prompt.md",
        }
        m = builtin.get_builtin_manifest(self.COORD)
        assert m.capability("node.content.generate").reads == (
            "dataflowContext", "nodeId", "subtask", "workflowGoal",
        )
        # Worked examples under its chat and under its mode alike.
        assert builtin.gets_worked_examples(self.COORD)
        assert builtin.gets_worked_examples(self.COORD, "node.content.generate")

    def test_review_policy_and_thirteen_byte_parity(self):
        # The composite declares review-before-apply; every migrated manifest
        # dict stays byte-identical (no delegatesTo key, report-only runtime) —
        # the dev/48 regression requirement, amended by dev/84 (D4): Connection
        # Builder is the ONE migrated manifest that gains delegatesTo (the
        # dev/16 §3.3 addendum); everything else about it is unchanged.
        nb = builtin.build_builtin_manifest(builtin.get_builtin_spec(self.COORD))
        assert nb["runtime"] == {"execution": "foreground", "reviewPolicy": "review-before-apply"}
        assert nb["delegatesTo"] == [
            {"id": "agent.node-builder", "capabilities": ["node.content.generate"]},
            {"id": "agent.dataflow-planner", "capabilities": ["execution.followup.plan"]},
            {"id": "agent.researcher", "capabilities": ["research.verify"]},
            "agent.package-builder",  # dev/84, dev/89
            "agent.generated-content-evaluator",
            "agent.dataset-finder",  # dev/114
        ]
        cb = builtin.build_builtin_manifest(
            builtin.get_builtin_spec("agent.connection-builder@1.0.0")
        )
        assert cb["delegatesTo"] == [  # dev/84 D4
            {"id": "agent.package-builder", "capabilities": ["package.recommend"]},
        ]
        assert cb["runtime"] == {"execution": "foreground", "reviewPolicy": "report-only"}
        composites = {"agent.node-builder", "agent.dataset-finder", "agent.dataflow-builder",
                      "agent.package-builder",  # dev/84, dev/89: asserted in its class
                      "agent.researcher",  # dev/90 — asserted in its class
                      "agent.connection-builder"}  # dev/84 D4 — asserted above
        for spec in builtin.BUILTIN_AGENTS:
            if spec.agent_id in composites:
                continue
            raw = builtin.build_builtin_manifest(spec)
            assert "delegatesTo" not in raw, spec.agent_id
            assert raw["runtime"] == {"execution": "foreground", "reviewPolicy": "report-only"}
            # requires stays empty for every migrated agent (dev/50 parity).
            assert all(t["requires"] == [] for t in raw["compatibleTargets"]), spec.agent_id

    def test_net_new_instruction_resolves(self):
        # Net-new asset (dev/15 §3.3: no migrated source) — reads through the
        # same PROMPT_SOURCE_DIR path as every migration.
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
        assert '"synthetic": true' in text
        assert "Never invent a filename" in text
        assert "ask the user for a path or URL instead of proposing" in text

    def test_instruction_sends_code_through_params_not_the_reply(self):
        # #245: the runtime now recovers a misplaced request, but the cheapest
        # fix is the model never misplacing it. Both the direct and the
        # delegated create paths must name params.content as the code channel.
        text = builtin.read_prompt_text(self.COORD, "instruction")
        assert "params.content" in text
        assert "code in your reply is not a node" in text


class TestCatalogReadGrants:
    """Which built-ins hold the catalog read tools that no other agent needs."""

    @staticmethod
    def _holders(tool_id: str) -> set[str]:
        return {spec.agent_id for spec in builtin.BUILTIN_AGENTS if tool_id in spec.tools}

    @staticmethod
    def _granted(agent_id: str) -> list[str]:
        from utk_curio.backend.app.agents.application import tools

        return tools.resolve_grants(builtin.get_builtin_manifest(f"{agent_id}@1.0.0").tools)

    def test_the_agents_that_write_node_code_search_the_model_catalog(self):
        # The Node Builder, in its chat and in its content mode.
        writers = {"agent.node-builder"}
        assert self._holders("models.search") == writers
        for agent_id in writers:
            assert "models.search" in self._granted(agent_id), agent_id

    def test_the_dataflow_builder_reads_the_worked_examples(self):
        assert self._holders("examples.read") == {"agent.dataflow-builder"}
        assert "examples.read" in self._granted("agent.dataflow-builder")


class TestDatasetFinderComposite:
    """The dev/50 roster entry — spec per dev/15 §3.4 + docs/06, minus
    recorded deviations."""

    COORD = "agent.dataset-finder@1.0.0"

    def test_manifest_surface(self):
        m = builtin.get_builtin_manifest(self.COORD)
        assert m is not None
        assert m.capability_ids == ["dataset.discover", "dataset.select"]
        assert m.delegates_to == [
            "agent.node-builder",
            "agent.dataflow-reader",
            "agent.dataflow-planner",
            "agent.researcher",
        ]
        assert m.delegate_scopes == {
            # Building the node, never its content mode.
            "agent.node-builder": ("node.build", "dataset.fetch.author"),
            "agent.dataflow-reader": ("workflow.suggest",),
            "agent.dataflow-planner": ("workflow.keyword.bind",),
            # Checking a fact, never composing notes.
            "agent.researcher": ("research.verify",),
        }
        by_kind = {t.kind: t for t in m.compatible_targets}
        assert set(by_kind) == {"node", "canvas"}
        # The docs/06 Data-Load gate: requires rides the node target only.
        assert by_kind["node"].requires == ["data-loading"]
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
        background = [
            spec.agent_id for spec in builtin.BUILTIN_AGENTS if spec.execution == "background"
        ]
        assert background == ["agent.dataflow-builder"]
        dfb = builtin.build_builtin_manifest(builtin.get_builtin_spec("agent.dataflow-builder@1.0.0"))
        assert dfb["runtime"] == {"execution": "background", "reviewPolicy": "review-before-apply"}
        for spec in builtin.BUILTIN_AGENTS:
            if spec.agent_id != "agent.dataflow-builder":
                assert builtin.build_builtin_manifest(spec)["runtime"]["execution"] == "foreground"
        # And the field parses through the manifest contract.
        assert builtin.get_builtin_manifest("agent.dataflow-builder@1.0.0") is not None


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
        assert requiring == ["agent.dataflow-builder", "agent.node-builder"]


class TestDataflowBuilderComposite:
    """The dev/52 roster entry — spec per dev/15 §3.4 minus recorded deviations."""

    COORD = "agent.dataflow-builder@1.0.0"

    def test_manifest_surface(self):
        m = builtin.get_builtin_manifest(self.COORD)
        assert m is not None
        assert m.capability_ids == ["dataflow.orchestrate"]
        assert m.delegates_to == [
            "agent.dataset-finder",
            "agent.node-builder",  # dev/73: chat-path content updates, its mode
            "agent.connection-builder",
            "agent.dataflow-planner", "agent.dataflow-reader",
            "agent.package-builder",  # dev/84 Recommend packages, dev/89 package-scale steps
            "agent.generated-content-evaluator",  # dev/86: advisory semantic check
            "agent.researcher",  # dev/95 (Follow-up D) reviewed notes, dev/67-4 verification
        ]
        assert [t.kind for t in m.compatible_targets] == ["canvas"]
        # dev/95: node.create is the reviewed lane the delegated Researcher's
        # note proposals mint on (grant-gated at the parent).
        assert [t.id for t in m.tools] == [
            "dataflow.read", "dataflow.plan.write", "node.runtime.read",
            "node.create",
            "examples.read",  # any worked example, beside the ones a run is given
        ]
        assert m.provenance.trust == "built-in"

    def test_requires_the_two_server_invoked_specialists(self):
        # dev/106: Solve/Validate hard-invoke node.content.generate, the Node
        # Builder's mode. dev/126: resolution hard-invokes dataset.discover,
        # and every plan-created node is given a Node Builder at the user's
        # Apply: server paths, so both are required. The other delegates stay
        # optional (no install fan-out).
        m = builtin.get_builtin_manifest(self.COORD)
        assert m.requires_agents == ["agent.dataset-finder", "agent.node-builder"]

    def test_net_new_instruction_resolves(self):
        text = builtin.read_prompt_text(self.COORD, "instruction")
        assert text and "dataflowPlan" in text
        # dev/59: removals exist but only on explicit request.
        assert "Never remove uninvited" in text
        assert builtin.read_prompt_text(self.COORD, "system")  # default preamble


class TestPackageRecommendation:
    """The dev/84 recommendation (spec per dev/16 / DEC-035), now the Package
    Builder's package.recommend mode: a delegated call, tool-less, over the
    packages the runtime passes. The reviewed install lane it used to hold is
    the Package Builder's chat."""

    COORD = "agent.package-builder@1.0.0"

    def test_manifest_surface(self):
        m = builtin.get_builtin_manifest(self.COORD)
        assert m is not None
        recommend = m.capability("package.recommend")
        assert recommend.instruction == "package.recommend"
        assert recommend.reads == ("mission", "targetContext", "existingPackages")
        assert m.prompts["package.recommend"].path == "prompts/package_recommendation_instruction.md"
        # The install lane and the catalog reads it grounds on, in its chat.
        for tool in ("packages.catalog", "packages.resolve", "package.install"):
            assert tool in [t.id for t in m.tools], tool
        assert m.provenance.trust == "built-in"

    def test_review_policy(self):
        raw = builtin.build_builtin_manifest(builtin.get_builtin_spec(self.COORD))
        assert raw["runtime"] == {"execution": "foreground", "reviewPolicy": "review-before-apply"}
        assert raw["category"] == "package"

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


class TestGeneratedContentEvaluator:
    """The DEC-055 authored built-in (dev/85 §4 contract; impl dev/86)."""

    COORD = "agent.generated-content-evaluator@1.0.0"

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
        raw = builtin.build_builtin_manifest(builtin.get_builtin_spec(self.COORD))
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


class TestPackageBuilder:
    """The dev/89 roster entry, the package specialist: its chat reuses first
    (a reviewed install of a package that already fits), then authors the
    package artifact as a reviewed draft; the dev/84 recommendation is its
    mode, listed first."""

    COORD = "agent.package-builder@1.0.0"

    def test_manifest_surface(self):
        m = builtin.get_builtin_manifest(self.COORD)
        assert m is not None
        assert m.capability_ids == [
            "package.recommend", "package.build", "package.extend", "node.kind.author",
        ]
        # Depth-1 leaf: it authors, its callers orchestrate.
        assert m.delegates_to == []
        assert [t.kind for t in m.compatible_targets] == ["node", "canvas"]
        assert [t.id for t in m.tools] == [
            "packages.catalog", "packages.resolve",
            "package.install",  # dev/84: the reviewed install lane, in its chat
            "dataflow.read", "package.draft.apply",
        ]
        assert m.provenance.trust == "built-in"

    def test_draft_tool_granted_now_that_the_contract_landed(self):
        from utk_curio.backend.app.agents.application import tools

        m = builtin.get_builtin_manifest(self.COORD)
        # dev/89 commit 8 registered the package.draft.apply ToolContract
        # (mutate — grantable for proposal purposes only, DEC-017).
        assert tools.resolve_grants(m.tools) == [
            "packages.catalog", "packages.resolve", "package.install",
            "dataflow.read", "package.draft.apply",
        ]

    def test_review_policy(self):
        raw = builtin.build_builtin_manifest(builtin.get_builtin_spec(self.COORD))
        assert raw["runtime"] == {"execution": "foreground", "reviewPolicy": "review-before-apply"}
        assert raw["category"] == "package"
        assert "delegatesTo" not in raw

    def test_delegation_wiring(self):
        # dev/89 topology: Node Builder's template fallback and Dataflow
        # Builder's package-scale plan steps both resolve the
        # package.create-or-extend intent to the Package Builder; reuse
        # (the recommendation) stays ahead of authoring in its capability
        # order, and both callers reach both.
        nb = builtin.get_builtin_manifest("agent.node-builder@1.0.0")
        dfb = builtin.get_builtin_manifest("agent.dataflow-builder@1.0.0")
        for parent in (nb, dfb):
            assert "agent.package-builder" in parent.delegates_to
            for capability in ("package.recommend", "package.build", "node.kind.author"):
                assert parent.delegates("agent.package-builder", capability), capability
        caps = builtin.get_builtin_manifest(self.COORD).capability_ids
        for authoring in ("package.build", "package.extend", "node.kind.author"):
            assert caps.index("package.recommend") < caps.index(authoring)

    def test_net_new_instruction_carries_the_contract(self):
        text = builtin.read_prompt_text(self.COORD, "instruction")
        assert text
        low = text.lower()
        # Reuse-first posture, the two modes, and the single draft tool.
        assert "reuse first" in low
        assert "CREATE" in text and "EXTEND" in text
        assert "package.draft.apply" in text
        # The never-rules: no self-install/publish, no read-only mutation,
        # no pretended builds (drafts degrade to findings, loudly).
        assert "never install" in low
        assert "never pretend" in low
        assert "read-only" in low
        # Backend generation stays out of scope (dev/89 Follow-up A).
        assert "backend sandbox" in low
        assert builtin.read_prompt_text(self.COORD, "system")  # default preamble

    def test_its_chat_proposes_installing_a_package_that_fits(self):
        # The dev/84 install rules, moved into the chat's reuse step: a
        # fitting package is proposed for install there, not only named.
        text = builtin.read_prompt_text(self.COORD, "instruction")
        reuse = text.split("## Reuse first", 1)[1].split("\n## ", 1)[0]
        low = reuse.lower()
        assert "proposed for install, not only named" in low
        assert "one package.install tool request per package" in low
        assert "dirname from the packages.catalog results" in low
        assert "is stated, not proposed" in low
        assert "builtin are always present" in low
        assert "packages.resolve" in reuse and "never force-resolve" in low
        assert "never present an install as done" in low

    def test_instruction_teaches_the_generic_authoring_contract(self):
        # dev/90 commit 2: ONE authoring contract for every custom look —
        # hook shape, registration, externals, safe rendering, appearance,
        # self-containment — with the gates named as the enforcement.
        text = builtin.read_prompt_text(self.COORD, "instruction")
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
        # dev/90 A5: dependency-minimal authoring is the default — write it
        # yourself before importing it through a supply chain.
        assert "ZERO JavaScript dependencies" in text
        assert "markdown-lite" in low
        # dev/90 A7: the delegate posture — a tool-less child replies with
        # ONE JSON build request, never a tool request it cannot execute.
        assert "DELEGATE" in text
        assert "delegated task from" in low
        assert "EXACTLY ONE JSON object" in text
        # dev/90 A8: the schema arrives as a runtime-supplied input — the
        # instruction points at it and bans the observed invented keys.
        assert "buildRequestContract" in text
        assert "behaviorKey" in text
        # No scenario content: looks come from CALLERS (dev/90 — the post-it
        # recipe lives with the Researcher, never with the generic specialist).
        assert "post-it" not in low
        assert "carr" in low and "no built-in looks" in low


class TestResearcher:
    """The dev/90 roster entry — the NOTES scenario owner: post-it recipe in
    its instruction, reuse-first, authoring delegated to the Package Builder,
    Dataflow Builder deliberately untouched (Follow-up D)."""

    COORD = "agent.researcher@1.0.0"

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
        "60ad0818d8842b693bcfe18bcee0a016c660de4f585038940693ed8dc3772f45"
    )

    def test_manifest_surface(self):
        m = builtin.get_builtin_manifest(self.COORD)
        assert m is not None
        # Composing notes in its chat; checking a fact is its mode.
        assert m.capability_ids == ["research.notes.compose", "research.verify"]
        # It delegates package authoring only: it checks facts itself.
        assert m.delegates_to == ["agent.package-builder"]
        assert m.delegate_scopes == {
            "agent.package-builder": ("package.build", "package.extend", "node.kind.author"),
        }
        assert [t.kind for t in m.compatible_targets] == ["node", "canvas"]
        # dataflow.read grounds reuse-first; web.search/web.fetch gather the
        # findings (dev/90 A1 — the recording's question→web→post-it loop);
        # node.create carries notes onto an installed template;
        # package.install is the dev/93 D4 middle rung — it enlists a package
        # the user already owns, without which a notes package outside this
        # project's lockfile was unreachable and authoring a near-duplicate
        # was the only move left; package.draft.apply authorizes the dev/90
        # delegate-draft MINT only — the draft content always comes from the
        # Package Builder delegate. node.read: the verification mode's own read.
        assert [t.id for t in m.tools] == [
            "dataflow.read", "node.read", "web.search", "web.fetch",
            "node.create", "package.install", "package.draft.apply",
        ]
        assert m.provenance.trust == "built-in"

    def test_review_policy(self):
        raw = builtin.build_builtin_manifest(builtin.get_builtin_spec(self.COORD))
        assert raw["runtime"] == {"execution": "foreground", "reviewPolicy": "review-before-apply"}
        assert raw["category"] == "node"

    def test_checking_a_fact_is_its_own_mode(self):
        # Verification (dev/67-4) is a mode of the Researcher: delegated
        # research.verify runs research_instruction.md, its chat its notes
        # prompt, and capability-keyed resolution finds both on one agent.
        m = builtin.get_builtin_manifest(self.COORD)
        assert m.capability("research.verify").instruction == "research.verify"
        assert m.capability("research.verify").reads == ("mission", "nodeContext")
        assert m.prompts["research.verify"].path == "prompts/research_instruction.md"
        assert m.prompts["instruction"].path == "prompts/researcher_notes_instruction.md"
        assert m.capability("research.notes.compose").instruction is None
        holders = {s.agent_id for s in builtin.BUILTIN_AGENTS if "research.verify" in s.capabilities}
        assert holders == {"agent.researcher"}
        # And the purpose line says it checks facts.
        spec = builtin.get_builtin_spec(self.COORD)
        assert "check a fact" in spec.purpose

    def test_dataflow_builder_prompt_stays_pinned_and_delegation_is_wired(self):
        # dev/90 Follow-up D DELIVERED by dev/95: the delegatesTo growth this
        # pin used to forbid is now the deliberate change (the dev/48 D4
        # precedent — a byte-pin updates WITH its memo, never incidentally).
        # The prompt sha updates only with the dev/95 prompt edit itself.
        import hashlib

        prompt = (builtin.PROMPT_SOURCE_DIR / "orchestration_instruction.md").read_bytes()
        assert hashlib.sha256(prompt).hexdigest() == self.DATAFLOW_BUILDER_PROMPT_SHA256
        dfb = builtin.get_builtin_manifest("agent.dataflow-builder@1.0.0")
        assert "agent.researcher" in dfb.delegates_to  # dev/95 Follow-up D

    def test_net_new_instruction_carries_the_recipe(self):
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


class TestConnectionBuilderCanBindToAnEdge:
    """Connection Builder attaches to a node OR to a connection.

    It declares a ``connectionSide`` read, which only means something for an
    agent bound to one edge: it tells the agent which end it is reasoning from,
    and its prompt is written to be "informed if the nodes you are suggesting
    will be connected into the input or output of the node".

    The backend has always accepted ``connection`` targets and the palette has
    always advertised the kind, but no drop gesture produced one and no agent
    declared the target, so the read had no producer and the advertised gesture
    silently attached to the canvas instead.
    """

    def test_it_declares_both_targets(self):
        m = builtin.get_builtin_manifest("agent.connection-builder@1.0.0")
        assert {t.kind for t in m.compatible_targets} == {"node", "connection"}

    def test_it_still_declares_the_side_it_reads(self):
        m = builtin.get_builtin_manifest("agent.connection-builder@1.0.0")
        assert "connectionSide" in m.inputs_reads
