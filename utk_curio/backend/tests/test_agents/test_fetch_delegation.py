"""dev/132 commit 2: a confirmed fetchable source builds itself.

The owner's instruction — *"The datafinder should be able to automatically
delegate the code to fetch external api datasets… Once it is uploaded, the
dataset finder should properly delegate the solving to the node builder or
content builder using the just-uploaded dataset."* `DEC-047` made that a
suggested PROMPT the user had to send; the selection now starts the node's own
builder itself, through the same detached per-node Solve the user's own button
starts.
"""

from __future__ import annotations

import json

from utk_curio.backend.app.agents import agent_jobs
from utk_curio.backend.app.agents import dataset_resolution as dr
from utk_curio.backend.app.agents import services as services_mod
from utk_curio.backend.tests.test_agents import test_routes as _tr
from utk_curio.backend.tests.test_agents.test_dataset_discovery_routes import _Harness

_auth = _tr._auth

DATA_OBSERVATION = {
    "status": "verified", "httpStatus": 200, "contentType": "application/geo+json",
    "sampleKeys": ["features", "type"], "checkedAt": "now",
}
#: Data code can read, in a format the Data Lake does not store, so the row is
#: handed to the builder rather than downloaded.
API_OBSERVATION = {
    "status": "verified", "httpStatus": 200, "contentType": "application/xml",
    "checkedAt": "now",
}
PORTAL_OBSERVATION = {
    "status": "verified", "httpStatus": 200, "contentType": "text/html",
    "pageTitle": "Downloads — community areas", "checkedAt": "now",
}


def _await_candidates(client, user, token, monkeypatch, **kw):
    h = _Harness(client, user, token, monkeypatch, **kw)
    h.solve()
    return h, h.finder_attachment_id()


def _select(h, finder_id, picks):
    return h.client.post(
        f"/api/agents/projects/{h.pid}/attachments/{finder_id}/dataset-selection",
        json={"picks": picks}, headers=_auth(h.token),
    )


def _drain(h, attachment_id, *, timeout=10.0):
    """Wait for the delegated job to finish and return its events."""
    job = agent_jobs.latest_job(h.ukey, attachment_id)
    assert job is not None, "no job was started"
    return list(agent_jobs.subscribe(job))


