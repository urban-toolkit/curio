"""Skills in a run: the catalog a chat loads from, ``skill.read``, the skills a run is handed, and what runs record.

A chat run lists its agent's skills, beyond those its preamble holds, under the
instruction of agentskills.io's guide for clients, and is granted
``skill.read``; a run with no skill to list gets neither. ``skill.read``
returns a skill's body, its frontmatter left out, wrapped as
``<skill_content>``, with the skill's files listed and not read. A skill the
conversation holds already is not sent again: what a turn loads is recorded on
it and handed to every later turn, however many turns are trimmed from the
context. Loading a skill spends no tool round, up to four a turn. A run with no
tools is handed the skills its task needs instead, and a Solve round after a
refusal the skills that answer the check that refused. Runs go through the
scripted provider (``testing_provider``).

New names are read inside each test, so this module imports on a checkout
without them and each test fails on its own.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from utk_curio.backend.app.agents.infrastructure import testing_provider
from utk_curio.backend.app.agents.infrastructure.providers import ProviderConfig
from utk_curio.backend.app.agents.repositories import storage
from utk_curio.backend.app.projects import storage as projects_storage
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.tests._support.agent_routes import _auth

NB = "agent.curio.node-builder@1"
DF = "agent.curio.dataset-finder@1"
RS = "agent.curio.researcher@1"
DFB = "agent.curio.dataflow-builder@1"
READER = "agent.curio.dataflow-reader@1"
PLANNER = "agent.curio.dataflow-planner@1"
EVALUATOR = "agent.curio.generated-content-evaluator@1"
CA = "curio.builtin/computation-analysis"
VEGA = "curio.builtin/vis-vega"
AUTK = "curio.builtin/autk-grammar"
EDIT = "curio.builtin/edit-features"
POOL = "curio.builtin/data-pool"
#: A node type no template resolves: its node names no behavior.
UNKNOWN = "acme.tools/clip"
#: The skills the default preamble holds, every agent's core.
CORE = ("compatibility", "node-control", "nodes")
#: The feature skills the three card chats list first, in their manifests' order.
FEATURE_SKILLS = [
    "node-functions", "catalogs", "widgets", "selection-chips", "autark", "vega-lite-starter",
    "autark-starter", "vega-lite-maps", "interaction-edges", "map-edits", "scenarios", "dashboards",
    "provenance",
]
#: The Node Builder's skills: the feature skills, then the procedures its runs follow.
NB_SKILLS = [*FEATURE_SKILLS, "reuse-first", "data-sources", "package-contract"]
#: The skills the Node Builder's instruction names: its chat is handed them,
#: and so is each of its capabilities with no instruction of its own.
NB_INSTRUCTION = ["reuse-first", "data-sources"]
CODE_SKILLS = ["node-functions", "catalogs", "widgets", "selection-chips"]
VEGA_SKILLS = ["widgets", "selection-chips", "vega-lite-starter", "vega-lite-maps"]
AUTK_SKILLS = ["widgets", "selection-chips", "autark", "autark-starter"]
#: The account the pure calls read packages for: none installed, so each
#: template is the package catalog's.
KEY = "4242"
PID = "p-skills"
ENDPOINT = ProviderConfig(api_key="", api_type="testing", base_url="", model="scripted",
                          config_id="llm-000000000003")


def _skill_runs():
    from utk_curio.backend.app.agents.application import skill_runs

    return skill_runs


def _manifest(coord: str):
    from utk_curio.backend.app.agents.domain import builtin

    return builtin.get_builtin_manifest(coord)


def _preamble(coord: str) -> str:
    from utk_curio.backend.app.agents.domain import builtin

    return builtin.read_prompt_text(coord, "system")


def _names(skills) -> list[str]:
    return [skill.name for skill in skills]


def _tail(payload: dict, prose: str = "Reading it.") -> str:
    """A reply that ends in one fenced request block."""
    return f"{prose}\n\n```curio.v1\n{json.dumps(payload)}\n```"


def _read(name: str, **params) -> str:
    return _tail({"toolRequest": {"tool": "skill.read", "params": {"name": name, **params}}})


def _slot(message: dict, kind: str) -> str | None:
    found = [slot["text"] for slot in message.get("slots") or [] if slot["kind"] == kind]
    assert len(found) <= 1, (kind, [slot["kind"] for slot in message["slots"]])
    return found[0] if found else None


def _kinds(message: dict) -> list[str]:
    return [slot["kind"] for slot in message["slots"]]


def _listed(catalog: str) -> list[str]:
    return re.findall(r"<name>([^<]+)</name>", catalog)


def _wrapped(text: str | None) -> list[str]:
    return re.findall(r'<skill_content name="([^"]+)">', text or "")


@pytest.fixture()
def scripted(client, user_and_token):
    """A scripted configuration as the account's default; the fenced
    protocol unless a test scripts native tools."""
    testing_provider.reset()
    _, token = user_and_token
    h = _auth(token)
    created = client.post("/api/agents/llm/configs", headers=h, json={
        "label": "Scripted", "apiType": "testing", "model": "scripted"})
    assert created.status_code == 201, created.get_json()
    client.put("/api/agents/llm/default", headers=h, json={"configId": created.get_json()["config"]["id"]})
    yield h
    testing_provider.reset()


def _project(client, headers, nodes=(), edges=()) -> str:
    body = {"name": "p", "spec": {"dataflow": {"nodes": list(nodes), "edges": list(edges), "packages": []}},
            "outputs": []}
    resp = client.post("/api/projects", json=body, headers=headers)
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def _attach(client, headers, pid, coord, target=None) -> str:
    client.post(f"/api/agents/projects/{pid}/install", json={"coord": coord}, headers=headers)
    resp = client.post(f"/api/agents/projects/{pid}/attachments",
                       json={"coord": coord, "target": target or {"kind": "canvas"}}, headers=headers)
    assert resp.status_code in (200, 201), resp.get_json()
    return resp.get_json()["attachmentId"]


def _run(client, headers, pid, att, message="go") -> dict:
    resp = client.post(f"/api/agents/projects/{pid}/attachments/{att}/run", json={"message": message},
                       headers=headers)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


def _turns(client, headers, pid, att) -> list[dict]:
    return client.get(f"/api/agents/projects/{pid}/attachments/{att}/session", headers=headers).get_json()["turns"]


def _run_calls() -> list[list]:
    """The captured message lists of the runs' own calls, the title call left out."""
    from utk_curio.backend.app.agents.application.turns import titles

    return [messages for messages in testing_provider.captured()
            if not (messages and messages[0].get("content") == titles.title_prompt())]


