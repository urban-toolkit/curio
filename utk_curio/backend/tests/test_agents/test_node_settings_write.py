"""An agent changes a setting of a node already on the canvas
(``node.settings.write``): a Data Pool's conflict modes, a Simple View's image
column, a Spatial Join's operation and output, or the values of a node's
widgets, a value node's among them: a Python node that returns its widget's
value to the nodes wired after it.

Each change is judged by its node's own rule, the one a planned or created
node's setting is judged by, so a mode the pool has not, an empty column, a
setting the node's template does not take or a value its widget would not take
comes back to the model in words it can act on. A key the change gives is
picked as the node's own select picks it, a key it leaves out stays, and ``{}``
puts the whole setting back to its default. The review card names the node and
says each change in the node's own words; Apply writes it into the saved node,
once what it changes is still what the user reviewed.

The modules this adds are imported inside each test, so a before-run fails
here and not the whole collection.
"""
from __future__ import annotations

import json

import pytest

from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests.test_agents.test_map_edits_grounding import _project
from utk_curio.backend.tests.test_agents.test_source_grounding_routes import (
    _attach,
    _install,
    _proposals,
    _run,
    _script,
    _tool_results,
)

NB = "agent.curio.node-builder@1"
DFB = "agent.curio.dataflow-builder@1"
TOOL = "node.settings.write"

COMBINE = {"name": "combine", "type": "choice", "label": "Combine", "default": "mean",
           "options": {"choices": ["mean", "sum", "max"]}}
THRESHOLD = {"name": "threshold", "type": "slider", "label": "Threshold", "default": 2,
             "options": {"min": 0, "max": 10}}
SEASON = {"name": "season", "type": "choice", "default": "summer", "options": {"choices": ["summer", "winter"]}}


def _nodes() -> list[dict]:
    """A node of each kind that keeps a setting, each set off its default."""
    return [
        {"id": "pool", "type": "curio.builtin/data-pool", "title": "Picked photos", "content": "", "x": 0, "y": 0,
         "metadata": {"dataPool": {"insideChart": "MERGE_OR"}}},
        {"id": "view", "type": "curio.builtin/vis-simple", "title": "Overlays", "content": "", "x": 400, "y": 0,
         "metadata": {"simpleVis": {"imageColumn": "image_url"}}},
        {"id": "join", "type": "curio.builtin/spatial-join", "title": "Trees in parks", "content": "",
         "x": 800, "y": 0, "metadata": {"spatialJoin": {"output": "counts"}}},
        {"id": "chart", "type": "curio.builtin/computation-analysis", "title": "Shadow by tract",
         "content": "return input_0.groupby('tract')['shadow'].agg([!! combine !!])", "x": 1200, "y": 0,
         "metadata": {"widgets": [dict(COMBINE), dict(THRESHOLD)]}},
        {"id": "season", "type": "curio.builtin/computation-analysis", "title": "Season",
         "content": "return [!! season !!]", "x": 1600, "y": 0, "metadata": {"widgets": [dict(SEASON)]}},
    ]


def _request(**params) -> str:
    return "```curio.v1\n" + json.dumps({"toolRequest": {"tool": TOOL, "params": params}}) + "\n```"


def _propose(client, user, token, monkeypatch, *, target="pool", coord=NB, **params):
    """A project holding the nodes above, *coord* attached to the node
    *target* (to the canvas when None) and asked once for a change with
    *params*: the project, the attachment, the proposal (None when there is
    none) and what the model was told of its request."""
    project = _project(client, user, token, _nodes())
    _install(client, token, project, *dict.fromkeys((coord, NB)))
    att = _attach(client, token, project, coord, target={"kind": "node", "targetId": target} if target else None)
    calls = _script(monkeypatch, [_request(**params), "Proposed: review it above."])
    proposals = _proposals(_run(client, token, project, att, "change it"))
    return project, att, (proposals[0] if proposals else None), _tool_results(calls[-1], TOOL)


def _apply(client, token, project, att, proposal):
    return client.post(
        f"/api/agents/projects/{project}/attachments/{att}/proposals/{proposal['proposalId']}/apply",
        headers=_auth(token),
    )


