"""A new node's widgets, set by name over the widgets its template declares.

A template declares the widgets a new node of it starts with, and an agent
sets one by its name in a plan or a node.create. The node keeps the template's
widget: its type, its default and the options that bound its value, a
choice's choices and a number's or a slider's minimum, maximum and step, with
the keys the agent gives set over it, and the value is judged against them. A
plan's duplicate sets a copy's values the same way, on a widget the plan
declares or on one only the template declares.

The test package's Shade template, whose starter is its whole content,
declares a slider, a number, a text and a choice. The helpers are the route
tests' own, reached through their modules so this one collects none of their
tests. What this adds is read inside each test, so a before-run fails here and
not the whole collection.
"""
from __future__ import annotations

import json

from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests.test_agents import test_plan_scenario_routes as scenario_routes
from utk_curio.backend.tests.test_agents import test_routes_proposals as routes
from utk_curio.backend.tests.test_agents import test_routes_starter_templates as starters
from utk_curio.backend.tests.test_agents.test_source_grounding_routes import _tool_results

LEVERS = "test.levers@1"
SHADE = "test.levers/shade"
SOURCE = ('return input_0.assign(shade=input_0["height"] * [!! factor !!] * [!! zoom !!], '
          'label=[!! title !!], season=[!! season !!])\n')
FACTOR = {"name": "factor", "type": "slider", "label": "Height factor", "default": 1,
          "options": {"min": 0.5, "max": 4, "step": 0.5}}
ZOOM = {"name": "zoom", "type": "number", "label": "Zoom level", "default": 16,
        "options": {"min": 1, "max": 20, "step": 1}}
TITLE = {"name": "title", "type": "text", "label": "Title", "default": "Shade"}
SEASON = {"name": "season", "type": "choice", "label": "Season", "default": "summer",
          "options": {"choices": ["spring", "summer", "winter"], "display": "radio"}}
WIDGETS = [FACTOR, ZOOM, TITLE, SEASON]
LOAD = {"ref": "load", "nodeType": "curio.builtin/python-computation", "title": "Load",
        "intent": "load the buildings"}


def _levers_manifest() -> dict:
    return {
        "id": "test.levers", "version": "1.0.0", "name": "Test levers", "publisher": "Test",
        "description": "A node whose widgets are its levers.", "license": "MIT",
        "compatibility": {"curioRuntime": ">=0.5.0", "major": 1},
        "permissions": [], "dependencies": {"packages": {}, "python": {}, "js": {}},
        "templates": [{
            "id": "shade", "label": "Shade", "category": "computation", "engine": "python",
            "editor": "code", "behavior": "code", "hasCode": True, "hasWidgets": True,
            "description": "Each building's shade from its height and the node's widgets.",
            "inputPorts": [{"types": ["DATAFRAME"], "cardinality": "1"}],
            "outputPorts": [{"types": ["DATAFRAME"], "cardinality": "1"}],
            "source": "sources/shade.py",
            "starterIsContent": True,
            "widgets": WIDGETS,
        }],
        "createdAt": "2026-11-15T00:00:00Z",
    }


def _install_levers(user_key: str) -> str:
    from utk_curio.backend.app.packages.repositories.store import user_packages_dir

    folder = user_packages_dir(user_key) / LEVERS
    (folder / "sources").mkdir(parents=True, exist_ok=True)
    (folder / "manifest.json").write_text(json.dumps(_levers_manifest()), encoding="utf-8")
    (folder / "sources" / "shade.py").write_text(SOURCE, encoding="utf-8")
    return LEVERS


def _set(widget: dict, **keys) -> dict:
    """*widget* as the node holds it once *keys* are set over it."""
    return {**widget, **keys}


def _create(client, user_and_token, project_id, monkeypatch, *widget_lists):
    """The Node Builder's node.create of a Shade node for each of
    *widget_lists*, each tried after the one before it was refused, in a
    project that holds the test package: the card and the node of the one
    that landed (None when none did), and what the model was told of each."""
    user, token = user_and_token
    helper = routes.TestNodeCreate()
    replies = [helper._create_tail_json(nodeType=SHADE, title="Shade", content="", widgets=widgets)
               for widgets in widget_lists]
    att_id, calls = helper._setup(client, user=user, token=token, project_id=project_id,
                                  monkeypatch=monkeypatch, replies=[*replies, "Added it."])
    key = routes.TestDataflowPlanMint()._ukey(user)
    starters._enlist(key, project_id, [_install_levers(key)])
    response = helper._run(client, token, project_id, att_id)
    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    card = next((p for p in routes._changes(body) if p["kind"] == "node"), None)
    created = helper._created(body) if card is not None else None
    return card, created, _tool_results(calls[-1], "node.create")


