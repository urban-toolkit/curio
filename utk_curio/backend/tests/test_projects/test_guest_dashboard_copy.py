"""A hosted guest's dashboard of an example is their own copy's
(``projects/visitor_copies.py``).

Every hosted guest (a guest on a Curio started with ``--deploy``) signs in to
the one shared guest account, which owns the shipped examples, and what a
guest changes in an example is kept in a copy of it of their own: what their
agents write, their plays, their datasets, their name for it. The example's
dashboard (``/dashboard/<id>``) shows that guest the copy too: its page
carries the copy's pins, tiles and code, with the saved outputs that still
hold for the copy, and its viewer runs (``runs/viewer.py``) run the copy's
code, read the guest's own datasets and keep what they make on the copy.

These tests sign two visitors, A and B, in to that account, as
``test_guest_copy_leaks.py`` does, and change A's copy as an agent's change
lands there, through ``visitor_copies``. B, a guest with no copy, and a
visitor who sends no sign-in get the example as it ships, and the example's
spec, manifest and kept outputs are byte for byte what they were.

The example pins Shade, a Python node whose code reads its own widget,
Period, and the chart Shade feeds, whose tile reads Shade's output, which the
example ships saved. The sandbox is ``FakeSandbox``: a node's run answers an
artifact named after the node, and each run is recorded with what it sent.
"""
from __future__ import annotations

import hashlib
import io
import json

import pandas as pd
import pytest

from utk_curio.backend import config
from utk_curio.backend.app.common.user_storage import GUEST_KEY
from utk_curio.backend.app.runs.models import KeptStepOutput
from utk_curio.backend.tests.test_datasets.computed_test_helpers import (
    auth_headers,
    store_sandbox_artifact,
)
from utk_curio.backend.tests.test_projects.test_guest_copy_leaks import (
    VISITOR_A,
    VISITOR_B,
    _copy_of,
    _digests,
    _open,
)
from utk_curio.backend.tests.test_runs.test_dashboard_viewer_runs import FakeSandbox, _wait

CODE = "curio.builtin/python-computation"
CHART = "curio.builtin/vis-vega"
#: Shade's code as the example ships it, and as A's copy holds it.
SHIPPED_CODE = "# node shade\nreturn [!! period !!]"
COPY_CODE = "# node shade\nreturn [!! period !!] + ' (my copy)'"
#: What A's copy's code adds to Shade's result, which the example's never does.
MINE = "(my copy)"


def _period() -> dict:
    return {
        "name": "period", "type": "choice", "label": "Period", "default": "Date",
        "options": {"choices": ["Date", "Month", "Year"], "display": "radio"},
    }


def _nodes() -> list:
    """Shade, pinned, reading its own Period, feeds the pinned chart."""
    return [
        {"id": "shade", "type": CODE, "content": SHIPPED_CODE, "dashboardPinned": True,
         "metadata": {"widgets": [_period()]}},
        {"id": "chart", "type": CHART, "content": "{}", "dashboardPinned": True},
    ]


EDGES = [{"id": "shade-chart", "source": "shade", "target": "chart"}]


@pytest.fixture()
def app(tmp_curio, tmp_path, monkeypatch):
    """The app on a fresh workspace whose store a test writes artifacts to, as
    ``test_guest_copy_leaks.py``'s is, with its database in a file: a viewer's
    run writes from threads of its own (``test_runs/conftest.py``)."""
    from utk_curio.backend.app import create_app
    from utk_curio.backend.extensions import db as _db
    from utk_curio.backend.tests._unit_fixtures import TestConfig
    from utk_curio.sandbox.util.db import release_connection

    class FileConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'guest-dashboard.db'}"

    release_connection()
    monkeypatch.setenv("CURIO_SHARED_DATA", str(tmp_curio / ".curio" / "data"))
    application = create_app(FileConfig)
    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()
        _db.engine.dispose()
    release_connection()


