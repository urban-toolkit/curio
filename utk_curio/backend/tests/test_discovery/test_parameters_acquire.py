"""Declared parameters end to end: the manifest's rule, the providers' URLs, the
rows that offer them, and what a download with answers records and holds.

The routes run against the recorded corpus, as in ``test_acquire.py``.
"""
from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from utk_curio.backend.app.discovery.domain import manifest as M
from utk_curio.backend.app.discovery.domain.manifest import load_source_manifest
from utk_curio.backend.app.discovery.domain.parameters import ParameterError
from utk_curio.backend.app.discovery.providers import build_provider
from utk_curio.backend.app.discovery.providers import socrata as socrata_mod
from utk_curio.backend.app.discovery.providers.wfs import _wfs_bbox
from utk_curio.backend.tests.test_discovery.conftest import SHIPPED_ROOT, a_manifest
from utk_curio.backend.tests.test_discovery.test_acquire import (
    CHICAGO,
    GEOSAMPA,
    acquire,
    wait_for,
)

LOOP = [-87.64, 41.875, -87.62, 41.89]
SAO_PAULO = [-46.66, -23.57, -46.62, -23.54]
AREA = {"id": "area", "type": "area", "label": "Area", "accepts": ["box"]}


@pytest.fixture()
def auth(user_and_token):
    _user, token = user_and_token
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def live(app, shipped_root, fixture_corpus):
    return app


class TestTheManifestRule:
    """A source may declare only the parameters its provider reads."""

    def test_socrata_and_wfs_read_an_area(self):
        for kind, base in (("socrata", "https://portal.example"), ("wfs", "https://ows.example/ows")):
            parsed = M._parse_manifest(
                a_manifest(provider={"type": kind, "baseUrl": base}, parameters=[AREA]),
                where="manifest.json",
            )
            assert [p.id for p in parsed.parameters] == ["area"]

    def test_a_provider_that_reads_none_takes_none(self):
        with pytest.raises(M.ManifestError, match="a ckan source reads no parameter named area; it takes none"):
            M._parse_manifest(
                a_manifest(provider={"type": "ckan", "baseUrl": "https://ckan.example"}, parameters=[AREA]),
                where="manifest.json",
            )

    def test_an_id_the_provider_does_not_read_is_refused(self):
        link = {"id": "link", "type": "url", "label": "Link"}
        with pytest.raises(M.ManifestError, match="reads no parameter named link; it reads area"):
            M._parse_manifest(
                a_manifest(provider={"type": "socrata", "baseUrl": "https://portal.example"}, parameters=[link]),
                where="manifest.json",
            )

    def test_the_shipped_portals_that_can_narrow_by_area_declare_it(self):
        for dir_name in (CHICAGO, GEOSAMPA):
            manifest = load_source_manifest(SHIPPED_ROOT / dir_name)
            assert [p.id for p in manifest.parameters] == ["area"], dir_name


class TestTheProvidersURLs:
    def test_wfs_puts_latitude_first_for_2_0_and_1_1(self):
        assert _wfs_bbox(LOOP, "2.0.0") == "41.875,-87.64,41.89,-87.62,urn:ogc:def:crs:EPSG::4326"
        assert _wfs_bbox(LOOP, "1.1.0") == "41.875,-87.64,41.89,-87.62,urn:ogc:def:crs:EPSG::4326"

    def test_wfs_puts_longitude_first_for_1_0(self):
        assert _wfs_bbox(LOOP, "1.0.0") == "-87.64,41.875,-87.62,41.89"

    def test_a_wfs_download_carries_the_bbox(self):
        from utk_curio.backend.tests.test_discovery.test_providers import _provider

        provider, _, _ = _provider(GEOSAMPA)
        url = provider.download_url("geoportal:bicicletario_paraciclo", "geojson",
                                    values={"area": {"box": SAO_PAULO}}).url
        assert parse_qs(urlsplit(url).query)["bbox"] == ["-23.57,-46.66,-23.54,-46.62,urn:ogc:def:crs:EPSG::4326"]

    def test_a_socrata_download_keeps_the_rows_inside_the_box(self):
        from utk_curio.backend.tests.test_discovery.test_providers import _provider

        provider, _, _ = _provider(CHICAGO)
        url = provider.download_url("ijzp-q8t2", "csv", values={"area": {"box": LOOP}}).url
        query = parse_qs(urlsplit(url).query)
        assert query["$where"] == ["within_box(location, 41.89, -87.64, 41.875, -87.62)"]
        assert query["$limit"] == [str(socrata_mod.EXPORT_LIMIT)]

    def test_a_shape_column_is_tested_with_intersects(self):
        assert socrata_mod._shape_clause("the_geom", LOOP) == (
            "intersects(the_geom, 'POLYGON((-87.64 41.875, -87.62 41.875, -87.62 41.89, "
            "-87.64 41.89, -87.64 41.875))')"
        )

    def test_a_dataset_without_a_location_column_refuses_an_area(self):
        manifest = load_source_manifest(SHIPPED_ROOT / CHICAGO)

        class _NoGeometry:
            def json_get(self, url, **_):
                return {"columns": [{"fieldName": "name", "dataTypeName": "text"}]}

        provider = build_provider(manifest, _NoGeometry())
        with pytest.raises(ParameterError, match="has no location column"):
            provider.download_url("abcd-1234", "csv", values={"area": {"box": LOOP}})

    def test_a_column_name_is_checked_before_it_enters_the_query(self):
        manifest = load_source_manifest(SHIPPED_ROOT / CHICAGO)

        class _HostileName:
            def json_get(self, url, **_):
                return {"columns": [{"fieldName": "x) OR (1=1", "dataTypeName": "point"}]}

        provider = build_provider(manifest, _HostileName())
        with pytest.raises(ParameterError):
            provider.download_url("abcd-1234", "csv", values={"area": {"box": LOOP}})


