"""The Agent Catalog's details window says what an agent does in the docs'
three words (docs/AGENT-CATALOG.md, "The agents"): what you ask it in chat,
the tools it uses there, and its modes, with who asks for each.

Every catalog card carries them, computed from the shipped manifests:

- ``tools``: the agent's grants, each by its tool contract's plain-word label,
  what it reads before what it proposes;
- ``modes``: its labeled capabilities, one entry per label, each with its
  capability ids, the prompt it runs, and who asks for it: the agent itself
  through a ``delegatesTo`` entry naming it, then every other built-in whose
  ``delegatesTo`` covers it, in roster order, then Solve;
- ``promptRuns``: when each prompt file runs.

The tables below are the docs' words, pinned as they are, not recomputed from
``delegatesTo``. New names are read inside each test, so this module imports
on a checkout without them and each test fails on its own.
"""

from __future__ import annotations

from utk_curio.backend.app.agents.application import catalog as agents_catalog
from utk_curio.backend.app.agents.application import tools as agents_tools
from utk_curio.backend.app.agents.domain import builtin
from utk_curio.backend.app.agents.domain.manifest import parse_agent_manifest
from utk_curio.backend.tests._support.agent_routes import _auth


#: Each card's tools, as its details window lists them: what it reads, then
#: what it changes and what it proposes for review.
_TOOLS = {
    "agent.curio.researcher": [
        "Read the dataflow", "Read a node", "Read a node's last run", "Search the web",
        "Read a web page", "Add a node", "Propose a package install",
        "Propose a package draft",
    ],
    "agent.curio.node-builder": [
        "Read the dataflow", "Read a node", "Read a node's last run", "Read a node's history",
        "Search the Data Catalog", "Search the Model Catalog", "Search the Node Catalog",
        "Check a package's dependencies and permissions", "Add a node",
        "Write a node's content", "Change a node's settings", "Propose a package install",
        "Propose a package draft",
    ],
    "agent.curio.dataflow-builder": [
        "Read the dataflow", "Read a node's last run", "Read a node's history", "Read worked examples",
        "Search the Scenario Catalog", "Write a plan", "Add a node", "Change a node's settings",
        "Propose a package draft",
    ],
    "agent.curio.dataset-finder": [
        "Search the Data Catalog", "List the data portals", "Search the data portals",
        "Read the dataflow", "Propose a download", "Propose adding a dataset",
    ],
}

#: Each card's modes as the docs' four-agent table words them: the label, its
#: capability ids, the prompt the mode runs, and who asks for it.
_MODES = {
    "agent.curio.researcher": [
        ("Notes from search results", ["research.notes.compose"],
         "prompts/researcher_notes_instruction.md", ["Dataflow Builder"]),
        ("Check a fact", ["research.verify"],
         "prompts/research_instruction.md",
         ["Node Builder", "Dataset Finder", "Dataflow Builder"]),
    ],
    "agent.curio.node-builder": [
        ("Write a node's content", ["node.content.generate"],
         "prompts/new_content_prompt.md", ["Node Builder", "Dataflow Builder", "Solve"]),
        ("Recommend packages", ["package.recommend"],
         "prompts/package_recommendation_instruction.md", ["Dataflow Builder"]),
        ("Write a package", ["package.build", "package.extend", "node.kind.author"],
         "prompts/package_build_instruction.md",
         ["Node Builder", "Researcher", "Dataflow Builder"]),
    ],
    # Nothing asks the Dataflow Builder for anything: it only chats.
    "agent.curio.dataflow-builder": [],
    # Its own instruction, asked for by two agents and by Solve, for a
    # data-loading node whose source is not settled.
    "agent.curio.dataset-finder": [
        ("Find datasets", ["dataset.discover"],
         "prompts/discovery_instruction.md", ["Node Builder", "Dataflow Builder", "Solve"]),
    ],
}

#: When each card's prompt files run: the preamble on every call, the
#: instruction for a message you type, and each mode's prompt when it is asked
#: for. The Dataset Finder's datasets mode runs its own instruction.
_PROMPT_RUNS = {
    "agent.curio.researcher": [
        ("prompts/default_preamble.md", ["every call"]),
        ("prompts/researcher_instruction.md", ["a message you type"]),
        ("prompts/researcher_notes_instruction.md", ["Notes from search results"]),
        ("prompts/research_instruction.md", ["Check a fact"]),
    ],
    "agent.curio.node-builder": [
        ("prompts/default_preamble.md", ["every call"]),
        ("prompts/node_build_instruction.md", ["a message you type"]),
        ("prompts/new_content_prompt.md", ["Write a node's content"]),
        ("prompts/package_recommendation_instruction.md", ["Recommend packages"]),
        ("prompts/package_build_instruction.md", ["Write a package"]),
        ("prompts/new_content_autk_prompt.md", ["Write a node's content, for an Autark node"]),
    ],
    "agent.curio.dataflow-builder": [
        ("prompts/default_preamble.md", ["every call"]),
        ("prompts/orchestration_instruction.md", ["a message you type"]),
    ],
    "agent.curio.dataset-finder": [
        ("prompts/default_preamble.md", ["every call"]),
        ("prompts/discovery_instruction.md", ["a message you type", "Find datasets"]),
    ],
}

