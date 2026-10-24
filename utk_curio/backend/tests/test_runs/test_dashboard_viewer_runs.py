"""A dashboard viewer changes a pinned control and the dataflow runs again on
the server (komar41's #1117), with nothing saved to the dataflow or its
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
    sessions it is asked about. *hold* keeps the named nodes running."""

    def __init__(self):
        self.lock = threading.Lock()
        self.runs = []
        self.made = {}
        self.forgotten = []
        self.hold = set()
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
        node_id = body["code"].split("# node ", 1)[1].split("\n", 1)[0]
        self.started.set()
        if node_id in self.hold:
            assert self.gate.wait(timeout=30), "the test never released the gate"
        with self.lock:
            self.runs.append((node_id, body))
            path_out = f"art-{node_id}-{len(self.runs)}"
            self.made[body["session_id"]] = path_out
        return Reply({"stdout": [f"ran {node_id}"], "stderr": "",
                      "output": {"path": path_out, "dataType": "str"}})


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
def sandbox(monkeypatch):
    from utk_curio.backend import config
    from utk_curio.backend.app.runs import jobs, viewer

    monkeypatch.setattr(config, "CURIO_DEFAULT_SAVE_NODE_OUTPUT", False)
    jobs.REGISTRY.reset()
    viewer.reset()
    fake = FakeSandbox()
    monkeypatch.setattr("utk_curio.backend.app.execution.node_exec.sandbox_request", fake)
    monkeypatch.setattr("utk_curio.backend.app.runs.viewer.sandbox_request", fake)
    yield fake
    fake.release()


@pytest.fixture()
def saved(monkeypatch):
    """The dashboard's saved outputs, as a load hydrates them: Grid's, unless a
    test empties the list."""
    from utk_curio.backend.app.projects import storage
    from utk_curio.backend.app.projects.schemas import OutputRef
    from utk_curio.backend.app.runs import viewer

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
    from utk_curio.backend.app.runs import viewer
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

    def test_a_tile_with_no_saved_output_runs_the_nodes_before_it_on_open(self, client, user_and_token, sandbox, saved):
        _, token = user_and_token
        pid = _create(client, token)
        saved.clear()

        started = _run(client, pid, {})
        assert started.status_code == 202, started.get_data(as_text=True)
        _wait(started.get_json()["runId"])

        assert [node for node, _ in sandbox.runs] == ["grid"]
        assert '"Date"' in sandbox.runs[0][1]["code"]

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


class TestRefusedValues:
    @pytest.mark.parametrize("values, words", [
        ({"param": {"period": "Week"}}, "Pick one of the choices"),
        ({"param": {"nope": 1}}, "not a control"),
        ({"grid": {"period": "Month"}}, "not a control"),
        ({"note": {"note": "x"}}, "not a control"),
        ("Month", "must map"),
    ])
    def test_a_value_that_is_not_a_controls_or_does_not_suit_it_is_refused(
        self, client, user_and_token, sandbox, saved, values, words,
    ):
        _, token = user_and_token
        note = {"id": "note", "type": PARAMETER, "content": "", "dashboardPinned": True,
                "metadata": {"widgets": [{"name": "note", "type": "text", "default": ""}]}}
        pid = _create(client, token, _nodes(extra=[note]))

        resp = client.post(
            f"/api/projects/{pid}/dashboard/runs", data=json.dumps({"values": values}),
            headers={"Content-Type": "application/json"},
        )

        assert resp.status_code in (400, 422), resp.get_data(as_text=True)
        assert words in resp.get_json()["error"]
        assert sandbox.runs == []

    def test_text_text_lists_and_files_are_read_only_as_the_contract_says(self):
        from utk_curio.backend.app.runs import viewer
        from utk_curio.common import shared_constants

        assert viewer.READ_ONLY_WIDGET_KINDS == {"text", "text-list", "file"}
        assert viewer.READ_ONLY_WIDGET_KINDS == set(shared_constants.read("dashboardRuns")["readOnlyWidgetKinds"])
        spec = {"dataflow": {"nodes": [
            {"id": "p", "dashboardPinned": True, "metadata": {"widgets": [
                {"name": kind.replace("-", "_"), "type": kind} for kind in ("text", "text-list", "file", "slider")
            ]}},
            {"id": "q", "metadata": {"widgets": [{"name": "k", "type": "slider"}]}},
        ]}}
        assert set(viewer.dashboard_controls(spec)) == {("p", "slider")}

    def test_a_node_that_reads_a_key_stops_with_the_message(self, client, user_and_token, sandbox, saved):
        from utk_curio.backend.app.runs import viewer

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


