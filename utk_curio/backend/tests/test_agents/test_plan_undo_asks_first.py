"""A Dataflow Builder plan's Undo asks first when someone typed into the plan's nodes after it landed.

The plan's Undo (``proposals/plans.py``, ``_undo_plan``) takes the plan's
nodes away with everything in them. When people typed into those nodes since
the plan landed, a typing of the history or one still under way, and no
agent's code replaced it since, the Undo asks first: it answers 200 with the
change still applied and the facts its question names (``typed``: each such
node, named as its header names it, with who typed into it, by account and
name), and changes nothing. Called again with ``{"anyway": true}``, it ends
the typing still under way in the plan's nodes, each a version of its own, so
the version before the Undo holds what was typed, then takes the plan away as
before; the change and its card keep the facts, which the card's Undone line
names. With nobody's typing in the plan's nodes, it asks nothing. A change
outside the plan's nodes still refuses it, with its reason, and never asks.

The Undo is a version of its own made from the one on the canvas, as every
other change is, named after the Undo ("Undid Dataflow Builder's change"):
its result is the dataflow now without what the plan wrote, not the version
before the plan, which it still names (``restores``). So the Provenance
drawer lists every version on one line, the plan's, then the typing, then
the Undo, and the version right above the Undo holds what was typed.

alice owns the dataflow and asks every Undo; ana is an editor she invited.
Each types through a tab of her own, a pycrdt doc syncing over a
Flask-SocketIO test client (``test_collaboration/_ydoc_client.py``), as the
canvas types into a node's code. A typing becomes a version of the history
once its typist leaves the node's editor, or after a pause; a typing "under
way" is one that has not yet.

On main, where the Undo never asks, the three questions fail at their check
of the answer, and the Undo anyway fails at its check that the version before
the Undo holds the typing that was still under way: main ends no typing
before it takes the nodes away, so the version before its put-back is the
plan's own, and that typing never becomes a version. The Undo as a version
on top fails at its check of the Undo's parent: on main it is a put-back of
the version before the plan, which leaves the plan and the typing on a
branch the drawer folds. The other tests are guards, passing on main too.
"""
from __future__ import annotations

import pytest

from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests.test_agents.test_agent_changes import (
    CA,
    DFB,
    _ask,
    _by_id,
    _person_writes,
    _plan_tail,
    _saved,
    _setup,
    _the_card,
    _undo,
)
from utk_curio.backend.tests.test_agents.test_agents_write_through_the_doc import _typed

ANA = "ana-token-undo-asks"
#: The agent whose code a plan's node can get after the plan landed, as Solve's.
NODE_BUILDER = "agent.curio.node-builder@1"


@pytest.fixture(autouse=True)
def _rooms():
    from utk_curio.backend.app.collaboration import room_state

    room_state.reset_for_tests()
    yield
    room_state.reset_for_tests()


