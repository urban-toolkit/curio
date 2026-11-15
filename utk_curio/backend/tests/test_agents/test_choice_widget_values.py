"""A value an agent writes for a choice widget is one of the widget's choices.

An agent writes widget values in three places: a plan's nodes and a
node.create declare widgets, a template's among them, which it sets by name,
and a node.settings.write gives a node already on the canvas new values by
name. Each value is judged against the widget as the node defines it: the
node's own widgets, or for a new node the widget of that name its template
declares, whose type and choices the node keeps. A value the choice does not
offer is refused to the model in words naming the widget and its choices,
which the model cannot see as the Widgets tab shows them; one it offers lands.

The Vega-Lite package's Bars chart declares Combine, a choice of six
aggregates, and its starter is its whole content, so a node of it holds only
what its widgets say. The helpers are the route tests' own, reached through
their modules so this one collects none of their tests.

The checks this adds are read inside each test, so a before-run fails here and
not the whole collection.
"""
from __future__ import annotations

import json

from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests.test_agents import test_routes_proposals as routes
from utk_curio.backend.tests.test_agents import test_routes_starter_templates as starters
from utk_curio.backend.tests.test_agents.test_node_settings_write import _change

BARS = "curio.vega-lite/bars"
#: The Bars chart's Combine widget's choices, as its manifest lists them.
AGGREGATES = "mean, sum, median, min, max, count"
LOAD = {"ref": "load", "nodeType": "curio.builtin/python-computation", "title": "Load",
        "intent": "load the shadow minutes"}


def _grammar():
    from utk_curio.backend.app.agents.domain import widget_grammar

    return widget_grammar


def _bars_widgets() -> list[dict]:
    """The Bars chart's widgets, as the package Curio ships declares them."""
    _starter, widgets = starters._vega_lite_bars()
    return widgets


def _combine() -> dict:
    (combine,) = [w for w in _bars_widgets() if w["name"] == "combine"]
    assert combine["type"] == "choice" and ", ".join(combine["options"]["choices"]) == AGGREGATES
    return combine


def _bars(*widgets: dict) -> dict:
    """A planned Bars chart that sets *widgets*."""
    return {"ref": "bars", "nodeType": BARS, "title": "Mean shadow", "intent": "draw the mean shadow",
            "widgets": list(widgets)}


def _not_a_choice(where: str, value: str) -> str:
    return f"{where} must be one of the combine widget's choices: {AGGREGATES}; got {json.dumps(value)}"


def _keeps_its_choices(where: str) -> str:
    return (
        f"{where}: combine is the template's choice widget, and the node keeps its type and its choices, "
        f"{AGGREGATES}: write it with type choice, no other choices, and a value among them"
    )