def _user_agent(user, coord: str, *, preamble: str | None = None, skills=None, tools=()) -> str:
    """A user's agent in the account's store, as an import writes it: one
    chat, the preamble *preamble* names (``curio:<page>``) or holds, and the
    skills field only when *skills* is given."""
    agent_id = coord.split("@", 1)[0]
    manifest = {
        "id": agent_id, "name": "My Helper", "category": "canvas", "version": "1.0.0",
        "capabilities": [{"id": "conversation.respond", "contractVersion": "1"}],
        "prompts": {"instruction": {"path": "prompts/chat.md", "variables": []}},
        "compatibleTargets": [{"kind": "canvas", "requires": []}, {"kind": "node", "requires": []}],
        "tools": [{"id": tool} for tool in tools],
        "provenance": {"publisher": "me", "trust": "imported"},
    }
    files = {"prompts/chat.md": "You help with dataflows."}
    if preamble is not None:
        if preamble.startswith("curio:"):
            manifest["prompts"]["system"] = {"path": preamble, "variables": []}
        else:
            manifest["prompts"]["system"] = {"path": "prompts/system.md", "variables": []}
            files["prompts/system.md"] = preamble
    if skills is not None:
        manifest["skills"] = list(skills)
    storage.write_definition(_user_dir_key(user), coord, manifest, files)
    return coord


# --- The catalog ---------------------------------------------------------------------


def test_a_chat_lists_its_agents_skills_under_the_guides_instruction_and_holds_skill_read(
    client, user_and_token, tmp_curio, scripted,
):
    """The Node Builder's chat lists the skills its manifest names, none of
    the core three its preamble holds, in a slot of its own after the
    preamble, and is granted skill.read, last among its tools. On the canvas
    it is handed only the skills its instruction names."""
    from utk_curio.backend.app.agents.domain import agent_text, builtin

    skill_runs = _skill_runs()
    pid = _project(client, scripted)
    att = _attach(client, scripted, pid, NB)
    testing_provider.push_reply("Hello.")
    _run(client, scripted, pid, att)
    (system, *_), = _run_calls()
    assert _kinds(system)[:4] == ["preamble", "skill-catalog", "skills", "instruction"], _kinds(system)
    catalog = _slot(system, "skill-catalog")
    assert catalog.startswith(agent_text.section(builtin.FRAMES_FILE, "skill-catalog") + "\n\n<available_skills>\n")
    assert catalog.endswith("\n</available_skills>")
    assert _listed(catalog) == list(_manifest(NB).skills) == NB_SKILLS
    assert not set(_listed(catalog)) & set(CORE)
    assert _wrapped(_slot(system, "skills")) == list(_manifest(NB).instruction_skills) == NB_INSTRUCTION
    assert "- skill.read:" in _slot(system, "tool-protocol")
    pins = _turns(client, scripted, pid, att)[-1]["execution"]["pins"]
    assert pins["tools"][-1] == "skill.read" and pins["tools"].count("skill.read") == 1, pins["tools"]
    assert pins["skills"] == {"catalog": NB_SKILLS, "handed": NB_INSTRUCTION}
    assert skill_runs.TOOL == "skill.read"


def test_the_catalog_is_the_guides_list_of_names_and_descriptions(tmp_curio):
    """``<available_skills>``, one ``<skill>`` each with its name and its
    description, as the guide shows it, the text escaped for XML."""
    from utk_curio.backend.app.agents.domain import agent_text, builtin, skills

    skill_runs = _skill_runs()
    real = skills.parse(skills.skills_dir() / "widgets")
    odd = skills.Skill(
        name="street-trees", description="Use this skill when a <tree> & its species matter.", license=None,
        compatibility=None, metadata={}, allowed_tools=None, body="## Trees\n", folder=Path("street-trees"),
        files=(), body_line=1,
    )
    text = skill_runs.catalog_text(skill_runs.RunSkills(catalog=(real, odd)))
    assert text == (
        agent_text.section(builtin.FRAMES_FILE, "skill-catalog") + "\n\n<available_skills>\n"
        f"  <skill>\n    <name>widgets</name>\n    <description>{real.description}</description>\n  </skill>\n"
        "  <skill>\n    <name>street-trees</name>\n"
        "    <description>Use this skill when a &lt;tree&gt; &amp; its species matter.</description>\n"
        "  </skill>\n</available_skills>"
    )
    assert "call the skill.read tool with the skill's name" in text
    assert skill_runs.catalog_text(skill_runs.RunSkills()) is None


def test_a_run_with_no_skills_gets_no_catalog_and_no_tool(client, user_and_token, tmp_curio, scripted):
    """A user's agent that names no skill (``skills: []``) lists none and holds
    no skill.read, on either protocol, as the guide says of an agent with no
    skills: no empty list, no tool with nothing to load."""
    user, _ = user_and_token
    coord = _user_agent(user, "agent.test.no-skills@1", preamble="curio:default_preamble.md", skills=[],
                        tools=["dataflow.read"])
    pid = _project(client, scripted)
    att = _attach(client, scripted, pid, coord)
    testing_provider.push_reply("Hello.")
    _run(client, scripted, pid, att)
    (system, *_), = _run_calls()
    assert "skill-catalog" not in _kinds(system) and "skills" not in _kinds(system), _kinds(system)
    assert "<available_skills>" not in system["content"] and "skill.read" not in system["content"]
    pins = _turns(client, scripted, pid, att)[-1]["execution"]["pins"]
    assert pins["tools"] == ["dataflow.read"] and "skills" not in pins, pins
    testing_provider.reset()
    testing_provider.script_chat_capabilities(tools=True)
    testing_provider.push_reply("Hello again.")
    _run(client, scripted, pid, att)
    assert testing_provider.offered()[0]["tools"] == ["dataflow__read"], testing_provider.offered()


