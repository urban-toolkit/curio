"""The Data Lake Catalog's HTTP surface.

None of these routes makes an outbound request - the roster is served from
disk. That is deliberate and worth asserting: it means the catalog renders,
and a source can be inspected, on a deployment with no egress at all.
"""

from __future__ import annotations

import pytest

from utk_curio.backend.tests.test_datalakes.conftest import (
    TINY_PNG,
    a_manifest,
    write_source,
)


@pytest.fixture()
def auth(user_and_token):
    _user, token = user_and_token
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def seeded(lake_root):
    write_source(lake_root, "lake.a.portal@1", a_manifest(
        id="lake.a.portal", name="Alpha Portal", icon="icon.png",
        provider={"type": "socrata", "baseUrl": "https://alpha.example"},
        auth={"mode": "optional-token", "secretId": "socrata.app-token",
              "headerName": "X-App-Token", "helpUrl": "https://help.example"}),
        icon=TINY_PNG)
    write_source(lake_root, "lake.b.plain@1", a_manifest(
        id="lake.b.plain", name="Beta Plain"))
    return lake_root


class TestAuthIsRequired:
    @pytest.mark.parametrize(
        "path",
        [
            "/api/datalakes/catalog",
            "/api/datalakes/sources/lake.a.portal@1",
            "/api/datalakes/sources/lake.a.portal@1/icon",
        ],
    )
    def test_without_a_token(self, client, seeded, path):
        assert client.get(path).status_code == 401


class TestCatalogRoute:
    def test_it_lists_sources_and_facets(self, client, auth, seeded):
        res = client.get("/api/datalakes/catalog", headers=auth)
        assert res.status_code == 200
        body = res.get_json()
        assert [s["sourceId"] for s in body["sources"]] == ["lake.a.portal", "lake.b.plain"]
        assert body["facets"]["provider"] == {"ckan": 1, "socrata": 1}

    def test_query_parameters_filter(self, client, auth, seeded):
        res = client.get("/api/datalakes/catalog?provider=ckan", headers=auth)
        assert [s["sourceId"] for s in res.get_json()["sources"]] == ["lake.b.plain"]
        res = client.get("/api/datalakes/catalog?q=alpha", headers=auth)
        assert [s["sourceId"] for s in res.get_json()["sources"]] == ["lake.a.portal"]

    def test_an_icon_url_is_served_only_when_there_is_a_file(self, client, auth, seeded):
        rows = {s["sourceId"]: s for s in client.get("/api/datalakes/catalog", headers=auth).get_json()["sources"]}
        assert rows["lake.a.portal"]["iconUrl"].endswith("/sources/lake.a.portal@1/icon")
        assert rows["lake.b.plain"]["iconUrl"] is None

    def test_no_response_field_carries_a_credential(self, client, auth, seeded):
        auth_block = client.get("/api/datalakes/catalog", headers=auth).get_json()["sources"][0]["auth"]
        assert auth_block == {
            "mode": "optional-token",
            "required": False,
            "usesToken": True,
            "secretId": "socrata.app-token",   # the SLOT name, not a value
            "present": False,
            "helpUrl": "https://help.example",
        }


class TestSourceRoute:
    def test_it_returns_one_source(self, client, auth, seeded):
        res = client.get("/api/datalakes/sources/lake.a.portal@1", headers=auth)
        assert res.status_code == 200
        assert res.get_json()["name"] == "Alpha Portal"

    def test_an_unknown_source_is_404(self, client, auth, seeded):
        assert client.get("/api/datalakes/sources/lake.no.such@1", headers=auth).status_code == 404

    @pytest.mark.parametrize("bad", ["..%2f..%2fetc", "lake.a.portal", "nonsense"])
    def test_a_malformed_name_is_404_not_500(self, client, auth, seeded, bad):
        assert client.get(f"/api/datalakes/sources/{bad}", headers=auth).status_code == 404