class TestLimits:
    def test_the_limiter_counts_each_forwarded_address_on_its_own(self, client, user_and_token, sandbox, saved, monkeypatch):
        from utk_curio.backend.app.common.address_limiter import AddressLimiter
        from utk_curio.backend.app.runs import viewer

        _, token = user_and_token
        pid = _create(client, token)
        monkeypatch.setattr(viewer, "_LIMITER", AddressLimiter(2, 100))

        statuses = [_run(client, pid, address="10.0.0.1").status_code for _ in range(3)]
        other = _run(client, pid, address="10.0.0.2").status_code

        assert statuses == [200, 200, 429]
        assert other == 200

    @pytest.mark.parametrize("proxy_hops", [0])
    def test_with_no_proxy_named_a_forwarded_address_is_not_believed(self, client, user_and_token, sandbox, saved, monkeypatch):
        """Without ``--proxy-hops`` anyone reaching the backend could write
        X-Forwarded-For, so a new address there is no new budget."""
        from utk_curio.backend.app.common.address_limiter import AddressLimiter
        from utk_curio.backend.app.runs import viewer

        _, token = user_and_token
        pid = _create(client, token)
        monkeypatch.setattr(viewer, "_LIMITER", AddressLimiter(2, 100))

        statuses = [_run(client, pid, address=f"10.0.0.{n}").status_code for n in range(1, 4)]

        assert statuses == [200, 200, 429]

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
        from utk_curio.backend.app.runs import viewer

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
        from utk_curio.backend.app.runs.models import DashboardStepOutput

        _, token = user_and_token
        pid = _create(client, token)
        _month(client, pid)
        entry = DashboardStepOutput.query.filter_by(project_id=pid).one()
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
        assert entry.session_id.startswith("dashboard-") and entry.session_id != token
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
        from utk_curio.backend.app.runs import viewer

        dataset = tmp_path / "trees.csv"
        dataset.write_text("a\n1\n")

        def key(**changes):
            fields = dict(packages="p1", node_type=CODE, engine="python", code="return 1", input_ref=None,
                          input_slots=None, datasets={"trees": viewer._file_identity(str(dataset))})
            fields.update(changes)
            return viewer.step_key(**fields)

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

    def test_an_owners_upgrade_runs_the_step_again(self, client, user_and_token, sandbox, saved, monkeypatch):
        import utk_curio

        _, token = user_and_token
        pid = _create(client, token)
        _month(client, pid)
        monkeypatch.setattr(utk_curio, "__version__", "99.0.0")

        _month(client, pid)

        assert len(sandbox.runs) == 2


class TestKeptOutputsGo:
    def _entry(self, pid, *, days=0, hours=0, size=100, private=False, used_days=None):
        from utk_curio.backend.app.runs.models import DashboardStepOutput, naive_utc_now
        from utk_curio.backend.extensions import db
        from utk_curio.common.dashboard_sessions import new_session_id

        now = naive_utc_now()
        entry = DashboardStepOutput(
            project_id=pid, node_id="grid", step_key="k" * 64, session_id=new_session_id(),
            output=json.dumps({"path": "p", "dataType": "str"}), output_path="p",
            artifact_ids='["p"]', size_bytes=size, private_to="t" * 64 if private else None,
            created_at=now - timedelta(days=days, hours=hours),
            used_at=now - timedelta(days=used_days if used_days is not None else days, hours=hours),
        )
        db.session.add(entry)
        db.session.commit()
        return entry.id, entry.session_id

    def test_an_output_goes_after_thirty_days_and_a_tabs_own_after_an_hour(self, client, user_and_token, sandbox):
        from utk_curio.backend.app.runs import viewer
        from utk_curio.backend.app.runs.models import DashboardStepOutput

        _, token = user_and_token
        pid = _create(client, token)
        fresh = self._entry(pid, days=29)
        old = self._entry(pid, days=31)
        tab_fresh = self._entry(pid, private=True)
        tab_old = self._entry(pid, private=True, hours=2)

        assert viewer.prune() == 2

        left = {row.id for row in DashboardStepOutput.query.all()}
        assert left == {fresh[0], tab_fresh[0]}
        assert sorted(sandbox.forgotten) == sorted([old[1], tab_old[1]])

    def test_a_dashboard_past_its_size_drops_the_least_recently_used(self, client, user_and_token, sandbox, monkeypatch):
        from utk_curio.backend.app.runs import viewer
        from utk_curio.backend.app.runs.models import DashboardStepOutput

        _, token = user_and_token
        pid = _create(client, token)
        monkeypatch.setattr(viewer, "MAX_KEPT_BYTES_PER_DASHBOARD", 250)
        stale = self._entry(pid, size=100, used_days=3)
        recent = self._entry(pid, size=100, used_days=1)
        newest = self._entry(pid, size=100, used_days=0)

        viewer.prune()

        assert {row.id for row in DashboardStepOutput.query.all()} == {recent[0], newest[0]}
        assert sandbox.forgotten == [stale[1]]

    def test_deleting_the_dataflow_forgets_its_outputs(self, client, user_and_token, sandbox):
        from utk_curio.backend.app.runs.models import DashboardStepOutput

        _, token = user_and_token
        pid = _create(client, token)
        _, session = self._entry(pid)

        resp = client.delete(f"/api/projects/{pid}", headers=_auth(token))

        assert resp.status_code in (200, 204), resp.get_data(as_text=True)
        assert DashboardStepOutput.query.filter_by(project_id=pid).count() == 0
        assert sandbox.forgotten == [session]