def test_a_user_agent_that_names_no_skills_lists_every_skill_its_preamble_does_not_hold(
    client, user_and_token, tmp_curio, scripted,
):
    """Without a ``skills`` field an agent lists every skill Curio ships but
    the ones its preamble holds: the default preamble holds the core three,
    an agent's own preamble none."""
    from utk_curio.backend.app.agents.application.turns import prepare
    from utk_curio.backend.app.agents.domain import skills

    user, _ = user_and_token
    shipped = [folder.name for folder in skills.shipped_folders()]
    assert len(shipped) == 21 and set(CORE) <= set(shipped)
    pid = _project(client, scripted)
    for coord, preamble, listed in (
        ("agent.test.curio-preamble@1", "curio:default_preamble.md", [n for n in shipped if n not in CORE]),
        ("agent.test.own-preamble@1", "You are a careful assistant.", shipped),
    ):
        _user_agent(user, coord, preamble=preamble)
        att = _attach(client, scripted, pid, coord)
        *_rest, pins, loop_ctx = prepare._prepare_run(_user_dir_key(user), pid, att, "go", ENDPOINT)
        assert pins["skills"]["catalog"] == listed, coord
        assert pins["tools"] == ["skill.read"], coord
        assert loop_ctx["skills"].names == listed, coord


def test_a_native_run_is_offered_skill_read_with_its_skills_as_the_only_names(
    client, user_and_token, tmp_curio, scripted,
):
    """The tool's ``name`` takes exactly the skills the run lists (an enum),
    so a model cannot name a skill the run does not hold."""
    from utk_curio.backend.app.agents.application import tools
    from utk_curio.backend.app.agents.application.turns import prepare

    user, _ = user_and_token
    testing_provider.script_chat_capabilities(tools=True)
    pid = _project(client, scripted)
    for coord, listed in ((NB, NB_SKILLS), (DF, ["catalogs", "data-sources"])):
        att = _attach(client, scripted, pid, coord)
        *_rest, loop_ctx = prepare._prepare_run(_user_dir_key(user), pid, att, "go", ENDPOINT)
        (spec,) = [tool for tool in loop_ctx["native_tools"] if tool["name"] == tools.wire_name("skill.read")]
        assert spec["parameters"]["properties"]["name"]["enum"] == listed, coord
        assert spec["parameters"]["required"] == ["name"]
        # Last of its tools, before the delegation tool when it has one.
        names = [tool["name"] for tool in loop_ctx["native_tools"] if tool["name"] != tools.DELEGATE_TOOL]
        assert names[-1] == tools.wire_name("skill.read"), names
        assert len(spec["description"]) <= 1024
    # The registry's own schema names every skill Curio ships; a run gives its own.
    names = tools.REGISTRY["skill.read"].parameters["properties"]["name"]["enum"]
    assert len(names) == 21 and set(NB_SKILLS) <= set(names)


# --- skill.read ------------------------------------------------------------------------


@pytest.fixture()
def street_trees(tmp_path, monkeypatch):
    """Curio's skills, as a folder holding one skill with a file of its own."""
    from utk_curio.backend.app.agents.domain import skills

    root = tmp_path / "skills"
    folder = root / "street-trees"
    (folder / "references").mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        "---\nname: street-trees\ndescription: Use this skill when a node reads a city's street trees.\n"
        "metadata:\n  author: curio\n  version: \"1.0.0\"\n---\n## Street trees\n\nA tree's species is in its row.\n",
        encoding="utf-8",
    )
    (folder / "references" / "species.md").write_text("Oak, elm, maple.\n", encoding="utf-8")
    monkeypatch.setattr(skills, "skills_dir", lambda: root)
    return skills.parse(folder)


def test_skill_read_returns_the_body_wrapped_with_its_files_listed_and_not_read(tmp_curio, street_trees):
    from utk_curio.backend.app.agents.domain import agent_text, builtin

    skill_runs = _skill_runs()
    run = skill_runs.RunSkills(catalog=(street_trees,))
    status, text = skill_runs.read(run, {"name": "street-trees"})
    assert status == "ok"
    assert text == (
        '<skill_content name="street-trees">\n## Street trees\n\nA tree\'s species is in its row.\n\n'
        + agent_text.section(builtin.FRAMES_FILE, "skill-files")
        + "\n<skill_resources>\n  <file>references/species.md</file>\n</skill_resources>\n</skill_content>"
    )
    assert "Oak" not in text, "a file was read before it was asked for"
    assert run.loaded == ["street-trees"]
    # One of its files, by its path, wrapped as a file of the skill.
    status, text = skill_runs.read(run, {"name": "street-trees", "path": "references/species.md"})
    assert (status, text) == (
        "ok", '<skill_file name="street-trees" path="references/species.md">\nOak, elm, maple.\n</skill_file>',
    )