def _saved(user, project) -> dict[str, dict]:
    """The saved nodes, by id."""
    from utk_curio.backend.app.projects import storage as projects_storage
    from utk_curio.backend.app.projects.services import _user_dir_key

    spec = projects_storage.read_spec(_user_dir_key(user), project)
    return {node["id"]: node for node in spec["dataflow"]["nodes"]}


def _resave(client, token, project, nodes) -> None:
    """The user's own edit of the nodes, saved as the canvas saves them."""
    response = client.put(
        f"/api/projects/{project}",
        json={"name": "p", "spec": {"dataflow": {"nodes": nodes, "edges": [], "packages": []}}, "outputs": []},
        headers=_auth(token),
    )
    assert response.status_code == 200, response.get_data(as_text=True)


def _modules():
    from utk_curio.backend.app.agents.domain import data_pool_settings, simple_vis_settings, spatial_join_settings

    return data_pool_settings, simple_vis_settings, spatial_join_settings


class TestAChangeIsReadByItsNodesOwnRule:
    def test_each_key_given_is_picked_and_an_empty_setting_is_its_default(self):
        pool, view, join = _modules()
        assert pool.parse_change({"betweenCharts": "MERGE_AND"}, "w") == ({"betweenCharts": "MERGE_AND"}, [])
        # OVERWRITE is a pick of its own on a pool that merges.
        assert pool.parse_change({"insideChart": "OVERWRITE"}, "w") == ({"insideChart": "OVERWRITE"}, [])
        assert pool.parse_change({}, "w") == ({"insideChart": "OVERWRITE", "betweenCharts": "OVERWRITE"}, [])
        # The view reads the name trimmed, and no name as every image column.
        assert view.parse_change({"imageColumn": " overlay_url "}, "w") == ({"imageColumn": "overlay_url"}, [])
        assert view.parse_change({}, "w") == ({}, [])
        assert join.parse_change({"predicate": "within"}, "w") == ({"predicate": "within"}, [])
        assert join.parse_change({}, "w") == ({"predicate": "intersects", "output": "pairs"}, [])
        for module in (pool, view, join):
            assert module.parse_change(None, "w") == (None, []), module.KEY

    @pytest.mark.parametrize(
        "module, raw, expected",
        [
            (0, {"betweenCharts": "AND"},
             "w.betweenCharts must be one of OVERWRITE, MERGE_AND, MERGE_OR; got 'AND', which a Data Pool reads as "
             "OVERWRITE"),
            (0, {"propagate": "MERGE_OR"}, "w has keys a Data Pool does not: propagate (it has insideChart, betweenCharts)"),
            (1, {"imageColumn": ""}, "w.imageColumn must name a column, such as"),
            (1, "overlay_url", "w must be an object, such as"),
            (2, {"predicate": "near"},
             "w: The operation must be one of intersects, within, contains, touches, overlaps, crosses, nearest; "
             "got 'near'."),
        ],
    )
    def test_a_change_the_node_would_not_take_is_named_as_a_new_nodes_setting_is(self, module, raw, expected):
        change, errors = _modules()[module].parse_change(raw, "w")
        assert change is None
        assert any(expected in error for error in errors), errors

    def test_a_change_is_stored_as_the_node_writes_it(self):
        pool, view, join = _modules()
        # The pool keeps the mode the change leaves out, and writes no OVERWRITE.
        assert pool.after({"insideChart": "MERGE_OR"}, {"betweenCharts": "MERGE_AND"}) == {
            "insideChart": "MERGE_OR", "betweenCharts": "MERGE_AND",
        }
        assert pool.after({"insideChart": "MERGE_OR", "betweenCharts": "MERGE_AND"}, {"insideChart": "OVERWRITE"}) == {
            "betweenCharts": "MERGE_AND",
        }
        assert pool.after({"betweenCharts": "MERGE_AND"}, {"insideChart": "OVERWRITE", "betweenCharts": "OVERWRITE"}) is None
        # The view keeps the column it names, and none for every image column.
        assert view.after({"imageColumn": "image_url"}, {"imageColumn": "overlay_url"}) == {"imageColumn": "overlay_url"}
        assert view.after({"imageColumn": "image_url"}, {}) is None
        # The join keeps the key the change leaves out, and writes neither of its defaults.
        assert join.after({"output": "counts"}, {"predicate": "within"}) == {"predicate": "within", "output": "counts"}
        assert join.after({"predicate": "within", "output": "counts"}, {"predicate": "intersects", "output": "pairs"}) is None

    def test_the_card_says_each_change_in_the_nodes_own_words(self):
        from utk_curio.backend.app.agents.domain import node_settings, widget_grammar

        assert node_settings.describe_change({
            "dataPool": {"insideChart": "OVERWRITE"},
            "simpleVis": {},
            "spatialJoin": {"predicate": "intersects", "output": "pairs"},
        }) == ["operation intersects, output pairs", "Conflict inside visualization: Overwrite", "Image column: all"]
        assert node_settings.describe_change({"simpleVis": {"imageColumn": "overlay_url"}}) == [
            "Image column: overlay_url",
        ]
        # A widget as its row in the Widgets tab names it: its label, else its name.
        assert widget_grammar.describe_value(COMBINE, "max") == "Combine: max"
        assert widget_grammar.describe_value(SEASON, "winter") == "season: winter"
        assert widget_grammar.describe_value({"name": "years", "type": "number-list"}, [2020, 2050]) == (
            "years: [2020, 2050]"
        )

    def test_every_image_column_is_the_views_own_word_for_it(self):
        """The view's select offers every image column as ``all``; the card
        and the backend read the word where the select does."""
        from utk_curio.common import shared_constants

        assert shared_constants.read("nodeSettings")["simpleVis"]["all"] == "all"


