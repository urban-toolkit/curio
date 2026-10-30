"""The dashboard's Save layout writes where its tiles sit, and nothing else.

The dashboard page binds to no doc: a viewer's tried values never reach the
dataflow. Its Save layout sends each tile's place and size
(``PUT /api/projects/<id>/dashboard/layout``), which the server writes into the
dataflow's doc as the owner's change. The rest of the dataflow is the doc's,
whatever the page holds of it.
"""
import json

from utk_curio.backend.tests.test_projects.test_dashboard_route import (
    _auth,
    _create,
    _second_session,
    _spec_with_pinned_chart,
)


def _layout(client, token, pid, tiles):
    return client.put(
        f"/api/projects/{pid}/dashboard/layout",
        data=json.dumps({"tiles": tiles}),
        headers=_auth(token),
    )


def _nodes(user, pid) -> dict:
    """The dataflow's nodes as its doc holds them, by id."""
    from utk_curio.backend.app.collaboration import dataflow_docs
    from utk_curio.backend.app.projects.services import _user_dir_key

    spec = dataflow_docs.read(_user_dir_key(user), pid)
    return {node["id"]: node for node in spec["dataflow"]["nodes"]}


def _pinned_chart_with_code():
    spec = _spec_with_pinned_chart()
    chart = spec["dataflow"]["nodes"][1]
    chart["content"] = '{"mark": "bar"}'
    chart["dashboardX"], chart["dashboardY"] = 10, 20
    return spec


def test_save_layout_writes_each_tiles_place_and_size(client, user_and_token, tmp_curio):
    user, token = user_and_token
    pid = _create(client, token, spec=_pinned_chart_with_code())

    resp = _layout(client, token, pid, {"chart": {
        "dashboardX": 400, "dashboardY": 80, "dashboardWidth": 640, "dashboardHeight": 360,
    }})

    assert resp.status_code == 200, resp.get_data(as_text=True)
    chart = _nodes(user, pid)["chart"]
    assert (chart["dashboardX"], chart["dashboardY"]) == (400, 80)
    assert (chart["dashboardWidth"], chart["dashboardHeight"]) == (640, 360)


def test_save_layout_changes_nothing_but_the_tiles(client, user_and_token, tmp_curio):
    user, token = user_and_token
    pid = _create(client, token, spec=_pinned_chart_with_code())
    before = _nodes(user, pid)

    assert _layout(client, token, pid, {"chart": {"dashboardX": 400, "dashboardY": 80}}).status_code == 200

    after = _nodes(user, pid)
    assert after["py"] == before["py"]
    tile_fields = {"dashboardX", "dashboardY"}
    assert {k: v for k, v in after["chart"].items() if k not in tile_fields} == {
        k: v for k, v in before["chart"].items() if k not in tile_fields
    }


def test_a_tile_of_a_node_the_dataflow_no_longer_holds_is_left_out(client, user_and_token, tmp_curio):
    user, token = user_and_token
    pid = _create(client, token, spec=_pinned_chart_with_code())

    resp = _layout(client, token, pid, {"gone": {"dashboardX": 1, "dashboardY": 2}})

    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert set(_nodes(user, pid)) == {"py", "chart"}


def test_a_place_given_by_halves_is_refused(client, user_and_token, tmp_curio):
    user, token = user_and_token
    pid = _create(client, token, spec=_pinned_chart_with_code())

    for tile in ({"dashboardX": 400}, {"dashboardWidth": 640}, {"dashboardX": "400", "dashboardY": 80}):
        assert _layout(client, token, pid, {"chart": tile}).status_code == 400, tile

    chart = _nodes(user, pid)["chart"]
    assert (chart["dashboardX"], chart["dashboardY"]) == (10, 20)


def test_another_account_may_not_save_the_layout(client, user_and_token, db, tmp_curio):
    user, token = user_and_token
    pid = _create(client, token, spec=_pinned_chart_with_code())
    other = _second_session(db)

    resp = _layout(client, other, pid, {"chart": {"dashboardX": 400, "dashboardY": 80}})

    assert resp.status_code == 404
    assert _nodes(user, pid)["chart"]["dashboardX"] == 10