def test_skill_read_never_sends_a_skill_or_a_file_twice(tmp_curio, street_trees):
    from utk_curio.backend.app.agents.domain import agent_text

    skill_runs = _skill_runs()
    run = skill_runs.RunSkills(catalog=(street_trees,))
    skill_runs.read(run, {"name": "street-trees"})
    assert skill_runs.read(run, {"name": "street-trees"}) == (
        "ok", agent_text.message("skills.already-loaded", name="street-trees"),
    )
    skill_runs.read(run, {"name": "street-trees", "path": "references/species.md"})
    assert skill_runs.read(run, {"name": "street-trees", "path": "references/species.md"}) == (
        "ok", agent_text.message("skills.file-already-read", name="street-trees", path="references/species.md"),
    )
    assert run.loaded == ["street-trees"]
    # A skill the run was handed, kept from an earlier turn or holds in its
    # preamble is in the conversation already.
    for held in (skill_runs.RunSkills(catalog=(street_trees,), handed=(street_trees,)),
                 skill_runs.RunSkills(catalog=(street_trees,), kept=(street_trees,)),
                 skill_runs.RunSkills(catalog=(street_trees,), placed=frozenset({"street-trees"}))):
        assert skill_runs.read(held, {"name": "street-trees"})[1] == agent_text.message(
            "skills.already-loaded", name="street-trees"), held
        assert held.loaded == []


def test_skill_read_refuses_a_name_the_run_does_not_list_and_a_file_the_skill_does_not_hold(
    tmp_curio, street_trees,
):
    from utk_curio.backend.app.agents.domain import agent_text

    skill_runs = _skill_runs()
    run = skill_runs.RunSkills(catalog=(street_trees,))
    for params in ({}, {"name": "widgets"}, {"name": 7}):
        assert skill_runs.read(run, params) == ("refused", agent_text.message(
            "skills.not-listed", name=repr(params.get("name")), names="street-trees")), params
    for path in ("references/../SKILL.md", "SKILL.md", "/etc/passwd", 3):
        assert skill_runs.read(run, {"name": "street-trees", "path": path}) == ("refused", agent_text.message(
            "skills.no-such-file", name="street-trees", path=repr(path), files="references/species.md")), path
    assert run.loaded == [] and run.files_read == []


@pytest.mark.parametrize("native", [False, True], ids=["fenced", "native"])
def test_a_skill_a_chat_loads_is_kept_for_the_conversation_and_never_sent_twice(
    client, user_and_token, tmp_curio, scripted, native,
):
    """Turn one loads ``widgets``: its result is the skill, and the turn
    records it; its system turn holds only the skills the instruction names.
    Turn two is handed it in its system turn, after those, and loading it
    again answers that it is in the conversation already."""
    from utk_curio.backend.app.agents.domain import agent_text

    if native:
        testing_provider.script_chat_capabilities(tools=True)
    call = {"toolCalls": [{"name": "skill.read", "arguments": {"name": "widgets"}}]}
    pid = _project(client, scripted)
    att = _attach(client, scripted, pid, NB)
    testing_provider.push_replies(call if native else _read("widgets"), "Done.")
    _run(client, scripted, pid, att)
    first = _run_calls()
    result = first[1][-1]
    assert result["role"] == ("tool" if native else "user"), result
    assert _wrapped(result["content"]) == ["widgets"], result["content"][:200]
    assert _wrapped(_slot(first[0][0], "skills")) == NB_INSTRUCTION
    record = _turns(client, scripted, pid, att)[-1]["execution"]
    assert record["skillsLoaded"] == ["widgets"]
    assert [c["tool"] for c in record["toolCalls"]] == ["skill.read"]

    testing_provider.reset()
    if native:
        testing_provider.script_chat_capabilities(tools=True)
    testing_provider.push_replies(call if native else _read("widgets"), "Done again.")
    _run(client, scripted, pid, att, "and again")
    second = _run_calls()
    assert _wrapped(_slot(second[0][0], "skills")) == [*NB_INSTRUCTION, "widgets"]
    again = second[1][-1]["content"]
    assert agent_text.message("skills.already-loaded", name="widgets") in again and not _wrapped(again)
    record = _turns(client, scripted, pid, att)[-1]["execution"]
    assert "skillsLoaded" not in record
    assert record["pins"]["skills"]["kept"] == ["widgets"]


def test_a_loaded_skill_is_kept_when_its_turn_is_trimmed_from_the_context(
    client, user_and_token, tmp_curio, scripted,
):
    """The context carries the last turns only (``sessions.CONTEXT_WINDOW_TURNS``);
    a skill loaded in a turn older than those is still handed to the run."""
    from utk_curio.backend.app.agents.application import attachments
    from utk_curio.backend.app.agents.repositories import sessions

    user, _ = user_and_token
    pid = _project(client, scripted)
    att = _attach(client, scripted, pid, NB)
    testing_provider.push_replies(_read("map-edits"), "Done.")
    _run(client, scripted, pid, att)
    session_id = attachments.get_attachment(projects_storage.read_spec(_user_dir_key(user), pid), att)["sessionId"]
    later = [sessions.make_turn(role, f"turn {i}") for i in range(sessions.CONTEXT_WINDOW_TURNS)
             for role in ("user", "agent")]
    sessions.append_turns(_user_dir_key(user), pid, session_id, att, later)
    testing_provider.reset()
    testing_provider.push_reply("Hello.")
    _run(client, scripted, pid, att, "anything new?")
    (system, *context) = _run_calls()[0]
    assert not any("map-edits" in str(m.get("content")) for m in context), "the loading turn is still in context"
    assert _wrapped(_slot(system, "skills")) == [*NB_INSTRUCTION, "map-edits"]


def test_loading_a_skill_spends_no_tool_round_up_to_four_a_turn(client, user_and_token, tmp_curio, scripted):
    """Four loads are free; each further one spends a round, so a model that
    keeps loading still meets the round cap: here the eighth request is the
    one the cap drops, after seven loads."""
    from utk_curio.backend.app.agents.application import tool_rounds

    skill_runs = _skill_runs()
    assert (skill_runs.FREE_READS, tool_rounds.MAX_TOOL_ROUNDS) == (4, 3)
    pid = _project(client, scripted)
    att = _attach(client, scripted, pid, NB)
    asked = FEATURE_SKILLS[:8]
    testing_provider.push_replies(*[_read(name) for name in asked], "Done.")
    _run(client, scripted, pid, att)
    calls = _run_calls()
    assert len(calls) == 8, len(calls)
    record = _turns(client, scripted, pid, att)[-1]["execution"]
    assert record["skillsLoaded"] == asked[:7]
    assert [c["tool"] for c in record["toolCalls"]] == ["skill.read"] * 7
    # The seventh load spent the last round, and its result says so.
    from utk_curio.backend.app.agents.domain import agent_text

    assert agent_text.message("tool-round.final-round") in calls[7][-1]["content"]
    assert agent_text.message("tool-round.final-round") not in calls[6][-1]["content"]