class TestRowsOfferWhatApplies:
    def test_a_socrata_row_with_a_location_column_offers_an_area(self, client, auth, live):
        rows = client.get(f"/api/discovery/sources/{CHICAGO}/search?q=crimes", headers=auth).get_json()["resources"]
        crimes = next(r for r in rows if r["resourceId"] == "ijzp-q8t2")
        assert [p["id"] for p in crimes["parameters"]] == ["area"]
        assert crimes["parameters"][0]["accepts"] == ["box"]

    def test_the_source_row_lists_its_parameters(self, client, auth, live):
        row = client.get(f"/api/discovery/sources/{GEOSAMPA}", headers=auth).get_json()
        assert [p["id"] for p in row["parameters"]] == ["area"]


class TestADownloadWithAnswers:
    def test_the_answers_are_checked_before_a_job_exists(self, client, auth, live):
        res = acquire(client, auth, CHICAGO, "ijzp-q8t2", format="csv", parameters={"radius": 5})
        assert res.status_code == 400
        assert "no parameter named radius" in res.get_json()["error"]
        res = acquire(client, auth, CHICAGO, "ijzp-q8t2", format="csv",
                      parameters={"area": {"box": [-87.62, 41.875, -87.64, 41.89]}})
        assert res.status_code == 400

    def test_the_dataset_records_them_and_an_identical_add_finds_it_held(self, client, auth, live):
        answers = {"area": {"box": LOOP, "label": "The Loop"}}
        job = wait_for(client, auth, acquire(client, auth, CHICAGO, "ijzp-q8t2", format="csv",
                                             parameters=answers).get_json()["jobId"])
        assert job["status"] == "completed", job
        block = job["dataset"]["discoverySource"]
        assert block["parameters"] == {"area": {"box": LOOP, "label": "The Loop"}}
        assert len(block["parametersHash"]) == 16
        assert "within_box" in unquote(block["resourceUrl"])

        again = acquire(client, auth, CHICAGO, "ijzp-q8t2", format="csv",
                        parameters={"area": {"box": LOOP, "label": "Chicago Loop"}})
        assert again.status_code == 200
        assert again.get_json()["alreadyPresent"] is True
        assert again.get_json()["dataset"]["id"] == job["dataset"]["id"]

    def test_the_whole_dataset_and_a_part_of_it_are_two_datasets(self, client, auth, live):
        whole = wait_for(client, auth, acquire(client, auth, CHICAGO, "ijzp-q8t2", format="csv").get_json()["jobId"])
        part = acquire(client, auth, CHICAGO, "ijzp-q8t2", format="csv", parameters={"area": {"box": LOOP}})
        assert part.status_code == 202, "a part is not held because the whole is"
        part_job = wait_for(client, auth, part.get_json()["jobId"])
        assert part_job["dataset"]["id"] != whole["dataset"]["id"]

    def test_a_part_does_not_mark_the_row_held(self, client, auth, live):
        wait_for(client, auth, acquire(client, auth, CHICAGO, "ijzp-q8t2", format="csv",
                                       parameters={"area": {"box": LOOP}}).get_json()["jobId"])
        rows = client.get(f"/api/discovery/sources/{CHICAGO}/search?q=crimes", headers=auth).get_json()["resources"]
        crimes = next(r for r in rows if r["resourceId"] == "ijzp-q8t2")
        assert crimes["heldFormats"] == {} and crimes["alreadyHeldDatasetId"] is None


class TestHeldIsPerFormat:
    """#477: holding one format of a row is not holding the others."""

    def test_a_csv_download_marks_only_csv_held(self, client, auth, live):
        job = wait_for(client, auth, acquire(client, auth, CHICAGO, "ijzp-q8t2", format="csv").get_json()["jobId"])
        rows = client.get(f"/api/discovery/sources/{CHICAGO}/search?q=crimes", headers=auth).get_json()["resources"]
        crimes = next(r for r in rows if r["resourceId"] == "ijzp-q8t2")
        assert crimes["heldFormats"] == {"csv": job["dataset"]["id"]}
        assert "geojson" in crimes["formats"] and "geojson" not in crimes["heldFormats"]