class TestAFetchableRowIsDelegated:
    def test_confirming_an_api_row_starts_the_node_builder_on_it(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h, finder_id = _await_candidates(
            client, user, token, monkeypatch,
            dl_replies=[
                'import pandas as pd\nreturn pd.read_csv("invented.csv")',
                'import pandas as pd\nreturn pd.read_csv("invented.csv")',
                'import pandas as pd\nreturn pd.read_csv("invented.csv")',
                'import geopandas as gpd\nreturn gpd.read_file('
                '"https://data.example.org/areas.geojson")',
            ],
        )
        monkeypatch.setattr(
            "utk_curio.backend.app.agents.verify.verify_external_source",
            lambda url, **k: dict(API_OBSERVATION),
        )
        body = _select(h, finder_id, [
            {"lane": "external", "key": "https://data.example.org/areas.geojson"},
        ]).get_json()
        assert body["status"] == dr.STATE_RESOLVED
        delegated = body["delegated"]
        assert delegated["status"] == "delegating"
        assert delegated["nodeId"] == h.load
        assert delegated["sources"] == ["Chicago community areas"]
        # The build runs detached, exactly like the user's own per-node Solve.
        events = _drain(h, delegated["attachmentId"])
        done = next(p for k, p in events if k == "done")
        assert done["verdict"] == "pass"
        # And it built from the confirmed source, not from a guess.
        assert "confirmedSource" in h.dl_calls[-1]
        assert "https://data.example.org/areas.geojson" in h.dl_calls[-1]
        assert "https://data.example.org/areas.geojson" in h.node_content(h.load)

    def test_a_portal_row_is_not_delegated_and_says_what_to_do(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h, finder_id = _await_candidates(client, user, token, monkeypatch)
        monkeypatch.setattr(
            "utk_curio.backend.app.agents.verify.verify_external_source",
            lambda url, **k: dict(PORTAL_OBSERVATION),
        )
        body = _select(h, finder_id, [
            {"lane": "external", "key": "https://data.example.org/areas.geojson"},
        ]).get_json()
        assert body["picks"][0]["access"] == "manual-download"
        assert body["picks"][0]["downloadSteps"]
        assert body["delegated"]["status"] == "manual-download"
        assert "Import dataset" in body["delegated"]["reason"]
        assert agent_jobs.latest_job(h.ukey, h.load) is None
        assert h.node_content(h.load) == ""  # nothing was authored for a file that is not here

    def test_an_unreachable_row_delegates_nothing(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h, finder_id = _await_candidates(client, user, token, monkeypatch)
        monkeypatch.setattr(
            "utk_curio.backend.app.agents.verify.verify_external_source",
            lambda url, **k: {"status": "unreachable", "httpStatus": 404,
                              "detail": "the endpoint answered 404"},
        )
        body = _select(h, finder_id, [
            {"lane": "external", "key": "https://data.example.org/areas.geojson"},
        ]).get_json()
        assert body["status"] == dr.STATE_CANDIDATES_PENDING
        assert "delegated" not in body

    def test_a_running_session_owns_the_node_instead(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """Two builders on one node would race for its content: when dev/131's
        session is live, the moved selection record IS its trigger."""
        user, token = user_and_token
        h, finder_id = _await_candidates(client, user, token, monkeypatch)
        monkeypatch.setattr(
            "utk_curio.backend.app.agents.verify.verify_external_source",
            lambda url, **k: dict(API_OBSERVATION),
        )
        monkeypatch.setattr(
            agent_jobs, "live_job", lambda user_key, attachment_id: _FakeJob(),
        )
        body = _select(h, finder_id, [
            {"lane": "external", "key": "https://data.example.org/areas.geojson"},
        ]).get_json()
        assert body["delegated"]["status"] == "session-running"


class _FakeJob:
    kind = "solve-batch"
    job_id = "job-1"


class TestAfterTheImportSolvingContinues:
    """dev/132 (R3): the download steps end at Import dataset, and the dataset
    the user just imported IS the node's source — no explanation needed, and no
    second card. The card posts the new dataset id as a catalog pick; the
    runtime resolves it against its OWN Data Catalog listing (the same one
    catalog.search serves and DEC-072's gate grounds against), so nothing the
    client sends can introduce a source."""

    def test_an_imported_dataset_resolves_the_node_and_starts_the_builder(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        from utk_curio.backend.app.agents import services as services_mod

        user, token = user_and_token
        h, finder_id = _await_candidates(client, user, token, monkeypatch)
        # The user follows the portal steps and imports the file: the ONE
        # catalog import, which the card calls through its shared hook.
        dataset_id = _tr.TestDatasetFinderTools()._seed_dataset(user, filename="areas.csv")
        loader = (
            "import pandas as pd\n"
            f'return pd.read_csv(curio_dataset_path("{dataset_id}"))'
        )
        frames: list[str] = []

        def _reply(config, messages, **kwargs):
            if messages and messages[0].get("content") == services_mod.TITLE_PROMPT:
                return "Title"
            frames.append(messages[-1].get("content") or "")
            return loader

        monkeypatch.setattr(
            "utk_curio.backend.app.agents.services.run_chat_completion", _reply
        )
        body = _select(h, finder_id, [{"lane": "catalog", "key": dataset_id}]).get_json()
        assert body["status"] == dr.STATE_RESOLVED  # its file is here; nothing to install
        pick = body["picks"][0]
        assert pick["datasetId"] == dataset_id and pick["imported"] is True
        delegated = body["delegated"]
        assert delegated["status"] == "delegating"
        events = _drain(h, delegated["attachmentId"])
        done = next(p for k, p in events if k == "done")
        assert done["verdict"] == "pass"
        # The builder was handed the confirmed source, and built against the
        # imported dataset BY ID — dev/114's grounded form.
        assert any("confirmedSource" in f and dataset_id in f for f in frames)
        assert f'curio_dataset_path("{dataset_id}")' in h.node_content(h.load)

    def test_a_dataset_id_the_catalog_does_not_have_is_still_refused(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h, finder_id = _await_candidates(client, user, token, monkeypatch)
        r = _select(h, finder_id, [{"lane": "catalog", "key": "imported.not-a-dataset"}])
        assert r.status_code == 422
        assert "not a catalog candidate" in r.get_json()["error"]


class TestAMidSessionDatasetStillGetsItsPath:
    """dev/131 F4, closed here. The sandbox path mapping is resolved when a
    Solve starts (dev/115's rule — a detached job holds no request context), so
    a dataset that appeared DURING the session had no path inside the running
    job. What the resolution actually needs is the acting user, and a job can
    hold that from its start."""

    def test_an_id_the_eager_mapping_never_saw_is_resolved_with_the_captured_user(
        self, app, tmp_curio, user_and_token, monkeypatch
    ):
        user, _token = user_and_token
        dataset_id = _tr.TestDatasetFinderTools()._seed_dataset(user, filename="mid.csv")
        code = f'return pd.read_csv(curio_dataset_path("{dataset_id}"))'
        mapping: dict = {}  # what the session started with: nothing
        with app.test_request_context():
            paths = services_mod._session_dataset_paths(
                "p-132", user, mapping, [code],
            )
        assert paths[dataset_id].endswith("mid.csv")
        assert mapping[dataset_id] == paths[dataset_id]  # cached for the session

    def test_without_a_user_the_mapping_is_unchanged_and_nothing_raises(
        self, tmp_curio
    ):
        code = 'return pd.read_csv(curio_dataset_path("imported.ghost"))'
        assert services_mod._session_dataset_paths("p-132", None, {}, [code]) == {}

    def test_an_already_mapped_id_costs_no_lookup(self, tmp_curio, monkeypatch):
        called: list = []
        monkeypatch.setattr(
            services_mod, "_dataset_path_topup",
            lambda *a, **k: called.append(a) or a[2],
        )
        code = 'return pd.read_csv(curio_dataset_path("imported.known"))'
        paths = services_mod._session_dataset_paths(
            "p-132", object(), {"imported.known": "/data/known.csv"}, [code],
        )
        assert paths == {"imported.known": "/data/known.csv"}
        # The top-up is consulted, and it is the one that skips a resolved id.
        assert len(called) == 1
        assert services_mod._dataset_ids_in([code]) == ["imported.known"]


#: A connector row the Finder found with datalake.search: a portal landing page,
#: and the coordinate that lets Curio download the resource itself.
CHICAGO = "lake.cityofchicago.data-portal@1"
LAKE_CANDIDATES = json.dumps({"datasetCandidates": {"lanes": {
    "external": [{
        "name": "Chicago community areas", "sourceType": "lake",
        "url": "https://data.example.org/areas.geojson",
        "sourceId": CHICAGO, "resourceId": "cauq-8yn6",
    }, {
        "name": "Chicago wards", "sourceType": "lake",
        "sourceId": CHICAGO, "resourceId": "sp34-6z76",
    }],
    "catalog": [],
}}})
ROSTER = {CHICAGO: {"dirName": CHICAGO, "provider": "socrata",
                    "capabilities": {"download": True, "formats": ["csv", "geojson"]}}}


class _FakeLake:
    """``DataLakeService`` as the confirmation sees it."""

    def __init__(self, started=None, job=None, error=None):
        self.started, self.job, self.error = started, job, error
        self.calls: list = []

    def start_acquire(self, source_id, resource_id, fmt=None):
        from utk_curio.backend.app.datalakes.domain.errors import DataLakeError

        self.calls.append((source_id, resource_id, fmt))
        if self.error:
            raise DataLakeError(self.error)
        return self.started

    def get_job(self, job_id):
        return self.job


def _lake_harness(client, user, token, monkeypatch, lake):
    roster = services_mod._LazyRoster
    monkeypatch.setattr(services_mod, "_LazyRoster", lambda: roster(dict(ROSTER)))
    monkeypatch.setattr(services_mod, "_lake_service", lambda: lake)
    monkeypatch.setattr(services_mod, "_LAKE_APPLY_WAIT_S", 0.2)
    return _await_candidates(client, user, token, monkeypatch,
                             discover_replies=[LAKE_CANDIDATES])


class TestAnAcquirableRowIsDownloaded:
    """A row Curio can download is downloaded by the Data Lake when it is
    confirmed, and recorded as the catalog pick it becomes. It never reaches
    the builder as a URL to write fetch code for."""

    def test_the_delegated_discovery_marks_the_row(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h, finder_id = _lake_harness(client, user, token, monkeypatch, _FakeLake())
        part = next(
            p for turn in h.session_turns(finder_id)
            for p in turn.get("content") or [] if p.get("type") == "datasetCandidates"
        )
        assert [r.get("acquirable") for r in part["lanes"]["external"]] == [True, True]

    def test_a_held_resource_resolves_the_node_and_starts_the_builder(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        dataset_id = _tr.TestDatasetFinderTools()._seed_dataset(user, filename="areas.csv")
        lake = _FakeLake(started={"dataset": {"id": dataset_id}, "alreadyPresent": True})
        h, finder_id = _lake_harness(client, user, token, monkeypatch, lake)
        loader = f'import pandas as pd\nreturn pd.read_csv(curio_dataset_path("{dataset_id}"))'
        monkeypatch.setattr(
            "utk_curio.backend.app.agents.services.run_chat_completion",
            lambda config, messages, **k: (
                "Title" if messages[0].get("content") == services_mod.TITLE_PROMPT else loader
            ),
        )
        monkeypatch.setattr(
            "utk_curio.backend.app.agents.verify.verify_external_source",
            lambda url, **k: dict(PORTAL_OBSERVATION),
        )
        body = _select(h, finder_id, [
            {"lane": "external", "key": "https://data.example.org/areas.geojson"},
        ]).get_json()
        assert lake.calls == [(CHICAGO, "cauq-8yn6", None)]
        assert body["status"] == dr.STATE_RESOLVED
        pick = body["picks"][0]
        assert pick["lane"] == "catalog" and pick["datasetId"] == dataset_id
        assert pick["imported"] is True
        assert pick["lakeSource"] == {"sourceId": CHICAGO, "resourceId": "cauq-8yn6"}
        assert body["acquisitions"][0]["status"] == "acquired"
        assert body["delegated"]["status"] == "delegating"
        events = _drain(h, body["delegated"]["attachmentId"])
        assert next(p for k, p in events if k == "done")["verdict"] == "pass"
        assert f'curio_dataset_path("{dataset_id}")' in h.node_content(h.load)

    def test_a_plain_file_link_is_downloaded_through_direct_url(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        dataset_id = _tr.TestDatasetFinderTools()._seed_dataset(user, filename="areas.csv")
        lake = _FakeLake(started={"dataset": {"id": dataset_id}, "alreadyPresent": True})
        direct = "lake.curio.direct-url@1"
        roster = services_mod._LazyRoster
        monkeypatch.setattr(services_mod, "_LazyRoster", lambda: roster({direct: {
            "dirName": direct, "provider": "direct",
            "capabilities": {"download": True, "formats": ["csv", "geojson"]},
        }}))
        monkeypatch.setattr(services_mod, "_lake_service", lambda: lake)
        # The Finder's row names only a link: no coordinate was ever proposed.
        h, finder_id = _await_candidates(client, user, token, monkeypatch)
        loader = f'import pandas as pd\nreturn pd.read_csv(curio_dataset_path("{dataset_id}"))'
        monkeypatch.setattr(
            "utk_curio.backend.app.agents.services.run_chat_completion",
            lambda config, messages, **k: (
                "Title" if messages[0].get("content") == services_mod.TITLE_PROMPT else loader
            ),
        )
        monkeypatch.setattr(
            "utk_curio.backend.app.agents.verify.verify_external_source",
            lambda url, **k: dict(DATA_OBSERVATION),
        )
        url = "https://data.example.org/areas.geojson"
        body = _select(h, finder_id, [{"lane": "external", "key": url}]).get_json()
        assert lake.calls == [(direct, url, "geojson")]
        assert body["picks"][0]["datasetId"] == dataset_id
        assert body["picks"][0]["lakeSource"] == {"sourceId": direct, "resourceId": url}
        events = _drain(h, body["delegated"]["attachmentId"])
        assert next(p for k, p in events if k == "done")["verdict"] == "pass"

    def test_a_row_with_no_url_is_confirmed_by_its_coordinate(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        lake = _FakeLake(started={"jobId": "job-1", "status": "queued"},
                         job={"status": "running"})
        h, finder_id = _lake_harness(client, user, token, monkeypatch, lake)
        body = _select(h, finder_id, [
            {"lane": "external", "key": f"{CHICAGO}/sp34-6z76"},
        ]).get_json()
        assert lake.calls == [(CHICAGO, "sp34-6z76", None)]
        assert body["picks"][0]["acquiring"] == {"jobId": "job-1"}

    def test_a_slow_download_waits_and_is_settled_once_it_lands(
        self, app, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        lake = _FakeLake(started={"jobId": "job-1", "status": "queued"},
                         job={"status": "running"})
        h, finder_id = _lake_harness(client, user, token, monkeypatch, lake)
        body = _select(h, finder_id, [
            {"lane": "external", "key": "https://data.example.org/areas.geojson"},
        ]).get_json()
        assert body["status"] == dr.STATE_AWAITING_INSTALL
        assert body["picks"][0]["acquiring"] == {"jobId": "job-1"}
        assert body["delegated"]["status"] == "acquiring"
        assert "downloading into your Data Catalog" in body["delegated"]["reason"]
        assert agent_jobs.latest_job(h.ukey, h.load) is None
        assert "downloading" in dr.node_source_state(h.spec(), h.load)["detail"]

        # The file lands; the next Solve's entry reads what the account holds.
        from utk_curio.backend.app.datasets.repositories import user_store

        monkeypatch.setattr(
            user_store.UserDatasetRepository, "lake_resource_index",
            lambda self: {(CHICAGO, "cauq-8yn6"): "lake.areas"},
        )
        monkeypatch.setattr(services_mod, "_acting_user", lambda: user)
        services_mod._settle_lake_acquisitions(h.ukey, h.pid)
        record = dr.source_record(h.spec(), h.load)
        assert record["status"] == dr.STATE_RESOLVED
        assert record["picks"][0]["datasetId"] == "lake.areas"
        assert record["picks"][0]["imported"] is True

    def test_a_failed_download_is_reported_and_nothing_is_built(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        lake = _FakeLake(error="the portal refused the request")
        h, finder_id = _lake_harness(client, user, token, monkeypatch, lake)
        # Even a probe that reads data does not send a downloadable row to the
        # builder as fetch code.
        monkeypatch.setattr(
            "utk_curio.backend.app.agents.verify.verify_external_source",
            lambda url, **k: dict(DATA_OBSERVATION),
        )
        body = _select(h, finder_id, [
            {"lane": "external", "key": "https://data.example.org/areas.geojson"},
        ]).get_json()
        assert body["acquisitions"][0]["status"] == "failed"
        assert body["delegated"]["status"] == "acquire-failed"
        assert "the portal refused the request" in body["delegated"]["reason"]
        assert agent_jobs.latest_job(h.ukey, h.load) is None


class TestSettlingAcquisitions:
    def _spec(self, picks, status=dr.STATE_AWAITING_INSTALL):
        return {"dataflow": {"agentAttachments": [{
            "attachmentId": "f1", "coord": f"{dr.FINDER_AGENT_ID}@1.0.0",
            "target": {"kind": "node", "targetId": "n1"},
            dr.RECORD_KEY: {"status": status, "picks": picks},
        }]}}

    def test_only_a_landed_download_resolves(self):
        waiting = dr.acquiring_pick(
            {"name": "Areas", "sourceId": CHICAGO, "resourceId": "a"}, "job-1")
        spec = self._spec([waiting])
        assert dr.has_acquiring_picks(spec)
        assert dr.settle_acquisitions(spec, {}) == []
        assert dr.settle_acquisitions(spec, {(CHICAGO, "a"): "lake.areas"}) == ["f1"]
        state = spec["dataflow"]["agentAttachments"][0][dr.RECORD_KEY]
        assert state["status"] == dr.STATE_RESOLVED
        assert not dr.has_acquiring_picks(spec)

    def test_another_pick_still_waiting_keeps_the_node_waiting(self):
        spec = self._spec([
            dr.acquiring_pick({"name": "Areas", "sourceId": CHICAGO, "resourceId": "a"}, "j1"),
            dr.acquiring_pick({"name": "Wards", "sourceId": CHICAGO, "resourceId": "b"}, "j2"),
        ])
        dr.settle_acquisitions(spec, {(CHICAGO, "a"): "lake.areas"})
        state = spec["dataflow"]["agentAttachments"][0][dr.RECORD_KEY]
        assert state["status"] == dr.STATE_AWAITING_INSTALL
        assert state["picks"][0]["imported"] is True and state["picks"][1]["acquiring"]

    def test_an_installed_catalog_pick_beside_a_downloaded_one_resolves(self):
        spec = self._spec([
            {"lane": "catalog", "datasetId": "d1", "installed": False},
            dr.acquired_pick({"name": "Areas", "sourceId": CHICAGO, "resourceId": "a"}, "lake.a"),
        ])
        assert dr.mark_dataset_installed(spec, "d1") == ["f1"]

    def test_the_builder_is_told_the_coordinate(self):
        spec = self._spec([{
            "lane": "external", "name": "Areas", "url": "https://x.example/a",
            "sourceId": CHICAGO, "resourceId": "a", "acquirable": True,
        }], status=dr.STATE_RESOLVED)
        pick = dr.confirmed_source(spec, "n1")["picks"][0]
        assert pick["sourceId"] == CHICAGO and pick["acquirable"] is True