class TestTheWidgetsDefinitionJudgesTheValue:
    def test_a_value_a_choice_does_not_offer_is_named_with_the_widgets_choices(self):
        wg = _grammar()
        combine = _combine()
        assert wg.value_problem(combine, "average", "params.widgets.combine") == _not_a_choice(
            "params.widgets.combine", "average")
        assert wg.value_problem(combine, 3, "v") == f"v must be one of the combine widget's choices: {AGGREGATES}; got 3"
        assert wg.value_problem(combine, "max", "params.widgets.combine") is None

    def test_a_declared_choices_own_default_or_value_outside_its_choices_is_named_with_them(self):
        widgets, errors = _grammar().parse_widgets(
            [{"name": "season", "type": "choice", "default": "monsoon", "options": {"choices": ["summer", "winter"]}}],
            "nodes[0].widgets",
        )
        assert widgets == []
        assert errors == [
            'nodes[0].widgets[0].default must be one of the season widget\'s choices: summer, winter; got "monsoon"',
        ]
        _widgets, errors = _grammar().parse_widgets(
            [{"name": "season", "type": "choice", "value": "monsoon", "options": {"choices": ["summer", "winter"]}}],
            "nodes[0].widgets",
        )
        assert errors == [
            'nodes[0].widgets[0].value must be one of the season widget\'s choices: summer, winter; got "monsoon"',
        ]

    def test_a_templates_choice_is_set_by_name_among_its_choices_and_keeps_them(self):
        wg = _grammar()
        declared = _bars_widgets()

        def judged(*raw):
            widgets, errors = wg.read_widgets(list(raw), "params.widgets")
            assert errors == [], errors
            return wg.template_problems(widgets, declared, "params.widgets")

        # Its name, its type and a value it offers: no choices to restate.
        assert judged({"name": "combine", "type": "choice", "value": "max"}) == []
        assert judged({"name": "combine", "type": "choice", "options": {"choices": AGGREGATES.split(", ")},
                       "value": "sum"}) == []
        assert judged({"name": "combine", "type": "choice", "value": "average"}) == [
            _not_a_choice("params.widgets[0].value", "average"),
        ]
        assert judged({"name": "combine", "type": "choice", "default": "average"}) == [
            _not_a_choice("params.widgets[0].default", "average"),
        ]
        # Choices of its own, or another type, would change the template's widget.
        assert judged({"name": "combine", "type": "choice", "options": {"choices": ["mean", "average"]},
                       "value": "average"}) == [_keeps_its_choices("params.widgets[0]")]
        assert judged({"name": "combine", "type": "text", "value": "max"}) == [_keeps_its_choices("params.widgets[0]")]
        # A choice with no choices that names no widget of the template is refused as the Widgets tab refuses it.
        assert judged({"name": "y", "type": "text", "value": "shadow"},
                      {"name": "stat", "type": "choice", "value": "max"}) == [
            "params.widgets[1] ('stat'): Give at least one choice.",
        ]
        assert wg.parse_widgets([{"name": "stat", "type": "choice", "value": "max"}], "w") == (
            [], ["w[0] ('stat'): Give at least one choice."])
        # The node holds the template's Combine with the value set over it.
        assert wg.parse_widgets([{"name": "combine", "type": "choice", "value": "max"}], "w", declared)[0] == [
            declared[0], {**_combine(), "value": "max"}, declared[2],
        ]


class TestANodeCreate:
    """The Node Builder's node.create of a Bars chart, which sets the
    template's Combine widget by name."""

    def _create(self, client, user_and_token, project_id, monkeypatch, *widget_lists):
        user, token = user_and_token
        create = routes.TestNodeCreate()._create_tail_json
        replies = [create(nodeType=BARS, title="Mean shadow", content="", widgets=widgets) for widgets in widget_lists]
        test = starters.TestACreatedTemplateStartsFromItsStarter()
        return test._run(client, user, token, project_id, monkeypatch, *replies)

    def test_a_value_its_choice_offers_lands_with_the_templates_choices(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch,
    ):
        _helper, card, created, [landed] = self._create(
            client, user_and_token, alice_project, monkeypatch,
            [{"name": "combine", "type": "choice", "value": "max"}],
        )
        assert landed.startswith("[tool result] node.create: applied"), landed
        assert card["summary"] == "Created a new Bars node · Mean shadow · widgets y, combine, y_title"
        widgets = {w["name"]: w for w in created["metadata"]["widgets"]}
        assert widgets["combine"] == {**_combine(), "value": "max"}

    def test_a_value_it_does_not_offer_or_other_choices_are_refused_naming_its_choices(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch,
    ):
        user, _token = user_and_token
        helper, card, _created, refused = self._create(
            client, user_and_token, alice_project, monkeypatch,
            [{"name": "combine", "type": "choice", "value": "average"}],
            [{"name": "combine", "type": "choice", "options": {"choices": ["mean", "average"]}, "value": "average"}],
        )
        assert card is None, "a Bars chart combining by a choice it does not offer landed"
        assert len(refused) == 2 and all(r.startswith("[tool result] node.create: refused") for r in refused), refused
        assert _not_a_choice("params.widgets[0].value", "average") in refused[0], refused[0]
        assert _keeps_its_choices("params.widgets[0]") in refused[1], refused[1]
        assert [n["id"] for n in helper._spec_nodes(user, alice_project)] == ["n1"]