def test_a_refused_load_is_a_correction_the_model_can_make(client, user_and_token, tmp_curio, scripted):
    """A name the run does not list is refused with the names it does, as a
    parameter the model fixes, and the run goes on."""
    from utk_curio.backend.app.agents.domain import agent_text

    pid = _project(client, scripted)
    att = _attach(client, scripted, pid, DF)
    testing_provider.push_replies(_read("widgets"), _read("catalogs"), "Found it.")
    body = _run(client, scripted, pid, att)
    assert body["reply"].endswith("Found it.")
    calls = _run_calls()
    assert agent_text.message(
        "skills.not-listed", name="'widgets'", names="catalogs, data-sources") in calls[1][-1]["content"]
    assert _wrapped(calls[2][-1]["content"]) == ["catalogs"]
    record = _turns(client, scripted, pid, att)[-1]["execution"]
    assert [(c["tool"], c["status"]) for c in record["toolCalls"]] == [("skill.read", "refused"), ("skill.read", "ok")]
    assert record["skillsLoaded"] == ["catalogs"]


# --- Handed skills -----------------------------------------------------------------------


def test_a_chat_on_a_node_is_handed_its_nodes_skills_and_still_lists_the_rest(
    client, user_and_token, tmp_curio, scripted,
):
    from utk_curio.backend.app.agents.domain import agent_text

    pid = _project(client, scripted, nodes=[{"id": "chart", "type": VEGA, "content": "{}", "x": 0, "y": 0}])
    att = _attach(client, scripted, pid, NB, {"kind": "node", "targetId": "chart"})
    testing_provider.push_replies(_read("vega-lite-maps"), "Done.")
    _run(client, scripted, pid, att)
    calls = _run_calls()
    system = calls[0][0]
    assert _kinds(system)[:4] == ["preamble", "skill-catalog", "skills", "instruction"], _kinds(system)
    assert _wrapped(_slot(system, "skills")) == [*VEGA_SKILLS, *NB_INSTRUCTION]
    assert "<skill_resources>" not in _slot(system, "skills"), "the shipped skills hold no other files"
    assert _listed(_slot(system, "skill-catalog")) == NB_SKILLS
    assert agent_text.message("skills.already-loaded", name="vega-lite-maps") in calls[1][-1]["content"]
    record = _turns(client, scripted, pid, att)[-1]["execution"]
    assert record["pins"]["skills"] == {"catalog": NB_SKILLS, "handed": [*VEGA_SKILLS, *NB_INSTRUCTION]}
    assert "skillsLoaded" not in record


@pytest.mark.parametrize("coord, capability, inputs, handed", [
    (NB, "node.content.generate", {"nodeType": CA}, [*CODE_SKILLS, "data-sources"]),
    (NB, "node.content.generate", {"nodeType": VEGA}, [*VEGA_SKILLS, "data-sources"]),
    (NB, "node.content.generate", {"nodeContext": {"nodeType": AUTK}}, [*AUTK_SKILLS, "data-sources"]),
    (NB, "node.content.generate", {"nodeId": "tile"}, [*AUTK_SKILLS, "data-sources"]),
    (NB, "node.content.generate", {"nodeType": EDIT}, [*CODE_SKILLS, "map-edits", "data-sources"]),
    (NB, "node.content.generate", {"nodeType": POOL}, ["interaction-edges", "data-sources"]),
    (NB, "node.content.generate", {"nodeType": UNKNOWN}, ["data-sources"]),
    (NB, "package.build", {"packageIntent": "a counter"}, [*CODE_SKILLS, "package-contract", "reuse-first"]),
    (NB, "package.extend", {}, [*CODE_SKILLS, "package-contract", "reuse-first"]),
    (NB, "node.kind.author", {}, [*CODE_SKILLS, "package-contract", "reuse-first"]),
    (NB, "package.recommend", {"mission": "count"}, ["reuse-first"]),
    (NB, "node.build", {"nodeIntent": "count the rows"}, [*CODE_SKILLS, *NB_INSTRUCTION]),
    (NB, "node.build", {"nodeId": "chart"}, [*VEGA_SKILLS, "node-functions", "catalogs", *NB_INSTRUCTION]),
    (NB, "dataset.fetch.author", {"nodeIntent": "fetch the stations"}, [*CODE_SKILLS, *NB_INSTRUCTION]),
    (DF, "dataset.discover", {"mission": "air quality"}, ["catalogs"]),
    (DF, "dataset.discover", {"nodeContext": {"nodeType": "curio.builtin/data-loading"}}, ["catalogs"]),
    (DF, "dataset.select", {}, []),
    (RS, "research.verify", {"url": "https://example.org"}, ["fact-checking"]),
    (RS, "research.notes.compose", {"question": "why"}, ["research-notes"]),
    (DFB, "dataflow.orchestrate", {"mission": "chart the stations"}, ["reuse-first"]),
    (NB, "node.content.generate", {"intent": "a node for no node"}, [*CODE_SKILLS, "data-sources"]),
    (READER, "dataflow.explain", {}, [*CODE_SKILLS, "autark", "vega-lite-starter", "autark-starter",
                                       "vega-lite-maps", "interaction-edges", "scenarios", "dashboards"]),
    (PLANNER, "workflow.plan.create", {}, ["interaction-edges", "scenarios", "dashboards"]),
    (PLANNER, "workflow.keywords.extract", {"workflowGoal": "count"}, []),
    (EVALUATOR, "content.quality.evaluate", {"nodeContext": {"nodeType": VEGA}}, VEGA_SKILLS),
    (EVALUATOR, "content.quality.evaluate", {}, []),
])
def test_a_run_with_no_tools_is_handed_the_skills_its_task_needs(tmp_curio, coord, capability, inputs, handed):
    """A run that writes or checks a node, the node's; a run that writes
    code for no node, node code's; a mode that reads the dataflow, those of
    its nodes and features; and a capability's own, here the Dataset Finder's
    ``catalogs``, node code's for the Node Builder's runs that build a node
    for another agent, after the named node's, and the procedures of each
    mode, last. A capability with no instruction of its own runs the agent's
    instruction, so it is also handed the instruction's skills: the Node
    Builder's runs that build a node, and the Dataflow Builder's
    ``reuse-first``. Never a skill the agent does not name."""
    skill_runs = _skill_runs()
    spec = {"dataflow": {
        "nodes": [
            {"id": "count", "type": CA, "content": "return 1"},
            {"id": "chart", "type": VEGA, "content": "{}", "dashboardPinned": True},
            {"id": "tile", "type": AUTK, "content": "{}"},
            {"id": "pool", "type": POOL, "content": ""},
        ],
        "edges": [{"id": "e1", "source": "chart", "target": "pool", "type": "Interaction",
                   "sourceHandle": "in/out", "targetHandle": "in/out"}],
        "scenarios": [{"id": "s1", "name": "Hotter", "nodes": ["count"]}],
    }}
    manifest = _manifest(coord)
    run = skill_runs.for_delegated(KEY, PID, manifest, capability, inputs, spec, _preamble(coord))
    assert _names(run.handed) == handed
    assert set(handed) <= set(manifest.skills), "a run was handed a skill its agent does not name"
    assert run.catalog == () and skill_runs.grants([], run) == []


