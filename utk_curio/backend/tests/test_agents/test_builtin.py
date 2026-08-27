"""Tests for the built-in agent roster (the 13 prompt-agent migrations + the
P5 composites, memo dev/48)."""

from __future__ import annotations

from utk_curio.backend.app.agents import builtin
from utk_curio.backend.app.agents.manifest import AgentManifest


# The dev/06 canonical map: agent id -> its prompt file and capabilities.
_EXPECTED = {
    "agent.chat-agent": ("chat_prompt.txt", ["conversation.respond", "attachment.refine"]),
    "agent.debug-agent": ("debug_prompt.txt", ["code.debug.diagnose", "code.fix.propose"]),
    "agent.dataflow-explainer": ("explanation_prompt.txt", ["dataflow.explain"]),
    "agent.node-explainer": ("single_box_explanation_prompt.txt", ["node.explain", "node.output.interpret"]),
    "agent.node-content-builder": ("new_content_prompt.txt", ["node.content.generate"]),
    "agent.execution-subtask-planner": ("new_subtask_from_exec_prompt.txt", ["execution.followup.plan"]),
    "agent.dataflow-task-planner": ("new_subtasks_prompt.txt", ["workflow.plan.create"]),
    "agent.connection-builder": ("new_connection_prompt.txt", ["connection.propose"]),
    "agent.workflow-suggester": ("workflow_suggestions_prompt.txt", ["workflow.suggest"]),
    "agent.plan-coherence-validator": ("evaluate_coherence_subtasks_prompt.txt", ["workflow.coherence.validate"]),
    "agent.syntax-analysis-agent": ("syntax_analysis_prompt.txt", ["code.syntax.analyze"]),
    "agent.task-refresh-agent": ("task_refresh_prompt.txt", ["workflow.plan.refresh"]),
    "agent.keyword-binding-agent": ("keywords_binding_prompt.txt", ["workflow.keyword.bind"]),
}


class TestRoster:
    def test_sixteen_agents(self):
        # 13 migrations + the three composites (dev/48, dev/50, dev/52)
        # + the node researcher (dev/67-4) + package recommendation (dev/84)
        # + the authored evaluator (DEC-055, dev/85/86)
        # + the package builder (dev/89) + the notes researcher (dev/90).
        assert len(builtin.BUILTIN_AGENTS) == 21

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
        # The composites are the only non-migration entries (dev/48, dev/50).
        extras = {s.agent_id for s in builtin.BUILTIN_AGENTS} - set(_EXPECTED)
        assert extras == {"agent.node-builder", "agent.dataset-finder",
                          "agent.dataflow-builder", "agent.node-researcher",
                          "agent.package-recommendation",
                          "agent.generated-content-evaluator",
                          "agent.package-builder",
                          "agent.researcher"}

    def test_every_prompt_file_exists(self):
        for spec in builtin.BUILTIN_AGENTS:
            assert (builtin.PROMPT_SOURCE_DIR / spec.prompt_file).is_file(), spec.prompt_file


class TestManifests:
    def test_all_validate(self):
        manifests = builtin.list_builtin_manifests()
        assert len(manifests) == 21
        assert all(isinstance(m, AgentManifest) for m in manifests)

    def test_coords_and_capabilities(self):
        by_id = {m.agent_id: m for m in builtin.list_builtin_manifests()}
        for agent_id, (_, caps) in _EXPECTED.items():
            m = by_id[agent_id]
            assert m.dir_name == f"{agent_id}@1.0.0"
            assert m.capability_ids == caps
            assert m.provenance.trust == "built-in"

    def test_get_by_coord(self):
        m = builtin.get_builtin_manifest("agent.node-explainer@1.0.0")
        assert m is not None and m.agent_id == "agent.node-explainer"
        assert builtin.get_builtin_manifest("agent.node-explainer@9.9.9") is None
        assert builtin.get_builtin_manifest("curio.builtin@1") is None


