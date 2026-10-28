"""Skills in the Agent Catalog, and the skills an account adds to an agent or removes from it.

An account changes an agent's skills in the agent's details: **Add skill**,
**Remove** and **Restore**, kept in ``.curio/users/<key>/agent-skills.json``
(``infrastructure/agent_skills.py``) and read when each run starts, as the
model chosen for the agent is, so a run's catalog and the skills it is handed
follow them. The core skills and a mode's own skills cannot be removed, a
hosted guest may change nothing, and a chat message that starts with
``/<name>`` hands that skill to its run. The skills listing names what each
skill serves and the agents that use it. Runs go through the scripted
provider (``testing_provider``).

New names are read inside each test, so this module imports on a checkout
without them and each test fails on its own.
"""

from __future__ import annotations

import json
import os
import re
import stat
from unittest.mock import patch

import pytest

from utk_curio.backend.app.agents.infrastructure import testing_provider
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.tests._support.agent_routes import _auth

NB = "agent.curio.node-builder@1"
DF = "agent.curio.dataset-finder@1"
RS = "agent.curio.researcher@1"
PLANNER = "agent.curio.dataflow-planner@1"
CORE = ["compatibility", "node-control", "nodes"]
VEGA = "curio.builtin/vis-vega"


def _store():
    from utk_curio.backend.app.agents.infrastructure import agent_skills

    return agent_skills


def _skill_runs():
    from utk_curio.backend.app.agents.application import skill_runs

    return skill_runs


def _rows_url(coord: str) -> str:
    return f"/api/agents/definitions/{coord}/skills"


def _names(rows: dict) -> list[str]:
    return [row["name"] for row in rows["skills"]]


def _row(rows: dict, name: str) -> dict:
    return next(row for row in rows["skills"] if row["name"] == name)


def _listed(system: dict) -> list[str]:
    catalog = next((slot["text"] for slot in system.get("slots") or [] if slot["kind"] == "skill-catalog"), "")
    return re.findall(r"<name>([^<]+)</name>", catalog)


def _wrapped(system: dict) -> list[str]:
    held = next((slot["text"] for slot in system.get("slots") or [] if slot["kind"] == "skills"), "")
    return re.findall(r'<skill_content name="([^"]+)">', held)


@pytest.fixture()
def scripted(client, user_and_token):
    """A scripted configuration as the account's default, on the fenced protocol."""
    testing_provider.reset()
    _, token = user_and_token
    h = _auth(token)
    created = client.post("/api/agents/llm/configs", headers=h, json={
        "label": "Scripted", "apiType": "testing", "model": "scripted"})
    assert created.status_code == 201, created.get_json()
    client.put("/api/agents/llm/default", headers=h, json={"configId": created.get_json()["config"]["id"]})
    yield h
    testing_provider.reset()


def _project(client, headers, nodes=()) -> str:
    body = {"name": "p", "spec": {"dataflow": {"nodes": list(nodes), "edges": [], "packages": []}}, "outputs": []}
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


def _tail(payload: dict, prose: str = "Reading it.") -> str:
    return f"{prose}\n\n```curio.v1\n{json.dumps(payload)}\n```"


# --- The store ---------------------------------------------------------------------


def test_the_store_keeps_each_agents_change_in_an_owner_only_file(user_and_token, tmp_curio):
    agent_skills = _store()
    user, _ = user_and_token
    key = _user_dir_key(user)
    store = agent_skills.default_store()
    assert store.read(key) == {} and not store.choice(key, "agent.curio.dataset-finder")
    kept = store.update(key, "agent.curio.dataset-finder",
                        lambda current: agent_skills.SkillChoice(added=("widgets", "widgets", "Not A Name")))
    assert kept == agent_skills.SkillChoice(added=("widgets",))
    path = store.path(key)
    assert path.name == "agent-skills.json" and path.parent.name == key
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert json.loads(path.read_text()) == {
        "version": 1, "agents": {"agent.curio.dataset-finder": {"added": ["widgets"], "removed": []}},
    }
    store.clear(key, "agent.curio.dataset-finder")
    assert json.loads(path.read_text()) == {"version": 1, "agents": {}}