def _plan_turn(client, user, token, project_id, monkeypatch, *plans):
    """The Dataflow Builder's turn whose replies are the plans of *plans*
    (each a list of nodes, the loader feeding the chart), each tried after the
    one before it was refused, in a project that holds the Vega-Lite package:
    the plan that landed, or None, and what the model was told after each."""
    helper = routes.TestDataflowPlanMint()
    replies = ["Here is the plan.\n" + helper._plan_tail(nodes=nodes, edges=[{"from": "load", "to": "bars"}])
               for nodes in plans]
    att_id, calls = helper._setup(client, user, token, project_id, monkeypatch, replies=[*replies, starters.WRITTEN])
    key = helper._ukey(user)
    starters._enlist(key, project_id, [starters._install_vega_lite(key)])
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


class TestAPlan:
    """The Dataflow Builder's plan of a loader feeding a Bars chart, which
    sets the template's Combine widget by name."""

    def test_a_value_its_choice_offers_lands_with_the_templates_choices(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch,
    ):
        user, token = user_and_token
        card, _calls = _plan_turn(
            client, user, token, alice_project, monkeypatch,
            [LOAD, _bars({"name": "combine", "type": "choice", "value": "median"})],
        )
        assert card is not None, "a plan setting Combine to an aggregate it offers was refused"
        (bars,) = [n for n in card["canvas"]["nodes"] if n["type"].startswith(BARS)]
        widgets = {w["name"]: w for w in bars["metadata"]["widgets"]}
        assert list(widgets) == ["y", "combine", "y_title"]
        assert widgets["combine"] == {**_combine(), "value": "median"}
        saved = {n["id"]: n for n in routes.TestNodeCreate()._spec_nodes(user, alice_project)}
        assert saved[bars["id"]]["metadata"]["widgets"] == bars["metadata"]["widgets"]

    def test_a_value_it_does_not_offer_is_refused_naming_its_choices_and_the_fixed_plan_lands(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch,
    ):
        user, token = user_and_token
        card, calls = _plan_turn(
            client, user, token, alice_project, monkeypatch,
            [LOAD, _bars({"name": "combine", "type": "choice", "value": "average"})],
            [LOAD, _bars({"name": "combine", "type": "choice", "value": "mean"})],
        )
        assert len(calls) >= 2, "a plan setting Combine to a choice it does not offer landed"
        told = calls[1][-1]["content"]
        assert "the plan's widgets or scenarios are invalid" in told, told
        assert _not_a_choice("nodes[1].widgets[0].value", "average") in told, told
        assert card is not None
        (bars,) = [n for n in card["canvas"]["nodes"] if n["type"].startswith(BARS)]
        assert {w["name"]: w for w in bars["metadata"]["widgets"]}["combine"] == {**_combine(), "value": "mean"}


class TestANodeSettingsWrite:
    """node.settings.write on a Python node whose Combine widget offers mean,
    sum and max (``test_node_settings_write._nodes``)."""

    def test_a_value_its_choice_offers_lands(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        _project, _att, change, [said], _ = _change(
            client, user, token, monkeypatch, target="chart", widgets={"combine": "sum"},
        )
        assert said.startswith("[tool result] node.settings.write: applied"), said
        assert change["settingLines"] == ["Combine: sum"]

    def test_a_value_it_does_not_offer_is_refused_naming_its_choices(
        self, client, user_and_token, tmp_curio, monkeypatch,
    ):
        user, token = user_and_token
        _project, _att, change, [refused], landed = _change(
            client, user, token, monkeypatch, target="chart", widgets={"combine": "median"},
        )
        assert change is None and landed == [], "the change landed"
        assert refused.startswith("[tool result] node.settings.write: refused"), refused
        assert (
            'params.widgets.combine must be one of the combine widget\'s choices: mean, sum, max; got "median"'
        ) in refused, refused