def test_a_delegated_run_carries_its_skills_after_its_preamble_and_pins_them(client, user_and_token, tmp_curio):
    """The system turn a delegated run sends: the preamble, then the skills
    it is handed, each wrapped, then its instruction; a run handed none has no
    such slot. Its record names them."""
    from utk_curio.backend.app.agents.application import delegation

    user, token = user_and_token
    key = _user_dir_key(user)
    pid = _project(client, _auth(token), nodes=[{"id": "chart", "type": VEGA, "content": "{}", "x": 0, "y": 0}])
    for coord, capability, inputs, handed in (
        (NB, "node.content.generate", {"nodeType": VEGA, "intent": "a chart"}, [*VEGA_SKILLS, "data-sources"]),
        (NB, "package.recommend", {"mission": "count the trees"}, ["reuse-first"]),
        (DF, "dataset.select", {"mission": "count the trees"}, []),
    ):
        testing_provider.reset()
        status, _text, record = delegation.run_delegate(
            key, pid, coord, capability, inputs, ENDPOINT,
            parent_execution_id="p", parent_coord="agent.curio.dataflow-builder@1", attachment_id=None,
        )
        assert status == "ok"
        (system, *_), = testing_provider.captured()
        if handed:
            assert _kinds(system)[:3] == ["preamble", "skills", "instruction"], _kinds(system)
            assert record["pins"]["skills"] == {"handed": handed}
        else:
            assert "skills" not in _kinds(system) and "skills" not in record["pins"]
        assert _wrapped(_slot(system, "skills")) == handed
        assert "skill.read" not in system["content"], "a run with no tools was told of skill.read"
    testing_provider.reset()


# --- A Solve round after a refusal -------------------------------------------------------


@pytest.mark.parametrize("inputs, refused, added", [
    ({"nodeType": AUTK}, "dashboard-tile", ["dashboards"]),
    ({"nodeType": AUTK}, "document-invalid", []),
    ({"nodeType": VEGA}, "document-invalid", []),
    ({"nodeType": UNKNOWN}, "document-invalid", ["autark", "vega-lite-starter"]),
    ({"nodeType": UNKNOWN}, "map-edits", ["map-edits"]),
    ({"nodeType": UNKNOWN}, "ungrounded-code", ["node-functions"]),
    ({"nodeType": UNKNOWN}, "ungrounded-source", ["catalogs"]),
    ({"nodeType": UNKNOWN}, "execution-error", []),
])
def test_a_refused_round_is_handed_the_skills_that_answer_the_check(tmp_curio, inputs, refused, added):
    """The next round after a check refused is handed, beside its node's
    skills, those whose ``curio-refusals`` names that check's kind; of those
    serving a node's behavior, only its node's: the document check is
    answered by Autark's skill for an Autark node and the Vega-Lite starter
    for a chart."""
    skill_runs = _skill_runs()
    manifest = _manifest(NB)
    before = skill_runs.for_delegated(KEY, PID, manifest, "node.content.generate", inputs, None, _preamble(NB))
    after = skill_runs.for_delegated(KEY, PID, manifest, "node.content.generate", inputs, None, _preamble(NB),
                                     refused=refused)
    assert _names(after.handed) == _names(before.handed) + added


def test_every_refusal_a_skill_answers_is_a_kind_a_check_of_solve_records():
    """``curio-refusals`` names the kinds Solve's checks record on a refused
    round: the Map Editor's, the dashboard's, the document check's and the
    two grounding gates'."""
    from utk_curio.backend.app.agents.application import source_grounding
    from utk_curio.backend.app.agents.application.solve import rounds
    from utk_curio.backend.app.agents.domain import dashboards, map_edits, skills

    named = {kind for skill in skills.shipped_skills()
             for kind in str(skill.metadata.get("curio-refusals") or "").split()}
    assert named == {map_edits.KIND, dashboards.KIND, "document-invalid", source_grounding.CODE_KIND,
                     source_grounding.SOURCE_KIND}
    assert named <= set(rounds._HEAD_FIRST_KINDS)


