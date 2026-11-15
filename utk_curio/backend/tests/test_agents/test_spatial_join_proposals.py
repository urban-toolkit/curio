"""A Spatial Join an agent adds: a Dataflow Builder plan and a Node Builder
node.create, through the real mint and the change that lands, with the
built-in package as Curio ships it. The join's starter is its whole content,
so a new join holds its template's code and the agent sets its two widgets,
Operation and Output, by name. A value they do not offer, content given for
the join, or the setting it kept before its code comes back to the model as
an error naming it, and nothing lands.

The helpers are the proposal route tests' own, reached through their modules
so this one collects none of their tests. What this adds is read inside each
test, so a before-run fails here and not the whole collection.
"""
from __future__ import annotations

import json
from pathlib import Path

from utk_curio.backend.tests.test_agents import test_routes_proposals as routes
from utk_curio.backend.tests.test_agents import test_routes_starter_templates as starters
from utk_curio.backend.tests.test_agents import test_source_grounding_routes as grounding_routes
from utk_curio.backend.tests.test_agents.test_node_settings_write import OPERATION, OUTPUT

REPO_ROOT = Path(__file__).resolve().parents[4]
BUILTIN = "curio.builtin@1"
JOIN = "curio.builtin/spatial-join"
CA = "curio.builtin/python-computation"
OPERATIONS = "intersects, within, contains, touches, overlaps, crosses, nearest"
#: A planned join's widgets, set by name as a plan writes them.
WITHIN_COUNTS = [{"name": "operation", "type": "choice", "value": "within"},
                 {"name": "output", "type": "choice", "value": "counts"}]
#: What the model is told, after where it gives the join's old setting.
OLD_SETTING = (
    ": a Spatial Join keeps its operation and output in its widgets operation and output: set them by name "
    'in widgets, such as {"name": "operation", "type": "choice", "value": "within"}'
)


def _starter() -> str:
    """The join's code, its template's starter, as the built-in package holds it."""
    package = REPO_ROOT / "packages" / BUILTIN
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    (template,) = [t for t in manifest["templates"] if t["id"] == "spatial-join"]
    return (package / template["source"]).read_text(encoding="utf-8")


def _plan(**join) -> dict:
    """Two code nodes feeding a join that sets *join*."""
    return {
        "goal": "count sidewalk labels per neighborhood",
        "nodes": [
            {"ref": "labels", "nodeType": CA, "title": "Labels", "intent": "sidewalk label points"},
            {"ref": "hoods", "nodeType": CA, "title": "Neighborhoods", "intent": "neighborhood polygons"},
            {"ref": "join", "nodeType": JOIN, "title": "Labels per neighborhood",
             "intent": "count the sidewalk labels within each neighborhood", **join},
        ],
        "edges": [
            {"from": "labels", "to": "join", "toHandle": "in"},
            {"from": "hoods", "to": "join", "toHandle": "in_1"},
        ],
    }


def _reply(plan: dict) -> str:
    return "Here is the plan.\n```curio.v1\n" + json.dumps({"dataflowPlan": plan}) + "\n```"


def _land(client, user, token, project_id, monkeypatch, replies):
    """The Dataflow Builder's turn whose replies are *replies*, each tried
    after the one before it was refused, in a project whose account holds the
    built-in package Curio ships: its attachment, the plan that landed (its
    change card, with ``canvas``) or None, and the model's calls."""
    helper = routes.TestDataflowPlanMint()
    att_id, calls = helper._setup(client, user, token, project_id, monkeypatch, replies=replies)
    starters._install_shipped(helper._ukey(user), BUILTIN)
    r = helper._run(client, token, project_id, att_id)
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert not [p for p in body["content"] if p["type"] == "proposal"], "a plan waited for review"
    landed = any(p.get("kind") == "plan" for p in routes._changes(body))
    return att_id, (routes._landed_plan(body) if landed else None), calls


def _spec_nodes(user, project_id) -> list[dict]:
    return [n for n in routes.TestDataflowPlanApply()._spec(user, project_id)["dataflow"]["nodes"] if n["id"] != "n1"]