def test_an_unreadable_store_is_an_error_never_an_empty_one(user_and_token, tmp_curio):
    agent_skills = _store()
    user, _ = user_and_token
    key = _user_dir_key(user)
    store = agent_skills.default_store()
    store.update(key, "agent.curio.researcher", lambda current: agent_skills.SkillChoice(removed=("provenance",)))
    store.path(key).write_text("{not json", encoding="utf-8")
    with pytest.raises(agent_skills.AgentSkillsError):
        store.read(key)
    # A run starts all the same, on the skills the manifest names.
    from utk_curio.backend.app.agents.domain import builtin

    skill_runs = _skill_runs()
    assert not skill_runs.account_choice(key, builtin.get_builtin_manifest(RS))


# --- The listing -------------------------------------------------------------------


def test_the_listing_names_every_skill_with_what_it_serves_and_who_uses_it(client, user_and_token, tmp_curio):
    _, token = user_and_token
    body = client.get("/api/agents/skills", headers=_auth(token)).get_json()
    assert body["editable"] is True and body["reason"] is None
    cards = {card["name"]: card for card in body["skills"]}
    assert len(cards) == 16
    assert sorted(name for name, card in cards.items() if card["core"]) == CORE
    widgets = cards["widgets"]
    assert widgets["description"].startswith("Use this skill")
    assert widgets["author"] == "curio" and widgets["license"] == "MIT" and widgets["files"] == []
    # Its kinds of node come from the templates whose behavior it serves, the
    # base package's first.
    assert widgets["nodeKinds"][:3] == ["Data Loading", "Data Export", "Data Transformation"]
    assert "Vega-Lite" in widgets["nodeKinds"] and "Autark" in widgets["nodeKinds"]
    assert cards["scenarios"]["features"] == ["scenario-boxes"] and cards["scenarios"]["nodeKinds"] == []
    assert cards["provenance"]["nodeKinds"] == [] and cards["provenance"]["features"] == []
    users = {agent["name"]: agent for agent in cards["catalogs"]["agents"]}
    assert {"Researcher", "Node Builder", "Dataflow Builder", "Dataset Finder"} <= set(users)
    assert users["Dataset Finder"]["card"] is True and users["Dataset Finder"]["always"] is True
    assert users["Dataflow Reader"]["card"] is False
    assert {agent["name"] for agent in cards["nodes"]["agents"]} >= {"Researcher", "Dataset Finder"}


def test_one_skill_reads_as_an_agent_reads_it(client, user_and_token, tmp_curio):
    from utk_curio.backend.app.agents.domain import agent_text

    _, token = user_and_token
    body = client.get("/api/agents/skills/widgets", headers=_auth(token)).get_json()
    assert body == {"name": "widgets", "text": agent_text.skill_text("widgets"), "files": []}
    assert not body["text"].startswith("---") and "{{" not in body["text"]
    assert client.get("/api/agents/skills/no-such-skill", headers=_auth(token)).status_code == 404


# --- An agent's skills ---------------------------------------------------------------


def test_an_agents_skills_are_its_core_ones_its_own_and_its_modes(client, user_and_token, tmp_curio):
    _, token = user_and_token
    rows = client.get(_rows_url(DF), headers=_auth(token)).get_json()
    assert _names(rows) == [*CORE, "catalogs"]
    assert all(_row(rows, name)["core"] and not _row(rows, name)["removable"] for name in CORE)
    catalogs = _row(rows, "catalogs")
    assert catalogs["modes"] == ["Find datasets"] and catalogs["removable"] is False
    assert {skill["name"] for skill in rows["addable"]} == {
        "node-functions", "widgets", "selection-chips", "autark", "vega-lite-starter", "autark-starter",
        "vega-lite-maps", "interaction-edges", "map-edits", "scenarios", "dashboards", "provenance",
    }
    assert rows["changed"] is False and rows["editable"] is True and rows["reason"] is None
    researcher = client.get(_rows_url(RS), headers=_auth(token)).get_json()
    assert _row(researcher, "provenance")["removable"] is True and researcher["addable"] == []