#: A helper's modes, in the docs' helpers table words. Only other agents ask
#: for them, and nothing asks for the keywords to be extracted.
_PLANNER_MODES = [
    ("Plan a dataflow's tasks", ["workflow.plan.create"],
     "prompts/new_subtasks_prompt.md", []),
    ("Plan a follow-up from a node's run", ["execution.followup.plan"],
     "prompts/new_subtask_from_exec_prompt.md", ["Node Builder"]),
    ("Refresh a dataflow's tasks", ["workflow.plan.refresh"],
     "prompts/task_refresh_prompt.md", []),
    ("Check a plan's coherence", ["workflow.coherence.validate"],
     "prompts/evaluate_coherence_subtasks_prompt.md", []),
    ("Bind the keywords of a description", ["workflow.keyword.bind"],
     "prompts/keywords_binding_prompt.md", ["Dataset Finder"]),
    ("Extract the keywords of a description", ["workflow.keywords.extract"],
     "prompts/syntax_analysis_prompt.md", []),
]

#: An agent Curio does not ship: one capability its chat answers, one mode it
#: asks of itself, a tool Curio defines and one it does not.
_IMPORTED = {
    "id": "agent.test.my-explainer",
    "name": "My Explainer",
    "category": "node",
    "version": "1.0.0",
    "capabilities": [
        {"id": "node.explain", "contractVersion": "1"},
        {"id": "node.output.interpret", "contractVersion": "1", "instruction": "interpret"},
    ],
    "prompts": {
        "system": {"path": "prompts/default_preamble.md"},
        "instruction": {"path": "prompts/explain_node.md"},
        "interpret": {"path": "prompts/interpret_output.md"},
    },
    "delegatesTo": [{"id": "agent.test.my-explainer", "capabilities": ["node.output.interpret"]}],
    "tools": [{"id": "node.create"}, {"id": "dataflow.read"}, {"id": "ghost.tool"}],
    "compatibleTargets": [{"kind": "node", "requires": []}],
    "provenance": {"publisher": "someone", "trust": "imported"},
}


def _cards(client, token) -> dict[str, dict]:
    body = client.get("/api/agents/catalog", headers=_auth(token)).get_json()
    return {card["id"]: card for card in body["items"]}


def _rows(modes: list[dict]) -> list[tuple]:
    return [(m["label"], m["capabilities"], m["prompt"], m["askedBy"]) for m in modes]


