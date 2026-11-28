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

import pytest

from utk_curio.backend.app.agents.infrastructure import agent_jobs
from utk_curio.backend.app.agents.application import attachments
from utk_curio.backend.app.agents.application import dataset_resolution as dr
from utk_curio.backend.app.agents.application.proposals import acquire
from utk_curio.backend.app.agents.application.proposals import store
from utk_curio.backend.app.agents.application import spec_reads
from utk_curio.backend.app.agents.application.solve import budgets
from utk_curio.backend.app.agents.application.turns import grounding
from utk_curio.backend.app.agents.application.turns import roster as packages_roster
from utk_curio.backend.app.agents.application.turns import titles
from utk_curio.backend.app.agents.domain import content
from utk_curio.backend.app.agents.infrastructure import providers
from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests.test_agents import test_routes_turns as routes_turns
from utk_curio.backend.tests.test_agents.test_dataset_discovery_routes import URL, _Harness, _sse_events

DATA_OBSERVATION = {
    "status": "verified", "httpStatus": 200, "contentType": "application/geo+json",
    "sampleKeys": ["features", "type"], "checkedAt": "now",
}
#: Data code can read, in a format the Discovery Catalog does not store, so the row is
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
        # The Finder is asked before the loader's builder, which writes only
        # the code that loads the pick.
        h, finder_id = _await_candidates(
            client, user, token, monkeypatch,
            dl_replies=[
                ('import geopandas as gpd\nreturn gpd.read_file('
                 '"https://data.example.org/areas.geojson")'),
            ],
        )
        assert h.dl_calls == []
        monkeypatch.setattr(
            'utk_curio.backend.app.agents.application.verify.verify_external_source',
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
            'utk_curio.backend.app.agents.application.verify.verify_external_source',
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
            'utk_curio.backend.app.agents.application.verify.verify_external_source',
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
            'utk_curio.backend.app.agents.application.verify.verify_external_source',
            lambda url, **k: dict(API_OBSERVATION),
        )
        monkeypatch.setattr(
            agent_jobs, "live_job", lambda user_key, attachment_id: _FakeJob(),
        )
        body = _select(h, finder_id, [
            {"lane": "external", "key": "https://data.example.org/areas.geojson"},
        ]).get_json()
        assert body["delegated"]["status"] == "session-running"