class _Clock:
    """The doc server's clock, which a test moves past a typing's pause."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture()
def clock(monkeypatch):
    from utk_curio.backend.app.collaboration import dataflow_docs

    moved = _Clock()
    monkeypatch.setattr(dataflow_docs, "_clock", moved)
    return moved


def _landed(client, user, token, monkeypatch):
    """alice's dataflow, a loader feeding a sum, where the Dataflow Builder
    landed a plan of two new nodes, Parks and Count, and the connection
    between them, on an empty goal: the project, the attachment, the plan's
    card, the dataflow as it was before the plan, and the plan's node ids by
    title."""
    project, att = _setup(client, user, token, coord=DFB)
    before = _saved(client, token, project)
    plan = {
        "goal": "count the parks by street",
        "nodes": [{"ref": "parks", "nodeType": CA, "title": "Parks", "intent": "load the parks"},
                  {"ref": "count", "nodeType": CA, "title": "Count", "intent": "count the parks by street"}],
        "edges": [{"from": "parks", "to": "count"}],
    }
    body, _ = _ask(client, token, project, att, monkeypatch, ["Here.\n" + _plan_tail(plan)])
    card = _the_card(body)
    assert card["kind"] == "plan", card
    ids = {node.get("title"): node["id"] for node in _saved(client, token, project)["nodes"]
           if node["id"] not in {"load", "sum"}}
    assert set(ids) == {"Parks", "Count"}, ids
    return project, att, card, before, ids


def _ana(db, alice, project):
    """ana, invited by alice to edit *project*."""
    from utk_curio.backend.app.projects import access
    from utk_curio.backend.app.users.models import User, UserSession

    ana = User(username="ana", name="Ana", email="ana@test.com")
    db.session.add(ana)
    db.session.flush()
    db.session.add(UserSession(user_id=ana.id, token=ANA))
    db.session.commit()
    access.add_editor(alice, project, "ana")
    return ana


def _tab(app, token, project):
    from utk_curio.backend.tests.test_collaboration._ydoc_client import synced_tab

    return synced_tab(app, token, project)


def _types(tab, node_id: str, text: str, *, leaves: bool = True) -> None:
    """The tab's person types *text* into *node_id*'s code, in its editor;
    with *leaves*, they leave the editor after, which makes their typing a
    version of the history; else it stays under way."""
    tab.set_presence({"editing": node_id})
    tab.edit(_typed(node_id, text))
    if leaves:
        tab.set_presence({"editing": None})


def _code(flow: dict, node_id: str):
    return next((node.get("content") for node in flow.get("nodes") or [] if node.get("id") == node_id), None)


def _asks(client, token, project, att, change_id, *, anyway: bool = False):
    url = f"/api/agents/projects/{project}/attachments/{att}/changes/{change_id}/undo"
    return client.post(url, headers=_auth(token), json={"anyway": True} if anyway else {})


def _card_in_the_chat(client, token, project, att, change_id) -> dict:
    read = client.get(f"/api/agents/projects/{project}/attachments/{att}/session", headers=_auth(token))
    assert read.status_code == 200, read.get_data(as_text=True)
    cards = [part for turn in read.get_json()["turns"] for part in turn.get("content") or []
             if part.get("type") == "change" and part.get("changeId") == change_id]
    assert len(cards) == 1, cards
    return cards[0]


def _versions(client, token, project) -> list[dict]:
    """The dataflow's versions as the Provenance drawer reads them."""
    listed = client.get(f"/api/projects/{project}/history", headers=_auth(token))
    assert listed.status_code == 200, listed.get_data(as_text=True)
    return listed.get_json()["versions"]


def _as_it_is(user, project) -> tuple:
    """The file, the doc's state and its log's end, and the history's points."""
    from utk_curio.backend.app.collaboration import dataflow_docs, history
    from utk_curio.backend.app.projects import storage
    from utk_curio.backend.app.projects.services import _user_dir_key

    key = _user_dir_key(user)
    dataflow_docs.flush(project)
    with dataflow_docs._held(project, key) as entry:
        doc = (entry.doc.get_state(), dataflow_docs.log_end(entry))
    return storage.read_spec_file(key, project), doc, history.points(key, project)


def _asked_and_nothing_changed(client, user, token, project, att, card, asked) -> dict:
    """The Undo *asked* answered with its question and changed nothing: the
    change and its card are still applied, and the file, the doc and the
    history are as they were. The question's facts."""
    assert asked.status_code == 200, asked.get_json()
    answer = asked.get_json()
    assert answer.get("status") == "applied", f"the Undo did not ask first: {answer}"
    assert answer.get("typed"), f"the Undo asked without naming who typed where: {answer}"
    assert not answer.get("canvas"), answer
    assert _card_in_the_chat(client, token, project, att, card["changeId"])["status"] == "applied"
    return answer["typed"]