def _plan(*nodes, scenarios=None) -> dict:
    """A plan of the loader feeding *nodes*, each a Shade node."""
    plan = {
        "goal": "the shade of each building",
        "nodes": [LOAD, *nodes],
        "edges": [{"from": "load", "to": node["ref"]} for node in nodes],
    }
    if scenarios:
        plan["scenarios"] = scenarios
    return plan


def _shade(ref: str = "shade", **extra) -> dict:
    return {"ref": ref, "nodeType": SHADE, "title": "Shade", "intent": "the shade of each building", **extra}


def _land(client, user_and_token, project_id, monkeypatch, *plans):
    """The Dataflow Builder's turn whose replies are *plans*, each tried after
    the one before it was refused, in a project that holds the test package:
    the plan that landed (its card, with ``canvas``), or None, and the model's
    calls, each holding what it was told of the one before."""
    user, token = user_and_token
    helper = routes.TestDataflowPlanMint()
    att_id, calls = helper._setup(client, user, token, project_id, monkeypatch,
                                  replies=[*(scenario_routes._reply(plan) for plan in plans), starters.WRITTEN])
    key = helper._ukey(user)
    starters._enlist(key, project_id, [_install_levers(key)])
    monkeypatch.setattr(
        "utk_curio.backend.app.execution.runner._http_exec",
        lambda endpoint, payload: {"stdout": [], "stderr": "", "output": {"path": "art-1", "dataType": "dataframe"}},
    )
    client.post(f"/api/agents/projects/{project_id}/install", json={"coord": starters.TestSolve.WRITER},
                headers=_auth(token))
    response = helper._run(client, token, project_id, att_id)
    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    landed = [p for p in routes._changes(body) if p.get("kind") == "plan"]
    return (routes._landed_plan(body) if landed else None), calls


def _shades(card: dict) -> list[dict]:
    """The Shade nodes the plan created: the original first, then each copy
    in the order the plan made them."""
    return [n for n in card["canvas"]["nodes"] if n["type"].startswith("test.levers/shade")]


class TestANodeCreateSetsATemplatesWidgetsByName:
    def test_a_slider_set_by_name_keeps_the_templates_bounds(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch,
    ):
        card, created, [landed] = _create(
            client, user_and_token, alice_project, monkeypatch,
            [{"name": "factor", "type": "slider", "value": 2.5}],
        )
        assert landed.startswith("[tool result] node.create: applied"), landed
        assert card is not None
        assert created["metadata"]["widgets"] == [_set(FACTOR, value=2.5), ZOOM, TITLE, SEASON]

    def test_a_number_and_a_text_set_by_name_keep_the_templates_defaults_and_bounds(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch,
    ):
        card, created, [landed] = _create(
            client, user_and_token, alice_project, monkeypatch,
            [{"name": "zoom", "type": "number", "value": 18}, {"name": "title", "type": "text", "value": "Tall"}],
        )
        assert landed.startswith("[tool result] node.create: applied"), landed
        assert card["summary"] == "Created a new Shade node · widgets factor, zoom, title, season"
        assert created["metadata"]["widgets"] == [FACTOR, _set(ZOOM, value=18), _set(TITLE, value="Tall"), SEASON]

    def test_a_value_outside_the_templates_bounds_is_refused_naming_them(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch,
    ):
        card, _created, refused = _create(
            client, user_and_token, alice_project, monkeypatch,
            [{"name": "factor", "type": "slider", "value": 9}],
            [{"name": "zoom", "type": "number", "value": 25}],
        )
        assert card is None, "a Shade node with a value past its template's bounds landed"
        assert len(refused) == 2 and all(r.startswith("[tool result] node.create: refused") for r in refused), refused
        assert "params.widgets[0] ('factor'): Enter a number from 0.5 to 4." in refused[0], refused[0]
        assert "params.widgets[0] ('zoom'): Enter a number from 1 to 20." in refused[1], refused[1]

    def test_other_bounds_or_another_type_for_a_templates_widget_are_refused(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch,
    ):
        card, _created, refused = _create(
            client, user_and_token, alice_project, monkeypatch,
            [{"name": "factor", "type": "slider", "options": {"min": 0, "max": 10}, "value": 9}],
            [{"name": "title", "type": "number", "value": 3}],
        )
        assert card is None, "a Shade node whose widget changes its template's bounds or type landed"
        assert len(refused) == 2 and all(r.startswith("[tool result] node.create: refused") for r in refused), refused
        assert (
            "params.widgets[0]: factor is the template's slider widget, and the node keeps its type and its "
            "bounds (min 0.5, max 4, step 0.5): write it with type slider, no other min, max or step, and a "
            "value within them"
        ) in refused[0], refused[0]
        assert (
            "params.widgets[0]: title is the template's text widget, and the node keeps its type: write it with "
            "type text"
        ) in refused[1], refused[1]