def test_the_tool_offers_each_setting_with_the_nodes_choices_and_widget_values_by_name():
    from utk_curio.backend.app.agents.application import tools
    from utk_curio.backend.app.common import spatial

    contract = tools.REGISTRY[TOOL]
    assert contract.effect == "mutate"
    assert contract.label == "Propose a settings change"
    params = contract.parameters
    assert list(params["properties"]) == ["nodeId", "dataPool", "simpleVis", "spatialJoin", "widgets"]
    assert "required" not in params
    pool = params["properties"]["dataPool"]["properties"]
    assert pool["insideChart"]["enum"] == pool["betweenCharts"]["enum"] == ["OVERWRITE", "MERGE_AND", "MERGE_OR"]
    join = params["properties"]["spatialJoin"]["properties"]
    assert join["predicate"]["enum"] == list(spatial.PREDICATES)
    assert join["output"]["enum"] == list(spatial.OUTPUTS)
    assert params["properties"]["simpleVis"]["properties"]["imageColumn"]["type"] == "string"
    assert params["properties"]["widgets"]["type"] == "object"
    # A change keeps what it leaves out, where a new node starts at the
    # default: the change tool says so in its own words.
    created = tools.REGISTRY["node.create"].parameters["properties"]
    for key in ("dataPool", "simpleVis", "spatialJoin", "widgets"):
        assert params["properties"][key]["description"] != created[key]["description"], key
        assert f'"{key}"' in contract.description, key


def test_both_builders_are_told_to_change_an_existing_nodes_setting_in_place():
    """Asked to change a setting of a node already on the canvas, a builder
    proposes node.settings.write with just that change, never a new node or
    rewritten content."""
    from utk_curio.backend.app.agents.domain import builtin

    assert "propose node.settings.write with that node's REAL id" in builtin.read_prompt_text(DFB, "instruction")
    assert "propose node.settings.write with just that change" in builtin.read_prompt_text(NB, "instruction")


def test_every_agent_reads_how_an_existing_nodes_settings_change():
    """The pages the preamble includes say it of each setting where they
    describe it: the pool's modes, the view's column, the join's operation and
    output, and widget values."""
    from utk_curio.backend.app.agents.domain import builtin

    preamble = builtin.read_prompt_text(DFB, "system")
    for words in (
        "A pool already on the canvas changes its modes through node.settings.write",
        "A view already on the canvas changes its column through node.settings.write",
        "one already on the canvas changes them through node.settings.write",
        "A node already on the canvas takes new widget values through node.settings.write",
    ):
        assert words in preamble, words