def test_undo_asks_first_when_someone_else_typed_into_a_plan_node(
    app, client, db, user_and_token, tmp_curio, monkeypatch,
):
    """ana typed into Count after the plan landed: alice's Undo asks first,
    naming Count and ana, and changes nothing. On main it took the plan away
    with what ana typed."""
    alice, token = user_and_token
    project, att, card, _before, ids = _landed(client, alice, token, monkeypatch)
    ana = _ana(db, alice, project)
    _types(_tab(app, ANA, project), ids["Count"], "# ana's count\n")
    held = _as_it_is(alice, project)

    asked = _asks(client, token, project, att, card["changeId"])

    typed = _asked_and_nothing_changed(client, alice, token, project, att, card, asked)
    assert typed == [{"nodeId": ids["Count"], "name": "Count", "by": [{"account": str(ana.id), "name": "Ana"}]}]
    assert _as_it_is(alice, project) == held
    flow = _saved(client, token, project)
    assert _code(flow, ids["Count"]).startswith("# ana's count\n")


def test_undo_asks_first_naming_everyone_who_typed_the_asker_among_them(
    app, client, db, user_and_token, tmp_curio, monkeypatch,
):
    """ana typed into Count, alice into Parks, her typing still under way,
    then ana into Parks too: the question names Parks first, as the plan
    does, with alice and ana in the order they first typed there, then Count
    with ana. Asking ends no typing: alice's is still under way after it."""
    from utk_curio.backend.app.collaboration import history
    from utk_curio.backend.app.projects.services import _user_dir_key

    alice, token = user_and_token
    project, att, card, _before, ids = _landed(client, alice, token, monkeypatch)
    ana = _ana(db, alice, project)
    alices_tab, anas_tab = _tab(app, token, project), _tab(app, ANA, project)
    _types(anas_tab, ids["Count"], "# ana's count\n")
    _types(alices_tab, ids["Parks"], "# alice's parks\n", leaves=False)
    anas_tab.pump()
    _types(anas_tab, ids["Parks"], "# ana's parks\n")
    held = _as_it_is(alice, project)

    asked = _asks(client, token, project, att, card["changeId"])

    typed = _asked_and_nothing_changed(client, alice, token, project, att, card, asked)
    alice_by, ana_by = {"account": str(alice.id), "name": "Alice"}, {"account": str(ana.id), "name": "Ana"}
    assert typed == [
        {"nodeId": ids["Parks"], "name": "Parks", "by": [alice_by, ana_by]},
        {"nodeId": ids["Count"], "name": "Count", "by": [ana_by]},
    ]
    assert _as_it_is(alice, project) == held
    points = history.points(_user_dir_key(alice), project)
    assert not [p for p in points if p.get("kind") == "typing" and (p.get("by") or {}).get("name") == "Alice"], (
        "asking ended alice's typing")


def test_undo_asks_first_when_only_the_asker_typed(app, client, db, user_and_token, tmp_curio, monkeypatch):
    """alice typed into Count herself: her own Undo asks first too, naming
    Count and her."""
    alice, token = user_and_token
    project, att, card, _before, ids = _landed(client, alice, token, monkeypatch)
    _types(_tab(app, token, project), ids["Count"], "# my count\n")
    held = _as_it_is(alice, project)

    asked = _asks(client, token, project, att, card["changeId"])

    typed = _asked_and_nothing_changed(client, alice, token, project, att, card, asked)
    assert typed == [{"nodeId": ids["Count"], "name": "Count", "by": [{"account": str(alice.id), "name": "Alice"}]}]
    assert _as_it_is(alice, project) == held