class TestAPlanSetsATemplatesWidgetsByName:
    def test_a_slider_a_number_and_a_text_set_by_name_keep_the_templates_widgets(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch,
    ):
        card, _calls = _land(
            client, user_and_token, alice_project, monkeypatch,
            _plan(_shade(widgets=[
                {"name": "factor", "type": "slider", "value": 2.5},
                {"name": "zoom", "type": "number", "value": 18},
                {"name": "title", "type": "text", "value": "Tall"},
            ])),
        )
        assert card is not None, "a plan setting the template's widgets by name was refused"
        (shade,) = _shades(card)
        assert shade["metadata"]["widgets"] == [
            _set(FACTOR, value=2.5), _set(ZOOM, value=18), _set(TITLE, value="Tall"), SEASON,
        ]

    def test_a_value_outside_the_templates_bounds_is_refused_and_the_fixed_plan_lands(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch,
    ):
        card, calls = _land(
            client, user_and_token, alice_project, monkeypatch,
            _plan(_shade(widgets=[{"name": "zoom", "type": "number", "value": 25}])),
            _plan(_shade(widgets=[{"name": "zoom", "type": "number", "value": 20}])),
        )
        assert len(calls) >= 2, "a plan setting Zoom past the template's maximum landed"
        assert "nodes[1].widgets[0] ('zoom'): Enter a number from 1 to 20." in calls[1][-1]["content"]
        assert card is not None
        (shade,) = _shades(card)
        assert shade["metadata"]["widgets"] == [FACTOR, _set(ZOOM, value=20), TITLE, SEASON]


#: A duplicate of the Summer scenario that sets the copy's widgets the plan
#: does not declare, only the template does, and a duplicate of that one.
SEASONS = [
    {"name": "Summer", "nodes": ["shade"]},
    {"name": "Winter", "duplicateOf": "Summer", "copies": {"shade": "shade_winter"},
     "values": {"shade_winter": {"season": "winter", "factor": 2}}},
    {"name": "Winter, taller", "duplicateOf": "Winter", "copies": {"shade_winter": "shade_tall"},
     "values": {"shade_tall": {"factor": 3}}},
]


class TestADuplicateSetsATemplatesWidgets:
    def test_a_copy_takes_the_values_its_duplicate_sets_on_the_templates_widgets(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch,
    ):
        card, _calls = _land(client, user_and_token, alice_project, monkeypatch, _plan(_shade(), scenarios=SEASONS))
        assert card is not None, "a duplicate setting the template's widgets was refused"
        shade, winter, taller = _shades(card)
        assert "copiedFrom" not in shade["metadata"]
        assert shade["metadata"]["widgets"] == WIDGETS
        assert winter["metadata"]["copiedFrom"] == [shade["id"]]
        assert winter["metadata"]["widgets"] == [_set(FACTOR, value=2), ZOOM, TITLE, _set(SEASON, value="winter")]
        # A copy of the copy holds what that copy holds, its own value set over it.
        assert taller["metadata"]["copiedFrom"] == [shade["id"], winter["id"]]
        assert taller["metadata"]["widgets"] == [_set(FACTOR, value=3), ZOOM, TITLE, _set(SEASON, value="winter")]

    def test_a_value_the_templates_widget_does_not_take_is_refused_naming_it(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch,
    ):
        wrong = [dict(SEASONS[0]), {**SEASONS[1], "values": {"shade_winter": {
            "season": "monsoon", "factor": 9, "height": 2,
        }}}]
        card, calls = _land(
            client, user_and_token, alice_project, monkeypatch,
            _plan(_shade(), scenarios=wrong), _plan(_shade(), scenarios=SEASONS[:2]),
        )
        assert len(calls) >= 2, "a duplicate setting values the template's widgets do not take landed"
        told = calls[1][-1]["content"]
        for words in (
            'scenarios[1].values.shade_winter.season must be one of the season widget\'s choices: '
            'spring, summer, winter; got "monsoon"',
            "scenarios[1].values.shade_winter.factor: Enter a number from 0.5 to 4.",
            "scenarios[1].values.shade_winter.height: the node has no widget named 'height' "
            "(it has factor, zoom, title, season)",
        ):
            assert words in told, told
        assert card is not None
        assert [n["metadata"]["widgets"][-1] for n in _shades(card)] == [SEASON, _set(SEASON, value="winter")]