class TestIconRoute:
    def test_it_serves_the_png(self, client, auth, seeded):
        res = client.get("/api/datalakes/sources/lake.a.portal@1/icon", headers=auth)
        assert res.status_code == 200
        assert res.data.startswith(b"\x89PNG\r\n\x1a\n")

    def test_the_content_type_is_fixed_by_the_route_and_not_sniffable(self, client, auth, seeded):
        """Whatever the bytes are, the browser is told exactly one thing and
        told not to second-guess it."""
        res = client.get("/api/datalakes/sources/lake.a.portal@1/icon", headers=auth)
        assert res.mimetype == "image/png"
        assert res.headers["X-Content-Type-Options"] == "nosniff"
        assert res.headers["Content-Disposition"] == "inline"

    def test_it_carries_a_stable_etag(self, client, auth, seeded):
        first = client.get("/api/datalakes/sources/lake.a.portal@1/icon", headers=auth)
        second = client.get("/api/datalakes/sources/lake.a.portal@1/icon", headers=auth)
        assert first.headers["ETag"] and first.headers["ETag"] == second.headers["ETag"]

    def test_the_etag_changes_when_the_file_does(self, client, auth, seeded):
        before = client.get("/api/datalakes/sources/lake.a.portal@1/icon", headers=auth).headers["ETag"]
        (seeded / "lake.a.portal@1" / "icon.png").write_bytes(TINY_PNG + b"\x00" * 16)
        after = client.get("/api/datalakes/sources/lake.a.portal@1/icon", headers=auth).headers["ETag"]
        assert before != after

    def test_a_source_with_no_icon_is_404(self, client, auth, seeded):
        """So the client renders the shared lake glyph instead."""
        assert client.get("/api/datalakes/sources/lake.b.plain@1/icon", headers=auth).status_code == 404

    def test_a_named_but_missing_file_is_404_too(self, client, auth, lake_root):
        """A deleted icon costs a logo, not a page."""
        write_source(lake_root, "lake.c.gone@1", a_manifest(id="lake.c.gone", icon="icon.png"))
        assert client.get("/api/datalakes/sources/lake.c.gone@1/icon", headers=auth).status_code == 404

    def test_an_oversized_icon_is_refused(self, client, auth, lake_root):
        from utk_curio.backend.app.datalakes.routes import MAX_ICON_BYTES

        write_source(lake_root, "lake.d.big@1", a_manifest(id="lake.d.big", icon="icon.png"),
                     icon=TINY_PNG + b"\x00" * MAX_ICON_BYTES)
        assert client.get("/api/datalakes/sources/lake.d.big@1/icon", headers=auth).status_code == 404

    def test_a_traversing_icon_value_never_reaches_the_filesystem(self, client, auth, lake_root, tmp_path):
        """The manifest validator refuses the path, so the source does not load
        at all - the icon route is the second line, not the first."""
        secret = tmp_path / "secret.png"
        secret.write_bytes(b"\x89PNG\r\n\x1a\nsecret")
        write_source(lake_root, "lake.e.evil@1", a_manifest(
            id="lake.e.evil", icon="../../secret.png"))
        assert client.get("/api/datalakes/sources/lake.e.evil@1", headers=auth).status_code == 404
        assert client.get("/api/datalakes/sources/lake.e.evil@1/icon", headers=auth).status_code == 404
        # And the source is invisible in the roster rather than half-broken.
        listed = client.get("/api/datalakes/catalog", headers=auth).get_json()["sources"]
        assert "lake.e.evil" not in [s["sourceId"] for s in listed]


class TestTheRosterNeedsNoNetwork:
    def test_listing_and_reading_make_no_outbound_request(self, client, auth, seeded):
        """Asserted rather than assumed. The socket guard would already fail
        the test if a request were made, so this documents the property and
        pins it against a future refactor that resolves something eagerly."""
        assert client.get("/api/datalakes/catalog", headers=auth).status_code == 200
        assert client.get("/api/datalakes/sources/lake.a.portal@1", headers=auth).status_code == 200
        assert client.get("/api/datalakes/sources/lake.a.portal@1/icon", headers=auth).status_code == 200