def test_undo_anyway_takes_the_plan_away_and_the_version_before_it_holds_what_was_typed(
    app, client, db, user_and_token, tmp_curio, monkeypatch, clock,
):
    """ana typed into Parks and left its editor; alice typed into Count, her
    typing still under way. Undo anyway takes the plan away and empties the
    goal it set, as an Undo with nothing typed does. The Provenance drawer's
    list then ends with alice's Undo, and the version listed before it holds
    what both typed: the Undo ended alice's typing first, a version of its
    own. No version of that typing comes after the Undo, once her pause is
    over. The answer, the change and its card in the chat keep who typed
    where. On main the version before the Undo was ana's, and alice's typing
    never became a version."""
    from utk_curio.backend.app.agents.application import attachments
    from utk_curio.backend.app.collaboration import dataflow_docs, history
    from utk_curio.backend.app.projects.services import _user_dir_key

    alice, token = user_and_token
    key = _user_dir_key(alice)
    project, att, card, before, ids = _landed(client, alice, token, monkeypatch)
    ana = _ana(db, alice, project)
    alices_tab, anas_tab = _tab(app, token, project), _tab(app, ANA, project)
    _types(anas_tab, ids["Parks"], "# ana's parks\n")
    alices_tab.pump()
    _types(alices_tab, ids["Count"], "# alice's count\n", leaves=False)

    undone = _asks(client, token, project, att, card["changeId"], anyway=True)

    assert undone.status_code == 200, undone.get_json()
    answer = undone.get_json()
    assert answer["status"] == "undone", answer
    flow = _saved(client, token, project)
    assert _by_id(flow) == _by_id(before)
    assert flow["edges"] == before["edges"]
    assert flow.get("task", "") == ""
    versions = _versions(client, token, project)
    undo, last = versions[-1], versions[-2]
    assert undo["by"]["name"] == "Alice", versions[-3:]
    kept = history.dataflow_at(key, project, last["id"])
    typed_there = {title: (_code(kept, node_id) or "") for title, node_id in ids.items()}
    assert typed_there["Parks"].startswith("# ana's parks\n") and typed_there["Count"].startswith("# alice's count\n"), (
        f"the version before the Undo, {last.get('kind')} {last.get('what')!r} by "
        f"{(last.get('by') or {}).get('name')}, does not hold what was typed: {typed_there}")
    assert (last["kind"], last["what"]) == ("typing", "Alice edited"), last
    # Her pause over, and her editor left, no version of her typing comes after the Undo.
    clock.now += history.TYPING_PAUSE_S + 1
    dataflow_docs.flush_due(clock.now)
    alices_tab.set_presence({"editing": None})
    assert _versions(client, token, project)[-1]["id"] == undo["id"]
    alice_by, ana_by = {"account": str(alice.id), "name": "Alice"}, {"account": str(ana.id), "name": "Ana"}
    typed = [
        {"nodeId": ids["Parks"], "name": "Parks", "by": [ana_by]},
        {"nodeId": ids["Count"], "name": "Count", "by": [alice_by]},
    ]
    assert answer.get("typed") == typed, answer
    shown = _card_in_the_chat(client, token, project, att, card["changeId"])
    assert (shown["status"], shown.get("typed")) == ("undone", typed), shown
    record = attachments.get_attachment(dataflow_docs.live(key, project), att)
    [change] = [c for c in record.get("changes") or [] if c.get("changeId") == card["changeId"]]
    assert (change["status"], change.get("typed")) == ("undone", typed), change


def test_a_plans_undo_is_a_version_on_top_of_the_one_before_it_named_after_the_undo(
    app, client, db, user_and_token, tmp_curio, monkeypatch,
):
    """ana typed into Parks and left its editor, then alice undid the plan
    anyway. Her Undo is a version made from the one on the canvas, ana's
    typing, as any other change is: so the history is one line, which the
    Provenance drawer lists with no branch folded, the plan, then the typing,
    then the Undo. It is named after what it did, "Undid Dataflow Builder's
    change", since what it leaves is the dataflow as it was without what the
    plan wrote, not the version before the plan, which it still names
    (``restores``). On main it was a put-back of the version before the plan,
    made from that version, which left the plan and the typing on a branch."""
    alice, token = user_and_token
    project, att, card, before, ids = _landed(client, alice, token, monkeypatch)
    _ana(db, alice, project)
    _types(_tab(app, ANA, project), ids["Parks"], "# ana's parks\n")

    undone = _asks(client, token, project, att, card["changeId"], anyway=True)

    assert undone.status_code == 200, undone.get_json()
    assert undone.get_json()["status"] == "undone", undone.get_json()
    assert _by_id(_saved(client, token, project)) == _by_id(before)
    listed = client.get(f"/api/projects/{project}/history", headers=_auth(token)).get_json()
    versions = listed["versions"]
    plan, typing, undo = versions[-3], versions[-2], versions[-1]
    assert (typing["kind"], typing["what"]) == ("typing", "Ana edited"), versions[-3:]
    assert listed["head"] == undo["id"], listed["head"]
    assert undo.get("parent") == typing["id"], (
        f"the Undo was made from {undo.get('parent')}, not from the version on the canvas, ana's typing "
        f"{typing['id']}: {versions[-4:]}")
    # One line from the first version to the Undo: no version left on a branch.
    by_id = {version["id"]: version for version in versions}
    line, at = [], listed["head"]
    while at is not None and at not in line:
        line.append(at)
        at = (by_id.get(at) or {}).get("parent")
    assert line[::-1] == [version["id"] for version in versions], (line[::-1], versions)
    assert (undo["kind"], undo["what"], undo["by"]["name"]) == ("graph", "Undid Dataflow Builder's change", "Alice"), undo
    assert undo.get("restores") == plan.get("parent"), (undo, plan)


