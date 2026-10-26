"""A dashboard viewer changes a pinned control and the dataflow runs again on
the server (komar41's #1117), which never changes the dataflow or its
owner's Data Catalog.

The dashboard here pins a Parameter node, Period, and a chart fed by a Python
node, Grid, whose code reads Period's value as ``[!! @period !!]``. The
sandbox is a fake behind ``sandbox_request``: it answers a node's run with an
artifact named after the node, and records what the backend asks it to
describe and forget. ``viewer`` is imported inside each test, so a checkout
without it fails each test on its own.
"""
from __future__ import annotations

import json
import threading
from datetime import timedelta

import pytest

CODE = "curio.builtin/computation-analysis"
PARAMETER = "curio.builtin/parameter"
CHART = "curio.builtin/vis-vega"
TOKEN_HEADER = "X-Curio-Run-Token"


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _period(**fields):
    return {
        "name": "period", "type": "choice", "label": "Period", "default": "Date",
        "options": {"choices": ["Date", "Month", "Year"], "display": "radio"}, **fields,
    }


def _day_node():
    """A pinned Parameter node holding a date, Day, saved at Dec 21."""
    return {"id": "day", "type": PARAMETER, "content": "", "dashboardPinned": True,
            "metadata": {"widgets": [{"name": "day", "type": "date", "label": "Day", "default": "2027-12-21"}]}}


def _nodes(*, grid_code="return [!! @period !!]", extra=()):
    return [
        {"id": "param", "type": PARAMETER, "content": "", "dashboardPinned": True,
         "metadata": {"widgets": [_period()]}},
        {"id": "grid", "type": CODE, "content": f"# node grid\n{grid_code}"},
        {"id": "chart", "type": CHART, "content": "{}", "dashboardPinned": True},
        *extra,
    ]


EDGES = [{"id": "grid-chart", "source": "grid", "target": "chart"}]


