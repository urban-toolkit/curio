"""The Computed tab lists node outputs newest first: by when each was computed.

The drawer asks for "Sort: Recent activity", which orders by ``updatedAt``. A
save sends the output of every node the dataflow keeps, and a run on the server
records the output its play just installed, so most outputs are installed again
and again without changing. Each of those installs dated the dataset anew, to
the second: a save that sent an older output again, a second after a newer one
was computed, listed the older one first. That is the order
``test_computed_json_output_e2e.py`` saw flip between runs (the dict's dataset
before the scalar's).

Every test saves as the canvas does, through ``PUT /api/projects/<id>``, with
the record clock stopped at chosen moments, and reads the order the drawer's
Computed tab asks for.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from utk_curio.backend.app.datasets.install.installer import computed_dataset_id
from utk_curio.backend.tests.test_datasets.computed_test_helpers import (
    auth_headers,
    create_project,
    store_sandbox_artifact,
)

START = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
# What the canvas sends with each output (``buildOutputRefs``): the node's
# header and type. One name for every node, so a title never breaks a tie.
LABEL = "Python Computation"
NODE_TYPE = "curio.builtin/computation-analysis"


@pytest.fixture()
def clock(monkeypatch):
    """The record clock, stopped; ``clock(s)`` moves it to *s* seconds past START.

    Stopped rather than set (``record_clock.set_now`` runs on from the moment it
    is given), so a slow runner cannot carry a step into the next second.
    """
    from utk_curio.backend.app.common import record_clock

    stopped = {"at": START}

    class _Stopped(datetime):
        @classmethod
        def now(cls, tz=None):
            moment = stopped["at"]
            return moment.astimezone(tz) if tz is not None else moment.replace(tzinfo=None)

    monkeypatch.setattr(record_clock, "datetime", _Stopped)
    monkeypatch.setattr(record_clock, "_offset", timedelta(0))

    def move_to(seconds: float) -> None:
        stopped["at"] = START + timedelta(seconds=seconds)

    return move_to


def _ref(node_id: str, artifact: str, data_type: str) -> dict:
    return {
        "node_id": node_id,
        "filename": artifact,
        "data_type": data_type,
        "node_name": LABEL,
        "node_type": NODE_TYPE,
    }


def _save(client, token, project_id: str, *refs: dict) -> None:
    resp = client.put(
        f"/api/projects/{project_id}",
        data=json.dumps({"outputs": list(refs)}),
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    warnings = resp.get_json().get("dataset_install_warnings")
    assert warnings == [], warnings


def _computed_tab(client, token, project_id: str, ids: list[str]) -> list[tuple[str, str]]:
    """``(id, updatedAt)`` of *ids*, in the order the drawer's Computed tab lists them."""
    resp = client.get(
        f"/api/datasets/catalog?includeHub=true&dataflowId={project_id}"
        "&sort=recent&origin=computed",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    wanted = set(ids)
    return [
        (item["id"], item.get("updatedAt"))
        for item in resp.get_json()["items"]
        if item["id"] in wanted
    ]


@pytest.mark.parametrize(
    "value,data_type",
    [
        ({"city": "Chicago", "zones": [1, 2, 3]}, "dict"),
        ((1, "x"), "outputs"),
    ],
    ids=["one-file", "bundle"],
)
def test_an_output_sent_again_unchanged_keeps_its_date(
    app, client, user_and_token, clock, value, data_type
):
    """The e2e's case: the dict ran first, the scalar second, and the save that
    followed the scalar's run sent the dict's output again, in the next second.

    The ids are the e2e's too: on a tie of time the scalar's sorts first, so
    only a new date on the dict's dataset puts it first.
    """
    _, token = user_and_token
    project = create_project(client, token)
    first = store_sandbox_artifact(value, node_id="json-output-b-dict")
    later = store_sandbox_artifact(42, node_id="json-output-a-scalar")
    first_id = computed_dataset_id("json-output-b-dict", project)
    later_id = computed_dataset_id("json-output-a-scalar", project)
    ids = [first_id, later_id]

    clock(0.2)
    _save(client, token, project, _ref("json-output-b-dict", first, data_type))
    computed_at = dict(_computed_tab(client, token, project, ids))[first_id]

    clock(0.7)
    _save(
        client, token, project,
        _ref("json-output-b-dict", first, data_type),
        _ref("json-output-a-scalar", later, "int"),
    )
    clock(1.2)
    _save(client, token, project, _ref("json-output-b-dict", first, data_type))

    listed = _computed_tab(client, token, project, ids)
    assert dict(listed)[first_id] == computed_at, (
        "the first output was computed at {} and is dated {} after a save sent "
        "it again unchanged; only a new output dates a dataset".format(
            computed_at, dict(listed)[first_id]
        )
    )
    assert [dataset_id for dataset_id, _ in listed] == [later_id, first_id], (
        "the Computed tab lists {}; the output computed last comes first".format(listed)
    )


def test_outputs_computed_in_one_second_list_the_later_first(
    app, client, user_and_token, clock
):
    """Two nodes computed half a second apart, the later one's id sorting
    last, and a save that then sends both outputs again unchanged."""
    _, token = user_and_token
    project = create_project(client, token)
    first = store_sandbox_artifact({"step": 1}, node_id="a-first")
    later = store_sandbox_artifact({"step": 2}, node_id="b-later")
    first_id = computed_dataset_id("a-first", project)
    later_id = computed_dataset_id("b-later", project)

    clock(0.2)
    _save(client, token, project, _ref("a-first", first, "dict"))
    clock(0.7)
    _save(client, token, project, _ref("a-first", first, "dict"), _ref("b-later", later, "dict"))
    clock(1.2)
    _save(client, token, project, _ref("a-first", first, "dict"), _ref("b-later", later, "dict"))

    listed = _computed_tab(client, token, project, [first_id, later_id])
    assert [dataset_id for dataset_id, _ in listed] == [later_id, first_id], (
        "the Computed tab lists {}; b-later was computed half a second after "
        "a-first, so it comes first".format(listed)
    )


def test_a_node_that_runs_again_moves_its_dataset_up(app, client, user_and_token, clock):
    """A new output is new activity: its dataset is dated when it is installed."""
    _, token = user_and_token
    project = create_project(client, token)
    first_output = store_sandbox_artifact({"run": 1}, node_id="a-rerun")
    other_output = store_sandbox_artifact({"run": 1}, node_id="b-other")
    rerun_id = computed_dataset_id("a-rerun", project)
    other_id = computed_dataset_id("b-other", project)

    clock(0.2)
    _save(client, token, project, _ref("a-rerun", first_output, "dict"))
    clock(0.7)
    _save(
        client, token, project,
        _ref("a-rerun", first_output, "dict"),
        _ref("b-other", other_output, "dict"),
    )
    clock(1.2)
    second_output = store_sandbox_artifact({"run": 2}, node_id="a-rerun")
    _save(
        client, token, project,
        _ref("a-rerun", second_output, "dict"),
        _ref("b-other", other_output, "dict"),
    )

    listed = _computed_tab(client, token, project, [rerun_id, other_id])
    assert [dataset_id for dataset_id, _ in listed] == [rerun_id, other_id], listed
    rerun_at = datetime.fromisoformat(dict(listed)[rerun_id])
    assert rerun_at >= START + timedelta(seconds=1), (
        "a-rerun ran again at 12:00:01.2 and its dataset is dated {}".format(rerun_at)
    )