def test_a_solve_round_is_handed_the_skill_the_refusal_before_it_names(app, tmp_curio):
    """A node whose template names no behavior is handed no skill. The
    grounding gate refuses its first round for a function Curio does not give
    node code, and the round after it, run by the real delegation, is handed
    the functions skill, which answers that check."""
    from utk_curio.backend.app.agents.application.solve import rounds
    from utk_curio.backend.tests.test_agents.test_routes_proposals import TestNodeCreate
    from utk_curio.backend.tests.test_agents.test_verified_rounds import _drive, _Exec, _Resolution

    TestNodeCreate()._write_builtin_package(KEY)
    node = {"id": "n1", "type": CA, "goal": "count the rows", "content": "", "x": 0, "y": 0}
    spec = {"dataflow": {"nodes": [node], "edges": [], "name": "wf", "task": "count rows"}}
    projects_storage.write_spec(KEY, PID, spec)
    testing_provider.reset()
    testing_provider.push_replies("return curio_fetch_rows()", "df = input_0[0]\nreturn df")
    try:
        with app.test_request_context():
            gen = rounds._verified_content_rounds(
                KEY, PID, spec=spec, node=node, resolution=_Resolution(), config=ENDPOINT,
                parent_execution_id="exec-1", parent_coord="agent.curio.dataflow-builder@1",
                attachment_id=None, exec_fn=_Exec(), grounding_loop_ctx={"granted": [], "manifest": None},
            )
            _events, outcome = _drive(gen)
        generations = [messages[0] for messages in testing_provider.captured()][:2]
    finally:
        testing_provider.reset()
    assert [attempt["kind"] for attempt in outcome["attempts"]][:1] == ["ungrounded-code"], outcome["attempts"]
    first, second = generations
    assert "skills" not in _kinds(first), _kinds(first)
    assert _wrapped(_slot(second, "skills")) == ["node-functions"]
    assert outcome["delegations"][1]["pins"]["skills"] == {"handed": ["node-functions"]}


def test_the_loop_hands_the_round_after_the_map_editor_refused_that_check_s_kind(app, tmp_curio):
    """The verified loop passes its runner the kind of the refusal each round
    answers: none for the first, the Map Editor's for the round after the Map
    Editor check refused its code."""
    from utk_curio.backend.app.agents.application.solve import rounds
    from utk_curio.backend.tests.test_agents import test_map_edits_grounding as grounding
    from utk_curio.backend.tests.test_agents.test_verified_rounds import KEY as ROUNDS_KEY, PID as ROUNDS_PID
    from utk_curio.backend.tests.test_agents.test_verified_rounds import _drive, _Resolution

    grounding._seed_builtin(ROUNDS_KEY)
    spec = grounding._solve_spec()
    node = spec["dataflow"]["nodes"][1]
    projects_storage.write_spec(ROUNDS_KEY, ROUNDS_PID, spec)
    replies = [grounding.UNREADABLE, grounding.REMOVE_TWO]
    seen: list = []

    def _runner(inputs, refused=None):
        seen.append(refused)
        return "ok", replies.pop(0) if replies else grounding.REMOVE_TWO, {"executionId": f"c{len(seen)}"}

    sandbox = grounding._Sandbox({grounding.REMOVE_TWO_MARK: grounding._sandbox_says([{"op": "remove", "ids": [2]}])})
    with app.test_request_context():
        gen = rounds._verified_content_rounds(
            ROUNDS_KEY, ROUNDS_PID, spec=spec, node=node, resolution=_Resolution(), config=None,
            parent_execution_id="exec-1", parent_coord="agent.curio.dataflow-builder@1", attachment_id="att-1",
            exec_fn=sandbox, grounding_loop_ctx={"granted": [], "manifest": None}, delegate_runner=_runner,
        )
        _events, outcome = _drive(gen)
    assert [attempt["kind"] for attempt in outcome["attempts"]] == ["map-edits", "executed"], outcome["attempts"]
    assert seen == [None, "map-edits"]


# --- Caching -----------------------------------------------------------------------------


@pytest.mark.parametrize("kinds, marked", [
    (["preamble", "skill-catalog", "skills", "instruction", "tool-protocol", "runtime"], [1, 2]),
    (["preamble", "skill-catalog", "instruction", "tool-protocol"], [1]),
    (["preamble", "skills", "instruction", "configuration"], [0, 1]),
    (["preamble", "instruction", "runtime"], [0]),
    (["skill-catalog", "instruction", "tool-protocol"], [0]),
    (["instruction", "tool-protocol"], []),
])
def test_anthropic_caches_up_to_the_shared_slots_and_again_after_the_skills(kinds, marked):
    """Two cache breakpoints: after the slots an agent's runs share (the
    preamble and the catalog), and after the skills a run is handed."""
    from utk_curio.backend.app.agents.infrastructure import providers

    system = {"role": "system", "content": "", "slots": [{"kind": kind, "text": kind.upper()} for kind in kinds]}
    blocks = providers._anthropic_system([system], not_given=None)
    assert [at for at, block in enumerate(blocks) if "cache_control" in block] == marked
    assert all(block["cache_control"] == {"type": "ephemeral"} for block in blocks if "cache_control" in block)
    assert [block["text"] for block in blocks] == [kind.upper() for kind in kinds]


# --- The manifest ------------------------------------------------------------------------


def _parse(**fields):
    from utk_curio.backend.app.agents.domain.manifest import parse_agent_manifest

    raw = {
        "id": "agent.test.skilled", "name": "Skilled", "category": "canvas", "version": "1.0.0",
        "capabilities": [{"id": "conversation.respond", "contractVersion": "1"}],
        "provenance": {"publisher": "me", "trust": "imported"},
    }
    raw.update(fields)
    return parse_agent_manifest(raw)