class TestTools:
    def test_each_card_names_its_tools_in_plain_words(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        cards = _cards(client, token)
        assert {agent: [t["label"] for t in cards[agent]["tools"]] for agent in _TOOLS} == _TOOLS

    def test_a_tool_is_listed_by_its_contract_id_too(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        tools = _cards(client, token)["agent.curio.dataflow-builder"]["tools"]
        assert [t["id"] for t in tools] == [
            "dataflow.read", "node.runtime.read", "node.history.read", "examples.read", "scenarios.search",
            "dataflow.plan.write", "node.create", "node.settings.write", "package.draft.apply",
        ]

    def test_every_tool_contract_has_one_label_and_an_install_says_it_is_a_proposal(self):
        from utk_curio.backend.app.agents.application import editors

        labels = {tool_id: contract.label for tool_id, contract in agents_tools.REGISTRY.items()}
        assert [tool_id for tool_id, label in labels.items() if not label] == []
        assert len(set(labels.values())) == len(labels), labels
        # An install is a proposal the person applies, and its label says so;
        # any other change lands at once, and nothing that only reads, or
        # lands, claims to propose.
        wrong = {
            tool_id: label for tool_id, label in labels.items()
            if label.startswith("Propose ") != (tool_id in editors.ACCOUNT_INSTALL_TOOLS)
        }
        assert wrong == {}
        assert {tool_id for tool_id in editors.ACCOUNT_INSTALL_TOOLS} <= set(labels)
        assert all(agents_tools.REGISTRY[tool_id].effect == "mutate" for tool_id in editors.ACCOUNT_INSTALL_TOOLS)


class TestModes:
    def test_each_card_lists_its_modes_and_who_asks(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        cards = _cards(client, token)
        assert {agent: _rows(cards[agent]["modes"]) for agent in _MODES} == _MODES

    def test_a_helper_lists_its_modes_and_who_asks(self):
        planner = builtin.get_builtin_manifest("agent.curio.dataflow-planner@1")
        assert _rows(agents_catalog.agent_modes(planner)) == _PLANNER_MODES

    def test_the_evaluator_is_asked_to_check_generated_content(self):
        evaluator = builtin.get_builtin_manifest("agent.curio.generated-content-evaluator@1")
        assert _rows(agents_catalog.agent_modes(evaluator)) == [
            ("Check generated node content against its goal", ["content.quality.evaluate"],
             "prompts/evaluate_generated_content_prompt.md", ["Node Builder", "Dataflow Builder"]),
        ]

    def test_solve_asks_for_what_solve_and_validate_resolve(self, monkeypatch):
        """Solve's entry comes from the one list Solve and validate build their
        delegations from, not from a second list in the catalog."""
        from utk_curio.backend.app.agents.application.solve import session
        from utk_curio.backend.app.agents.domain import content

        monkeypatch.setattr(session, "_is_data_loading_node", lambda node: True)
        assert session._delegate_capabilities([{}]) == list(content.SOLVE_CAPABILITIES)
        monkeypatch.setattr(session, "_is_data_loading_node", lambda node: False)
        assert session._delegate_capabilities([{}]) == list(content.SOLVE_CAPABILITIES[:1])

        asked_by_solve = {
            capability
            for manifest in builtin.list_builtin_manifests()
            for mode in agents_catalog.agent_modes(manifest)
            if "Solve" in mode["askedBy"]
            for capability in mode["capabilities"]
        }
        assert asked_by_solve == set(content.SOLVE_CAPABILITIES)

    def test_every_builtin_mode_has_a_label(self):
        unlabeled = [
            (m.agent_id, capability.id)
            for m in builtin.list_builtin_manifests()
            for capability in m.capabilities
            if capability.instruction and not capability.label
        ]
        assert unlabeled == []


class TestPromptRuns:
    def test_each_prompt_says_when_it_runs(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        cards = _cards(client, token)
        got = {
            agent: [(row["path"], row["runs"]) for row in cards[agent]["promptRuns"]]
            for agent in _PROMPT_RUNS
        }
        assert got == _PROMPT_RUNS

    def test_a_helper_runs_no_prompt_for_a_message_you_type(self):
        """A helper has no chat: nothing you type reaches it."""
        planner = builtin.get_builtin_manifest("agent.curio.dataflow-planner@1")
        runs = agents_catalog.prompt_runs(planner, agents_catalog.agent_modes(planner))
        assert [row for row in runs if "a message you type" in row["runs"]] == []
        assert ("prompts/new_subtasks_prompt.md", ["Plan a dataflow's tasks"]) in [
            (row["path"], row["runs"]) for row in runs
        ]


class TestDefinitionsCurioDoesNotShip:
    def test_each_capability_shows_by_id_and_each_granted_tool_by_its_label(self):
        manifest = parse_agent_manifest(_IMPORTED)
        # A tool Curio does not define is never granted, so it is not listed.
        assert agents_catalog.agent_tools(manifest) == [
            {"id": "dataflow.read", "label": "Read the dataflow"},
            {"id": "node.create", "label": "Add a node"},
        ]
        modes = agents_catalog.agent_modes(manifest)
        assert _rows(modes) == [
            ("node.explain", ["node.explain"], "prompts/explain_node.md", []),
            ("node.output.interpret", ["node.output.interpret"], "prompts/interpret_output.md",
             ["My Explainer"]),
        ]
        assert [(row["path"], row["runs"]) for row in agents_catalog.prompt_runs(manifest, modes)] == [
            ("prompts/default_preamble.md", ["every call"]),
            ("prompts/explain_node.md", ["a message you type", "node.explain"]),
            ("prompts/interpret_output.md", ["node.output.interpret"]),
        ]

    def test_a_definition_at_a_builtins_coordinate_gets_none_of_its_labels(self):
        """An owned import may take a built-in's coordinate: the roster's words
        describe the built-in, not it."""
        manifest = parse_agent_manifest({
            **_IMPORTED,
            "id": "agent.curio.researcher",
            "capabilities": [{"id": "research.verify", "contractVersion": "1"}],
            "delegatesTo": [],
        })
        assert [m["label"] for m in agents_catalog.agent_modes(manifest)] == ["research.verify"]

    def test_an_imported_card_carries_the_three_words(self, client, user_and_token, tmp_curio):
        from utk_curio.backend.tests._support.agent_routes import _write_def

        user, token = user_and_token
        coord = _write_def(user)
        client.post("/api/agents/imports", json={"coord": coord}, headers=_auth(token))
        card = client.get("/api/agents/imports", headers=_auth(token)).get_json()["agents"][0]
        assert card["tools"] == []
        assert _rows(card["modes"]) == [("node.explain", ["node.explain"], None, [])]
        assert card["promptRuns"] == []
