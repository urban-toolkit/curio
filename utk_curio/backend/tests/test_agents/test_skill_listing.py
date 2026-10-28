"""Which skills each agent's runs hold: the listing, every skill reaches an agent, and no run loses a procedure.

Every agent Curio ships, and one agent a user imports, on one dataflow,
``docs/examples/26-several-inputs.json`` (Data Loading, Python, Data
Transformation, JavaScript, Vega-Lite and Autark nodes and a Data Pool):

- each chat's catalog, the skills it loads with ``skill.read`` when it needs
  one, the skills it is handed on the canvas, the ones its instruction names,
  and the skills it is handed when attached to a node of each kind the
  dataflow holds;
- each capability's delegated run, a mode's or another's, and the skills it is
  handed: a node's content and a check of it once per node kind, with the
  inputs Solve hands it, every other with only an intent.

The listing is recorded on the test (``record_property``), so the CI report
shows it. Beside it, every skill Curio ships reaches some agent's run: the
default preamble holds the core three, and every other is in a chat's catalog
or handed to a run. Each skill names what it serves by names the code knows:
behaviors the shipped templates declare and features ``skill_runs`` reads.

The procedures the agents' prompts shared are skills of their own: their text
left the prompts that held it, and every run of each of those prompts is
handed the skill in its place.

New names are read inside each test, so this module imports on a checkout
without them and each test fails on its own.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
DATAFLOW = REPO_ROOT / "docs" / "examples" / "26-several-inputs.json"
KEY = "4242"
PID = "p-listing"
TASK = "Chart the mean PM2.5 of each ZIP code beside the map of the stations."
CORE = ["compatibility", "node-control", "nodes"]
FEATURES = [
    "node-functions", "catalogs", "widgets", "selection-chips", "autark", "vega-lite-starter",
    "autark-starter", "vega-lite-maps", "interaction-edges", "map-edits", "scenarios", "dashboards",
    "provenance",
]
#: The procedures several agents' prompts held, each a skill of its own now.
PROCEDURES = ["reuse-first", "data-sources", "package-contract", "fact-checking", "research-notes"]
CODE = ["node-functions", "catalogs", "widgets", "selection-chips"]
VEGA = ["widgets", "selection-chips", "vega-lite-starter", "vega-lite-maps"]
AUTK = ["widgets", "selection-chips", "autark", "autark-starter"]
#: The node kinds of example 26, in its order.
KINDS = [
    "curio.builtin/data-loading", "curio.builtin/computation-analysis", "curio.builtin/data-transformation",
    "curio.builtin/js-computation", "curio.builtin/vis-vega", "curio.builtin/autk-grammar",
    "curio.builtin/data-pool",
]
BY_KIND = {
    "curio.builtin/data-loading": CODE, "curio.builtin/computation-analysis": CODE,
    "curio.builtin/data-transformation": CODE, "curio.builtin/js-computation": CODE,
    "curio.builtin/vis-vega": VEGA, "curio.builtin/autk-grammar": AUTK,
    "curio.builtin/data-pool": ["interaction-edges"],
}
#: What the Node Builder's and the Researcher's instructions name: every run
#: of either is handed these, after the skills of the node it is on.
NODE_BUILDER_OWN = ["reuse-first", "data-sources"]
RESEARCHER_OWN = ["reuse-first", "fact-checking", "research-notes"]
#: What a delegated run reads when it writes or checks a node.
NODE_CAPABILITIES = ("node.content.generate", "content.quality.evaluate")


def _then(also: list[str]) -> dict[str, list[str]]:
    """By node kind, the skills a run on a node of that kind is handed, then *also*."""
    return {kind: [*skills, *also] for kind, skills in BY_KIND.items()}


#: The listing: by agent, its chat's catalog and the skills each run is handed.
LISTING = {
    "agent.curio.researcher@1": {
        "chat": [*FEATURES, *RESEARCHER_OWN],
        "chat, handed": RESEARCHER_OWN,
        "chat on a node": _then(RESEARCHER_OWN),
        "research.notes.compose": ["research-notes"],
        "research.verify": ["fact-checking"],
    },
    "agent.curio.dataflow-planner@1": {
        "workflow.plan.create": ["interaction-edges"],
        "execution.followup.plan": [],
        "workflow.plan.refresh": ["interaction-edges"],
        "workflow.coherence.validate": ["interaction-edges"],
        "workflow.keyword.bind": ["interaction-edges"],
        "workflow.keywords.extract": [],
    },
    "agent.curio.dataflow-reader@1": {
        "dataflow.explain": [*CODE, "autark", "vega-lite-starter", "autark-starter", "vega-lite-maps",
                             "interaction-edges"],
        "workflow.suggest": [*CODE, "autark", "vega-lite-starter", "autark-starter", "vega-lite-maps",
                             "interaction-edges"],
    },
    "agent.curio.node-builder@1": {
        "chat": [*FEATURES, *NODE_BUILDER_OWN, "package-contract"],
        "chat, handed": NODE_BUILDER_OWN,
        "chat on a node": _then(NODE_BUILDER_OWN),
        "node.build": [*CODE, *NODE_BUILDER_OWN],
        "dataset.fetch.author": [*CODE, *NODE_BUILDER_OWN],
        "node.content.generate": _then(["data-sources"]),
        "package.recommend": ["reuse-first"],
        "package.build": [*CODE, "package-contract", "reuse-first"],
        "package.extend": [*CODE, "package-contract", "reuse-first"],
        "node.kind.author": [*CODE, "package-contract", "reuse-first"],
    },
    "agent.curio.dataset-finder@1": {
        "chat": ["catalogs", "data-sources"],
        "chat, handed": [],
        "chat on a node": {"curio.builtin/data-loading": ["catalogs"]},
        "dataset.discover": ["catalogs"],
        "dataset.select": [],
    },
    "agent.curio.dataflow-builder@1": {
        "chat": [*FEATURES, "reuse-first", "data-sources"],
        "chat, handed": ["reuse-first"],
        "dataflow.orchestrate": ["reuse-first"],
    },
    "agent.curio.generated-content-evaluator@1": {
        "content.quality.evaluate": {**{kind: skills for kind, skills in BY_KIND.items()},
                                     "curio.builtin/data-pool": []},
    },
}
#: An agent a user imports with no ``skills`` field, on the default preamble:
#: its chat lists every skill Curio ships but the core three, by name.
USER_AGENT_CHAT = sorted({*FEATURES, *PROCEDURES})
#: Where each procedure's text was before it became a skill: by agent, the
#: file of the prompt that held it, and the skills that took its text. Every
#: run of that prompt is handed them: the chat, for an instruction, and each
#: capability whose prompt it is.
HELD = {
    ("agent.curio.node-builder@1", "prompts/node_build_instruction.md"): ["reuse-first", "data-sources"],
    ("agent.curio.node-builder@1", "prompts/new_content_prompt.md"): ["data-sources"],
    ("agent.curio.node-builder@1", "prompts/package_build_instruction.md"): ["package-contract", "reuse-first"],
    ("agent.curio.researcher@1", "prompts/researcher_instruction.md"):
        ["reuse-first", "fact-checking", "research-notes"],
    ("agent.curio.researcher@1", "prompts/research_instruction.md"): ["fact-checking"],
    ("agent.curio.researcher@1", "prompts/researcher_notes_instruction.md"): ["research-notes"],
}
#: The page of the base entry the plan rules stay on: they are a tool's
#: contract (``dataflow.plan.write``'s), not a procedure.
PLAN_RULES = "rules/plan-rules.md"


def _names(skills) -> list[str]:
    return [skill.name for skill in skills]


def _spec() -> dict:
    return json.loads(DATAFLOW.read_text(encoding="utf-8"))


def _first_of_each_kind(spec: dict) -> dict[str, dict]:
    nodes: dict[str, dict] = {}
    for node in spec["dataflow"]["nodes"]:
        nodes.setdefault(node["type"], node)
    return nodes


def _node_inputs(kind: str, node: dict) -> dict:
    """The inputs a run that writes or checks a node of *kind* is handed."""
    return {"nodeType": kind, "intent": node.get("goal"), "nodeContext": {"nodeType": kind}}


def _listing() -> dict:
    """The listing, as the runtime composes each run's skills."""
    from utk_curio.backend.app.agents.application import skill_runs
    from utk_curio.backend.app.agents.domain import builtin

    spec = _spec()
    nodes = _first_of_each_kind(spec)
    assert list(nodes) == KINDS, list(nodes)
    listing: dict = {}
    for m in builtin.list_builtin_manifests():
        preamble = builtin.read_prompt_text(m.dir_name, "system")
        rows: dict = {}
        if m.catalog.listed:
            chat = skill_runs.for_chat(KEY, PID, m, spec, {"kind": "canvas"}, preamble, [])
            assert chat.kept == ()
            rows["chat"] = chat.names
            rows["chat, handed"] = _names(chat.handed)
            node_target = next((t for t in m.compatible_targets if t.kind == "node"), None)
            if node_target is not None:
                rows["chat on a node"] = {
                    kind: _names(skill_runs.for_chat(KEY, PID, m, spec, {"kind": "node", "targetId": node["id"]},
                                                     preamble, []).handed)
                    for kind, node in nodes.items()
                    if all(_declares(m, kind, need) for need in node_target.requires)
                }
        for capability in m.capability_ids:
            if capability in NODE_CAPABILITIES:
                rows[capability] = {
                    kind: _names(skill_runs.for_delegated(
                        KEY, PID, m, capability, _node_inputs(kind, node), spec, preamble).handed)
                    for kind, node in nodes.items()
                }
            else:
                rows[capability] = _names(skill_runs.for_delegated(
                    KEY, PID, m, capability, {"intent": TASK}, spec, preamble).handed)
        listing[m.dir_name] = rows
    return listing