def test_a_manifest_names_its_skills_and_a_capability_its_own():
    assert _parse().skills is None, "no field is every skill Curio ships"
    assert _parse(skills=[]).skills == ()
    assert _parse(skills=["widgets", "street-trees"]).skills == ("widgets", "street-trees")
    m = _parse(capabilities=[{"id": "conversation.respond", "contractVersion": "1", "skills": ["catalogs"]}])
    assert m.capability("conversation.respond").skills == ("catalogs",)
    assert _parse().capability("conversation.respond").skills == ()
    # The instruction names the skills every run of it is handed.
    m = _parse(prompts={"instruction": {"path": "prompts/chat.md", "skills": ["reuse-first", "catalogs"]}})
    assert m.instruction_skills == m.prompts["instruction"].skills == ("reuse-first", "catalogs")
    assert _parse(prompts={"instruction": {"path": "prompts/chat.md"}}).instruction_skills == ()
    assert _parse().instruction_skills == (), "a manifest with no instruction names none"


@pytest.mark.parametrize("prompts, capability, named", [
    ({"system": {"path": "curio:default_preamble.md", "skills": ["catalogs"]}}, {}, "system"),
    ({"respond": {"path": "prompts/respond.md", "skills": ["catalogs"]}}, {"instruction": "respond"}, "respond"),
    ({"autk-grammar": {"path": "prompts/autk.md", "runs": "Write an Autark document", "skills": ["autark"]}},
     {}, "autk-grammar"),
])
def test_only_the_instruction_names_the_skills_its_runs_are_handed(prompts, capability, named):
    """The preamble, a mode's prompt and a prompt run in a mode's place name
    no skills: a mode's own are its capability's ``skills``."""
    from utk_curio.backend.app.agents.domain.manifest import AgentManifestError

    capabilities = [{"id": "conversation.respond", "contractVersion": "1", **capability}]
    with pytest.raises(AgentManifestError, match=re.escape(f"prompts.{named}.skills: only the instruction")):
        _parse(prompts={"instruction": {"path": "prompts/chat.md"}, **prompts}, capabilities=capabilities)


def test_every_run_of_the_instruction_is_handed_its_skills_and_a_modes_run_is_not(tmp_curio, caplog):
    """An agent's chat, on the canvas or on a node, and a delegated run of a
    capability with no instruction of its own run the instruction, so each is
    handed the skills it names, after the ones that serve its node, whatever
    the agent's ``skills`` are. A mode runs its own prompt and is handed its
    capability's. A name Curio ships no skill by is left out and logged."""
    skill_runs = _skill_runs()
    m = _parse(
        skills=["widgets"],
        prompts={"system": {"path": "curio:default_preamble.md"},
                 "instruction": {"path": "prompts/chat.md", "skills": ["reuse-first", "no-such-skill", "nodes"]},
                 "respond": {"path": "prompts/respond.md"}},
        capabilities=[{"id": "node.build", "contractVersion": "1"},
                      {"id": "notes.compose", "contractVersion": "1", "instruction": "respond",
                       "skills": ["research-notes"]}],
    )
    preamble = _preamble(NB)
    spec = {"dataflow": {"nodes": [{"id": "chart", "type": VEGA, "content": "{}"}], "edges": []}}
    with caplog.at_level("WARNING"):
        canvas = skill_runs.for_chat(KEY, PID, m, spec, {"kind": "canvas"}, preamble, [])
        on_a_chart = skill_runs.for_chat(KEY, PID, m, spec, {"kind": "node", "targetId": "chart"}, preamble, [])
        built = skill_runs.for_delegated(KEY, PID, m, "node.build", {"intent": "a node"}, spec, preamble)
        mode = skill_runs.for_delegated(KEY, PID, m, "notes.compose", {"question": "why"}, spec, preamble)
    # The core skill is in the preamble already, so no run holds it twice.
    assert _names(canvas.handed) == ["reuse-first"] and _names(canvas.catalog) == ["widgets"]
    assert _names(on_a_chart.handed) == ["widgets", "reuse-first"]
    assert _names(built.handed) == ["reuse-first"]
    assert _names(mode.handed) == ["research-notes"]
    assert "no-such-skill" in caplog.text and "names a skill Curio does not ship" in caplog.text


@pytest.mark.parametrize("skills_field, said", [
    ("widgets", "must be a list of skill names"),
    (["Widgets"], "is no skill's name"),
    (["street_trees"], "is no skill's name"),
    (["a" * 65], "is no skill's name"),
    ([7], "is no skill's name"),
    (["widgets", "widgets"], "duplicate skill 'widgets'"),
])
def test_a_manifest_that_names_a_skill_wrongly_is_refused(skills_field, said):
    from utk_curio.backend.app.agents.domain.manifest import AgentManifestError

    with pytest.raises(AgentManifestError, match=re.escape(said)):
        _parse(skills=skills_field)
    with pytest.raises(AgentManifestError, match=re.escape(said)):
        _parse(capabilities=[{"id": "conversation.respond", "contractVersion": "1", "skills": skills_field}])
    with pytest.raises(AgentManifestError, match=re.escape(said)):
        _parse(prompts={"instruction": {"path": "prompts/chat.md", "skills": skills_field}})


def test_the_schema_declares_skills_by_the_specifications_names():
    from utk_curio.backend.app.agents.domain import skills

    schema = json.loads((Path(__file__).resolve().parents[4] / "docs" / "schemas" / "agent-package.v1.json")
                        .read_text(encoding="utf-8"))
    for field in (schema["properties"]["skills"], schema["properties"]["capabilities"]["items"]["properties"]["skills"],
                  schema["properties"]["prompts"]["additionalProperties"]["properties"]["skills"]):
        assert field["type"] == "array" and field["uniqueItems"] is True
        assert field["items"]["maxLength"] == skills.NAME_MAX
        pattern = re.compile(field["items"]["pattern"])
        for name in ("widgets", "vega-lite-maps", "a", "v2-maps", "a" * 64):
            assert pattern.match(name) and skills.is_name(name), name
        for name in ("Widgets", "-maps", "maps-", "vega--lite", "street_trees"):
            assert not pattern.match(name) and not skills.is_name(name), name