class TestTheBuildRunsOnTheBuildersConfiguration:
    """The selection is posted to the Dataset Finder, but the node is built by
    its own builder, so the build answers with the builder's configuration."""

    _API_ROW = [{"lane": "external", "key": "https://data.example.org/areas.geojson"}]

    def _config(self, client, token, label, model):
        body = {"label": label, "apiType": "openai_compatible", "baseUrl": "https://llm.example.com/v1",
                "apiKey": "sk-some-key-0123456789", "model": model}
        return client.post("/api/agents/llm/configs", json=body, headers=_auth(token)).get_json()["config"]["id"]

    def _ready(self, client, user, token, monkeypatch):
        h, finder_id = _await_candidates(
            client, user, token, monkeypatch,
            dl_replies=[
                ('import geopandas as gpd\nreturn gpd.read_file('
                 '"https://data.example.org/areas.geojson")'),
            ],
        )
        assert h.dl_calls == [], "the loader's builder was asked before its Finder"
        monkeypatch.setattr(
            'utk_curio.backend.app.agents.application.verify.verify_external_source',
            lambda url, **k: dict(API_OBSERVATION),
        )
        return h, finder_id

    def test_never_the_finders(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        h, finder_id = self._ready(client, user, token, monkeypatch)
        client.put("/api/agents/llm/assignments", json={
            "agent.curio.dataset-finder": self._config(client, token, "Finder", "finder-model"),
            "agent.curio.node-builder": self._config(client, token, "Builder", "builder-model"),
        }, headers=_auth(token))
        inner = providers.run_chat_turn
        models = []

        def _recording(config, messages, **kwargs):
            models.append(config.model)
            return inner(config, messages, **kwargs)

        monkeypatch.setattr('utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn', _recording)
        delegated = _select(h, finder_id, self._API_ROW).get_json()["delegated"]
        assert delegated["status"] == "delegating"
        _drain(h, delegated["attachmentId"])
        assert models and set(models) == {"builder-model"}

    def test_a_builder_that_cannot_run_is_named(self, client, user_and_token, tmp_curio, monkeypatch):
        from utk_curio.backend.app.agents.infrastructure import llm_configs

        user, token = user_and_token
        h, finder_id = self._ready(client, user, token, monkeypatch)
        builder = self._config(client, token, "Builder", "builder-model")
        client.put("/api/agents/llm/assignments", json={"agent.curio.node-builder": builder},
                   headers=_auth(token))
        store = llm_configs.default_store()
        doc = store.read(h.ukey)
        del doc["configs"][builder]  # the choice now names nothing
        store._write(h.ukey, doc)
        body = _select(h, finder_id, self._API_ROW).get_json()
        assert body["status"] == dr.STATE_RESOLVED  # the selection is recorded regardless
        assert body["delegated"]["status"] == "skipped"
        assert body["delegated"]["reason"].startswith("the node's Node Builder cannot start")


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
        from utk_curio.backend.app.agents.application.proposals import acquire
        from utk_curio.backend.app.agents.application import spec_reads
        from utk_curio.backend.app.agents.application.turns import grounding
        from utk_curio.backend.app.agents.application.turns import roster as packages_roster
        from utk_curio.backend.app.agents.application.turns import titles
        from utk_curio.backend.app.agents.infrastructure import providers

        user, token = user_and_token
        h, finder_id = _await_candidates(client, user, token, monkeypatch)
        # The user follows the portal steps and imports the file: the ONE
        # catalog import, which the card calls through its shared hook.
        dataset_id = routes_turns.TestDatasetFinderTools()._seed_dataset(user, filename="areas.csv")
        loader = (
            "import pandas as pd\n"
            f'return pd.read_csv(curio_data_path("{dataset_id}"))'
        )
        frames: list[str] = []

        def _reply(config, messages, **kwargs):
            if messages and messages[0].get("content") == titles.title_prompt():
                return "Title"
            frames.append(messages[-1].get("content") or "")
            return loader

        monkeypatch.setattr(
            'utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn', _reply
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
        assert f'curio_data_path("{dataset_id}")' in h.node_content(h.load)

    def test_a_dataset_id_the_catalog_does_not_have_is_still_refused(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h, finder_id = _await_candidates(client, user, token, monkeypatch)
        r = _select(h, finder_id, [{"lane": "catalog", "key": "imported.not-a-dataset"}])
        assert r.status_code == 422
        assert "not a catalog candidate" in r.get_json()["error"]


class TestAMidSessionDatasetStillGetsItsPath:
    """dev/131 F4, closed here. The sandbox path mapping was resolved when a
    Solve started (dev/115's rule, a detached job holds no request context), so
    a dataset that appeared DURING the session had no path inside the running
    job. What the resolution actually needs is the acting user, and a job can
    hold that from its start."""

    def test_an_id_the_eager_mapping_never_saw_is_resolved_with_the_captured_user(
        self, app, tmp_curio, user_and_token, monkeypatch
    ):
        user, _token = user_and_token
        dataset_id = routes_turns.TestDatasetFinderTools()._seed_dataset(user, filename="mid.csv")
        code = f'return pd.read_csv(curio_data_path("{dataset_id}"))'
        mapping: dict = {}  # what the session started with: nothing
        with app.test_request_context():
            paths = grounding._session_dataset_paths(
                "p-132", user, mapping, [code],
            )
        assert paths[dataset_id].endswith("mid.csv")
        assert mapping[dataset_id] == paths[dataset_id]  # cached for the session

    def test_without_a_user_the_mapping_is_unchanged_and_nothing_raises(
        self, tmp_curio
    ):
        code = 'return pd.read_csv(curio_data_path("imported.ghost"))'
        assert grounding._session_dataset_paths("p-132", None, {}, [code]) == {}

    def test_an_already_mapped_id_costs_no_lookup(self, tmp_curio, monkeypatch):
        called: list = []
        monkeypatch.setattr(
            grounding, "_dataset_path_topup",
            lambda *a, **k: called.append(a) or a[2],
        )
        code = 'return pd.read_csv(curio_data_path("imported.known"))'
        paths = grounding._session_dataset_paths(
            "p-132", object(), {"imported.known": "/data/known.csv"}, [code],
        )
        assert paths == {"imported.known": "/data/known.csv"}
        # The top-up is consulted, and it is the one that skips a resolved id.
        assert len(called) == 1
        assert grounding._dataset_ids_in([code]) == ["imported.known"]


#: A connector row the Finder found with discovery.search: a portal landing page,
#: and the coordinate that lets Curio download the resource itself.
CHICAGO = "source.cityofchicago.data-portal@1"
DISCOVERY_CANDIDATES = json.dumps({"datasetCandidates": {"lanes": {
    "external": [{
        "name": "Chicago community areas", "sourceType": "discovery",
        "url": "https://data.example.org/areas.geojson",
        "sourceId": CHICAGO, "resourceId": "cauq-8yn6",
    }, {
        "name": "Chicago wards", "sourceType": "discovery",
        "sourceId": CHICAGO, "resourceId": "sp34-6z76",
    }],
    "catalog": [],
}}})
ROSTER = {CHICAGO: {"dirName": CHICAGO, "provider": "socrata",
                    "capabilities": {"download": True, "formats": ["csv", "geojson"]}}}


class _FakeDiscovery:
    """``DiscoveryService`` as the confirmation sees it: the portal describes
    the two resources :data:`DISCOVERY_CANDIDATES` names, and no other."""

    DESCRIBED = {(CHICAGO, "cauq-8yn6"), (CHICAGO, "sp34-6z76")}

    def __init__(self, started=None, job=None, error=None):
        self.started, self.job, self.error = started, job, error
        self.calls: list = []

    def describe_resource(self, source_id, resource_id):
        from utk_curio.backend.app.discovery.domain.errors import DiscoveryError

        if (source_id, resource_id) not in self.DESCRIBED:
            raise DiscoveryError(f"{resource_id} is not on {source_id}")
        return {"resourceId": resource_id, "name": resource_id, "formats": ["csv", "geojson"]}

    def start_acquire(self, source_id, resource_id, fmt=None, title=None):
        from utk_curio.backend.app.discovery.domain.errors import DiscoveryError

        # The title a pick's download is named by (step 5.6) is checked by
        # test_finder_follow_ups.py; each call is recorded as before.
        self.calls.append((source_id, resource_id, fmt))
        if self.error:
            raise DiscoveryError(self.error)
        return self.started

    def get_job(self, job_id):
        return self.job


def _the_discovery_catalog_is(monkeypatch, fake) -> None:
    """*fake* stands in for the Discovery Catalog of whoever asks: the
    request's account, and the person a Solve's thread runs for, whom a
    card's describes are asked as, whatever lock its reads are made under."""
    monkeypatch.setattr(acquire, "_discovery_service", lambda **_reads: fake)
    monkeypatch.setattr(acquire, "_discovery_service_for", lambda user, **_reads: fake)


def _discovery_harness(client, user, token, monkeypatch, fake):
    roster = packages_roster._LazyRoster
    monkeypatch.setattr(packages_roster, "_LazyRoster", lambda: roster(dict(ROSTER)))
    _the_discovery_catalog_is(monkeypatch, fake)
    monkeypatch.setattr(acquire, "_DISCOVERY_APPLY_WAIT_S", 0.2)
    return _await_candidates(client, user, token, monkeypatch,
                             discover_replies=[DISCOVERY_CANDIDATES])


class TestAnAcquirableRowIsDownloaded:
    """A row Curio can download is downloaded by the Discovery Catalog when it is
    confirmed, and recorded as the catalog pick it becomes. It never reaches
    the builder as a URL to write fetch code for."""

    def test_the_delegated_discovery_marks_the_row(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h, finder_id = _discovery_harness(client, user, token, monkeypatch, _FakeDiscovery())
        part = next(
            p for turn in h.session_turns(finder_id)
            for p in turn.get("content") or [] if p.get("type") == "datasetCandidates"
        )
        assert [r.get("acquirable") for r in part["lanes"]["external"]] == [True, True]

    def test_a_held_resource_resolves_the_node_and_starts_the_builder(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        dataset_id = routes_turns.TestDatasetFinderTools()._seed_dataset(user, filename="areas.csv")
        fake = _FakeDiscovery(started={"dataset": {"id": dataset_id}, "alreadyPresent": True})
        h, finder_id = _discovery_harness(client, user, token, monkeypatch, fake)
        loader = f'import pandas as pd\nreturn pd.read_csv(curio_data_path("{dataset_id}"))'
        monkeypatch.setattr(
            'utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn',
            lambda config, messages, **k: (
                "Title" if messages[0].get("content") == titles.title_prompt() else loader
            ),
        )
        monkeypatch.setattr(
            'utk_curio.backend.app.agents.application.verify.verify_external_source',
            lambda url, **k: dict(PORTAL_OBSERVATION),
        )
        body = _select(h, finder_id, [
            {"lane": "external", "key": "https://data.example.org/areas.geojson"},
        ]).get_json()
        assert fake.calls == [(CHICAGO, "cauq-8yn6", None)]
        assert body["status"] == dr.STATE_RESOLVED
        pick = body["picks"][0]
        assert pick["lane"] == "catalog" and pick["datasetId"] == dataset_id
        assert pick["imported"] is True
        assert pick["discoverySource"] == {"sourceId": CHICAGO, "resourceId": "cauq-8yn6"}
        assert body["acquisitions"][0]["status"] == "acquired"
        assert body["delegated"]["status"] == "delegating"
        events = _drain(h, body["delegated"]["attachmentId"])
        assert next(p for k, p in events if k == "done")["verdict"] == "pass"
        assert f'curio_data_path("{dataset_id}")' in h.node_content(h.load)

    def test_a_plain_file_link_is_downloaded_through_direct_url(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        dataset_id = routes_turns.TestDatasetFinderTools()._seed_dataset(user, filename="areas.csv")
        fake = _FakeDiscovery(started={"dataset": {"id": dataset_id}, "alreadyPresent": True})
        direct = "source.curio.direct-url@1"
        roster = packages_roster._LazyRoster
        monkeypatch.setattr(packages_roster, "_LazyRoster", lambda: roster({direct: {
            "dirName": direct, "provider": "direct",
            "capabilities": {"download": True, "formats": ["csv", "geojson"]},
        }}))
        _the_discovery_catalog_is(monkeypatch, fake)
        # The Finder's row names only a link: no coordinate was ever proposed.
        h, finder_id = _await_candidates(client, user, token, monkeypatch)
        loader = f'import pandas as pd\nreturn pd.read_csv(curio_data_path("{dataset_id}"))'
        monkeypatch.setattr(
            'utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn',
            lambda config, messages, **k: (
                "Title" if messages[0].get("content") == titles.title_prompt() else loader
            ),
        )
        monkeypatch.setattr(
            'utk_curio.backend.app.agents.application.verify.verify_external_source',
            lambda url, **k: dict(DATA_OBSERVATION),
        )
        url = "https://data.example.org/areas.geojson"
        body = _select(h, finder_id, [{"lane": "external", "key": url}]).get_json()
        assert fake.calls == [(direct, url, "geojson")]
        assert body["picks"][0]["datasetId"] == dataset_id
        assert body["picks"][0]["discoverySource"] == {"sourceId": direct, "resourceId": url}
        events = _drain(h, body["delegated"]["attachmentId"])
        assert next(p for k, p in events if k == "done")["verdict"] == "pass"

    def test_a_row_with_no_url_is_confirmed_by_its_coordinate(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        fake = _FakeDiscovery(started={"jobId": "job-1", "status": "queued"},
                         job={"status": "running"})
        h, finder_id = _discovery_harness(client, user, token, monkeypatch, fake)
        body = _select(h, finder_id, [
            {"lane": "external", "key": f"{CHICAGO}/sp34-6z76"},
        ]).get_json()
        assert fake.calls == [(CHICAGO, "sp34-6z76", None)]
        assert body["picks"][0]["acquiring"] == {"jobId": "job-1"}

    def test_a_slow_download_waits_and_is_settled_once_it_lands(
        self, app, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        fake = _FakeDiscovery(started={"jobId": "job-1", "status": "queued"},
                         job={"status": "running"})
        h, finder_id = _discovery_harness(client, user, token, monkeypatch, fake)
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
            user_store.UserDatasetRepository, "discovery_resource_index",
            lambda self: {(CHICAGO, "cauq-8yn6"): "source.areas"},
        )
        monkeypatch.setattr(spec_reads, "_acting_user", lambda: user)
        acquire._settle_discovery_acquisitions(h.ukey, h.pid)
        record = dr.source_record(h.spec(), h.load)
        assert record["status"] == dr.STATE_RESOLVED
        assert record["picks"][0]["datasetId"] == "source.areas"
        assert record["picks"][0]["imported"] is True

    def test_a_failed_download_is_reported_and_nothing_is_built(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        fake = _FakeDiscovery(error="the portal refused the request")
        h, finder_id = _discovery_harness(client, user, token, monkeypatch, fake)
        # Even a probe that reads data does not send a downloadable row to the
        # builder as fetch code.
        monkeypatch.setattr(
            'utk_curio.backend.app.agents.application.verify.verify_external_source',
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
            "attachmentId": "f1", "coord": "agent.curio.dataset-finder@1",
            "target": {"kind": "node", "targetId": "n1"},
            dr.RECORD_KEY: {"status": status, "picks": picks},
        }]}}

    def test_only_a_landed_download_resolves(self):
        waiting = dr.acquiring_pick(
            {"name": "Areas", "sourceId": CHICAGO, "resourceId": "a"}, "job-1")
        spec = self._spec([waiting])
        assert dr.has_acquiring_picks(spec)
        assert dr.settle_acquisitions(spec, {}) == []
        assert dr.settle_acquisitions(spec, {(CHICAGO, "a"): "source.areas"}) == ["f1"]
        state = spec["dataflow"]["agentAttachments"][0][dr.RECORD_KEY]
        assert state["status"] == dr.STATE_RESOLVED
        assert not dr.has_acquiring_picks(spec)

    def test_another_pick_still_waiting_keeps_the_node_waiting(self):
        spec = self._spec([
            dr.acquiring_pick({"name": "Areas", "sourceId": CHICAGO, "resourceId": "a"}, "j1"),
            dr.acquiring_pick({"name": "Wards", "sourceId": CHICAGO, "resourceId": "b"}, "j2"),
        ])
        dr.settle_acquisitions(spec, {(CHICAGO, "a"): "source.areas"})
        state = spec["dataflow"]["agentAttachments"][0][dr.RECORD_KEY]
        assert state["status"] == dr.STATE_AWAITING_INSTALL
        assert state["picks"][0]["imported"] is True and state["picks"][1]["acquiring"]

    def test_an_installed_catalog_pick_beside_a_downloaded_one_resolves(self):
        spec = self._spec([
            {"lane": "catalog", "datasetId": "d1", "installed": False},
            dr.acquired_pick({"name": "Areas", "sourceId": CHICAGO, "resourceId": "a"}, "source.a"),
        ])
        assert dr.mark_dataset_installed(spec, "d1") == ["f1"]

    def test_the_builder_is_told_the_coordinate(self):
        spec = self._spec([{
            "lane": "external", "name": "Areas", "url": "https://x.example/a",
            "sourceId": CHICAGO, "resourceId": "a", "acquirable": True,
        }], status=dr.STATE_RESOLVED)
        pick = dr.confirmed_source(spec, "n1")["picks"][0]
        assert pick["sourceId"] == CHICAGO and pick["acquirable"] is True


def _plan_session(h) -> dict:
    """The plan's ledger and pause, as the Dataflow Builder's record holds them."""
    return dict((attachments.get_attachment(h.spec(), h.att) or {}).get("builderSession") or {})


class TestAPlanWaitsAsItsSourceDoes:
    """A loader that a plan's Build & validate found waiting for its source
    waits as its Dataset Finder's record says: for the user's pick, for its
    download into the Data Catalog, or for the install of the dataset picked.
    Its row and the pause say which. The record's resolution puts the row
    back wherever the record resolves: a download that lands, an install
    applied, a pick while a Solve session runs. A portal row's pick keeps the
    plan waiting for its import, which the Finder's chat asks the user for.
    On main the row needed a source and the pause said the Finder's chat
    asked for it whatever the record said, and only a pick that resolved the
    node at once and started no session's build put the row back."""

    @pytest.fixture(autouse=True)
    def _six_actions(self, monkeypatch):
        monkeypatch.setattr(budgets, "SIMULATE_MAX_ACTIONS", 6)

    def test_a_pick_that_downloads_says_so_and_its_landing_puts_the_row_back(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        dataset_id = routes_turns.TestDatasetFinderTools()._seed_dataset(user, filename="wards.csv")
        fake = _FakeDiscovery(started={"jobId": "job-1", "status": "queued"}, job={"status": "running"})
        roster = packages_roster._LazyRoster
        monkeypatch.setattr(packages_roster, "_LazyRoster", lambda: roster(dict(ROSTER)))
        _the_discovery_catalog_is(monkeypatch, fake)
        monkeypatch.setattr(acquire, "_DISCOVERY_APPLY_WAIT_S", 0)
        loader = f'import pandas as pd\nreturn pd.read_csv(curio_data_path("{dataset_id}"))'
        h = _Harness(client, user, token, monkeypatch, discover_replies=[DISCOVERY_CANDIDATES],
                     dl_replies=[loader])
        h.simulate("auto")
        assert h.dl_calls == [], "the loader's builder was asked before its Finder"
        picked = h.select(URL)
        assert picked["status"] == dr.STATE_AWAITING_INSTALL, picked
        assert (picked.get("delegated") or {}).get("status") == "acquiring", picked
        session = _plan_session(h)
        assert session["nodeStates"]["load"] == "awaiting-download", session
        reason = session.get("pauseReason") or {}
        assert [n.get("ref") for n in reason.get("nodes") or []] == ["load"], reason
        assert "download" in reason["message"] and "asks you" not in reason["message"], reason
        # Nothing waits for the user's pick.
        assert h.cards()[h.finder_attachment_id()]["waitsForYou"] == []
        # The download lands, and a Solve's entry reads what the account holds.
        from utk_curio.backend.app.datasets.repositories import user_store

        monkeypatch.setattr(
            user_store.UserDatasetRepository, "discovery_resource_index",
            lambda self: {(CHICAGO, "cauq-8yn6"): dataset_id},
        )
        with monkeypatch.context() as patched:
            patched.setattr(spec_reads, "_acting_user", lambda: user)
            acquire._settle_discovery_acquisitions(h.ukey, h.pid)
        assert dr.source_record(h.spec(), h.load)["status"] == dr.STATE_RESOLVED
        session = _plan_session(h)
        assert session["nodeStates"]["load"] == "created", session
        assert "pauseReason" not in session, session
        # The next Build & validate builds the loader from the dataset, once.
        tried = len(h.dl_calls)
        done = h.simulate("auto")[-1][1]
        assert done.get("status") == "completed", done
        assert len(h.dl_calls) == tried + 1
        assert f'curio_data_path("{dataset_id}")' in h.node_content(h.load)

    def _downloading(self, client, user, token, monkeypatch):
        """A plan whose loader Build & validate left waiting for its source,
        whose candidates are a row Curio downloads, and the dataset that
        download lands as. Returns ``(harness, dataset_id)``."""
        dataset_id = routes_turns.TestDatasetFinderTools()._seed_dataset(user, filename="wards.csv")
        fake = _FakeDiscovery(started={"jobId": "job-1", "status": "queued"}, job={"status": "running"})
        roster = packages_roster._LazyRoster
        monkeypatch.setattr(packages_roster, "_LazyRoster", lambda: roster(dict(ROSTER)))
        _the_discovery_catalog_is(monkeypatch, fake)
        monkeypatch.setattr(acquire, "_DISCOVERY_APPLY_WAIT_S", 0)
        loader = f'import pandas as pd\nreturn pd.read_csv(curio_data_path("{dataset_id}"))'
        h = _Harness(client, user, token, monkeypatch, discover_replies=[DISCOVERY_CANDIDATES],
                     dl_replies=[loader])
        h.simulate("auto")
        assert h.dl_calls == [], "the loader's builder was asked before its Finder"
        return h, dataset_id

    def test_a_download_picked_for_a_waiting_loader_points_at_the_builders_build(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """The loader waits in a plan whose Build & validate paused on it, so
        its plan builds it, not a Solve of the node. Nothing settles the
        download's landing by itself: the pick's answer and the Source
        recorded turn, in the Finder's chat and in the Dataflow Builder's, say
        to press Resume in the Dataflow Builder's chat once it lands, and
        never ask for a Solve of the node. On main they said "Solve the node
        once it lands", and that Solve built the loader outside its plan; on
        04d7e8c03f they said the Dataflow Builder's Build & validate builds the
        loader once it lands, which no build did by itself."""
        user, token = user_and_token
        h, _dataset_id = self._downloading(client, user, token, monkeypatch)
        picked = h.select(URL)
        delegated = picked.get("delegated") or {}
        assert delegated.get("status") == "acquiring", picked
        for said in (delegated.get("reason") or "", *[
            (h.session_turns(chat)[-1].get("text") or "") for chat in (h.finder_attachment_id(), h.att)
        ]):
            assert "Solve the node" not in said, said
            assert "once it lands, press Resume in the Dataflow Builder's chat to build the loader" in said, said

    def test_a_loader_solve_this_node_built_after_its_download_is_not_built_again(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """Once the download lands, Solve this node, from the loader's own Node
        Builder, builds the loader outside the plan that waited for it. Its
        code passed its check, so it counts as built in that plan: the row
        reads Validated, and the next Build & validate records it and builds
        nothing again. On main the row went back to Placed, and the next Build
        & validate built the loader a second time."""
        user, token = user_and_token
        h, dataset_id = self._downloading(client, user, token, monkeypatch)
        h.select(URL)
        from utk_curio.backend.app.datasets.repositories import user_store

        monkeypatch.setattr(
            user_store.UserDatasetRepository, "discovery_resource_index",
            lambda self: {(CHICAGO, "cauq-8yn6"): dataset_id},
        )
        r = client.post(
            f"/api/agents/projects/{h.pid}/attachments/{h.node_builder_attachment_id()}/solve-node",
            json={"nodeId": h.load}, headers=_auth(token),
        )
        assert r.status_code == 200, r.get_data(as_text=True)
        done = _sse_events(r)[-1][1]
        assert done.get("verdict") == "pass", done
        assert f'curio_data_path("{dataset_id}")' in h.node_content(h.load)
        built, row = len(h.dl_calls), _plan_session(h)["nodeStates"]["load"]
        done = h.simulate("auto")[-1][1]
        assert len(h.dl_calls) == built, (
            f"Build & validate built the loader again: {len(h.dl_calls) - built} more call(s) "
            f"for its code, after Solve this node left its row {row!r}"
        )
        assert row == "validated", row
        assert done.get("status") == "completed", done
        assert done["builderSession"]["nodeStates"]["load"] == "approved", done["builderSession"]

    @staticmethod
    def _catalog_row(dataset_id: str) -> str:
        return json.dumps({"datasetCandidates": {"lanes": {"external": [], "catalog": [
            {"name": "Community areas", "sourceType": "catalog", "datasetId": dataset_id},
        ]}}})

    def test_an_editors_pick_waiting_for_its_install_says_so_and_the_owners_apply_puts_the_row_back(
        self, client, db, user_and_token, tmp_curio, monkeypatch
    ):
        """Since step 5.4 the owner's own pick of a Data Catalog dataset the
        dataflow does not hold adds it at once ("Pick adds it", 11-26), so the
        pick that waits for its install is an editor's: he asks the owner, as
        his Add to project does. The pick, the plan's row and its pause say it
        waits for the install, and the owner's Apply of his request puts the
        row back. Before step 5.4 the owner's pick waited so, and the
        Finder's applied dataset.install put it back, which
        ``test_the_finders_applied_install_puts_a_waiting_row_back`` keeps."""
        from utk_curio.backend.app.projects import access
        from utk_curio.backend.tests.test_agents.test_editors_drive_agents import BOB_TOKEN, _account

        alice, alice_token = user_and_token
        bob = _account(db, "bob", "Bob", BOB_TOKEN)
        dataset_id = routes_turns.TestDatasetFinderTools()._seed_dataset(bob, filename="wards.csv")
        h = _Harness(client, alice, alice_token, monkeypatch, discover_replies=[self._catalog_row(dataset_id)])
        access.add_editor(alice, h.pid, "bob")
        # Bob drives the build: the Finder lists his Data Catalog for him.
        h.token = BOB_TOKEN
        h.simulate("auto")
        finder = h.finder_attachment_id()
        r = _select(h, finder, [{"lane": "catalog", "key": dataset_id}])
        assert r.status_code == 200, r.get_data(as_text=True)
        assert r.get_json()["status"] == dr.STATE_AWAITING_INSTALL, r.get_json()
        session = _plan_session(h)
        assert session["nodeStates"]["load"] == "awaiting-install", session
        message = (session.get("pauseReason") or {}).get("message") or ""
        assert "install" in message and "asks you" not in message, session
        # The owner applies his request: the dataset is in her dataflow.
        listed = client.get(f"/api/dataflows/{h.pid}/datasets/requests", headers=_auth(alice_token))
        assert listed.status_code == 200, listed.get_data(as_text=True)
        requests = listed.get_json()["requests"]
        assert [(r["datasetId"], r["nodeIds"]) for r in requests] == [(dataset_id, [h.load])], requests
        applied = client.post(f"/api/dataflows/{h.pid}/datasets/requests/{requests[0]['proposalId']}/apply",
                              headers=_auth(alice_token))
        assert applied.status_code == 200, applied.get_data(as_text=True)
        assert dr.source_record(h.spec(), h.load)["status"] == dr.STATE_RESOLVED
        session = _plan_session(h)
        assert session["nodeStates"]["load"] == "created", session
        assert "pauseReason" not in session, session

    def test_the_finders_applied_install_puts_a_waiting_row_back(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """A pick that waits for the install of its dataset, as an editor's
        does, is put back by the Dataset Finder's own dataset.install once
        it is applied, as it was before step 5.4."""
        from utk_curio.backend.tests.test_agents.test_dataset_discovery_routes import (
            _a_pick_that_waits_for_its_install,
        )

        user, token = user_and_token
        dataset_id = routes_turns.TestDatasetFinderTools()._seed_dataset(user, filename="wards.csv")
        h = _Harness(client, user, token, monkeypatch, discover_replies=[self._catalog_row(dataset_id)])
        h.simulate("auto")
        finder = h.finder_attachment_id()
        _a_pick_that_waits_for_its_install(h, dr.source_record(h.spec(), h.load)["discoveryId"], dataset_id)
        assert dr.source_record(h.spec(), h.load)["status"] == dr.STATE_AWAITING_INSTALL
        # The Dataset Finder's install of that dataset is applied.
        spec = spec_reads._live_spec_or_404(h.ukey, h.pid)
        record = attachments.get_attachment(spec, finder)
        part = content.make_proposal_part(
            proposal_id="finder-install", tool="dataset.install", summary="Add the areas",
            preview=dataset_id, pins={"datasetId": dataset_id},
        )
        store._store_proposal(
            h.ukey, h.pid, spec, {"attachment_id": finder, "session_id": record["sessionId"]},
            {"proposalId": "finder-install", "tool": "dataset.install", "datasetId": dataset_id,
             "summary": "Add the areas", "status": "pending"},
            part,
        )
        applied = client.post(
            f"/api/agents/projects/{h.pid}/attachments/{finder}/proposals/finder-install/apply",
            headers=_auth(token),
        )
        assert applied.status_code == 200, applied.get_data(as_text=True)
        assert dr.source_record(h.spec(), h.load)["status"] == dr.STATE_RESOLVED
        session = _plan_session(h)
        assert session["nodeStates"]["load"] == "created", session
        assert "pauseReason" not in session, session

    def test_a_portal_pick_keeps_the_plan_waiting_for_its_import(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """A portal row's file is not here until the user downloads it and
        imports it from the card: the plan keeps waiting, and the listing says
        the Finder and the chat that asked wait for the user. On main the
        listing said nobody waited, while the pause said the Finder's chat
        asked for it. The imported dataset's pick puts the row back."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        h.simulate("auto")
        finder = h.finder_attachment_id()
        monkeypatch.setattr(
            'utk_curio.backend.app.agents.application.verify.verify_external_source',
            lambda url, **k: dict(PORTAL_OBSERVATION),
        )
        body = _select(h, finder, [{"lane": "external", "key": URL}]).get_json()
        assert body["delegated"]["status"] == "manual-download", body
        session = _plan_session(h)
        assert session["nodeStates"]["load"] == "awaiting-source", session
        assert [n.get("ref") for n in (session.get("pauseReason") or {}).get("nodes") or []] == ["load"]
        cards = h.cards()
        assert {a: cards[a]["waitsForYou"] for a in (finder, h.att)} == {finder: [h.load], h.att: [h.load]}
        dataset_id = routes_turns.TestDatasetFinderTools()._seed_dataset(user, filename="wards.csv")
        body = _select(h, finder, [{"lane": "catalog", "key": dataset_id}]).get_json()
        assert body["delegated"]["status"] == "plan-waiting", body
        session = _plan_session(h)
        assert session["nodeStates"]["load"] == "created", session
        assert "pauseReason" not in session, session

    def test_a_pick_while_a_solve_session_runs_puts_the_row_back(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """The running Solve session builds the node from its pick, so the
        plan waits for it no more. On main the session's answer came before
        the plan's release: the row still needed a source, and the pause
        still named it."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        h.simulate("auto")
        finder = h.finder_attachment_id()
        monkeypatch.setattr(
            'utk_curio.backend.app.agents.application.verify.verify_external_source',
            lambda url, **k: dict(API_OBSERVATION),
        )
        monkeypatch.setattr(agent_jobs, "live_job", lambda user_key, attachment_id: _FakeJob())
        body = _select(h, finder, [{"lane": "external", "key": URL}]).get_json()
        assert body["delegated"]["status"] == "session-running", body
        session = _plan_session(h)
        assert session["nodeStates"]["load"] == "created", session
        assert "pauseReason" not in session, session


def _solve_this_node(h, attachment_id) -> dict:
    """Solve this node on the loader, from the chat of *attachment_id*, to its
    end: its done payload."""
    r = h.client.post(
        f"/api/agents/projects/{h.pid}/attachments/{attachment_id}/solve-node",
        json={"nodeId": h.load}, headers=_auth(h.token),
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    return _sse_events(r)[-1][1]


def _recorded_turns(h, attachment_id) -> list[str]:
    """The Source recorded turns the chat of *attachment_id* holds for the
    loader, which a chat that asked for its candidates is told."""
    return [
        turn.get("text") or "" for turn in h.session_turns(attachment_id)
        if (turn.get("text") or "").startswith("Source recorded for Load boundaries")
    ]


class TestTheRecordSaysWhatComesNext:
    """What comes after a pick is one sentence the server writes, the same in
    the pick's Source recorded turns and on the Finder's record (``next``),
    which a card the pick left open shows in every tab. A download says what
    builds the loader once it lands, never a build nobody starts. Review of
    #1635, B3."""

    NEXT_ALONE = "It is downloading into the Data Catalog: Solve the node once it lands."

    @pytest.fixture(autouse=True)
    def _six_actions(self, monkeypatch):
        monkeypatch.setattr(budgets, "SIMULATE_MAX_ACTIONS", 6)

    def test_a_download_no_plan_waits_on_says_to_solve_the_node_once_it_lands(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """The Dataflow Builder's Solve asked for the loader's candidates, and
        no plan waits on the loader. The user picks a row Curio downloads, and
        the download is still running: the record keeps what comes next, to
        Solve the node once it lands, and the Finder's Source recorded turn
        ends with the same words. On 04d7e8c03f the record kept no such words,
        and the card said the loader is built from it once it lands, which
        nothing did."""
        user, token = user_and_token
        fake = _FakeDiscovery(started={"jobId": "job-1", "status": "queued"}, job={"status": "running"})
        h, finder_id = _discovery_harness(client, user, token, monkeypatch, fake)
        body = _select(h, finder_id, [{"lane": "external", "key": URL}]).get_json()
        assert body["status"] == dr.STATE_AWAITING_INSTALL, body
        record = dr.source_record(h.spec(), h.load) or {}
        assert record.get("next") == self.NEXT_ALONE, record
        said = h.session_turns(finder_id)[-1].get("text") or ""
        assert said.endswith(self.NEXT_ALONE), said

    def test_a_download_a_paused_plan_waits_on_says_to_press_resume_once_it_lands(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """Build & validate paused on the loader, and the user picks a row
        Curio downloads. Nothing settles the download's landing by itself, so
        the pick's answer and the record say to press Resume in the Dataflow
        Builder's chat once it lands. On 04d7e8c03f they said the Dataflow
        Builder's Build & validate builds the loader once it lands, which no
        build did: the paused plan waited for a Resume."""
        user, token = user_and_token
        h, _dataset_id = TestAPlanWaitsAsItsSourceDoes()._downloading(client, user, token, monkeypatch)
        picked = h.select(URL)
        delegated = picked.get("delegated") or {}
        assert delegated.get("status") == "acquiring", picked
        press = "once it lands, press Resume in the Dataflow Builder's chat to build the loader"
        assert press in (delegated.get("reason") or ""), delegated
        record = dr.source_record(h.spec(), h.load) or {}
        assert press in (record.get("next") or ""), record


class TestTheAskingChatHearsWhatHappens:
    """The Source recorded turn in the chat that asked for the candidates ends
    with what comes next, as the pick's outcome is: the node's builder
    writing the loader, a portal file to import, or what the user must do.
    Review of #1635, B8."""

    def test_a_pick_that_starts_the_builder_says_it_writes_the_loader(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """Solve this node, from the loader's Node Builder, asked for the
        candidates, and no plan waits on the loader. The pick of a row code
        can fetch starts the Node Builder on it. The Node Builder's chat is
        told that it is writing the loader, and never to Solve the node. On
        04d7e8c03f it was told to Solve the node to build its loader, while the
        Node Builder was already writing it."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        node_builder = h.node_builder_attachment_id()
        assert _solve_this_node(h, node_builder).get("verdict") == "awaiting-source"
        monkeypatch.setattr(
            'utk_curio.backend.app.agents.application.verify.verify_external_source',
            lambda url, **k: dict(API_OBSERVATION),
        )
        started: list = []
        monkeypatch.setattr(
            "utk_curio.backend.app.agents.application.solve.node_solve.solve_node_stream",
            lambda *a, **k: started.append(k.get("node_id")),
        )
        body = _select(h, h.finder_attachment_id(), [{"lane": "external", "key": URL}]).get_json()
        assert (body.get("delegated") or {}).get("status") == "delegating", body
        assert started == [h.load], started
        said = _recorded_turns(h, node_builder)
        assert len(said) == 1, [t.get("text") for t in h.session_turns(node_builder)]
        assert "is writing the loader from this source" in said[0], said[0]
        assert "Solve the node to build" not in said[0], said[0]

    def test_a_portal_pick_a_plan_waits_on_says_to_import_it(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """A row's Solve of the loader asked for the candidates, and the user
        picks a portal row, whose file the user downloads and imports from the
        card. The Dataflow Builder's chat is told it is a portal download, and
        never to Solve the node. On 04d7e8c03f it was told to Solve the node to
        build its loader, which no Solve could do before the import."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch)
        h.validate("load")
        monkeypatch.setattr(
            'utk_curio.backend.app.agents.application.verify.verify_external_source',
            lambda url, **k: dict(PORTAL_OBSERVATION),
        )
        body = _select(h, h.finder_attachment_id(), [{"lane": "external", "key": URL}]).get_json()
        assert (body.get("delegated") or {}).get("status") == "manual-download", body
        said = _recorded_turns(h, h.att)
        assert len(said) == 1, [t.get("text") for t in h.session_turns(h.att)]
        assert "It is a portal download" in said[0], said[0]
        assert "Solve the node to build" not in said[0], said[0]


class TestSolveThisNodeSaysWhatItsSourceWaitsOn:
    """Solve this node on a loader whose source waits says what the source
    waits on: the user's pick, a download into the Data Catalog, or an
    install. A pick the user already made is never asked for again. Review of
    #1635, B7."""

    def test_a_loader_whose_pick_downloads_says_it_is_downloading(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """Solve this node, from the loader's Node Builder, asks for the
        candidates, and the user picks a row Curio downloads. The download is
        still running when Solve this node runs again: it waits for its
        source, says the source is downloading into the Data Catalog, never
        asks for a pick, and its answer names what the source waits on
        (``sourceWait``). On 04d7e8c03f it asked the user to pick one with Use
        this source on the card, a pick the user had already made."""
        user, token = user_and_token
        fake = _FakeDiscovery(started={"jobId": "job-1", "status": "queued"}, job={"status": "running"})
        roster = packages_roster._LazyRoster
        monkeypatch.setattr(packages_roster, "_LazyRoster", lambda: roster(dict(ROSTER)))
        _the_discovery_catalog_is(monkeypatch, fake)
        monkeypatch.setattr(acquire, "_DISCOVERY_APPLY_WAIT_S", 0)
        h = _Harness(client, user, token, monkeypatch, discover_replies=[DISCOVERY_CANDIDATES])
        node_builder = h.node_builder_attachment_id()
        assert _solve_this_node(h, node_builder).get("verdict") == "awaiting-source"
        picked = _select(h, h.finder_attachment_id(), [{"lane": "external", "key": URL}]).get_json()
        assert picked["status"] == dr.STATE_AWAITING_INSTALL and picked["picks"][0].get("acquiring"), picked
        done = _solve_this_node(h, node_builder)
        assert done.get("verdict") == "awaiting-source", done
        said = h.session_turns(node_builder)[-1].get("text") or ""
        assert "is downloading into the Data Catalog" in said, said
        assert "pick one" not in said, said
        assert done.get("sourceWait") == "download", done

    def test_a_plans_solve_on_a_loader_whose_pick_downloads_says_it_is_downloading(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """The plan's Solve asks for the loader's candidates, and the user
        picks a row Curio downloads. The download is still running when the
        plan is Solved again: the loader stays pending, and its reason says
        what Solve this node says, that the source is downloading into the
        Data Catalog, never that it awaits the user's selection. On 00b5cfca04
        its reason said "awaiting your dataset selection", of a pick the user
        had already made."""
        user, token = user_and_token
        fake = _FakeDiscovery(started={"jobId": "job-1", "status": "queued"}, job={"status": "running"})
        roster = packages_roster._LazyRoster
        monkeypatch.setattr(packages_roster, "_LazyRoster", lambda: roster(dict(ROSTER)))
        _the_discovery_catalog_is(monkeypatch, fake)
        monkeypatch.setattr(acquire, "_DISCOVERY_APPLY_WAIT_S", 0)
        h = _Harness(client, user, token, monkeypatch, discover_replies=[DISCOVERY_CANDIDATES])
        first = h.solve()["results"][h.load]
        assert first["status"] == "pending", first
        assert first["reason"].startswith("awaiting your dataset selection"), first
        picked = _select(h, h.finder_attachment_id(), [{"lane": "external", "key": URL}]).get_json()
        assert picked["status"] == dr.STATE_AWAITING_INSTALL and picked["picks"][0].get("acquiring"), picked
        again = h.solve()["results"][h.load]
        assert again["status"] == "pending", again
        assert "is downloading into the Data Catalog" in again["reason"], again
        assert "awaiting your dataset selection" not in again["reason"], again