def test_undo_asks_nothing_when_nobody_typed_into_the_plans_nodes(
    app, client, db, user_and_token, tmp_curio, monkeypatch,
):
    """A guard. An agent wrote Count's code, as Solve does, and ana's typing
    in Parks was replaced by an agent's code after it: nothing anyone typed
    is in the plan's nodes, so the Undo asks nothing and takes the plan away
    at once."""
    from utk_curio.backend.app.collaboration import dataflow_docs
    from utk_curio.backend.app.projects.services import _user_dir_key

    alice, token = user_and_token
    key = _user_dir_key(alice)
    project, att, card, before, ids = _landed(client, alice, token, monkeypatch)
    _ana(db, alice, project)
    _types(_tab(app, ANA, project), ids["Parks"], "# ana's parks\n")

    def agents_code(flow):
        for node in flow["nodes"]:
            if node.get("id") in (ids["Parks"], ids["Count"]):
                node["content"] = "return 'the agent wrote it'"

    spec = dataflow_docs.live(key, project)
    agents_code(spec["dataflow"])
    dataflow_docs.write(key, project, spec, dataflow_docs.by_agent(NODE_BUILDER, key, "solve"))
    assert _code(_saved(client, token, project), ids["Parks"]) == "return 'the agent wrote it'"

    undone = _undo(client, token, project, att, card["changeId"])

    assert undone.status_code == 200, undone.get_json()
    assert undone.get_json()["status"] == "undone", undone.get_json()
    assert not undone.get_json().get("typed"), undone.get_json()
    flow = _saved(client, token, project)
    assert _by_id(flow) == _by_id(before)
    assert flow["edges"] == before["edges"]


@pytest.mark.parametrize("anyway", [False, True], ids=["asked", "anyway"])
def test_a_change_outside_the_plan_still_refuses_its_undo_when_its_nodes_were_typed_into(
    app, client, db, user_and_token, tmp_curio, monkeypatch, anyway,
):
    """A guard. alice typed into Count, and the sum, outside the plan, changed
    after it: the Undo is refused with its reason, as on main, never asked,
    and nothing changes, the flag to undo anyway or not."""
    alice, token = user_and_token
    project, att, card, _before, ids = _landed(client, alice, token, monkeypatch)
    _types(_tab(app, token, project), ids["Count"], "# my count\n")

    def changed(flow):
        for node in flow["nodes"]:
            if node.get("id") == "sum":
                node["content"] = "return input_0.max()  # after the plan"

    _person_writes(alice, project, changed)
    held = _as_it_is(alice, project)

    refused = _asks(client, token, project, att, card["changeId"], anyway=anyway)

    assert refused.status_code == 409, refused.get_json()
    assert "changed this dataflow after; nothing was undone." in refused.get_json()["error"]
    assert "typed" not in refused.get_json()
    assert _as_it_is(alice, project) == held
    assert _card_in_the_chat(client, token, project, att, card["changeId"])["status"] == "applied"