def _declares(manifest, node_type: str, need: str) -> bool:
    """Whether a node of *node_type* is one an agent's node target that
    requires *need* attaches to (``loadsDataset``: a node that loads data)."""
    from utk_curio.backend.app.packages import service as packages_services

    return bool(packages_services.template_flags(node_type) & {need})


def test_the_listing_of_every_agents_skills(tmp_curio, record_property):
    listing = _listing()
    record_property("skills listing", json.dumps(listing))
    assert listing == LISTING


def test_a_user_agent_that_names_no_skills_lists_every_skill_but_the_core(tmp_curio):
    from utk_curio.backend.app.agents.application import skill_runs
    from utk_curio.backend.app.agents.domain import builtin
    from utk_curio.backend.app.agents.domain.manifest import parse_agent_manifest

    manifest = parse_agent_manifest({
        "id": "agent.test.my-helper", "name": "My Helper", "category": "canvas", "version": "1.0.0",
        "capabilities": [{"id": "conversation.respond", "contractVersion": "1"}],
        "prompts": {"system": {"path": "curio:default_preamble.md"}, "instruction": {"path": "prompts/chat.md"}},
        "provenance": {"publisher": "me", "trust": "imported"},
    })
    preamble = builtin.read_page("default_preamble.md", wanted_by="the test")
    chat = skill_runs.for_chat(KEY, PID, manifest, _spec(), {"kind": "canvas"}, preamble, [])
    assert chat.names == USER_AGENT_CHAT
    assert sorted(chat.placed) == CORE
    assert chat.handed == (), "an instruction that names no skills hands none"
    assert skill_runs.grants([], chat) == ["skill.read"]