class TestPreambleAndInputs:
    """The dev/05 roster's System-file column + grounded inputs (dev/06 parity):
    every built-in manifest carries its preamble asset and non-empty reads."""

    def test_every_builtin_declares_system_asset_and_reads(self):
        from utk_curio.backend.app.agents import builtin

        for m in builtin.list_builtin_manifests():
            assert "system" in m.prompts, m.agent_id
            assert m.prompts["system"].path.startswith("prompts/"), m.agent_id
            assert m.inputs_reads, f"{m.agent_id} has no inputs.reads"

    def test_syntax_agent_uses_its_own_preamble(self):
        from utk_curio.backend.app.agents import builtin

        m = builtin.get_builtin_manifest("agent.syntax-analysis-agent@1.0.0")
        assert m.prompts["system"].path == "prompts/syntax_analysis_preamble.txt"
        others = builtin.get_builtin_manifest("agent.chat-agent@1.0.0")
        assert others.prompts["system"].path == "prompts/default_preamble.txt"

    def test_preamble_text_readable_for_all_builtins(self):
        from utk_curio.backend.app.agents import builtin

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
        (``default_preamble.txt``); it is the instruction that identifies.
        """
        from utk_curio.backend.app.agents import builtin

        by_text: dict[str, list[str]] = {}
        for spec in builtin.BUILTIN_AGENTS:
            text = builtin.read_instruction_text(f"{spec.agent_id}@1.0.0")
            assert text, spec.agent_id
            by_text.setdefault(text.strip(), []).append(spec.agent_id)

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
        from utk_curio.backend.app.agents import builtin

        texts = {
            spec.agent_id: builtin.read_instruction_text(f"{spec.agent_id}@1.0.0").strip()
            for spec in builtin.BUILTIN_AGENTS
        }
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
        assert m.capability_ids == ["node.build", "dataset.fetch.author"]
        assert m.delegates_to == [
            "agent.node-content-builder",
            "agent.execution-subtask-planner",
            "agent.node-researcher",  # dev/67-4: chainable verification
            "agent.package-recommendation",  # dev/84: required-package identify
            "agent.package-builder",  # dev/89: no-template-fits → authoring
            "agent.generated-content-evaluator",  # dev/86: advisory semantic check
        ]
        # dev/67-6 lifts the dev/48 canvas-only limitation: modify-existing
        # attaches to the node it modifies.
        assert [t.kind for t in m.compatible_targets] == ["canvas", "node"]
        assert [t.id for t in m.tools] == [
            "dataflow.read", "node.create", "node.template.create",
            "node.runtime.read",  # dev/67-2: diagnose before regenerating
            "node.content.write",  # dev/67-6: modify-existing, reviewed
        ]
        assert m.provenance.trust == "built-in"

    def test_review_policy_and_thirteen_byte_parity(self):
        # The composite declares review-before-apply; every migrated manifest
        # dict stays byte-identical (no delegatesTo key, report-only runtime) —
        # the dev/48 regression requirement, amended by dev/84 (D4): Connection
        # Builder is the ONE migrated manifest that gains delegatesTo (the
        # dev/16 §3.3 addendum); everything else about it is unchanged.
        nb = builtin.build_builtin_manifest(builtin.get_builtin_spec(self.COORD))
        assert nb["runtime"] == {"execution": "foreground", "reviewPolicy": "review-before-apply"}
        assert nb["delegatesTo"] == [
            "agent.node-content-builder", "agent.execution-subtask-planner",
            "agent.node-researcher", "agent.package-recommendation",
            "agent.package-builder",  # dev/89
            "agent.generated-content-evaluator",
        ]
        cb = builtin.build_builtin_manifest(
            builtin.get_builtin_spec("agent.connection-builder@1.0.0")
        )
        assert cb["delegatesTo"] == ["agent.package-recommendation"]  # dev/84 D4
        assert cb["runtime"] == {"execution": "foreground", "reviewPolicy": "report-only"}
        composites = {"agent.node-builder", "agent.dataset-finder", "agent.dataflow-builder",
                      "agent.package-recommendation",  # dev/84
                      "agent.package-builder",  # dev/89 — asserted in its class
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
            "agent.workflow-suggester",
            "agent.keyword-binding-agent",
            "agent.node-researcher",
        ]
        by_kind = {t.kind: t for t in m.compatible_targets}
        assert set(by_kind) == {"node", "canvas"}
        # The docs/06 Data-Load gate: requires rides the node target only.
        assert by_kind["node"].requires == ["data-loading"]
        assert by_kind["canvas"].requires == []
        assert [t.id for t in m.tools] == ["catalog.search", "dataset.install", "dataflow.read"]
        assert m.provenance.trust == "built-in"

    def test_net_new_instruction_resolves(self):
        text = builtin.read_prompt_text(self.COORD, "instruction")
        assert text and "two lanes" in text.lower()
        assert "never author" in text.lower() or "never authors" in text.lower()
        assert builtin.read_prompt_text(self.COORD, "system")  # default preamble


class TestRequiresAgentsRoster:
    """dev/106 roster-wide invariant: hard dependencies are declared delegates
    and resolve to a roster agent."""

    def test_requires_subset_of_delegates_and_visible(self):
        ids = {m.agent_id for m in builtin.list_builtin_manifests()}
        for m in builtin.list_builtin_manifests():
            for r in m.requires_agents:
                assert r in m.delegates_to, (m.agent_id, r)
                assert r in ids, (m.agent_id, r)

    def test_only_the_dataflow_builder_requires(self):
        requiring = [m.agent_id for m in builtin.list_builtin_manifests() if m.requires_agents]
        assert requiring == ["agent.dataflow-builder"]


class TestDataflowBuilderComposite:
    """The dev/52 roster entry — spec per dev/15 §3.4 minus recorded deviations."""

    COORD = "agent.dataflow-builder@1.0.0"

    def test_manifest_surface(self):
        m = builtin.get_builtin_manifest(self.COORD)
        assert m is not None
        assert m.capability_ids == ["dataflow.orchestrate"]
        assert m.delegates_to == [
            "agent.dataset-finder", "agent.node-builder",
            "agent.node-content-builder",  # dev/73: chat-path content updates
            "agent.connection-builder",
            "agent.dataflow-task-planner", "agent.execution-subtask-planner",
            "agent.task-refresh-agent", "agent.workflow-suggester",
            "agent.plan-coherence-validator", "agent.dataflow-explainer",
            "agent.node-researcher",  # dev/67-4: chainable verification
            "agent.package-recommendation",  # dev/84: Recommend packages step
            "agent.package-builder",  # dev/89: package-scale plan steps
            "agent.generated-content-evaluator",  # dev/86: advisory semantic check
            "agent.researcher",  # dev/95 (Follow-up D): research → reviewed notes
        ]
        assert [t.kind for t in m.compatible_targets] == ["canvas"]
        # dev/95: node.create is the reviewed lane the delegated Researcher's
        # note proposals mint on (grant-gated at the parent).
        assert [t.id for t in m.tools] == [
            "dataflow.read", "dataflow.plan.write", "node.runtime.read",
            "node.create",
        ]
        assert m.provenance.trust == "built-in"

    def test_requires_only_the_solve_specialist(self):
        # dev/106: Solve/Validate hard-invoke node.content.generate; every
        # other delegate stays optional (no 15-agent install fan-out).
        m = builtin.get_builtin_manifest(self.COORD)
        assert m.requires_agents == ["agent.node-content-builder"]

    def test_net_new_instruction_resolves(self):
        text = builtin.read_prompt_text(self.COORD, "instruction")
        assert text and "dataflowPlan" in text
        # dev/59: removals exist but only on explicit request.
        assert "Never remove uninvited" in text
        assert builtin.read_prompt_text(self.COORD, "system")  # default preamble


class TestPackageRecommendation:
    """The dev/84 roster entry — spec per dev/16 / DEC-035 minus the memo's
    recorded deviations (roster-generated manifest, tool-served installed
    flags)."""

    COORD = "agent.package-recommendation@1.0.0"

    def test_manifest_surface(self):
        m = builtin.get_builtin_manifest(self.COORD)
        assert m is not None
        assert m.capability_ids == ["package.recommend", "package.identify"]
        # dev/16 §3.3: import extraction is delegated, never guessed.
        assert m.delegates_to == ["agent.syntax-analysis-agent"]
        assert [t.kind for t in m.compatible_targets] == ["node", "canvas"]
        assert [t.id for t in m.tools] == [
            "packages.catalog", "packages.resolve", "package.install",
            "dataflow.read",
        ]
        assert m.provenance.trust == "built-in"

    def test_review_policy(self):
        raw = builtin.build_builtin_manifest(builtin.get_builtin_spec(self.COORD))
        assert raw["runtime"] == {"execution": "foreground", "reviewPolicy": "review-before-apply"}
        assert raw["category"] == "package"

    def test_net_new_instruction_resolves(self):
        text = builtin.read_prompt_text(self.COORD, "instruction")
        assert text and "packages.catalog" in text
        assert "never author" in text.lower() or "never authors" in text.lower()
        assert "package.install" in text
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
    """The dev/89 roster entry — the package AUTHORING specialist, deliberately
    separate from Package Recommendation (dev/89 §3): recommendation stays
    catalog-grounded discovery + reviewed install; authoring owns the package
    artifact as a reviewed draft."""

    COORD = "agent.package-builder@1.0.0"

    def test_manifest_surface(self):
        m = builtin.get_builtin_manifest(self.COORD)
        assert m is not None
        assert m.capability_ids == ["package.build", "package.extend", "node.kind.author"]
        # Depth-1 leaf: it authors, its callers orchestrate.
        assert m.delegates_to == []
        assert [t.kind for t in m.compatible_targets] == ["node", "canvas"]
        assert [t.id for t in m.tools] == [
            "packages.catalog", "packages.resolve", "dataflow.read",
            "package.draft.apply",
        ]
        assert m.provenance.trust == "built-in"

    def test_draft_tool_granted_now_that_the_contract_landed(self):
        from utk_curio.backend.app.agents import tools

        m = builtin.get_builtin_manifest(self.COORD)
        # dev/89 commit 8 registered the package.draft.apply ToolContract
        # (mutate — grantable for proposal purposes only, DEC-017).
        assert tools.resolve_grants(m.tools) == [
            "packages.catalog", "packages.resolve", "dataflow.read",
            "package.draft.apply",
        ]

    def test_review_policy(self):
        raw = builtin.build_builtin_manifest(builtin.get_builtin_spec(self.COORD))
        assert raw["runtime"] == {"execution": "foreground", "reviewPolicy": "review-before-apply"}
        assert raw["category"] == "package"
        assert "delegatesTo" not in raw

    def test_delegation_wiring(self):
        # dev/89 topology: Node Builder's template fallback and Dataflow
        # Builder's package-scale plan steps both resolve the
        # package.create-or-extend intent to the Package Builder; reuse/
        # catalog discovery (Package Recommendation) stays ahead of authoring
        # in both callers' preference order.
        nb = builtin.get_builtin_manifest("agent.node-builder@1.0.0")
        dfb = builtin.get_builtin_manifest("agent.dataflow-builder@1.0.0")
        for delegates in (nb.delegates_to, dfb.delegates_to):
            assert "agent.package-builder" in delegates
            assert (delegates.index("agent.package-recommendation")
                    < delegates.index("agent.package-builder"))

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
        "6000ae6c847e62095e94530a5e26a713f44769472b43ead998eb62a096a89a09"  # dev/95 commit 3: the deliberate Follow-up D prompt edit
    )

    def test_manifest_surface(self):
        m = builtin.get_builtin_manifest(self.COORD)
        assert m is not None
        assert m.capability_ids == ["research.notes.compose"]
        # Authoring first, optional verification second (preference order).
        assert m.delegates_to == ["agent.package-builder", "agent.node-researcher"]
        assert [t.kind for t in m.compatible_targets] == ["node", "canvas"]
        # dataflow.read grounds reuse-first; web.search/web.fetch gather the
        # findings (dev/90 A1 — the recording's question→web→post-it loop);
        # node.create carries notes onto an installed template;
        # package.install is the dev/93 D4 middle rung — it enlists a package
        # the user already owns, without which a notes package outside this
        # project's lockfile was unreachable and authoring a near-duplicate
        # was the only move left; package.draft.apply authorizes the dev/90
        # delegate-draft MINT only — the draft content always comes from the
        # Package Builder delegate.
        assert [t.id for t in m.tools] == [
            "dataflow.read", "web.search", "web.fetch",
            "node.create", "package.install", "package.draft.apply",
        ]
        assert m.provenance.trust == "built-in"

    def test_review_policy(self):
        raw = builtin.build_builtin_manifest(builtin.get_builtin_spec(self.COORD))
        assert raw["runtime"] == {"execution": "foreground", "reviewPolicy": "review-before-apply"}
        assert raw["category"] == "node"

    def test_disjoint_from_node_researcher(self):
        # "Researcher" (notes) vs "Node Researcher" (verification): distinct
        # ids, names, and capability sets — delegation resolution is
        # capability-keyed, so the split must stay structural.
        researcher = builtin.get_builtin_manifest(self.COORD)
        verifier = builtin.get_builtin_manifest("agent.node-researcher@1.0.0")
        assert researcher.agent_id != verifier.agent_id
        assert researcher.name != verifier.name
        assert not set(researcher.capability_ids) & set(verifier.capability_ids)
        # And the purpose line disambiguates at a glance.
        spec = builtin.get_builtin_spec(self.COORD)
        assert "Node Researcher" in spec.purpose

    def test_dataflow_builder_prompt_stays_pinned_and_delegation_is_wired(self):
        # dev/90 Follow-up D DELIVERED by dev/95: the delegatesTo growth this
        # pin used to forbid is now the deliberate change (the dev/48 D4
        # precedent — a byte-pin updates WITH its memo, never incidentally).
        # The prompt sha updates only with the dev/95 prompt edit itself.
        import hashlib

        prompt = (builtin.PROMPT_SOURCE_DIR / "orchestration_instruction.txt").read_bytes()
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
        # Disambiguation from the verification agent.
        assert "not the node researcher" in low
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
        from utk_curio.backend.app.agents import tools as tools_mod

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