def test_add_remove_and_restore_change_only_this_accounts_list(client, user_and_token, tmp_curio):
    user, token = user_and_token
    h = _auth(token)
    added = client.post(_rows_url(DF), json={"skill": "widgets"}, headers=h)
    assert added.status_code == 200, added.get_json()
    rows = added.get_json()
    assert _names(rows)[-1] == "widgets" and _row(rows, "widgets")["added"] is True
    assert _row(rows, "widgets")["removable"] is True and rows["changed"] is True
    assert "widgets" not in {skill["name"] for skill in rows["addable"]}
    # Adding it again changes nothing.
    assert client.post(_rows_url(DF), json={"skill": "widgets"}, headers=h).get_json() == rows
    path = _store().default_store().path(_user_dir_key(user))
    assert json.loads(path.read_text())["agents"] == {
        "agent.curio.dataset-finder": {"added": ["widgets"], "removed": []},
    }

    removed = client.delete(f"{_rows_url(DF)}/widgets", headers=h).get_json()
    assert "widgets" not in _names(removed) and removed["changed"] is False

    gone = client.delete(f"{_rows_url(RS)}/provenance", headers=h).get_json()
    assert "provenance" not in _names(gone) and gone["changed"] is True
    assert {skill["name"] for skill in gone["addable"]} == {"provenance"}
    back = client.post(_rows_url(RS), json={"skill": "provenance"}, headers=h).get_json()
    assert _names(back) == _names(client.get(_rows_url(RS), headers=h).get_json())
    assert back["changed"] is False and _row(back, "provenance")["added"] is False

    client.delete(f"{_rows_url(RS)}/provenance", headers=h)
    client.post(_rows_url(DF), json={"skill": "map-edits"}, headers=h)
    restored = client.delete(_rows_url(RS), headers=h).get_json()
    assert "provenance" in _names(restored) and restored["changed"] is False
    # Restore is the agent's own: the Dataset Finder keeps what was added to it.
    assert "map-edits" in _names(client.get(_rows_url(DF), headers=h).get_json())


@pytest.mark.parametrize(("method", "url", "body", "status", "said"), [
    ("post", _rows_url(DF), {"skill": "nodes"}, 400, "every call"),
    ("delete", f"{_rows_url(DF)}/nodes", None, 400, "every call"),
    ("delete", f"{_rows_url(DF)}/catalogs", None, 400, "Find datasets"),
    ("delete", f"{_rows_url(NB)}/widgets", None, 400, "always held"),
    ("delete", f"{_rows_url(DF)}/provenance", None, 404, "has no skill provenance"),
    ("post", _rows_url(DF), {"skill": "no-such-skill"}, 404, "ships no skill"),
    ("post", _rows_url(DF), {"name": "widgets"}, 400, "send {skill}"),
    ("post", _rows_url(PLANNER), {"skill": "widgets"}, 404, "no agent definition"),
    ("get", _rows_url("agent.nobody.none@1"), None, 404, "no agent definition"),
])
def test_a_change_the_rules_forbid_is_refused_and_nothing_is_saved(
    client, user_and_token, tmp_curio, method, url, body, status, said,
):
    user, token = user_and_token
    call = getattr(client, method)
    resp = call(url, json=body, headers=_auth(token)) if body is not None else call(url, headers=_auth(token))
    assert resp.status_code == status, resp.get_json()
    assert said in resp.get_json()["error"]
    assert not _store().default_store().path(_user_dir_key(user)).exists()


def test_a_hosted_guest_reads_an_agents_skills_but_changes_none(client, guest_user_and_token, tmp_curio):
    from utk_curio.backend import config

    _, token = guest_user_and_token
    h = _auth(token)
    with patch.object(config, "CURIO_NO_AUTH", False):
        rows = client.get(_rows_url(DF), headers=h).get_json()
        assert rows["editable"] is False and "guest" in rows["reason"]
        assert rows["addable"] == [] and not any(row["removable"] for row in rows["skills"])
        assert client.get("/api/agents/skills", headers=h).get_json()["editable"] is False
        for resp in (
            client.post(_rows_url(DF), json={"skill": "widgets"}, headers=h),
            client.delete(f"{_rows_url(RS)}/provenance", headers=h),
            client.delete(_rows_url(RS), headers=h),
        ):
            assert resp.status_code == 403 and "guest" in resp.get_json()["error"]