def test_every_skill_reaches_an_agent():
    """The default preamble, which every agent Curio ships reads, holds the
    core skills; every other skill is in a chat's catalog or handed to a run
    of the listing. This replaces the check that every page rode the
    preamble."""
    from utk_curio.backend.app.agents.application import skill_runs
    from utk_curio.backend.app.agents.domain import builtin, skills

    shipped = [folder.name for folder in skills.shipped_folders()]
    assert len(shipped) == 21
    preamble = builtin.read_page("default_preamble.md", wanted_by="the test")
    assert sorted(skill_runs.placed_in(preamble, skill_runs.shipped_skills())) == CORE
    for m in builtin.list_builtin_manifests():
        assert m.prompts["system"].path == "curio:default_preamble.md", m.dir_name
        assert builtin.read_prompt_text(m.dir_name, "system") == preamble, m.dir_name
    reached = set(CORE)
    for rows in LISTING.values():
        for value in rows.values():
            for names in value.values() if isinstance(value, dict) else [value]:
                reached |= set(names)
    assert sorted(reached) == sorted(shipped), sorted(set(shipped) - reached)


def test_each_agent_names_only_skills_curio_ships_and_each_card_chat_loads_them():
    from utk_curio.backend.app.agents.application import skill_runs, tools
    from utk_curio.backend.app.agents.domain import builtin, skills

    shipped = {folder.name for folder in skills.shipped_folders()}
    own = {}
    instructions = {}
    for m in builtin.list_builtin_manifests():
        assert m.skills is not None and set(m.skills) <= shipped - set(CORE), m.dir_name
        for capability in m.capabilities:
            assert set(capability.skills) <= set(m.skills), (m.dir_name, capability.id)
            if capability.skills:
                own[f"{m.dir_name} {capability.id}"] = list(capability.skills)
        assert set(m.instruction_skills) <= set(m.skills), m.dir_name
        if m.instruction_skills:
            instructions[m.dir_name] = list(m.instruction_skills)
    # The capabilities that write node code for another agent with no node
    # named, the Dataset Finder's search and the modes whose prompts held a
    # procedure name their own.
    assert own == {
        "agent.curio.node-builder@1 node.build": CODE,
        "agent.curio.node-builder@1 dataset.fetch.author": CODE,
        "agent.curio.node-builder@1 node.content.generate": ["data-sources"],
        "agent.curio.node-builder@1 package.recommend": ["reuse-first"],
        "agent.curio.node-builder@1 package.build": ["package-contract", "reuse-first"],
        "agent.curio.node-builder@1 package.extend": ["package-contract", "reuse-first"],
        "agent.curio.node-builder@1 node.kind.author": ["package-contract", "reuse-first"],
        "agent.curio.researcher@1 research.notes.compose": ["research-notes"],
        "agent.curio.researcher@1 research.verify": ["fact-checking"],
        "agent.curio.dataset-finder@1 dataset.discover": ["catalogs"],
    }
    # The instructions that held a procedure, and the Dataflow Builder's,
    # whose plans take the ladder's first rung, name theirs.
    assert instructions == {
        "agent.curio.node-builder@1": NODE_BUILDER_OWN,
        "agent.curio.researcher@1": RESEARCHER_OWN,
        "agent.curio.dataflow-builder@1": ["reuse-first"],
    }
    for m in builtin.list_builtin_manifests():
        assert "skill.read" not in [tool.id for tool in m.tools], "skill.read is granted by the catalog, not asked for"
        if m.catalog.listed:
            chat = skill_runs.for_chat(KEY, PID, m, _spec(), {"kind": "canvas"},
                                       builtin.read_prompt_text(m.dir_name, "system"), [])
            assert skill_runs.grants(tools.resolve_grants(m.tools), chat)[-1] == "skill.read", m.dir_name


