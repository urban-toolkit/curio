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

from utk_curio.backend.app.agents import agent_jobs
from utk_curio.backend.app.agents import dataset_resolution as dr
from utk_curio.backend.tests.test_agents import test_routes as _tr
from utk_curio.backend.tests.test_agents.test_dataset_discovery_routes import _Harness

_auth = _tr._auth

DATA_OBSERVATION = {
    "status": "verified", "httpStatus": 200, "contentType": "application/geo+json",
    "sampleKeys": ["features", "type"], "checkedAt": "now",
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
            lambda url, **k: dict(DATA_OBSERVATION),
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
            lambda url, **k: dict(DATA_OBSERVATION),
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