# --- Runs follow the account's changes ---------------------------------------------------


def test_a_chat_lists_a_skill_added_to_its_agent_and_never_one_removed(client, user_and_token, tmp_curio, scripted):
    pid = _project(client, scripted)
    finder = _attach(client, scripted, pid, DF)
    researcher = _attach(client, scripted, pid, RS)
    client.post(_rows_url(DF), json={"skill": "map-edits"}, headers=scripted)
    client.delete(f"{_rows_url(RS)}/provenance", headers=scripted)
    testing_provider.push_reply("Hello.")
    testing_provider.push_reply("Hello.")
    _run(client, scripted, pid, finder)
    _run(client, scripted, pid, researcher)
    (finder_system, *_), (researcher_system, *_) = _run_calls()
    assert _listed(finder_system) == ["catalogs", "map-edits"]
    assert "provenance" not in _listed(researcher_system) and "map-edits" in _listed(researcher_system)
    pins = _turns(client, scripted, pid, finder)[-1]["execution"]["pins"]
    assert pins["skills"] == {"catalog": ["catalogs", "map-edits"]}
    assert "skill.read" in pins["tools"]

    # Restored, the Researcher lists it again on its next run.
    client.delete(_rows_url(RS), headers=scripted)
    testing_provider.reset()
    testing_provider.push_reply("Hello again.")
    _run(client, scripted, pid, researcher)
    (system, *_), = _run_calls()
    assert "provenance" in _listed(system)


def test_a_mode_is_handed_only_the_skills_its_agent_holds_for_the_account(user_and_token, tmp_curio):
    """A delegated run reads the same change: the Node Builder's content mode for
    a Vega-Lite node goes without the skill the account removed from it."""
    from utk_curio.backend.app.agents.domain import builtin

    skill_runs = _skill_runs()
    agent_skills = _store()
    user, _ = user_and_token
    key = _user_dir_key(user)
    manifest = builtin.get_builtin_manifest(NB)
    preamble = builtin.read_prompt_text(NB, "system")
    spec = {"dataflow": {"nodes": [{"id": "chart", "type": VEGA}], "edges": []}}
    inputs = {"nodeId": "chart", "intent": "a bar chart"}

    def handed():
        run = skill_runs.for_delegated(key, "p", manifest, "node.content.generate", inputs, spec, preamble)
        return [skill.name for skill in run.handed]

    assert "vega-lite-maps" in handed()
    agent_skills.default_store().update(
        key, manifest.agent_id, lambda current: agent_skills.SkillChoice(removed=("vega-lite-maps",)),
    )
    assert "vega-lite-maps" not in handed() and "vega-lite-starter" in handed()


def test_a_skill_removed_after_a_turn_loaded_it_is_no_longer_kept(client, user_and_token, tmp_curio, scripted):
    pid = _project(client, scripted)
    att = _attach(client, scripted, pid, RS)
    testing_provider.push_reply(_tail({"toolRequest": {"tool": "skill.read", "params": {"name": "provenance"}}}))
    testing_provider.push_reply("Loaded.")
    _run(client, scripted, pid, att)
    assert _turns(client, scripted, pid, att)[-1]["execution"]["skillsLoaded"] == ["provenance"]

    client.delete(f"{_rows_url(RS)}/provenance", headers=scripted)
    testing_provider.reset()
    testing_provider.push_reply("Without it.")
    _run(client, scripted, pid, att, "and now?")
    (system, *_), = _run_calls()
    assert "provenance" not in _listed(system) and "provenance" not in _wrapped(system)
    assert "kept" not in _turns(client, scripted, pid, att)[-1]["execution"]["pins"].get("skills", {})


# --- /<name> in a chat message -----------------------------------------------------------