@pytest.fixture()
def dashboard(client, db, monkeypatch):
    """The example the shared guest owns, saved as the local guest saves one,
    with sign-in off, with Shade's output saved. The visitors come with sign-in
    on, as on a Curio started with ``--deploy``, and each opens the example
    once, as their canvases do, before anything is measured. Its id, and
    Shade's saved output."""
    from utk_curio.backend.app.users.models import User, UserSession

    guest = User(username=config.CURIO_SHARED_GUEST_USERNAME, name="Guest",
                 email="guest@test.com", is_guest=True)
    db.session.add(guest)
    db.session.flush()
    for token in (VISITOR_A, VISITOR_B):
        db.session.add(UserSession(user_id=guest.id, token=token))
    db.session.commit()
    saved = store_sandbox_artifact(pd.DataFrame({"period": ["Date"]}), node_id="shade")
    monkeypatch.setattr(config, "CURIO_NO_AUTH", True)
    created = client.post("/api/projects", data=json.dumps({
        "name": "Example",
        "spec": {"dataflow": {"name": "Example", "nodes": _nodes(), "edges": EDGES}},
        "outputs": [{"node_id": "shade", "filename": saved, "data_type": "dataframe"}],
    }), headers=auth_headers(VISITOR_A))
    assert created.status_code == 201, created.get_data(as_text=True)
    monkeypatch.setattr(config, "CURIO_NO_AUTH", False)
    example = created.get_json()["id"]
    for token in (VISITOR_A, VISITOR_B):
        _open(client, token, example)
    # The example ships with Shade's output saved, which its dashboard shows.
    assert {o["node_id"]: o["filename"] for o in _load(client, VISITOR_B, example)["outputs"]} == {"shade": saved}
    return example, saved


@pytest.fixture()
def sandbox(app, monkeypatch):
    """The fake sandbox behind every run, with no run live and no budget spent."""
    from utk_curio.backend.app.runs import jobs, viewer

    jobs.REGISTRY.reset()
    viewer.reset()
    fake = FakeSandbox()
    monkeypatch.setattr("utk_curio.backend.app.execution.node_exec.sandbox_request", fake)
    monkeypatch.setattr("utk_curio.backend.app.runs.viewer.sandbox_request", fake)
    monkeypatch.setattr("utk_curio.backend.app.runs.kept.sandbox_request", fake)
    yield fake
    fake.release()


@pytest.fixture()
def embedded(monkeypatch):
    """A dashboard's page built with each saved output a tile reads as the
    sandbox would answer it, and no descriptors; the saved outputs it read."""
    from utk_curio.backend.app.projects import services

    read: list = []

    def reader(_saved_path_of):
        def one(filename):
            read.append(filename)
            return {"dataType": "dataframe", "data": {"period": ["Date"]}, "schema": {}}
        return one

    monkeypatch.setattr(services, "_dashboard_envelope_reader", reader)
    monkeypatch.setattr(services, "_dashboard_registry",
                        lambda project_id: {"packages": [], "starters": [], "behaviorScripts": {}})
    return read


@pytest.fixture()
def relayed(monkeypatch):
    """The sandbox's answers to a dashboard's output reads: each read's
    parameters, as the backend relays it."""
    from utk_curio.backend.app.api import routes as api_routes

    asked: list = []

    class Stream:
        ok = True
        status_code = 200
        headers = {"Content-Type": "application/json"}

        def iter_content(self, chunk_size):
            yield b'{"dataType": "str", "data": "Month"}'

        def close(self):
            pass

    def sandbox_call(method, path, **kwargs):
        asked.append(kwargs["params"])
        return Stream()

    monkeypatch.setattr(api_routes, "_sandbox_call", sandbox_call)
    return asked


def _headers(token) -> dict:
    return auth_headers(token) if token else {"Content-Type": "application/json"}


def _shade(spec: dict) -> dict:
    return next(n for n in spec["dataflow"]["nodes"] if n["id"] == "shade")


def _change(token: str, example: str, code: str) -> str:
    """Shade's code in the copy of the visitor signed in as *token*, the copy
    made now, as an agent's change lands there (``visitor_copies.for_request``,
    ``dataflow_docs``); the copy's id."""
    from utk_curio.backend.app.collaboration import dataflow_docs
    from utk_curio.backend.app.projects import visitor_copies
    from utk_curio.backend.app.users.models import User

    guest = User.query.filter_by(username=config.CURIO_SHARED_GUEST_USERNAME).one()
    own = visitor_copies.for_request(guest, example, make=True, sign_in=token)
    assert own == _copy_of(token, example), "the visitor's copy was not made"
    with dataflow_docs.writing(GUEST_KEY, own, dataflow_docs.by_curio(GUEST_KEY, "agent")) as spec:
        _shade(spec)["content"] = code
    return own