def test_each_skill_names_what_it_serves_by_names_the_code_knows():
    """``curio-behaviors`` names behaviors the templates Curio ships declare;
    ``curio-features`` the features ``skill_runs`` reads of a dataflow. The
    core skills, always in the preamble, the history skill, loaded in chat
    when needed, and the procedures, handed by name to the runs whose prompts
    they left, serve nothing."""
    from utk_curio.backend.app.agents.application import skill_runs
    from utk_curio.backend.app.agents.domain import skills

    behaviors = set()
    for path in sorted((REPO_ROOT / "packages").glob("*/manifest.json")):
        for template in json.loads(path.read_text(encoding="utf-8")).get("templates", []):
            if template.get("behavior"):
                behaviors.add(template["behavior"])
    served = {}
    for skill in skills.shipped_skills():
        named_behaviors = str(skill.metadata.get("curio-behaviors") or "").split()
        named_features = str(skill.metadata.get("curio-features") or "").split()
        assert set(named_behaviors) <= behaviors, (skill.name, named_behaviors)
        assert set(named_features) <= set(skill_runs.FEATURES), (skill.name, named_features)
        assert len(named_behaviors) == len(set(named_behaviors)), skill.name
        served[skill.name] = (named_behaviors, named_features)
    assert {name for name, (b, f) in served.items() if not b and not f} == {*CORE, "provenance", *PROCEDURES}
    for name in PROCEDURES:
        assert "curio-refusals" not in skills.parse(skills.skills_dir() / name).metadata, name
    writes_code = ["code", "data-export", "data-summary", "edit-features"]
    assert served["node-functions"] == (writes_code, []) and served["catalogs"] == (writes_code, [])
    assert served["widgets"] == ([*writes_code, "vega", "autk-grammar"], [])
    assert served["selection-chips"] == ([*writes_code, "vega", "autk-grammar"], [])
    assert served["interaction-edges"] == (["data-pool"], ["interaction-edges"])
    assert served["scenarios"] == ([], ["scenario-boxes"]) and served["dashboards"] == ([], ["pinned-tiles"])