def test_a_message_that_names_a_skill_hands_it_to_the_run_and_the_conversation_keeps_it(
    client, user_and_token, tmp_curio, scripted,
):
    pid = _project(client, scripted)
    att = _attach(client, scripted, pid, NB)
    testing_provider.push_reply("Done.")
    payload = _run(client, scripted, pid, att, "/map-edits remove the two tallest towers")
    (system, *rest), = _run_calls()
    assert _wrapped(system) == ["map-edits"]
    assert rest[-1]["content"] == "/map-edits remove the two tallest towers"
    turns = _turns(client, scripted, pid, att)
    assert turns[-2]["text"] == "/map-edits remove the two tallest towers"
    assert turns[-1]["execution"]["pins"]["skills"]["named"] == ["map-edits"]
    # The reply's line reads it from the run's answer as from the saved turn.
    assert payload["skills"] == {"named": ["map-edits"]} and "skillsLoaded" not in payload

    # The next turn holds it, and loading it again sends nothing twice.
    testing_provider.reset()
    testing_provider.push_reply(_tail({"toolRequest": {"tool": "skill.read", "params": {"name": "map-edits"}}}))
    testing_provider.push_reply("Still here.")
    second = _run(client, scripted, pid, att, "and the next one?")
    first_call, second_call = _run_calls()
    assert _wrapped(first_call[0]) == ["map-edits"]
    assert "already in this conversation" in second_call[-1]["content"]
    assert second["skills"] == {"kept": ["map-edits"]}
    assert _turns(client, scripted, pid, att)[-1]["execution"]["pins"]["skills"]["kept"] == ["map-edits"]


@pytest.mark.parametrize("message", [
    "/catalog/agents lists the agents",
    "/nodes pick a node",
    "/no-such-skill do it",
    "please /map-edits later",
])
def test_a_message_names_no_skill_unless_it_starts_with_one_its_run_lists(
    client, user_and_token, tmp_curio, scripted, message,
):
    pid = _project(client, scripted)
    att = _attach(client, scripted, pid, NB)
    testing_provider.push_reply("Done.")
    payload = _run(client, scripted, pid, att, message)
    (system, *_), = _run_calls()
    assert _wrapped(system) == []
    assert "named" not in _turns(client, scripted, pid, att)[-1]["execution"]["pins"].get("skills", {})
    assert "skills" not in payload


def test_a_named_skill_the_chat_holds_already_is_not_handed_twice(client, user_and_token, tmp_curio, scripted):
    """A chat on a Vega-Lite node holds its kind's skills from its first
    message, so naming one of them hands nothing more."""
    pid = _project(client, scripted, nodes=[{"id": "chart", "type": VEGA, "content": "{}", "x": 0, "y": 0}])
    att = _attach(client, scripted, pid, NB, {"kind": "node", "targetId": "chart"})
    testing_provider.push_reply("Done.")
    payload = _run(client, scripted, pid, att, "/widgets /map-edits change the threshold")
    (system, *_), = _run_calls()
    held = _wrapped(system)
    assert held.count("widgets") == 1 and held[-1] == "map-edits"
    assert payload["skills"]["named"] == ["map-edits"] and "widgets" in payload["skills"]["handed"]


# --- A chat's skills, which / offers ---------------------------------------------------


def test_a_chat_offers_the_skills_its_next_run_lists_marking_those_it_holds(
    client, user_and_token, tmp_curio, scripted,
):
    pid = _project(client, scripted, nodes=[{"id": "chart", "type": VEGA, "content": "{}", "x": 0, "y": 0}])
    att = _attach(client, scripted, pid, NB, {"kind": "node", "targetId": "chart"})
    url = f"/api/agents/projects/{pid}/attachments/{att}/skills"
    offered = client.get(url, headers=scripted).get_json()["skills"]
    from utk_curio.backend.app.agents.domain import builtin

    assert [skill["name"] for skill in offered] == list(builtin.get_builtin_manifest(NB).skills)
    held = {skill["name"] for skill in offered if skill["held"]}
    assert held == {"widgets", "selection-chips", "vega-lite-starter", "vega-lite-maps"}
    assert all(skill["description"] for skill in offered)

    client.delete(f"{_rows_url(NB)}/provenance", headers=scripted)
    assert "provenance" not in [skill["name"] for skill in client.get(url, headers=scripted).get_json()["skills"]]
    assert client.get(f"/api/agents/projects/{pid}/attachments/nope/skills", headers=scripted).status_code == 404
