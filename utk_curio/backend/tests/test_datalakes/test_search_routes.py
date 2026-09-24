"""The live search and describe routes, driven through the recorded corpus.

These exercise the REAL backend stack - route, service, browse, provider,
parsing - with only the socket replaced. That is the point of the fixture
transport: a route test that stubbed the service would prove the route calls
something, not that a search works.
"""

from __future__ import annotations

import pytest


@pytest.fixture()
def auth(user_and_token):
    _user, token = user_and_token
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def live(app, shipped_root, fixture_corpus):
    """The shipped sources, answered from the recorded corpus."""
    return app


class TestScopedSearch:
    def test_it_returns_rows_from_the_portal(self, client, auth, live):
        res = client.get(
            "/api/datalakes/sources/lake.cityofchicago.data-portal@1/search?q=crimes",
            headers=auth,
        )
        assert res.status_code == 200
        body = res.get_json()
        assert body["resources"], body
        first = body["resources"][0]
        assert first["resourceId"] == "ijzp-q8t2"
        assert "Crimes" in first["name"]
        assert first["sourceName"] == "City of Chicago Data Portal"

    def test_the_row_shape_is_the_allowlist(self, client, auth, live):
        res = client.get(
            "/api/datalakes/sources/lake.saopaulo.geosampa@1/search?q=ciclo&limit=3",
            headers=auth,
        )
        row = res.get_json()["resources"][0]
        assert set(row) == {
            "sourceId", "sourceName", "resourceId", "name", "description",
            "publisher", "formats", "updatedAt", "landingUrl", "sizeHint",
            "acquirable", "alreadyHeldDatasetId",
        }

    def test_a_source_that_cannot_search_says_so(self, client, auth, live):
        res = client.get(
            "/api/datalakes/sources/lake.curio.direct-url@1/search?q=x", headers=auth
        )
        assert res.status_code == 400
        assert "nothing to browse" in res.get_json()["error"]

    def test_an_unknown_source_is_404(self, client, auth, live):
        res = client.get("/api/datalakes/sources/lake.no.such@1/search?q=x", headers=auth)
        assert res.status_code == 404

    def test_limit_is_clamped_rather_than_trusted(self, client, auth, live):
        res = client.get(
            "/api/datalakes/sources/lake.saopaulo.geosampa@1/search?q=ciclo&limit=99999",
            headers=auth,
        )
        assert res.status_code == 200
        assert len(res.get_json()["resources"]) <= 50

    def test_a_junk_limit_falls_back_to_the_default(self, client, auth, live):
        res = client.get(
            "/api/datalakes/sources/lake.saopaulo.geosampa@1/search?q=ciclo&limit=abc",
            headers=auth,
        )
        assert res.status_code == 200


class TestFederatedSearch:
    def test_it_answers_from_several_portals_with_per_source_status(self, client, auth, live):
        res = client.get("/api/datalakes/search?q=ciclo&limit=10", headers=auth)
        assert res.status_code == 200
        body = res.get_json()
        statuses = {s["sourceId"]: s["status"] for s in body["sources"]}
        assert statuses["lake.saopaulo.geosampa"] == "ok"
        assert statuses["lake.curio.direct-url"] == "unsupported"
        assert body["resources"]

    def test_a_failing_leg_gives_200_and_the_other_portals_rows(self, client, auth, live):
        """The property that matters most: one portal having a bad afternoon
        must not turn into our 502."""
        res = client.get("/api/datalakes/search?q=ciclo", headers=auth)
        assert res.status_code == 200
        body = res.get_json()
        assert any(s["status"] != "ok" for s in body["sources"]), "expected a failing leg"
        assert body["resources"], "the working portals' rows must survive"

    def test_rows_carry_the_name_of_the_portal_they_came_from(self, client, auth, live):
        body = client.get("/api/datalakes/search?q=ciclo", headers=auth).get_json()
        assert all(r["sourceName"] for r in body["resources"])

    def test_a_fan_out_offers_no_cursor(self, client, auth, live):
        """Five portals paginate independently; interleaving past page one would
        repeat and drop rows. Narrow to one source to page."""
        body = client.get("/api/datalakes/search?q=ciclo", headers=auth).get_json()
        assert body["nextCursor"] is None

    def test_a_provider_filter_narrows_the_fan_out(self, client, auth, live):
        body = client.get("/api/datalakes/search?q=ciclo&provider=wfs", headers=auth).get_json()
        assert {s["sourceId"] for s in body["sources"]} == {"lake.saopaulo.geosampa"}

    def test_an_empty_query_is_refused_rather_than_fanning_out(self, client, auth, live):
        res = client.get("/api/datalakes/search?q=%20%20", headers=auth)
        assert res.status_code == 400


class TestDescribe:
    def test_it_returns_the_field_list(self, client, auth, live):
        res = client.get(
            "/api/datalakes/sources/lake.cityofchicago.data-portal@1/resources/ijzp-q8t2",
            headers=auth,
        )
        assert res.status_code == 200
        body = res.get_json()
        assert body["resourceId"] == "ijzp-q8t2"
        assert any(f["name"] == "case_number" for f in body["fields"])

    def test_a_wfs_layer_reports_its_crs(self, client, auth, live):
        res = client.get(
            "/api/datalakes/sources/lake.saopaulo.geosampa@1/resources/"
            "geoportal%3Abicicletario_paraciclo",
            headers=auth,
        )
        assert res.status_code == 200
        assert res.get_json()["extra"].get("crs")

    def test_a_malformed_resource_id_is_404(self, client, auth, live):
        res = client.get(
            "/api/datalakes/sources/lake.cityofchicago.data-portal@1/resources/not-a-4x4",
            headers=auth,
        )
        assert res.status_code == 404


class TestAuthAndLimits:
    @pytest.mark.parametrize(
        "path",
        [
            "/api/datalakes/search?q=x",
            "/api/datalakes/sources/lake.cityofchicago.data-portal@1/search?q=x",
            "/api/datalakes/sources/lake.cityofchicago.data-portal@1/resources/ijzp-q8t2",
        ],
    )
    def test_every_live_route_needs_a_token(self, client, live, path):
        assert client.get(path).status_code == 401

    def test_exhausting_the_bucket_is_a_429(self, client, auth, live):
        from utk_curio.backend.app.datalakes.infrastructure import ratelimit

        for _ in range(40):
            res = client.get(
                "/api/datalakes/sources/lake.saopaulo.geosampa@1/search?q=ciclo",
                headers=auth,
            )
            if res.status_code == 429:
                break
        else:
            pytest.fail("the rate limiter never engaged")
        assert "per minute" in res.get_json()["error"]