def _create(client, token, nodes=None, edges=EDGES, name="Shade dashboard"):
    resp = client.post("/api/projects", data=json.dumps({
        "name": name,
        "spec": {"dataflow": {"name": name, "nodes": list(nodes or _nodes()), "edges": list(edges)}},
        "outputs": [],
    }), headers=_auth(token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


class Reply:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code
        self.text = json.dumps(body)

    def json(self):
        return self._body


class FakeSandbox:
    """Runs a node as an artifact named after it; describes and forgets the
    sessions it is asked about, and stores a page's result as ``page-<n>``.
    *hold* keeps the named nodes running; *outputs* gives a node's output
    instead, ``(path, dataType)`` from a callable."""

    def __init__(self):
        self.lock = threading.Lock()
        self.runs = []
        self.made = {}
        self.forgotten = []
        self.stored = []
        self.hold = set()
        self.outputs = {}
        self.gate = threading.Event()
        self.started = threading.Event()

    def release(self):
        self.gate.set()

    def __call__(self, method, path, **kwargs):
        body = json.loads(kwargs.get("data") or "{}")
        if path == "/artifact-sessions/describe":
            with self.lock:
                return Reply({"sessions": {
                    sid: {"bytes": 100, "ids": [self.made[sid]] if sid in self.made else []}
                    for sid in body["sessionIds"]
                }})
        if path == "/artifact-sessions/forget":
            with self.lock:
                self.forgotten.extend(body["sessionIds"])
            return Reply({"forgotten": len(body["sessionIds"])})
        if path == "/artifact-sessions/store":
            with self.lock:
                self.stored.append(body)
                path_out = f"page-{len(self.stored)}"
                self.made[body["sessionId"]] = path_out
            return Reply({"output": {"path": path_out, "dataType": "dict"}})
        node_id = body["code"].split("# node ", 1)[1].split("\n", 1)[0]
        self.started.set()
        if node_id in self.hold:
            assert self.gate.wait(timeout=30), "the test never released the gate"
        with self.lock:
            self.runs.append((node_id, body))
            path_out, kind = (
                self.outputs[node_id]() if node_id in self.outputs else (f"art-{node_id}-{len(self.runs)}", "str")
            )
            self.made[body["session_id"]] = path_out
        return Reply({"stdout": [f"ran {node_id}"], "stderr": "",
                      "output": {"path": path_out, "dataType": kind}})


@pytest.fixture()
def proxy_hops():
    """The proxies in front of the backend: one, as the hosted stacks run
    (``--proxy-hops 1``). A test parametrized on it runs behind that many."""
    return 1


@pytest.fixture(autouse=True)
def _signed_in_instance(monkeypatch, proxy_hops):
    """An instance with sign-in (``--deploy``) behind *proxy_hops* proxies:
    the backend reads a visitor's address from the X-Forwarded-For they add."""
    from utk_curio.backend import config

    monkeypatch.setattr(config, "CURIO_NO_AUTH", False)
    monkeypatch.setattr(config, "CURIO_PROXY_HOPS", proxy_hops)


@pytest.fixture()
def app(_signed_in_instance, app):
    """test_runs' app, built once the instance above is set. pytest-flask's
    own autouse fixture asks for the app before this module's run, and
    ``create_app`` reads the proxies when it builds the app."""
    return app


@pytest.fixture()
def sandbox(monkeypatch):
    from utk_curio.backend import config
    from utk_curio.backend.app.runs import jobs, kept, viewer

    monkeypatch.setattr(config, "CURIO_DEFAULT_SAVE_NODE_OUTPUT", False)
    jobs.REGISTRY.reset()
    viewer.reset()
    fake = FakeSandbox()
    monkeypatch.setattr("utk_curio.backend.app.execution.node_exec.sandbox_request", fake)
    monkeypatch.setattr("utk_curio.backend.app.runs.viewer.sandbox_request", fake)
    monkeypatch.setattr("utk_curio.backend.app.runs.kept.sandbox_request", fake)
    yield fake
    fake.release()


@pytest.fixture()
def saved(monkeypatch):
    """The dashboard's saved outputs, as a load lists those it can read:
    Grid's, unless a test empties the list."""
    from utk_curio.backend.app.projects import storage
    from utk_curio.backend.app.projects.schemas import OutputRef
    from utk_curio.backend.app.runs import kept, viewer

    refs = [OutputRef(node_id="grid", filename="saved-grid", data_type="str")]
    monkeypatch.setattr(
        viewer, "_saved_state",
        lambda user_key, project_id: (storage.read_spec(user_key, project_id), list(refs)),
    )
    return refs


def _run(client, project_id, values=None, *, address="10.0.0.1"):
    return client.post(
        f"/api/projects/{project_id}/dashboard/runs",
        data=json.dumps({"values": values or {}}),
        headers={"Content-Type": "application/json", "X-Forwarded-For": address},
    )


def _wait(run_id):
    from utk_curio.backend.app.runs import kept, viewer
    from utk_curio.backend.extensions import db

    job = viewer.REGISTRY.get_job(run_id)
    assert job is not None
    job.thread.join(timeout=30)
    assert not job.thread.is_alive()
    db.session.rollback()
    return job


def _events(client, project_id, run_id, token):
    resp = client.get(f"/api/projects/{project_id}/dashboard/runs/{run_id}/stream", headers={TOKEN_HEADER: token})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    events = []
    for block in resp.get_data(as_text=True).strip().split("\n\n"):
        kind = block.split("\n", 1)[0].removeprefix("event: ")
        events.append((kind, json.loads(block.split("data: ", 1)[1])))
    return events


def _month(client, project_id):
    started = _run(client, project_id, {"param": {"period": "Month"}})
    assert started.status_code == 202, started.get_data(as_text=True)
    body = started.get_json()
    _wait(body["runId"])
    return body


class TestAViewerRunsTheDashboard:
    def test_a_changed_choice_runs_the_node_that_reads_it_with_the_new_value(self, client, user_and_token, sandbox, saved):
        _, token = user_and_token
        pid = _create(client, token)

        body = _month(client, pid)

        assert body["runId"] and body["token"] and body["joined"] is False
        assert [node for node, _ in sandbox.runs] == ["grid"]
        assert '"Month"' in sandbox.runs[0][1]["code"]
        finished = [p for k, p in _events(client, pid, body["runId"], body["token"]) if k == "step_finished"]
        assert [(p["nodeId"], p["status"]) for p in finished] == [("grid", "ok")]
        assert finished[0]["output"]["path"] == "art-grid-1"
        # Every artifact the output holds, which the page reads through the
        # dashboard's output routes; no reply and no printed text.
        assert finished[0]["artifactIds"] == ["art-grid-1"]
        assert "reply" not in finished[0] and "stdoutTail" not in finished[0]

    def test_a_changed_date_runs_the_node_that_reads_it_with_the_date_written_as_the_canvas_writes_it(
        self, client, user_and_token, sandbox, saved,
    ):
        _, token = user_and_token
        pid = _create(client, token, _nodes(grid_code="return [!! @day !!]", extra=[_day_node()]))

        started = _run(client, pid, {"day": {"day": "2027-06-21"}})

        assert started.status_code == 202, started.get_data(as_text=True)
        _wait(started.get_json()["runId"])
        assert [node for node, _ in sandbox.runs] == ["grid"]
        # A text literal, as the canvas writes a date (codeReferences.cases.json).
        code = sandbox.runs[0][1]["code"]
        assert 'return "2027-06-21"' in code, code
        assert "2027-12-21" not in code, code

    def test_the_same_values_again_come_from_the_kept_output_with_no_run(self, client, user_and_token, sandbox, saved):
        _, token = user_and_token
        pid = _create(client, token)

        first = _month(client, pid)
        second = _month(client, pid)

        assert len(sandbox.runs) == 1, "the second viewer's values ran again"
        outputs = [
            (p["output"]["path"], p["artifactIds"]) for k, p in _events(client, pid, second["runId"], second["token"])
            if k == "step_finished"
        ]
        assert outputs == [("art-grid-1", ["art-grid-1"])]
        assert first["runId"] != second["runId"]

    def test_the_saved_values_with_every_tile_saved_need_no_run(self, client, user_and_token, sandbox, saved):
        _, token = user_and_token
        pid = _create(client, token)

        for values in ({}, {"param": {"period": "Date"}}):
            resp = _run(client, pid, values)
            assert resp.status_code == 200, resp.get_data(as_text=True)
            assert resp.get_json() == {"runId": None, "token": None, "joined": False, "nodeIds": []}
        assert sandbox.runs == []

    def test_a_dashboard_whose_tiles_read_no_node_runs_nothing(self, client, user_and_token, sandbox, saved):
        _, token = user_and_token
        nodes = [node for node in _nodes() if node["id"] == "param"]
        pid = _create(client, token, nodes, edges=[])

        resp = _run(client, pid, {})

        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert resp.get_json() == {"runId": None, "token": None, "joined": False, "nodeIds": []}
        assert sandbox.runs == []

    def test_a_tile_with_no_saved_output_runs_the_nodes_before_it_on_open(self, client, user_and_token, sandbox, saved):
        _, token = user_and_token
        pid = _create(client, token)
        saved.clear()

        started = _run(client, pid, {})
        assert started.status_code == 202, started.get_data(as_text=True)
        _wait(started.get_json()["runId"])

        assert [node for node, _ in sandbox.runs] == ["grid"]
        assert '"Date"' in sandbox.runs[0][1]["code"]

    def test_what_a_visit_made_for_a_tile_with_no_saved_output_answers_the_next_visit(
        self, client, user_and_token, sandbox, saved,
    ):
        """With no saved output, the first visit runs the nodes and keeps what
        they made; the next visitor's page gets it with nothing run again."""
        _, token = user_and_token
        pid = _create(client, token)
        saved.clear()

        for _ in range(2):
            resp = _run(client, pid, {})
            assert resp.status_code == 202, resp.get_data(as_text=True)
            started = resp.get_json()
            assert started["nodeIds"] == ["grid"]
            _wait(started["runId"])

        assert [node for node, _ in sandbox.runs] == ["grid"]
        finished = [p for k, p in _events(client, pid, started["runId"], started["token"]) if k == "step_finished"]
        assert [(p["nodeId"], p["output"]["path"]) for p in finished] == [("grid", "art-grid-1")]

    def test_a_node_the_change_does_not_reach_keeps_its_saved_output(self, client, user_and_token, sandbox, saved):
        from utk_curio.backend.app.projects.schemas import OutputRef

        _, token = user_and_token
        nodes = _nodes(grid_code="return input_0 + [!! @period !!]", extra=[
            {"id": "load", "type": CODE, "content": "# node load\nreturn 'rows'"},
        ])
        pid = _create(client, token, nodes, EDGES + [{"id": "load-grid", "source": "load", "target": "grid"}])
        saved.append(OutputRef(node_id="load", filename="saved-load", data_type="str"))

        _month(client, pid)

        assert [node for node, _ in sandbox.runs] == ["grid"]
        assert sandbox.runs[0][1]["file_path"] == "saved-load"

    def test_a_node_that_reads_a_key_keeps_its_saved_output_when_the_change_does_not_reach_it(
        self, client, user_and_token, sandbox, saved,
    ):
        """A viewer's run uses no key, and needs none here: the owner's saved
        output answers for the node, and the nodes below run on it."""
        from utk_curio.backend.app.projects.schemas import OutputRef

        _, token = user_and_token
        nodes = _nodes(grid_code="return input_0 + [!! @period !!]", extra=[
            {"id": "load", "type": CODE, "content": "# node load\nkey = curio_secret('weather')\nreturn 'rows'"},
        ])
        pid = _create(client, token, nodes, EDGES + [{"id": "load-grid", "source": "load", "target": "grid"}])
        saved.append(OutputRef(node_id="load", filename="saved-load", data_type="str"))

        body = _month(client, pid)

        assert body["nodeIds"] == ["grid"]
        assert [node for node, _ in sandbox.runs] == ["grid"]
        assert sandbox.runs[0][1]["file_path"] == "saved-load"


def _own_widget_nodes(*, chart_content="{}", chart_widgets=()):
    """Grid, pinned, reading a Period widget of its own, feeds the pinned chart."""
    return [
        {"id": "grid", "type": CODE, "content": "# node grid\nreturn [!! period !!]", "dashboardPinned": True,
         "metadata": {"widgets": [_period()]}},
        {"id": "chart", "type": CHART, "content": chart_content, "dashboardPinned": True,
         "metadata": {"widgets": list(chart_widgets)}},
    ]


class TestAPinnedNodesOwnWidgets:
    """A pinned node's widgets are its tile's controls (#1117): a viewer's
    change to a pinned code node's own widget runs it with the new value, and
    the tile below it shows what it made."""

    def test_a_pinned_code_nodes_own_widget_reruns_it_for_the_tile_below(self, client, user_and_token, sandbox, saved):
        _, token = user_and_token
        pid = _create(client, token, _own_widget_nodes())

        started = _run(client, pid, {"grid": {"period": "Month"}})

        assert started.status_code == 202, started.get_data(as_text=True)
        body = started.get_json()
        assert body["nodeIds"] == ["grid"]
        _wait(body["runId"])
        assert [node for node, _ in sandbox.runs] == ["grid"]
        assert '"Month"' in sandbox.runs[0][1]["code"]
        finished = [p for k, p in _events(client, pid, body["runId"], body["token"]) if k == "step_finished"]
        assert [(p["nodeId"], p["status"]) for p in finished] == [("grid", "ok")]

    def test_its_saved_value_needs_no_run(self, client, user_and_token, sandbox, saved):
        _, token = user_and_token
        pid = _create(client, token, _own_widget_nodes())

        resp = _run(client, pid, {"grid": {"period": "Date"}})

        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert resp.get_json() == {"runId": None, "token": None, "joined": False, "nodeIds": []}
        assert sandbox.runs == []

    def test_a_pinned_charts_own_widget_runs_nothing_on_the_server(self, client, user_and_token, sandbox, saved):
        """The chart draws with its new value in the page; the server takes
        the value and runs no node for it."""
        _, token = user_and_token
        opacity = {"name": "opacity", "type": "slider", "label": "Opacity", "default": 1,
                   "options": {"min": 0.1, "max": 1, "step": 0.1}}
        pid = _create(client, token, _own_widget_nodes(
            chart_content='{"mark": {"type": "bar", "opacity": [!! opacity !!]}}', chart_widgets=[opacity],
        ))

        resp = _run(client, pid, {"grid": {"period": "Date"}, "chart": {"opacity": 0.5}})

        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert resp.get_json() == {"runId": None, "token": None, "joined": False, "nodeIds": []}
        assert sandbox.runs == []


class TestRefusedValues:
    @pytest.mark.parametrize("values, words", [
        ({"param": {"period": "Week"}}, "Pick one of the choices"),
        ({"param": {"nope": 1}}, "not a control"),
        ({"grid": {"period": "Month"}}, "not a control"),
        ({"note": {"note": "x"}}, "not a control"),
        ("Month", "must map"),
        # A date the month does not have, a date with a time, and a number.
        ({"day": {"day": "2027-02-30"}}, "Day: Enter a date."),
        ({"day": {"day": "2027-06-21T12:00:00"}}, "Day: Enter a date."),
        ({"day": {"day": 20270621}}, "Day: Enter a date."),
    ])
    def test_a_value_that_is_not_a_controls_or_does_not_suit_it_is_refused(
        self, client, user_and_token, sandbox, saved, values, words,
    ):
        _, token = user_and_token
        note = {"id": "note", "type": PARAMETER, "content": "", "dashboardPinned": True,
                "metadata": {"widgets": [{"name": "note", "type": "text", "default": ""}]}}
        pid = _create(client, token, _nodes(extra=[note, _day_node()]))

        resp = client.post(
            f"/api/projects/{pid}/dashboard/runs", data=json.dumps({"values": values}),
            headers={"Content-Type": "application/json"},
        )

        assert resp.status_code in (400, 422), resp.get_data(as_text=True)
        assert words in resp.get_json()["error"]
        assert sandbox.runs == []

    def test_text_text_lists_and_files_are_read_only_as_the_contract_says(self):
        from utk_curio.backend.app.runs import kept, viewer
        from utk_curio.common import shared_constants

        assert viewer.READ_ONLY_WIDGET_KINDS == {"text", "text-list", "file"}
        assert viewer.READ_ONLY_WIDGET_KINDS == set(shared_constants.read("dashboardRuns")["readOnlyWidgetKinds"])
        spec = {"dataflow": {"nodes": [
            {"id": "p", "dashboardPinned": True, "metadata": {"widgets": [
                {"name": kind.replace("-", "_"), "type": kind} for kind in ("text", "text-list", "file", "slider", "date")
            ]}},
            {"id": "q", "metadata": {"widgets": [{"name": "k", "type": "slider"}]}},
        ]}}
        assert set(viewer.dashboard_controls(spec)) == {("p", "slider"), ("p", "date")}

    def test_a_node_that_reads_a_key_stops_with_the_message(self, client, user_and_token, sandbox, saved):
        from utk_curio.backend.app.runs import kept, viewer

        _, token = user_and_token
        pid = _create(client, token, _nodes(grid_code='key = curio_secret("weather")\nreturn [!! @period !!]'))

        body = _month(client, pid)

        assert sandbox.runs == []
        finished = [p for k, p in _events(client, pid, body["runId"], body["token"]) if k == "step_finished"]
        assert finished[0]["status"] == "error"
        assert finished[0]["stderrTail"] == viewer.NO_KEYS_MESSAGE


class TestNothingIsSaved:
    def test_the_spec_manifest_catalog_runs_and_journal_are_untouched(self, client, db, user_and_token, sandbox, saved, monkeypatch):
        from utk_curio.backend.app.projects import storage
        from utk_curio.backend.app.projects.services import _user_dir_key
        from utk_curio.backend.app.runs.models import DataflowRun

        user, token = user_and_token
        pid = _create(client, token)
        ukey = _user_dir_key(user)
        spec_before = json.dumps(storage.read_spec(ukey, pid), sort_keys=True)
        manifest_before = json.dumps(storage.read_manifest(ukey, pid), sort_keys=True)
        revision_before = storage.spec_revision(ukey, pid)
        installs, journal = [], []
        monkeypatch.setattr(
            "utk_curio.backend.app.datasets.application.auto_install.auto_install_node_output",
            lambda **kw: installs.append(kw) or {"status": "skipped"},
        )
        monkeypatch.setattr(
            "utk_curio.backend.app.execution.runtime_journal.record_execution",
            lambda *a, **kw: journal.append(a),
        )

        _month(client, pid)

        assert json.dumps(storage.read_spec(ukey, pid), sort_keys=True) == spec_before
        assert json.dumps(storage.read_manifest(ukey, pid), sort_keys=True) == manifest_before
        assert storage.spec_revision(ukey, pid) == revision_before
        assert sandbox.runs[0][1]["save_dataset"] is False
        assert installs == [] and journal == []
        assert db.session.query(DataflowRun).count() == 0

    def test_the_dashboard_payload_never_carries_a_viewers_output(self, client, user_and_token, sandbox, saved):
        _, token = user_and_token
        pid = _create(client, token)

        _month(client, pid)
        payload = client.get(f"/api/projects/{pid}/dashboard")

        assert "art-grid-1" not in payload.get_data(as_text=True)


def _tried(client, project_id, period, address):
    """A visitor's try of *period*, run to its end; its start's status."""
    resp = _run(client, project_id, {"param": {"period": period}}, address=address)
    if resp.status_code == 202:
        _wait(resp.get_json()["runId"])
    return resp.status_code


class TestLimits:
    def test_the_limiter_counts_each_forwarded_addresses_tries_on_its_own(self, client, user_and_token, sandbox, saved, monkeypatch):
        from utk_curio.backend.app.common.address_limiter import AddressLimiter
        from utk_curio.backend.app.runs import kept, viewer

        _, token = user_and_token
        pid = _create(client, token)
        monkeypatch.setattr(viewer, "_LIMITER", AddressLimiter(2, 100))

        statuses = [_tried(client, pid, period, "10.0.0.1") for period in ("Month", "Year", "Month")]
        other = _tried(client, pid, "Year", "10.0.0.2")

        assert statuses == [202, 202, 429]
        assert other == 202

    def test_opening_the_page_costs_the_address_nothing(self, client, user_and_token, sandbox, saved, monkeypatch):
        """A tile with no saved output runs with the saved values at each
        visit, the first making it and the rest getting it kept: only the
        values a visitor tries count against its address's budget."""
        from utk_curio.backend.app.common.address_limiter import AddressLimiter
        from utk_curio.backend.app.runs import kept, viewer

        _, token = user_and_token
        pid = _create(client, token)
        # No saved output, so each open starts a run.
        saved.clear()
        monkeypatch.setattr(viewer, "_LIMITER", AddressLimiter(1, 100))

        opens = [_tried(client, pid, "Date", "10.0.0.1") for _ in range(4)]
        tries = [_tried(client, pid, period, "10.0.0.1") for period in ("Month", "Year")]

        assert opens == [202, 202, 202, 202]
        assert tries == [202, 429]

    @pytest.mark.parametrize("proxy_hops", [0])
    def test_with_no_proxy_named_a_forwarded_address_is_not_believed(self, client, user_and_token, sandbox, saved, monkeypatch):
        """Without ``--proxy-hops`` anyone reaching the backend could write
        X-Forwarded-For, so a new address there is no new budget."""
        from utk_curio.backend.app.common.address_limiter import AddressLimiter
        from utk_curio.backend.app.runs import kept, viewer

        _, token = user_and_token
        pid = _create(client, token)
        monkeypatch.setattr(viewer, "_LIMITER", AddressLimiter(2, 100))

        statuses = [
            _tried(client, pid, period, f"10.0.0.{n}") for n, period in enumerate(("Month", "Year", "Month"), start=1)
        ]

        assert statuses == [202, 202, 429]

    def test_a_dashboard_runs_at_most_two_at_once(self, client, user_and_token, sandbox, saved):
        _, token = user_and_token
        pid = _create(client, token)
        saved.clear()
        sandbox.hold = {"grid"}

        first = _run(client, pid, {"param": {"period": "Date"}})
        second = _run(client, pid, {"param": {"period": "Month"}})
        third = _run(client, pid, {"param": {"period": "Year"}})

        assert (first.status_code, second.status_code) == (202, 202)
        assert third.status_code == 429, third.get_data(as_text=True)
        sandbox.release()
        _wait(first.get_json()["runId"])
        _wait(second.get_json()["runId"])

    def test_a_request_for_values_already_running_joins_that_run(self, client, user_and_token, sandbox, saved):
        _, token = user_and_token
        pid = _create(client, token)
        sandbox.hold = {"grid"}

        first = _run(client, pid, {"param": {"period": "Month"}}).get_json()
        assert sandbox.started.wait(timeout=10)
        second = _run(client, pid, {"param": {"period": "Month"}}).get_json()

        assert second["runId"] == first["runId"] and second["joined"] is True
        assert second["token"] == first["token"]
        sandbox.release()
        _wait(first["runId"])
        assert len(sandbox.runs) == 1

    def test_the_owners_own_runs_still_start_while_viewers_run(self, client, user_and_token, sandbox, saved):
        from utk_curio.backend.app.runs import jobs

        _, token = user_and_token
        pid = _create(client, token)
        sandbox.hold = {"grid"}
        viewer_run = _run(client, pid, {"param": {"period": "Month"}}).get_json()
        assert sandbox.started.wait(timeout=10)

        owner_run = client.post(f"/api/projects/{pid}/runs", data=json.dumps({}), headers=_auth(token))

        assert owner_run.status_code == 202, owner_run.get_data(as_text=True)
        sandbox.release()
        _wait(viewer_run["runId"])
        job = jobs.REGISTRY.get_job(owner_run.get_json()["id"])
        job.thread.join(timeout=30)

    def test_viewers_take_at_most_half_the_isolated_pool(self, monkeypatch):
        from utk_curio.common.exec_pool import exec_parallelism

        assert exec_parallelism({"CURIO_EXEC_PARALLELISM": "8"}) == 8
        assert exec_parallelism({"CURIO_EXEC_PARALLELISM": "nonsense"}) >= 2
        from utk_curio.backend.app.runs import kept, viewer

        assert 1 <= viewer.STEP_SLOTS <= max(1, exec_parallelism() // 2)


class TestFollowingAndReading:
    def test_a_run_is_followed_with_its_token_only(self, client, user_and_token, sandbox, saved):
        _, token = user_and_token
        pid = _create(client, token)
        body = _month(client, pid)
        stream = f"/api/projects/{pid}/dashboard/runs/{body['runId']}/stream"

        assert client.get(stream).status_code == 403
        assert client.get(stream, headers={TOKEN_HEADER: "not-it"}).status_code == 403
        other = _create(client, token, name="Another dashboard")
        assert client.get(
            f"/api/projects/{other}/dashboard/runs/{body['runId']}/stream", headers={TOKEN_HEADER: body["token"]},
        ).status_code == 404
        assert client.get(stream, headers={TOKEN_HEADER: body["token"]}).status_code == 200

    def test_an_output_is_read_in_its_own_session_and_only_on_its_dashboard(self, client, user_and_token, sandbox, saved, monkeypatch):
        from utk_curio.backend.app.api import routes as api_routes
        from utk_curio.backend.app.runs.models import KeptStepOutput

        _, token = user_and_token
        pid = _create(client, token)
        _month(client, pid)
        entry = KeptStepOutput.query.filter_by(project_id=pid).one()
        asked = []

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
        read = client.get(f"/api/projects/{pid}/dashboard/outputs/get?fileName={entry.output_path}")
        other = _create(client, token, name="Another dashboard")
        elsewhere = client.get(f"/api/projects/{other}/dashboard/outputs/get?fileName={entry.output_path}")
        unknown = client.get(f"/api/projects/{pid}/dashboard/outputs/get?fileName=someone-elses-artifact")

        assert read.status_code == 200 and read.get_json()["data"] == "Month"
        assert asked == [{"fileName": entry.output_path, "sessionId": entry.session_id}]
        assert entry.session_id.startswith("kept-") and entry.session_id != token
        assert (elsewhere.status_code, unknown.status_code) == (404, 404)

    def test_the_run_token_may_be_sent_cross_origin(self, client, user_and_token):
        from utk_curio.backend.app import CORS_HEADERS

        _, token = user_and_token
        pid = _create(client, token)
        allowed = {name.strip().lower() for name in CORS_HEADERS["Access-Control-Allow-Headers"].split(",")}
        preflight = client.options(f"/api/projects/{pid}/dashboard/runs/x/stream", headers={
            "Origin": "http://localhost:8080", "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": TOKEN_HEADER.lower(),
        })

        assert TOKEN_HEADER.lower() in allowed
        assert preflight.status_code == 204
        assert TOKEN_HEADER.lower() in preflight.headers["Access-Control-Allow-Headers"].lower()


class TestKeys:
    def test_a_new_curio_version_or_package_or_dataset_changes_the_key(self, tmp_path, monkeypatch):
        import utk_curio
        from utk_curio.backend.app.runs import kept, viewer

        dataset = tmp_path / "trees.csv"
        dataset.write_text("a\n1\n")

        def key(**changes):
            fields = dict(packages="p1", node_type=CODE, engine="python", code="return 1", input_ref=None,
                          input_slots=None, datasets={"trees": kept._file_identity(str(dataset))})
            fields.update(changes)
            return kept.step_key(**fields)

        base = key()
        assert key() == base
        assert key(packages="p2") != base
        assert key(code="return 2") != base
        assert key(input_ref={"path": "saved-load-2", "dataType": "str"}) != base
        dataset.write_text("a\n1\n2\n")
        reimported = key()
        assert reimported != base, "re-importing a dataset under the same id kept the old key"
        monkeypatch.setattr(utk_curio, "__version__", "99.0.0")
        assert key() != reimported, "a new Curio version kept the old key"

    def test_a_step_keys_the_same_whichever_spelling_its_type_came_in(self):
        """The canvas posts a node's type with its version
        (``curio.builtin/computation-analysis@1``), and a saved dataflow may
        hold it without one, as the shipped examples do, or by its old name:
        an owner's play keys its step as a viewer's run of the step does."""
        from utk_curio.backend.app.runs import kept

        def key(node_type):
            return kept.step_key(packages="p1", node_type=node_type, engine="python", code="return 1",
                                 input_ref=None, input_slots=None, datasets={})

        assert key("curio.builtin/computation-analysis@1") == key("curio.builtin/computation-analysis")
        assert key("COMPUTATION_ANALYSIS") == key("curio.builtin/computation-analysis")
        assert key("curio.builtin/data-loading") != key("curio.builtin/computation-analysis")

    def test_an_owners_upgrade_runs_the_step_again(self, client, user_and_token, sandbox, saved, monkeypatch):
        import utk_curio

        _, token = user_and_token
        pid = _create(client, token)
        _month(client, pid)
        monkeypatch.setattr(utk_curio, "__version__", "99.0.0")

        _month(client, pid)

        assert len(sandbox.runs) == 2


class TestKeptOutputsGo:
    def _entry(self, pid, *, days=0, hours=0, size=100, private=False, used_days=None, made_by="viewer"):
        from utk_curio.backend.app.runs.models import KeptStepOutput, naive_utc_now
        from utk_curio.backend.extensions import db
        from utk_curio.common.kept_sessions import new_session_id

        now = naive_utc_now()
        entry = KeptStepOutput(
            project_id=pid, node_id="grid", step_key="k" * 64, session_id=new_session_id(),
            output=json.dumps({"path": "p", "dataType": "str"}), output_path="p",
            artifact_ids='["p"]', size_bytes=size, private_to="t" * 64 if private else None, made_by=made_by,
            created_at=now - timedelta(days=days, hours=hours),
            used_at=now - timedelta(days=used_days if used_days is not None else days, hours=hours),
        )
        db.session.add(entry)
        db.session.commit()
        return entry.id, entry.session_id

    def test_an_output_goes_seven_days_after_it_was_made_and_a_tabs_own_after_an_hour(self, client, user_and_token, sandbox):
        from utk_curio.backend.app.runs import kept, viewer
        from utk_curio.backend.app.runs.models import KeptStepOutput

        _, token = user_and_token
        pid = _create(client, token)
        assert kept.KEPT_DAYS == 7
        fresh = self._entry(pid, days=6)
        old = self._entry(pid, days=8)
        # Counted from when it was made: a visit since does not keep it longer.
        old_used_today = self._entry(pid, days=8, used_days=0)
        tab_fresh = self._entry(pid, private=True)
        tab_old = self._entry(pid, private=True, hours=2)

        assert kept.prune() == 3

        left = {row.id for row in KeptStepOutput.query.all()}
        assert left == {fresh[0], tab_fresh[0]}
        assert sorted(sandbox.forgotten) == sorted([old[1], old_used_today[1], tab_old[1]])

    def test_a_visit_within_seven_days_gets_what_was_kept_and_one_after_them_runs_and_keeps_it_anew(
        self, client, user_and_token, sandbox, saved, monkeypatch,
    ):
        """What a run kept answers the same values until 7 days after it was
        made, and no longer, whether or not a sweep has run: at day 6 nothing
        runs and the kept output comes back; at day 8 the same values run
        again, and what that run makes is kept in its place."""
        from utk_curio.backend.app.runs import kept, viewer
        from utk_curio.backend.app.runs.models import KeptStepOutput

        _, token = user_and_token
        pid = _create(client, token)
        _month(client, pid)
        made = KeptStepOutput.query.filter_by(project_id=pid).one()
        made_at, made_session = made.created_at, made.session_id

        def visit(days: int) -> list:
            """The same values *days* days after the output was made: what each step answered."""
            monkeypatch.setattr(kept, "naive_utc_now", lambda: made_at + timedelta(days=days))
            body = _month(client, pid)
            return [
                (payload["nodeId"], payload["output"]["path"])
                for kind, payload in _events(client, pid, body["runId"], body["token"]) if kind == "step_finished"
            ]

        assert visit(6) == [("grid", "art-grid-1")]
        assert len(sandbox.runs) == 1, "a visit within the 7 days ran the step again"
        assert sandbox.forgotten == []

        assert visit(8) == [("grid", "art-grid-2")]
        assert len(sandbox.runs) == 2, "a visit past the 7 days did not run the step again"
        left = [row.output_path for row in KeptStepOutput.query.filter_by(project_id=pid).all()]
        assert left == ["art-grid-2"], f"what is kept now: {left!r}"
        assert sandbox.forgotten == [made_session]

    def test_what_a_first_visit_ran_for_a_tile_with_no_saved_output_serves_visits_for_seven_days(
        self, client, user_and_token, sandbox, saved, monkeypatch,
    ):
        """A tile with no saved output: the first visit runs its nodes and keeps
        what they made. A visit 6 days later gets that with nothing run; one 8
        days later runs them again and keeps the new output in its place
        (owner, 10-25)."""
        from utk_curio.backend.app.runs import kept
        from utk_curio.backend.app.runs.models import KeptStepOutput

        _, token = user_and_token
        pid = _create(client, token)
        saved.clear()

        def visit() -> list:
            """A visit with the saved values: what each step answered."""
            resp = _run(client, pid, {})
            assert resp.status_code == 202, resp.get_data(as_text=True)
            body = resp.get_json()
            _wait(body["runId"])
            return [
                (payload["nodeId"], payload["output"]["path"])
                for kind, payload in _events(client, pid, body["runId"], body["token"]) if kind == "step_finished"
            ]

        assert visit() == [("grid", "art-grid-1")]
        made = KeptStepOutput.query.filter_by(project_id=pid).one()
        made_at, made_session = made.created_at, made.session_id

        monkeypatch.setattr(kept, "naive_utc_now", lambda: made_at + timedelta(days=6))
        assert visit() == [("grid", "art-grid-1")]
        assert len(sandbox.runs) == 1, "a visit within the 7 days ran the step again"

        monkeypatch.setattr(kept, "naive_utc_now", lambda: made_at + timedelta(days=8))
        assert visit() == [("grid", "art-grid-2")]
        assert len(sandbox.runs) == 2, "a visit past the 7 days did not run the step again"
        left = [row.output_path for row in KeptStepOutput.query.filter_by(project_id=pid).all()]
        assert left == ["art-grid-2"], f"what is kept now: {left!r}"
        assert sandbox.forgotten == [made_session]

    def test_a_tabs_own_output_serves_its_tab_for_an_hour_whether_or_not_a_sweep_ran(
        self, client, user_and_token, sandbox,
    ):
        from utk_curio.backend.app.runs import kept, viewer

        _, token = user_and_token
        pid = _create(client, token)
        stale = self._entry(pid, private=True, hours=2)

        # Two hours old and not swept yet: its tab no longer gets it.
        assert kept.kept_output(pid, "k" * 64, "t" * 64) is None
        self._entry(pid, private=True)
        assert kept.kept_output(pid, "k" * 64, "t" * 64) is not None
        # The sweep takes the stale one only.
        assert kept.prune() == 1
        assert sandbox.forgotten == [stale[1]]

    def test_the_sweep_runs_a_minute_after_start_then_every_six_hours_and_never_under_testing(self, app, monkeypatch):
        """With no visit at all, what is past its time still goes on time."""
        from utk_curio.backend import config
        from utk_curio.backend.app.runs import kept, viewer

        monkeypatch.setattr(kept, "_prune_timer", None)
        kept.start_prune_scheduler(app)
        assert kept._prune_timer is None, "a sweep was scheduled under --testing"

        swept = []
        monkeypatch.setattr(kept, "prune", lambda now=None: swept.append(now) or 0)
        monkeypatch.setattr(config, "_is_testing", lambda: False)
        kept.start_prune_scheduler(app)
        first = kept._prune_timer
        try:
            assert first is not None and first.daemon and first.interval == 60
            first.cancel()
            first.function()
            assert swept == [None]
            assert kept._prune_timer.interval == kept.PRUNE_INTERVAL_HOURS * 3600 == 6 * 3600
        finally:
            kept._prune_timer.cancel()

    def test_a_dashboard_past_its_size_drops_the_least_recently_used(self, client, user_and_token, sandbox, monkeypatch):
        from utk_curio.backend.app.runs import kept, viewer
        from utk_curio.backend.app.runs.models import KeptStepOutput

        _, token = user_and_token
        pid = _create(client, token)
        monkeypatch.setattr(kept, "MAX_KEPT_BYTES", 250)
        stale = self._entry(pid, size=100, used_days=3)
        recent = self._entry(pid, size=100, used_days=1)
        newest = self._entry(pid, size=100, used_days=0)

        kept.prune()

        assert {row.id for row in KeptStepOutput.query.all()} == {recent[0], newest[0]}
        assert sandbox.forgotten == [stale[1]]

    def test_the_viewers_budget_never_evicts_the_owners_outputs(
        self, client, user_and_token, sandbox, monkeypatch,
    ):
        """Visitors trying values never evict what the owner's runs kept: the
        viewers' outputs past their budget drop their least recently used, and
        the owner's, though older still, stay (``test_owner_runs_kept`` pins
        that no budget evicts them at all)."""
        from utk_curio.backend.app.runs import kept
        from utk_curio.backend.app.runs.models import KeptStepOutput

        _, token = user_and_token
        pid = _create(client, token)
        monkeypatch.setattr(kept, "MAX_KEPT_BYTES", 250)
        owners = [self._entry(pid, size=100, used_days=5, made_by=kept.MADE_BY_OWNER) for _ in range(2)]
        stale = self._entry(pid, size=100, used_days=3)
        recent = self._entry(pid, size=100, used_days=1)
        newest = self._entry(pid, size=100, used_days=0)

        assert kept.prune() == 1

        left = {row.id for row in KeptStepOutput.query.all()}
        assert left == {owners[0][0], owners[1][0], recent[0], newest[0]}
        assert sandbox.forgotten == [stale[1]]

    def test_deleting_the_dataflow_forgets_its_outputs(self, client, user_and_token, sandbox):
        from utk_curio.backend.app.runs.models import KeptStepOutput

        _, token = user_and_token
        pid = _create(client, token)
        _, session = self._entry(pid)

        resp = client.delete(f"/api/projects/{pid}", headers=_auth(token))

        assert resp.status_code in (200, 204), resp.get_data(as_text=True)
        assert KeptStepOutput.query.filter_by(project_id=pid).count() == 0
        assert sandbox.forgotten == [session]


#: An Autark node that computes over its input: a step only a browser runs.
AUTARK = "curio.builtin/autk-grammar"
COMPUTE = json.dumps({"compute": [{
    "dataRef": "input_0", "attributes": {"v": "properties.count"},
    "outputColumnName": "doubled", "wglsFunction": ["return v * 2.0;"],
}]})
#: What a page sends of that node: one layer, as Autark hands it on.
LAYER = {"dataType": "geodataframe", "data": {"type": "FeatureCollection", "features": []}, "layerName": "grid"}


def _gpu_nodes():
    """Grid, then the GPU step the page runs, then After, which the chart reads."""
    return [
        {"id": "param", "type": PARAMETER, "content": "", "dashboardPinned": True,
         "metadata": {"widgets": [_period()]}},
        {"id": "grid", "type": CODE, "content": "# node grid\nreturn [!! @period !!]"},
        {"id": "gpu", "type": AUTARK, "content": COMPUTE},
        {"id": "after", "type": CODE, "content": "# node after\nreturn input_0"},
        {"id": "chart", "type": CHART, "content": "{}", "dashboardPinned": True},
    ]


GPU_EDGES = [
    {"id": "grid-gpu", "source": "grid", "target": "gpu"},
    {"id": "gpu-after", "source": "gpu", "target": "after"},
    {"id": "after-chart", "source": "after", "target": "chart"},
]


def _keep_step(client, project_id, run_id, token, node_id="gpu", value=None):
    return client.post(
        f"/api/projects/{project_id}/dashboard/runs/{run_id}/steps/{node_id}",
        data=json.dumps({"value": LAYER if value is None else value}),
        headers={"Content-Type": "application/json", TOKEN_HEADER: token},
    )


def _on_the_page(client, project_id, browser_outputs, token, values=None):
    headers = {"Content-Type": "application/json", "X-Forwarded-For": "10.0.0.1"}
    if token:
        headers[TOKEN_HEADER] = token
    return client.post(
        f"/api/projects/{project_id}/dashboard/runs",
        data=json.dumps({"values": values or {"param": {"period": "Month"}}, "browserOutputs": browser_outputs}),
        headers=headers,
    )


class TestTheStepsLeftToThePage:
    """A step only a browser runs is the page's: the run ends asking for it,
    the page sends what it made, and its next start runs the steps below on
    that, all of it kept for that page alone."""

    @pytest.fixture()
    def gpu(self, client, user_and_token, sandbox, saved):
        from utk_curio.backend.app.projects.schemas import OutputRef

        _, token = user_and_token
        saved[:] = [OutputRef(node_id="after", filename="saved-after", data_type="str")]
        return _create(client, token, nodes=_gpu_nodes(), edges=GPU_EDGES)

    def test_the_run_ends_asking_the_page_for_its_step(self, client, gpu, sandbox):
        from utk_curio.backend.app.runs import kept, viewer

        started = _month(client, gpu)
        events = _events(client, gpu, started["runId"], started["token"])

        steps = {payload["nodeId"]: payload["status"] for kind, payload in events if kind == "step_finished"}
        assert steps == {"grid": "ok", "gpu": "browser", "after": "waiting"}
        assert events[-1][0] == "run_finished" and events[-1][1]["status"] == "needs_canvas"
        assert [node for node, _body in sandbox.runs] == ["grid"]
        assert viewer._RUNS[started["runId"]]["browserSteps"] == ["gpu"]

    def test_what_the_page_sends_is_kept_for_it_alone(self, client, gpu, sandbox):
        from utk_curio.backend.app.runs import kept, viewer
        from utk_curio.backend.app.runs.models import KeptStepOutput

        started = _month(client, gpu)
        sent = _keep_step(client, gpu, started["runId"], started["token"])

        assert sent.status_code == 200, sent.get_data(as_text=True)
        output = sent.get_json()["output"]
        assert output == {"path": "page-1", "dataType": "dict"}
        # Written to the sandbox as it came, in a dashboard session of its own.
        assert sandbox.stored[0]["value"] == LAYER
        entry = KeptStepOutput.query.filter_by(project_id=gpu, output_path="page-1").one()
        assert entry.node_id == "gpu"
        assert entry.private_to == kept.digest(started["token"])
        # Read with no token, as another page would, it is not found.
        assert client.get(f"/api/projects/{gpu}/dashboard/outputs/get?fileName=page-1").status_code == 404

    def test_a_page_sends_only_what_its_run_left_to_it(self, client, gpu, sandbox, monkeypatch):
        from utk_curio.backend.app.runs import kept, viewer

        started = _month(client, gpu)
        run_id, token = started["runId"], started["token"]

        assert _keep_step(client, gpu, run_id, "another-token").status_code == 403
        assert _keep_step(client, gpu, run_id, token, node_id="grid").status_code == 409
        for wrong in ({"dataType": "str", "data": "x"}, {"dataType": "geodataframe"}, ["not", "an", "object"]):
            assert _keep_step(client, gpu, run_id, token, value=wrong).status_code == 422, wrong
        monkeypatch.setattr(viewer, "MAX_TAB_RESULT_BYTES", 10)
        assert _keep_step(client, gpu, run_id, token).status_code == 413
        assert sandbox.stored == []

    def test_a_page_hands_on_its_layers_and_never_names_an_output(self, client, gpu, sandbox):
        """The steps below read the page's result in a kept session, which
        reads what any kept run made, and the sandbox reads each output a
        result of several names (``worker._expand_outputs_wrapper``)."""
        started = _month(client, gpu)
        run_id, token = started["runId"], started["token"]
        layers = {"dataType": "outputs", "data": [LAYER, {**LAYER, "layerName": "roads"}]}

        assert _keep_step(client, gpu, run_id, token, value=layers).status_code == 200
        for named in (
            {"dataType": "outputs", "data": [LAYER, {"path": "1700000000000_deadbeef", "dataType": "dataframe"}]},
            {"dataType": "outputs", "data": ["1700000000000_deadbeef"]},
        ):
            assert _keep_step(client, gpu, run_id, token, value=named).status_code == 422, named
        assert [stored["value"] for stored in sandbox.stored] == [layers]

    def test_the_next_start_runs_the_steps_below_on_what_the_page_sent(self, client, gpu, sandbox):
        from utk_curio.backend.app.runs import kept, viewer
        from utk_curio.backend.app.runs.models import KeptStepOutput

        first = _month(client, gpu)
        page = _keep_step(client, gpu, first["runId"], first["token"]).get_json()["output"]["path"]

        resp = _on_the_page(client, gpu, {"gpu": page}, first["token"])
        assert resp.status_code == 202, resp.get_data(as_text=True)
        second = resp.get_json()
        _wait(second["runId"])

        assert second["token"] == first["token"]
        events = _events(client, gpu, second["runId"], second["token"])
        steps = {payload["nodeId"]: payload["status"] for kind, payload in events if kind == "step_finished"}
        # The page's result stands in for the GPU step, which no longer runs.
        assert steps["after"] == "ok" and "gpu" not in steps
        assert steps.get("grid", "ok") == "ok"
        assert events[-1][1]["status"] == "succeeded"
        # Grid ran in the first run only; After ran on the page's result.
        assert [node for node, _body in sandbox.runs] == ["grid", "after"]
        assert page in json.dumps(sandbox.runs[1][1])
        after = KeptStepOutput.query.filter_by(project_id=gpu, node_id="after").one()
        assert after.private_to == kept.digest(first["token"])

    def test_another_page_runs_its_own_step_and_cannot_name_the_first_ones(self, client, gpu, sandbox):
        first = _month(client, gpu)
        page = _keep_step(client, gpu, first["runId"], first["token"]).get_json()["output"]["path"]
        second = _month(client, gpu)

        # The shared step came back kept; the browser's step is the new page's to run.
        assert second["token"] != first["token"]
        events = _events(client, gpu, second["runId"], second["token"])
        steps = {payload["nodeId"]: payload["status"] for kind, payload in events if kind == "step_finished"}
        assert steps == {"grid": "ok", "gpu": "browser", "after": "waiting"}
        assert [node for node, _body in sandbox.runs] == ["grid"]
        assert _on_the_page(client, gpu, {"gpu": page}, second["token"]).status_code == 404
        assert _on_the_page(client, gpu, {"gpu": page}, None).status_code == 403

    def test_the_start_that_goes_on_from_the_page_costs_nothing_once(self, client, gpu, sandbox, monkeypatch):
        """The run that left the step to the page was counted; the start the
        page makes with its result is not, but a page that sends results again
        pays for each start that follows."""
        from utk_curio.backend.app.common.address_limiter import AddressLimiter
        from utk_curio.backend.app.runs import kept, viewer

        monkeypatch.setattr(viewer, "_LIMITER", AddressLimiter(1, 100))
        first = _month(client, gpu)
        run_id, token = first["runId"], first["token"]

        page = _keep_step(client, gpu, run_id, token).get_json()["output"]["path"]
        goes_on = _on_the_page(client, gpu, {"gpu": page}, token)
        assert goes_on.status_code == 202, goes_on.get_data(as_text=True)
        _wait(goes_on.get_json()["runId"])

        again = _keep_step(client, gpu, run_id, token, value={**LAYER, "layerName": "again"})
        assert again.status_code == 200, again.get_data(as_text=True)
        resp = _on_the_page(client, gpu, {"gpu": again.get_json()["output"]["path"]}, token)
        assert resp.status_code == 429, resp.get_data(as_text=True)


class TestAWrapperAStepReads:
    """A viewer's step runs in a kept session of its own, which reads what any
    kept run made, and the sandbox reads each output a wrapper among its
    inputs names (``worker._expand_outputs_wrapper``). Node code can write a
    wrapper naming any output, so a step reads one only when what it names is
    its dataflow's."""

    def _below_a_wrapper(self, client, token, sandbox, name_of):
        """A dashboard whose Grid answers a wrapper naming what *name_of*
        gives for the dataflow, and whose After reads Grid."""
        from utk_curio.common.kept_sessions import new_session_id
        from utk_curio.sandbox.util.parsers import save_to_duckdb

        after = {"id": "after", "type": CODE, "content": "# node after\nreturn input_0"}
        pid = _create(client, token, nodes=_nodes(extra=[after]), edges=[
            {"id": "grid-after", "source": "grid", "target": "after"},
            {"id": "after-chart", "source": "after", "target": "chart"},
        ])
        wrapper = save_to_duckdb(
            {"dataType": "outputs", "data": [{"path": name_of(pid), "dataType": "dataframe"}]},
            node_id="grid", session_id=new_session_id(),
        )
        sandbox.outputs["grid"] = lambda: (wrapper, "dict")
        return pid

    @staticmethod
    def _table(session):
        import pandas as pd

        from utk_curio.sandbox.util.parsers import save_to_duckdb

        return save_to_duckdb(pd.DataFrame({"n": [1]}), node_id="n", session_id=session)

    def test_a_step_does_not_read_what_another_dataflow_kept(self, client, user_and_token, sandbox, saved):
        from utk_curio.common.kept_sessions import new_session_id

        _, token = user_and_token
        theirs = self._table(new_session_id())
        pid = self._below_a_wrapper(client, token, sandbox, lambda _pid: theirs)

        _month(client, pid)

        assert [node for node, _ in sandbox.runs] == ["grid"]

    def test_a_step_reads_what_its_dataflow_kept(self, client, user_and_token, sandbox, saved):
        from utk_curio.backend.app.runs import kept
        from utk_curio.backend.app.runs.models import KeptStepOutput, naive_utc_now
        from utk_curio.backend.extensions import db
        from utk_curio.common.kept_sessions import new_session_id

        _, token = user_and_token

        def kept_for(pid):
            session = new_session_id()
            mine = self._table(session)
            now = naive_utc_now()
            db.session.add(KeptStepOutput(
                project_id=pid, node_id="earlier", step_key="e" * 64, session_id=session,
                output=json.dumps({"path": mine, "dataType": "dataframe"}), output_path=mine,
                artifact_ids=json.dumps([mine]), made_by=kept.MADE_BY_OWNER, created_at=now, used_at=now,
            ))
            db.session.commit()
            return mine

        pid = self._below_a_wrapper(client, token, sandbox, kept_for)

        _month(client, pid)

        assert [node for node, _ in sandbox.runs] == ["grid", "after"]