class TestAChangeReachesTheCardAndTheNode:
    def test_a_pools_mode_is_changed_beside_the_one_it_leaves(
        self, client, user_and_token, tmp_curio, monkeypatch,
    ):
        user, token = user_and_token
        project, att, proposal, [said] = _propose(
            client, user, token, monkeypatch, target="pool", dataPool={"betweenCharts": "MERGE_AND"},
        )
        assert said.startswith(f"[tool result] {TOOL}: proposed"), said
        assert proposal["summary"] == "Change the settings of the Data Pool node · Picked photos"
        assert proposal["settingLines"] == ["Conflict between visualizations: Merge (AND)"]
        assert proposal["pins"]["nodeId"] == "pool"
        # Nothing changes before the user applies it.
        assert _saved(user, project)["pool"]["metadata"]["dataPool"] == {"insideChart": "MERGE_OR"}

        response = _apply(client, token, project, att, proposal)
        assert response.status_code == 200, response.get_json()
        assert _saved(user, project)["pool"]["metadata"]["dataPool"] == {
            "insideChart": "MERGE_OR", "betweenCharts": "MERGE_AND",
        }
        # The canvas takes the change through the node's own select, and the
        # agent that proposed it is named.
        assert response.get_json()["appliedSettings"] == {
            "nodeId": "pool", "settings": {"dataPool": {"betweenCharts": "MERGE_AND"}}, "agent": "Node Builder",
        }
        turns = client.get(
            f"/api/agents/projects/{project}/attachments/{att}/session", headers=_auth(token),
        ).get_json()["turns"]
        result = json.dumps(turns[-1], ensure_ascii=False)
        assert "Applied: Data Pool node · Picked photos settings changed." in result
        assert "Conflict between visualizations: Merge (AND)" in result

    def test_a_pools_mode_back_at_overwrite_is_written_as_the_pool_writes_it(
        self, client, user_and_token, tmp_curio, monkeypatch,
    ):
        user, token = user_and_token
        project, att, proposal, _ = _propose(
            client, user, token, monkeypatch, target="pool", dataPool={"insideChart": "OVERWRITE"},
        )
        assert proposal["settingLines"] == ["Conflict inside visualization: Overwrite"]
        assert _apply(client, token, project, att, proposal).status_code == 200
        assert "dataPool" not in (_saved(user, project)["pool"].get("metadata") or {})

    def test_a_views_image_column(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        project, att, proposal, _ = _propose(
            client, user, token, monkeypatch, target="view", simpleVis={"imageColumn": " overlay_url "},
        )
        assert proposal["summary"] == "Change the settings of the Simple View node · Overlays"
        assert proposal["settingLines"] == ["Image column: overlay_url"]
        response = _apply(client, token, project, att, proposal)
        assert response.status_code == 200, response.get_json()
        assert _saved(user, project)["view"]["metadata"]["simpleVis"] == {"imageColumn": "overlay_url"}
        assert response.get_json()["appliedSettings"]["settings"] == {"simpleVis": {"imageColumn": "overlay_url"}}

    def test_every_image_column_clears_the_views_setting(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        project, att, proposal, _ = _propose(client, user, token, monkeypatch, target="view", simpleVis={})
        assert proposal["settingLines"] == ["Image column: all"]
        response = _apply(client, token, project, att, proposal)
        assert response.status_code == 200, response.get_json()
        assert "simpleVis" not in (_saved(user, project)["view"].get("metadata") or {})
        assert response.get_json()["appliedSettings"]["settings"] == {"simpleVis": {}}

    def test_a_joins_operation_keeps_its_output(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        project, att, proposal, _ = _propose(
            client, user, token, monkeypatch, target="join", spatialJoin={"predicate": "within"},
        )
        assert proposal["summary"] == "Change the settings of the Spatial Join node · Trees in parks"
        assert proposal["settingLines"] == ["operation within"]
        assert _apply(client, token, project, att, proposal).status_code == 200
        assert _saved(user, project)["join"]["metadata"]["spatialJoin"] == {"predicate": "within", "output": "counts"}

    def test_a_code_nodes_widget_value(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        project, att, proposal, _ = _propose(client, user, token, monkeypatch, target="chart", widgets={"combine": "max"})
        assert proposal["summary"] == "Change the settings of the Python Computation node · Shadow by tract"
        assert proposal["settingLines"] == ["Combine: max"]
        response = _apply(client, token, project, att, proposal)
        assert response.status_code == 200, response.get_json()
        widgets = {w["name"]: w for w in _saved(user, project)["chart"]["metadata"]["widgets"]}
        assert widgets["combine"]["value"] == "max"
        assert "value" not in widgets["threshold"]
        assert response.get_json()["appliedSettings"]["settings"] == {"widgets": {"combine": "max"}}

    def test_a_value_nodes_value_named_from_the_canvas(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        project, att, proposal, _ = _propose(
            client, user, token, monkeypatch, target=None, nodeId="season", widgets={"season": "winter"},
        )
        assert proposal["summary"] == "Change the settings of the Python Computation node · Season"
        assert proposal["settingLines"] == ["season: winter"]
        assert _apply(client, token, project, att, proposal).status_code == 200
        assert _saved(user, project)["season"]["metadata"]["widgets"][0]["value"] == "winter"

    def test_the_dataflow_builder_proposes_one_too(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        project, att, proposal, [said] = _propose(
            client, user, token, monkeypatch, target=None, coord=DFB, nodeId="pool",
            dataPool={"betweenCharts": "MERGE_AND"},
        )
        assert said.startswith(f"[tool result] {TOOL}: proposed"), said
        assert proposal["settingLines"] == ["Conflict between visualizations: Merge (AND)"]
        assert _apply(client, token, project, att, proposal).status_code == 200
        assert _saved(user, project)["pool"]["metadata"]["dataPool"]["betweenCharts"] == "MERGE_AND"


class TestAWrongChangeIsRefusedToTheModel:
    @staticmethod
    def _refused(client, user, token, monkeypatch, **kw) -> str:
        _project_id, _att, proposal, said = _propose(client, user, token, monkeypatch, **kw)
        assert proposal is None, "the change was proposed"
        [refused] = said
        assert refused.startswith(f"[tool result] {TOOL}: refused"), refused
        return refused

    def test_a_mode_the_pool_has_not(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        refused = self._refused(client, user, token, monkeypatch, target="pool", dataPool={"betweenCharts": "AND"})
        assert (
            "params.dataPool.betweenCharts must be one of OVERWRITE, MERGE_AND, MERGE_OR; got 'AND', "
            "which a Data Pool reads as OVERWRITE"
        ) in refused, refused

    def test_an_empty_image_column(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        refused = self._refused(client, user, token, monkeypatch, target="view", simpleVis={"imageColumn": "  "})
        assert "params.simpleVis.imageColumn must name a column, such as" in refused, refused

    def test_an_operation_the_join_has_not(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        refused = self._refused(client, user, token, monkeypatch, target="join", spatialJoin={"predicate": "near"})
        assert (
            "params.spatialJoin: The operation must be one of intersects, within, contains, touches, overlaps, "
            "crosses, nearest; got 'near'."
        ) in refused, refused

    def test_a_setting_the_nodes_template_does_not_take(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        refused = self._refused(
            client, user, token, monkeypatch, target="view", dataPool={"betweenCharts": "MERGE_AND"},
        )
        assert (
            "params.dataPool: a Simple View node has no conflict modes; only a Data Pool node takes dataPool"
        ) in refused, refused
        # An empty setting too: it would put a setting the node has not back to its default.
        refused = self._refused(client, user, token, monkeypatch, target="pool", spatialJoin={})
        assert (
            "params.spatialJoin: a Data Pool node has no operation or output; only a Spatial Join node takes "
            "spatialJoin"
        ) in refused, refused

    def test_a_widget_the_node_has_not(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        refused = self._refused(client, user, token, monkeypatch, target="chart", widgets={"stat": "max"})
        assert (
            "params.widgets.stat: the Python Computation node has no widget named 'stat'; it has combine, threshold"
        ) in refused, refused
        refused = self._refused(client, user, token, monkeypatch, target="pool", widgets={"combine": "max"})
        assert "params.widgets.combine: the Data Pool node has no widget named 'combine'; it has none" in refused, (
            refused
        )

    def test_a_value_outside_its_widgets_options_or_range_in_the_widgets_words(
        self, client, user_and_token, tmp_curio, monkeypatch,
    ):
        user, token = user_and_token
        refused = self._refused(
            client, user, token, monkeypatch, target="chart", widgets={"combine": "median", "threshold": 12},
        )
        # As the Widgets tab says it of a value the user types.
        assert "params.widgets.combine: Pick one of the choices." in refused, refused
        assert "params.widgets.threshold: Enter a number from 0 to 10." in refused, refused

    def test_widget_values_not_given_by_name(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        refused = self._refused(client, user, token, monkeypatch, target="chart", widgets=["max"])
        assert "params.widgets must map each widget's name to its new value" in refused, refused

    def test_a_change_the_node_already_has(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        refused = self._refused(client, user, token, monkeypatch, target="pool", dataPool={"insideChart": "MERGE_OR"})
        assert (
            "params changes nothing: the Data Pool node already has Conflict inside visualization: Merge (OR)"
        ) in refused, refused

    def test_a_request_that_changes_no_setting(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        refused = self._refused(client, user, token, monkeypatch, target="pool")
        assert "params names no setting to change: give dataPool, simpleVis, spatialJoin or widgets" in refused, (
            refused
        )
        refused = self._refused(client, user, token, monkeypatch, target="chart", content="return 1")
        assert (
            "params has keys node.settings.write does not take: content "
            "(it takes nodeId, dataPool, simpleVis, spatialJoin, widgets)"
        ) in refused, refused


class TestApplyChecksWhatTheUserReviewed:
    def test_a_setting_changed_since_the_review_is_refused_and_kept(
        self, client, user_and_token, tmp_curio, monkeypatch,
    ):
        user, token = user_and_token
        project, att, proposal, _ = _propose(
            client, user, token, monkeypatch, target="pool", dataPool={"betweenCharts": "MERGE_AND"},
        )
        # The user picks another mode in the pool before reviewing the card.
        nodes = _nodes()
        nodes[0]["metadata"]["dataPool"] = {"insideChart": "MERGE_OR", "betweenCharts": "MERGE_OR"}
        _resave(client, token, project, nodes)

        response = _apply(client, token, project, att, proposal)
        assert response.status_code == 409, response.get_json()
        assert "changed since" in response.get_json()["error"]
        assert _saved(user, project)["pool"]["metadata"]["dataPool"] == {
            "insideChart": "MERGE_OR", "betweenCharts": "MERGE_OR",
        }
        cards = client.get(f"/api/agents/projects/{project}/attachments", headers=_auth(token)).get_json()
        assert cards["attachments"][0]["activeProposal"]["status"] == "stale"

    def test_what_the_change_does_not_touch_may_change_since_the_review(
        self, client, user_and_token, tmp_curio, monkeypatch,
    ):
        """The review pins what the change touches: the node moved and its
        other widget given a value still apply."""
        user, token = user_and_token
        project, att, proposal, _ = _propose(client, user, token, monkeypatch, target="chart", widgets={"combine": "max"})
        nodes = _nodes()
        nodes[3]["x"] = 1500
        nodes[3]["metadata"]["widgets"][1]["value"] = 7
        _resave(client, token, project, nodes)

        response = _apply(client, token, project, att, proposal)
        assert response.status_code == 200, response.get_json()
        widgets = {w["name"]: w for w in _saved(user, project)["chart"]["metadata"]["widgets"]}
        assert widgets["combine"]["value"] == "max"
        assert widgets["threshold"]["value"] == 7
