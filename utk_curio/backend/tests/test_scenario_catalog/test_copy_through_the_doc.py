"""A scenario dropped into another dataflow adds the packages its levers need
to that dataflow's lockfile through the target's doc
(``collaboration/dataflow_docs.py``), so a tab of the target in its room gets
them as the drop lands, before any save.
"""

from __future__ import annotations

import pytest

from .test_copy import BASELINE, _copy, _node, _save_outputs, _source_and_target, _spec


@pytest.fixture(autouse=True)
def _rooms():
    from utk_curio.backend.app.collaboration import room_state

    room_state.reset_for_tests()
    yield
    room_state.reset_for_tests()


def test_a_drops_package_reaches_a_tab_of_its_target(app, client, user_and_token):
    from utk_curio.backend.tests.test_collaboration._ydoc_client import synced_tab

    _, token = user_and_token
    nodes = [
        _node("load", "data-loading", "return 1"),
        {"id": "a", "type": "curio.example-ui/column-filter@1", "content": "return input_0", "x": 300, "y": 0},
    ]
    edges = [{"id": "e1", "source": "load", "target": "a", "sourceHandle": "out", "targetHandle": "in"}]
    source, target = _source_and_target(client, token, _spec("Shadows", [{**BASELINE, "nodes": ["a"]}], nodes, edges))
    _save_outputs(client, token, source, {"load": "id\n1\n"})
    tab = synced_tab(app, token, target)
    assert "curio.example-ui@1" not in (tab.dataflow().get("packages") or [])

    resp = _copy(client, token, source, target, [{"source": "load", "node": "loader-1"}])

    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json()["added"] == ["curio.example-ui@1"]
    assert "curio.example-ui@1" in (tab.dataflow().get("packages") or []), (
        "the package the drop added never reached the target's tab"
    )
