"""The dashboard of a hosted guest's own new dataflow is that guest's alone
(``projects/visitor_copies.py``, ``runs/viewer.py``).

A hosted guest's File > New makes a dataflow of its own, which has no row.
Its dashboard (``/dashboard/<id>``, which the canvas's Share > Open dashboard
opens) shows that dataflow as it is now, with no saved output, and its viewer
runs run its code and keep what they make on it, as a guest's dashboard of an
example does on the guest's copy (``test_guest_dashboard_copy.py``, whose
dataflow, sandbox and output reader these tests use). Another guest, and a
visitor who sends no sign-in, find no such dashboard: not its page, its runs
nor its outputs.
"""
from __future__ import annotations

import json

import pytest

from utk_curio.backend import config
from utk_curio.backend.app.runs.models import KeptStepOutput
from utk_curio.backend.tests.test_datasets.computed_test_helpers import auth_headers
from utk_curio.backend.tests.test_projects.test_guest_copy_leaks import VISITOR_A, VISITOR_B
from utk_curio.backend.tests.test_projects.test_guest_dashboard_copy import (  # noqa: F401 - fixtures
    EDGES,
    SHIPPED_CODE,
    _headers,
    _nodes,
    _ran,
    _shade,
    _start,
    app,
    relayed,
    sandbox,
)


@pytest.fixture()
def mine(client, db, monkeypatch):
    """The dataflow VISITOR_A's File > New makes, with Shade pinned, reading
    its own Period, and feeding the pinned chart, as the example of
    ``test_guest_dashboard_copy.py`` has them; its id. Both visitors are
    signed in to the shared guest account, with sign-in on, as on a Curio
    started with ``--deploy``."""
    from utk_curio.backend.app.users.models import User, UserSession

    guest = User(username=config.CURIO_SHARED_GUEST_USERNAME, name="Guest",
                 email="guest@test.com", is_guest=True)
    db.session.add(guest)
    db.session.flush()
    for token in (VISITOR_A, VISITOR_B):
        db.session.add(UserSession(user_id=guest.id, token=token))
    db.session.commit()
    monkeypatch.setattr(config, "CURIO_NO_AUTH", False)
    created = client.post("/api/projects", data=json.dumps({
        "name": "Mine",
        "spec": {"dataflow": {"name": "Mine", "nodes": _nodes(), "edges": EDGES}},
        "outputs": [],
    }), headers=auth_headers(VISITOR_A))
    assert created.status_code == 201, created.get_data(as_text=True)
    assert created.get_json()["kept_for_visit"] is True
    return created.get_json()["id"]


def test_a_guests_dashboard_page_of_its_new_dataflow_is_its_own(client, mine):
    page = client.get(f"/api/projects/{mine}/dashboard", headers=auth_headers(VISITOR_A))
    assert page.status_code == 200, page.get_data(as_text=True)
    body = json.loads(page.get_data(as_text=True))

    # The dataflow as it is, named as A named it, with no saved output: the
    # page runs what its tiles show when it opens.
    assert body["meta"]["name"] == "Mine"
    assert _shade(body["spec"])["content"] == SHIPPED_CODE
    assert body["outputs"] == {}
    assert body["outputRefs"] == []
    # The account's packages draw its tiles, as an account's page has its own.
    assert "curio.builtin" in [p.get("packageId") for p in body["registry"]["packages"]]
    # A page that loads its own data gets the same dataflow.
    loaded = client.get(f"/api/projects/{mine}", headers=auth_headers(VISITOR_A))
    assert loaded.status_code == 200, loaded.get_data(as_text=True)
    assert _shade(loaded.get_json()["spec"])["content"] == SHIPPED_CODE
    assert loaded.get_json()["outputs"] == []

    # Another guest, and a visitor who sends no sign-in, find none.
    for token, path in (
        (VISITOR_B, f"/api/projects/{mine}/dashboard"),
        (None, f"/api/projects/{mine}/dashboard"),
        (VISITOR_B, f"/api/projects/{mine}"),
    ):
        refused = client.get(path, headers=_headers(token))
        assert refused.status_code == 404, (token, path, refused.get_data(as_text=True))


def test_a_guests_dashboard_runs_its_new_dataflow_and_keeps_on_it_for_it_alone(client, mine, sandbox, relayed):
    # A's page opens with no saved output: Shade runs with its saved Period,
    # and again with the Period A picks.
    _ran(client, VISITOR_A, mine, {})
    _ran(client, VISITOR_A, mine, {"shade": {"period": "Month"}})

    codes = [body["code"] for _node, body in sandbox.runs]
    assert len(codes) == 2, codes
    assert '"Date"' in codes[0] and '"Month"' in codes[1], codes
    # What A's runs made is kept on A's dataflow.
    made = KeptStepOutput.query.filter_by(project_id=mine).order_by(KeptStepOutput.id).all()
    assert len(made) == 2
    assert KeptStepOutput.query.count() == 2

    # Another guest, and a visitor who sends no sign-in, start no run of it.
    for token in (VISITOR_B, None):
        refused = _start(client, token, mine, {"shade": {"period": "Year"}})
        assert refused.status_code == 404, (token, refused.get_data(as_text=True))
    assert len(sandbox.runs) == 2

    # A's output is read on A's dashboard alone, in the session that made it.
    read = f"/api/projects/{mine}/dashboard/outputs/get"
    for token, status in ((VISITOR_A, 200), (VISITOR_B, 404), (None, 404)):
        resp = client.get(read, query_string={"fileName": made[-1].output_path}, headers=_headers(token))
        assert resp.status_code == status, (token, resp.get_data(as_text=True))
    assert relayed == [{"fileName": made[-1].output_path, "sessionId": made[-1].session_id}]