def _joins(nodes: list[dict]) -> list[dict]:
    return [n for n in nodes if str(n["type"]).startswith(JOIN)]


class TestAPlannedJoin:
    def test_it_lands_with_its_code_and_the_widgets_the_plan_set_by_name(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        att_id, card, _ = _land(client, user, token, alice_project, monkeypatch, [_reply(_plan(widgets=WITHIN_COUNTS))])
        assert card is not None and card["status"] == "applied"
        rows = {n["ref"]: n for n in card["plan"]["nodes"]}
        # The card's row names the widgets as the plan set them, and no other row names any.
        assert rows["join"]["widgets"] == WITHIN_COUNTS
        assert "widgets" not in rows["labels"] and "widgets" not in rows["hoods"]
        (saved,) = _joins(_spec_nodes(user, alice_project))
        created = {n["id"]: n for n in card["canvas"]["nodes"]}[saved["id"]]
        # Its template's code, which places both widgets, and the template's
        # widgets with the values the plan set over them: what it draws and runs.
        for node in (saved, created):
            assert node["content"] == _starter()
            assert node["metadata"]["widgets"] == [{**OPERATION, "value": "within"}, {**OUTPUT, "value": "counts"}]
            assert "spatialJoin" not in node["metadata"]
        # Nothing is left for Solve to write in it: its code is the template's.
        assert starters._session(client, token, alice_project, att_id)["nodeStates"] == {
            "labels": "created", "hoods": "created", "join": "approved",
        }

    def test_a_join_that_sets_none_holds_the_templates_widgets_at_their_defaults(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        _att_id, card, _ = _land(client, user, token, alice_project, monkeypatch, [_reply(_plan())])
        assert card is not None and "widgets" not in {n["ref"]: n for n in card["plan"]["nodes"]}["join"]
        (saved,) = _joins(_spec_nodes(user, alice_project))
        assert saved["content"] == _starter()
        assert saved["metadata"] == {"widgets": [OPERATION, OUTPUT]}

    def test_a_value_its_widget_does_not_offer_is_refused_naming_its_choices(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        near = [{"name": "operation", "type": "choice", "value": "near"}]
        _, card, calls = _land(
            client, user, token, alice_project, monkeypatch,
            [_reply(_plan(widgets=near)), _reply(_plan(widgets=WITHIN_COUNTS))],
        )
        assert len(calls) == 2, "the plan with an operation the join does not offer landed"
        told = calls[1][-1]["content"]
        assert f'nodes[2].widgets[0].value must be one of the operation widget\'s choices: {OPERATIONS}; got "near"' in told, told
        # The corrected plan landed.
        assert card is not None
        (saved,) = _joins(_spec_nodes(user, alice_project))
        assert saved["metadata"]["widgets"][0] == {**OPERATION, "value": "within"}

    def test_the_joins_old_setting_is_refused_and_its_widgets_land_in_its_place(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        old = _plan(spatialJoin={"predicate": "within", "output": "counts"})
        _, card, calls = _land(
            client, user, token, alice_project, monkeypatch, [_reply(old), _reply(_plan(widgets=WITHIN_COUNTS))],
        )
        assert len(calls) == 2, "a plan giving the join's old setting landed"
        told = calls[1][-1]["content"]
        assert f"nodes[2].spatialJoin{OLD_SETTING}" in told, told
        assert card is not None
        (saved,) = _joins(_spec_nodes(user, alice_project))
        assert saved["metadata"]["widgets"] == [{**OPERATION, "value": "within"}, {**OUTPUT, "value": "counts"}]
        assert all("spatialJoin" not in (n.get("metadata") or {}) for n in _spec_nodes(user, alice_project))


class _ShippedBuiltinNodeBuilder(routes.TestNodeCreate):
    """The node.create helper, in an account that holds the built-in package
    Curio ships, its sources among it."""

    def _write_builtin_package(self, user_key, templates=None):
        starters._install_shipped(user_key, BUILTIN)


class TestAJoinAnAgentAdds:
    def _run(self, client, user, token, project_id, monkeypatch, *replies):
        helper = _ShippedBuiltinNodeBuilder()
        att_id, calls = helper._setup(client, user=user, token=token, project_id=project_id,
                                      monkeypatch=monkeypatch, replies=[*replies, "Added it."])
        r = helper._run(client, token, project_id, att_id)
        assert r.status_code == 200, r.get_json()
        body = r.get_json()
        assert not [p for p in body["content"] if p["type"] == "proposal"]
        card = next((p for p in routes._changes(body) if p["kind"] == "node"), None)
        created = helper._created(body) if card is not None else None
        # Every recorded call is the one message list the loop appends to, so
        # each node.create result is read by its prefix, never by its index.
        return helper, card, created, grounding_routes._tool_results(calls[-1], "node.create")

    def test_with_no_content_it_starts_with_its_code_and_the_widgets_set_by_name(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        reply = _ShippedBuiltinNodeBuilder()._create_tail_json(
            nodeType=JOIN, title="Nearest label", content="",
            widgets=[{"name": "operation", "type": "choice", "value": "nearest"}],
        )
        helper, card, created, [landed] = self._run(client, user, token, alice_project, monkeypatch, reply)
        assert landed.startswith("[tool result] node.create: applied"), landed
        assert card["summary"] == "Created a new Spatial Join node · Nearest label · widgets operation, output"
        # The card shows what lands: the template's code, as its package holds it.
        assert card["preview"] == _starter()
        assert created["content"] == _starter()
        assert created["metadata"] == {"widgets": [{**OPERATION, "value": "nearest"}, OUTPUT]}
        stored = next(n for n in helper._spec_nodes(user, alice_project) if n["id"] == created["id"])
        assert stored["content"] == _starter()
        assert stored["metadata"]["widgets"] == created["metadata"]["widgets"]

    def test_content_given_for_it_is_refused_naming_its_widgets(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        reply = _ShippedBuiltinNodeBuilder()._create_tail_json(
            nodeType=JOIN, content=_starter(), widgets=[{"name": "operation", "type": "choice", "value": "within"}],
        )
        helper, card, _, [refused] = self._run(client, user, token, alice_project, monkeypatch, reply)
        assert card is None, "a Spatial Join with content of its own landed"
        assert (
            "params.content: a Spatial Join node starts from its template's own content, which a node.create does "
            "not replace. Leave content empty, and put the values it shows in params.widgets, under the names of "
            "its template's widgets: operation, output"
        ) in refused, refused
        assert [n["id"] for n in helper._spec_nodes(user, alice_project)] == ["n1"]

    def test_a_value_its_widget_does_not_offer_is_refused_naming_its_choices(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        reply = _ShippedBuiltinNodeBuilder()._create_tail_json(
            nodeType=JOIN, content="", widgets=[{"name": "output", "type": "choice", "value": "polygons"}],
        )
        helper, card, _, [refused] = self._run(client, user, token, alice_project, monkeypatch, reply)
        assert card is None
        assert (
            'params.widgets[0].value must be one of the output widget\'s choices: pairs, counts; got "polygons"'
        ) in refused, refused
        assert [n["id"] for n in helper._spec_nodes(user, alice_project)] == ["n1"]

    def test_the_joins_old_setting_is_refused_on_any_node(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        create = _ShippedBuiltinNodeBuilder()._create_tail_json
        helper, card, _, refused = self._run(
            client, user, token, alice_project, monkeypatch,
            create(nodeType=JOIN, content="", spatialJoin={"predicate": "within"}),
            create(nodeType=CA, content="return input_0", spatialJoin={"predicate": "within"}),
        )
        assert card is None, "a node giving the join's old setting landed"
        assert len(refused) == 2 and all(r.startswith("[tool result] node.create: refused") for r in refused), refused
        for said in refused:
            assert f"params.spatialJoin{OLD_SETTING}" in said, said
        assert [n["id"] for n in helper._spec_nodes(user, alice_project)] == ["n1"]