def _runs_of(manifest, file: str) -> list[tuple[str, str | None]]:
    """Each run of the prompt whose file is *file*: the chat, when it is the
    instruction of an agent with one (``("chat", None)``), and each capability
    whose instruction it is (``("capability", <id>)``), a capability with no
    instruction of its own running the agent's."""
    keys = {key for key, asset in manifest.prompts.items() if asset.path == file}
    assert keys, f"{manifest.dir_name} names no prompt at {file}"
    runs: list[tuple[str, str | None]] = []
    if "instruction" in keys and manifest.catalog.listed:
        runs.append(("chat", None))
    for capability in manifest.capabilities:
        if (capability.instruction or "instruction") in keys:
            runs.append(("capability", capability.id))
    return runs


def test_no_run_of_a_prompt_loses_a_procedure_its_text_held(tmp_curio):
    """Each prompt whose text held a procedure before it became a skill
    (``HELD``): every run of it is handed that skill in its place, the chat
    on the canvas and on every kind of node it attaches to, and each
    capability whose prompt it is, on every kind of node when it writes or
    checks one. A procedure's text that leaves a prompt with no skill handed
    in its place fails here."""
    from utk_curio.backend.app.agents.application import skill_runs
    from utk_curio.backend.app.agents.domain import builtin

    spec = _spec()
    nodes = _first_of_each_kind(spec)
    lost = []
    checked = 0
    for (coord, file), procedures in HELD.items():
        m = builtin.get_builtin_manifest(coord)
        preamble = builtin.read_prompt_text(coord, "system")
        runs = _runs_of(m, file)
        assert runs, (coord, file)
        for kind, capability in runs:
            if kind == "chat":
                targets = [{"kind": "canvas"}, *({"kind": "node", "targetId": node["id"]} for node in nodes.values())]
                held = [(str(target), skill_runs.for_chat(KEY, PID, m, spec, target, preamble, []))
                        for target in targets]
            elif capability in NODE_CAPABILITIES:
                held = [(f"{capability} on {node_type}", skill_runs.for_delegated(
                    KEY, PID, m, capability, _node_inputs(node_type, node), spec, preamble))
                    for node_type, node in nodes.items()]
            else:
                held = [(capability, skill_runs.for_delegated(KEY, PID, m, capability, {"intent": TASK}, spec,
                                                              preamble))]
            for where, run in held:
                checked += 1
                missing = [name for name in procedures if name not in _names(run.handed)]
                if missing:
                    lost.append((coord, file, where, missing))
    assert checked >= 30, checked
    assert not lost, f"these runs lost the procedures their prompts held: {lost}"


def test_each_procedures_text_is_in_its_skill_alone():
    """A procedure's text moved: each line of a procedure's skill, beyond its
    headings, is in no page of the base entry, no prompt of an agent Curio
    ships and no other skill, and no prompt or page includes one of the pages
    that held them. The base entry keeps only the plan rules, which are a
    tool's contract."""
    import re

    from utk_curio.backend.app.agents.domain import skills
    from utk_curio.backend.tests._support.prompt_files import prompt_files, prompt_name

    sources = {prompt_name(path): path.read_text(encoding="utf-8") for path in prompt_files("*.md")}
    assert set(f"{name}/SKILL.md" for name in PROCEDURES) <= set(sources), sorted(sources)
    for name in PROCEDURES:
        body = skills.parse(skills.skills_dir() / name).body
        # Each line as its text, its list mark left out.
        lines = [re.sub(r"^(?:[-*]|\d+\.)\s+", "", line.strip()) for line in body.splitlines()
                 if not line.lstrip().startswith("#")]
        lines = [line for line in lines if len(line) >= 40]
        assert len(lines) >= 3, name
        for where, text in sources.items():
            if where == f"{name}/SKILL.md":
                continue
            repeated = [line for line in lines if line in text]
            assert not repeated, (name, where, repeated[:2])
    included = {(where, page) for where, text in sources.items()
                for page in re.findall(r"\{\{include:([^{}]+)\}\}", text) if page != PLAN_RULES}
    assert not included, sorted(included)
    pages = json.loads((REPO_ROOT / "agents" / "agent.curio.builtin@1" / "manifest.json")
                       .read_text(encoding="utf-8"))["pages"]
    assert [page for page in pages if page.startswith("rules/")] == [PLAN_RULES]
