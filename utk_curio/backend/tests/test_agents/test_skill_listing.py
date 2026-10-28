"""Which skills each agent's runs hold: the listing, and every skill reaches an agent.

Every agent Curio ships, and one agent a user imports, on one dataflow,
``docs/examples/26-several-inputs.json`` (Data Loading, Python, Data
Transformation, JavaScript, Vega-Lite and Autark nodes and a Data Pool):

- each chat's catalog, the skills it loads with ``skill.read`` when it needs
  one, and the skills it is handed when attached to a node of each kind the
  dataflow holds;
- each capability's delegated run, a mode's or another's, and the skills it is
  handed: a node's content and a check of it once per node kind, with the
  inputs Solve hands it, every other with only an intent.

The listing is recorded on the test (``record_property``), so the CI report
shows it. Beside it, every skill Curio ships reaches some agent's run: the
default preamble holds the core three, and every other is in a chat's catalog
or handed to a run. Each skill names what it serves by names the code knows:
behaviors the shipped templates declare and features ``skill_runs`` reads.

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
#: What a delegated run reads when it writes or checks a node.
NODE_CAPABILITIES = ("node.content.generate", "content.quality.evaluate")
#: The listing: by agent, its chat's catalog and the skills each run is handed.
LISTING = {
    "agent.curio.researcher@1": {
        "chat": FEATURES,
        "chat on a node": BY_KIND,
        "research.notes.compose": [],
        "research.verify": [],
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
        "chat": FEATURES,
        "chat on a node": BY_KIND,
        "node.build": CODE,
        "dataset.fetch.author": CODE,
        "node.content.generate": BY_KIND,
        "package.recommend": [],
        "package.build": CODE,
        "package.extend": CODE,
        "node.kind.author": CODE,
    },
    "agent.curio.dataset-finder@1": {
        "chat": ["catalogs"],
        "chat on a node": {"curio.builtin/data-loading": ["catalogs"]},
        "dataset.discover": ["catalogs"],
        "dataset.select": [],
    },
    "agent.curio.dataflow-builder@1": {
        "chat": FEATURES,
        "dataflow.orchestrate": [],
    },
    "agent.curio.generated-content-evaluator@1": {
        "content.quality.evaluate": {**{kind: skills for kind, skills in BY_KIND.items()},
                                     "curio.builtin/data-pool": []},
    },
}
#: An agent a user imports with no ``skills`` field, on the default preamble:
#: its chat lists every skill Curio ships but the core three, by name.
USER_AGENT_CHAT = sorted(set(FEATURES))


def _names(skills) -> list[str]:
    return [skill.name for skill in skills]


def _spec() -> dict:
    return json.loads(DATAFLOW.read_text(encoding="utf-8"))


def _first_of_each_kind(spec: dict) -> dict[str, dict]:
    nodes: dict[str, dict] = {}
    for node in spec["dataflow"]["nodes"]:
        nodes.setdefault(node["type"], node)
    return nodes


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
            assert chat.handed == () and chat.kept == ()
            rows["chat"] = chat.names
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
                        KEY, PID, m, capability, {"nodeType": kind, "intent": node.get("goal"),
                                                  "nodeContext": {"nodeType": kind}},
                        spec, preamble).handed)
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
    assert skill_runs.grants([], chat) == ["skill.read"]


def test_every_skill_reaches_an_agent():
    """The default preamble, which every agent Curio ships reads, holds the
    core skills; every other skill is in a chat's catalog or handed to a run
    of the listing. This replaces the check that every page rode the
    preamble."""
    from utk_curio.backend.app.agents.application import skill_runs
    from utk_curio.backend.app.agents.domain import builtin, skills

    shipped = [folder.name for folder in skills.shipped_folders()]
    assert len(shipped) == 16
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
    for m in builtin.list_builtin_manifests():
        assert m.skills is not None and set(m.skills) <= shipped - set(CORE), m.dir_name
        for capability in m.capabilities:
            assert set(capability.skills) <= set(m.skills), (m.dir_name, capability.id)
            if capability.skills:
                own[f"{m.dir_name} {capability.id}"] = list(capability.skills)
    # The capabilities that write node code for another agent with no node
    # named, and the Dataset Finder's search, name their own.
    assert own == {
        "agent.curio.node-builder@1 node.build": CODE,
        "agent.curio.node-builder@1 dataset.fetch.author": CODE,
        "agent.curio.dataset-finder@1 dataset.discover": ["catalogs"],
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
    core skills, always in the preamble, and the history skill, loaded in
    chat when needed, serve nothing."""
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
    assert {name for name, (b, f) in served.items() if not b and not f} == {*CORE, "provenance"}
    writes_code = ["code", "data-export", "data-summary", "edit-features"]
    assert served["node-functions"] == (writes_code, []) and served["catalogs"] == (writes_code, [])
    assert served["widgets"] == ([*writes_code, "vega", "autk-grammar"], [])
    assert served["selection-chips"] == ([*writes_code, "vega", "autk-grammar"], [])
    assert served["interaction-edges"] == (["data-pool"], ["interaction-edges"])
    assert served["scenarios"] == ([], ["scenario-boxes"]) and served["dashboards"] == ([], ["pinned-tiles"])