def _payload(client, token, example) -> dict:
    """The dashboard's page as it is built for the visitor signed in as
    *token*, or for a visitor who sends no sign-in."""
    resp = client.get(f"/api/projects/{example}/dashboard", headers=_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return json.loads(resp.get_data(as_text=True))


def _load(client, token, example) -> dict:
    """The dataflow as a dashboard's page that fetches its data loads it:
    the owner's load, with no ``results=last`` (``ProjectLoader.tsx``)."""
    resp = client.get(f"/api/projects/{example}", headers=_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


def _start(client, token, example, values):
    return client.post(f"/api/projects/{example}/dashboard/runs", data=json.dumps({"values": values}),
                       headers=_headers(token))


def _ran(client, token, example, values) -> dict:
    """The visitor signed in as *token* starts the dashboard's run of
    *values*, which runs to its end; its start's answer."""
    resp = _start(client, token, example, values)
    assert resp.status_code == 202, resp.get_data(as_text=True)
    body = resp.get_json()
    _wait(body["runId"])
    return body


def _kept(project_id: str) -> str:
    """A digest of every output kept on *project_id*, field by field."""
    rows = KeptStepOutput.query.filter_by(project_id=project_id).order_by(KeptStepOutput.id).all()
    fields = [
        [r.node_id, r.step_key, r.session_id, r.output, r.output_path, r.artifact_ids,
         r.private_to, r.made_by, str(r.created_at), str(r.used_at)]
        for r in rows
    ]
    return hashlib.sha256(json.dumps(fields).encode("utf-8")).hexdigest()


def _example(example: str) -> dict:
    """The example's spec and manifest on disk, the guest account's dataset
    store, and the outputs kept on the example, each by a digest."""
    return {**_digests(example), "kept outputs": _kept(example)}


def _import(client, token: str) -> str:
    """The id of the file the visitor signed in as *token* imports, as the
    Data Catalog's Import does."""
    resp = client.post(
        "/api/datasets/import", headers={"Authorization": f"Bearer {token}"},
        data={"file": (io.BytesIO(b"tree,height\noak,12\n"), "trees.csv")}, content_type="multipart/form-data",
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def test_a_hosted_guests_dashboard_page_carries_their_own_copy(client, dashboard, embedded):
    example, saved = dashboard
    before = _example(example)
    _change(VISITOR_A, example, COPY_CODE)

    mine = _payload(client, VISITOR_A, example)
    theirs = _payload(client, VISITOR_B, example)
    anyones = _payload(client, None, example)

    # A's page carries A's copy: Shade as the copy holds it, and none of the
    # output the example's code made, so A's page runs Shade when it opens.
    assert _shade(mine["spec"])["content"] == COPY_CODE
    assert saved not in mine["outputs"]
    assert [ref["node_id"] for ref in mine.get("outputRefs") or []] == []
    # B, a guest with no copy, and a visitor who sends no sign-in get the
    # example as it ships, with its saved output.
    for page in (theirs, anyones):
        assert _shade(page["spec"])["content"] == SHIPPED_CODE
        assert saved in page["outputs"]
        assert [ref["node_id"] for ref in page["outputRefs"]] == ["shade"]
    # The page built for A never read it.
    assert embedded == [saved, saved]
    assert _example(example) == before


def test_a_hosted_guests_dashboard_that_fetches_its_data_loads_their_own_copy(client, dashboard):
    """A dashboard's page served without its data (its server could not build
    it in time, or the dev server) loads it as the owner's load does, which
    every hosted guest is, the shared account owning the examples."""
    example, saved = dashboard
    before = _example(example)
    _change(VISITOR_A, example, COPY_CODE)

    mine, theirs = _load(client, VISITOR_A, example), _load(client, VISITOR_B, example)

    assert _shade(mine["spec"])["content"] == COPY_CODE
    assert mine["outputs"] == []
    assert _shade(theirs["spec"])["content"] == SHIPPED_CODE
    assert {o["node_id"]: o["filename"] for o in theirs["outputs"]} == {"shade": saved}
    assert _example(example) == before


def test_a_hosted_guests_dashboard_runs_their_own_copy_and_keeps_on_it(client, dashboard, sandbox, relayed):
    example, _saved = dashboard
    before = _example(example)
    mine = _change(VISITOR_A, example, COPY_CODE)

    # A's page opens on A's copy, whose Shade the example's saved output was
    # not made by: Shade runs with the saved values, and again with A's change.
    _ran(client, VISITOR_A, example, {})
    _ran(client, VISITOR_A, example, {"shade": {"period": "Month"}})

    codes = [body["code"] for _node, body in sandbox.runs]
    assert len(codes) == 2, codes
    assert all(MINE in code for code in codes), codes
    assert '"Date"' in codes[0] and '"Month"' in codes[1], codes
    # What A's runs made is kept on A's copy, and nothing on the example.
    made = KeptStepOutput.query.filter_by(project_id=mine).order_by(KeptStepOutput.id).all()
    assert len(made) == 2
    assert KeptStepOutput.query.count() == 2
    assert _example(example) == before

    # B has no copy: the example's saved output answers B's page as it
    # opens, and B's change runs the example's code.
    opened = _start(client, VISITOR_B, example, {})
    assert opened.status_code == 200, opened.get_data(as_text=True)
    assert opened.get_json()["runId"] is None
    _ran(client, VISITOR_B, example, {"shade": {"period": "Month"}})
    _node, theirs = sandbox.runs[-1]
    assert len(sandbox.runs) == 3
    assert MINE not in theirs["code"] and '"Month"' in theirs["code"], theirs["code"]

    # A's output is read on A's dashboard alone, in the session that made it.
    read = f"/api/projects/{example}/dashboard/outputs/get"
    for token, status in ((VISITOR_A, 200), (VISITOR_B, 404), (None, 404)):
        resp = client.get(read, query_string={"fileName": made[-1].output_path}, headers=_headers(token))
        assert resp.status_code == status, (token, resp.get_data(as_text=True))
    assert relayed == [{"fileName": made[-1].output_path, "sessionId": made[-1].session_id}]


def test_another_guests_start_never_joins_a_hosted_guests_run(client, dashboard, sandbox):
    """A start of values a run already runs joins that run, and is handed its
    token: never one of another guest's copy, though the values are the same."""
    example, _saved = dashboard
    _change(VISITOR_A, example, COPY_CODE)
    sandbox.hold.add("shade")
    try:
        mine = _start(client, VISITOR_A, example, {"shade": {"period": "Month"}})
        assert mine.status_code == 202, mine.get_data(as_text=True)
        assert sandbox.started.wait(timeout=30)
        theirs = _start(client, VISITOR_B, example, {"shade": {"period": "Month"}})
    finally:
        sandbox.release()

    assert theirs.status_code == 202, theirs.get_data(as_text=True)
    assert theirs.get_json()["joined"] is False
    assert theirs.get_json()["token"] != mine.get_json()["token"]
    _wait(mine.get_json()["runId"])
    _wait(theirs.get_json()["runId"])
    codes = sorted(body["code"] for _node, body in sandbox.runs)
    assert len(codes) == 2 and sum(MINE in code for code in codes) == 1, codes


def test_a_hosted_guests_own_upload_reaches_their_dashboards_runs_alone(client, dashboard, sandbox):
    example, _saved = dashboard
    uploaded = _import(client, VISITOR_A)
    before = _example(example)
    reading = f'# node shade\nrows = curio_load_data("{uploaded}")\nreturn [!! period !!]'
    # B's copy names A's upload too, which B's runs must not read.
    _change(VISITOR_A, example, reading)
    _change(VISITOR_B, example, reading)

    _ran(client, VISITOR_A, example, {})
    _ran(client, VISITOR_B, example, {})

    (_node, mine), (_other, theirs) = sandbox.runs
    assert set(mine.get("dataset_paths") or {}) == {uploaded}, mine.get("dataset_paths")
    assert uploaded not in (theirs.get("dataset_paths") or {}), theirs.get("dataset_paths")
    assert _example(example) == before
