"""Mapillary: a service asked over HTTP, whose images land as one collection.

The provider's request shapes run against small stand-in transports. The
whole add runs against the recorded corpus (``fixtures/mapillary``), whose
image URLs are indexed to a synthetic JPEG, so no photo of Mapillary's is in
the repository and no test opens a socket.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from utk_curio.backend.app.discovery.domain import manifest as M
from utk_curio.backend.app.discovery.domain.errors import DiscoveryError, ProviderError
from utk_curio.backend.app.discovery.domain.manifest import load_source_manifest
from utk_curio.backend.app.discovery.infrastructure.transport import FixtureDiscoveryTransport
from utk_curio.backend.app.discovery.providers import build_service, mapillary
from utk_curio.backend.tests.test_discovery.conftest import FIXTURES, SHIPPED_ROOT, a_manifest
from utk_curio.backend.tests.test_discovery.test_acquire import acquire, wait_for

SOURCE = "source.mapillary.imagery@1"
LINCOLN_PARK = {"box": [-87.642, 41.918, -87.639, 41.92], "label": "Lincoln Park"}
#: What the recorded corpus was asked; see SERVICE_PLAN in the recorder.
RECORDED = {"area": LINCOLN_PARK, "size": "256", "maxImages": 6}
SECRET = "MLY|1234567890|s3cr3t-mapillary-value"


@pytest.fixture()
def auth(user_and_token):
    _user, token = user_and_token
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def live(app, shipped_root, fixture_corpus):
    return app


@pytest.fixture()
def keyed(client, auth, live):
    """An account that saved a Mapillary token in API Settings."""
    res = client.patch("/api/auth/me", headers=auth, json={"mapillary_access_token": SECRET})
    assert res.status_code == 200, res.get_data(as_text=True)
    return auth


def _manifest():
    return load_source_manifest(SHIPPED_ROOT / SOURCE)


class _Answers:
    """A transport that answers searches from a function and records each URL."""

    def __init__(self, answer):
        self.answer = answer
        self.urls: list[str] = []
        self.downloads: list[str] = []

    def json_get(self, url, *, credential=None, headers=None):
        self.urls.append(url)
        return json.dumps(self.answer(url))

    def download(self, url, sink, *, max_bytes, credential=None, headers=None, progress=None, ceiling=None):
        self.downloads.append(url)
        sink(b"\xff\xd8\xff\xd9")
        return type("R", (), {"final_url": url})()


def _bbox_of(url: str) -> list[float]:
    return [float(v) for v in parse_qs(urlsplit(url).query)["bbox"][0].split(",")]


# ── the manifest ───────────────────────────────────────────────────────────


def _mapillary(**overrides):
    raw = a_manifest(
        provider={"type": "mapillary", "baseUrl": "https://graph.mapillary.com",
                  "options": {"imageHosts": ["fbcdn.net"]}},
        auth={"mode": "required-token", "secretId": "mapillary.token",
              "headerName": "Authorization", "valuePrefix": "OAuth "},
        resources=[{"id": "images", "name": "Images", "kind": "images",
                    "options": {"endpoint": "images"},
                    "parameters": [{"id": "area", "type": "area", "label": "Area", "required": True}]}],
    )
    raw.pop("capabilities", None)
    raw.update(overrides)
    return raw


class TestTheManifest:
    def test_the_shipped_source_is_a_service_of_images_and_points(self):
        manifest = _manifest()
        assert manifest.is_service and manifest.provider.type == "mapillary"
        assert [(r.id, r.kind, r.dataset_format) for r in manifest.resources] == [
            ("images", "images", "collection"), ("map-features", "table", "geojson"),
        ]
        assert manifest.auth.secret_id == "mapillary.token" and manifest.auth.needs_token

    def test_it_lists_the_hosts_its_images_come_from(self, tmp_path):
        raw = _mapillary(provider={"type": "mapillary", "baseUrl": "https://graph.mapillary.com"})
        with pytest.raises(M.ManifestError, match="imageHosts"):
            M._parse_manifest(raw, where="manifest.json")

    def test_an_images_resource_has_no_format(self):
        raw = _mapillary()
        raw["resources"][0]["format"] = "geojson"
        with pytest.raises(M.ManifestError, match="land as a collection"):
            M._parse_manifest(raw, where="manifest.json")

    def test_each_kind_asks_its_own_endpoint(self):
        raw = _mapillary()
        raw["resources"][0]["options"] = {"endpoint": "map_features"}
        with pytest.raises(M.ManifestError, match="endpoint must be 'images'"):
            M._parse_manifest(raw, where="manifest.json")

    def test_a_parameter_it_does_not_read_is_refused(self):
        raw = _mapillary()
        raw["resources"][0]["parameters"].append({"id": "zoom", "type": "integer", "label": "Zoom"})
        with pytest.raises(M.ManifestError, match="reads no parameter named zoom"):
            M._parse_manifest(raw, where="manifest.json")

    def test_the_parameters_are_what_the_provider_reads(self):
        assert M.PROVIDER_PARAMETER_IDS["mapillary"] == mapillary.PARAMETER_IDS


# ── searching ──────────────────────────────────────────────────────────────


class TestTheBoxIsTiled:
    def test_a_small_box_is_one_search(self):
        assert mapillary.cells([-87.642, 41.918, -87.639, 41.92]) == [[-87.642, 41.918, -87.639, 41.92]]

    def test_a_large_box_becomes_cells_under_mapillarys_bound(self):
        box = [-87.75, 41.80, -87.55, 41.95]
        parts = mapillary.cells(box)
        assert len(parts) > 1
        for west, south, east, north in parts:
            assert (east - west) * (north - south) <= mapillary.MAX_CELL_SQ_DEG + 1e-9
        assert min(p[0] for p in parts) == box[0] and max(p[2] for p in parts) == box[2]
        assert min(p[1] for p in parts) == box[1] and max(p[3] for p in parts) == box[3]
        area = sum((p[2] - p[0]) * (p[3] - p[1]) for p in parts)
        assert area == pytest.approx((box[2] - box[0]) * (box[3] - box[1]), rel=1e-6)

    def test_a_cell_that_answers_its_most_is_split_in_four(self):
        first = [-87.642, 41.918, -87.639, 41.92]

        def answer(url):
            if _bbox_of(url) == first:
                return {"data": [{"id": str(i)} for i in range(mapillary.SEARCH_LIMIT)]}
            return {"data": [{"id": f"q{_bbox_of(url)[0]}{_bbox_of(url)[1]}"}]}

        transport = _Answers(answer)
        service = mapillary.MapillaryService(_manifest(), transport=transport)
        groups = service._search("images", first, {"fields": "id"}, None)
        assert len(transport.urls) == 5
        assert [len(g) for g in groups] == [1, 1, 1, 1]
        quarters = [_bbox_of(u) for u in transport.urls[1:]]
        assert quarters == mapillary.quarters(first)

    def test_splitting_stops(self):
        transport = _Answers(lambda url: {"data": [{"id": str(i)} for i in range(mapillary.SEARCH_LIMIT)]})
        service = mapillary.MapillaryService(_manifest(), transport=transport)
        groups = service._search("images", [-87.642, 41.918, -87.639, 41.92], {}, None)
        assert len(groups) == 4 ** mapillary.MAX_SPLITS
        assert len(transport.urls) == sum(4 ** d for d in range(mapillary.MAX_SPLITS + 1))


class TestTheImagesKept:
    def test_they_come_from_each_cell_in_turn_newest_first(self):
        a = [{"id": "a1", "captured_at": 1}, {"id": "a2", "captured_at": 3}]
        b = [{"id": "b1", "captured_at": 2}]
        assert [r["id"] for r in mapillary.MapillaryService.spread([a, b], 3)] == ["a2", "b1", "a1"]

    def test_an_image_in_two_cells_is_kept_once(self):
        a = [{"id": "x", "captured_at": 5}, {"id": "a", "captured_at": 1}]
        b = [{"id": "x", "captured_at": 5}, {"id": "b", "captured_at": 2}]
        assert [r["id"] for r in mapillary.MapillaryService.spread([a, b], 10)] == ["x", "a", "b"]

    def test_the_answers_narrow_the_search(self):
        service = mapillary.MapillaryService(_manifest(), transport=None)
        filters = service._image_filters({
            "imageType": "panoramas", "captured": {"start": "2023-01-01", "end": "2023-12-31"},
        })
        assert filters["is_pano"] == "true"
        assert filters["start_captured_at"] == "2023-01-01T00:00:00Z"
        assert filters["end_captured_at"] == "2023-12-31T23:59:59Z"
        assert service._image_filters({"imageType": "flat"})["is_pano"] == "false"
        assert "is_pano" not in service._image_filters({"imageType": "all"})

    def test_a_search_asks_no_thumbnail(self):
        """Signed thumbnail URLs would double an answer past the catalog's
        metadata ceiling; they are looked up for the images kept only."""
        assert "thumb" not in mapillary.IMAGE_FIELDS


class TestTheImageHosts:
    @pytest.mark.parametrize("url, ok", [
        ("https://scontent-ord5-1.xx.fbcdn.net/m1/v/t6/x.jpg", True),
        ("https://fbcdn.net/x.jpg", True),
        ("https://evilfbcdn.net/x.jpg", False),
        ("https://fbcdn.net.evil.example/x.jpg", False),
        ("https://graph.mapillary.com/x.jpg", False),
    ])
    def test_a_host_or_a_subdomain_of_one(self, url, ok):
        assert mapillary.host_allowed(url, ("fbcdn.net",)) is ok

    def test_an_image_off_the_listed_hosts_is_skipped(self, tmp_path):
        def answer(url):
            query = parse_qs(urlsplit(url).query)
            if "image_ids" in query:
                return {"data": [
                    {"id": "1", "thumb_256_url": "https://scontent.xx.fbcdn.net/1.jpg"},
                    {"id": "2", "thumb_256_url": "https://elsewhere.example/2.jpg"},
                ]}
            return {"data": [{"id": "1", "captured_at": 2}, {"id": "2", "captured_at": 1}]}

        transport = _Answers(answer)
        service = mapillary.MapillaryService(_manifest(), transport=transport)
        spec = _manifest().resource("images")
        answer_ = service.load(spec, {"area": LINCOLN_PARK, "size": "256", "maxImages": 5}, tmp_path)
        assert [i.image_id for i in answer_.images] == ["1"] and answer_.skipped == 1
        assert transport.downloads == ["https://scontent.xx.fbcdn.net/1.jpg"]

    def test_a_redirect_off_them_is_refused(self, tmp_path):
        class Redirected(_Answers):
            def download(self, url, sink, **kwargs):
                sink(b"\xff\xd8")
                return type("R", (), {"final_url": "https://elsewhere.example/1.jpg"})()

        transport = Redirected(lambda url: {"data": [{"id": "1", "thumb_256_url": "https://x.fbcdn.net/1.jpg"}]})
        service = mapillary.MapillaryService(_manifest(), transport=transport)
        with pytest.raises(ProviderError, match="redirected off"):
            service.load(_manifest().resource("images"),
                         {"area": LINCOLN_PARK, "size": "256", "maxImages": 1}, tmp_path)
        assert not list(tmp_path.rglob("*.jpg"))


class TestTheRecordedCorpus:
    def test_it_answers_what_the_app_asks(self, tmp_path):
        service = build_service(_manifest(), FixtureDiscoveryTransport(FIXTURES))
        answer = service.load(_manifest().resource("images"), RECORDED, tmp_path)
        assert len(answer.images) == 6
        first = answer.images[0]
        assert first.path.is_file() and first.relpath == f"images/{first.image_id}.jpg"
        columns = first.columns
        assert columns["creator"] and columns["mapillary_url"].endswith(first.image_id)
        assert -87.643 < columns["gps_lon"] < -87.638 and 41.917 < columns["gps_lat"] < 41.921
        assert columns["captured_at"].year >= 2010

    def test_it_holds_no_token(self):
        recorded = [p for p in (FIXTURES / "mapillary").iterdir()]
        assert recorded
        index = json.loads((FIXTURES / "index.json").read_text(encoding="utf-8"))
        mine = {url: entry for url, entry in index.items() if "mapillary" in url or "fbcdn" in url}
        assert mine
        for text in [p.read_text(encoding="utf-8") for p in recorded] + [json.dumps(mine)]:
            assert "MLY|" not in text and "access_token" not in text and "OAuth" not in text

    def test_its_images_are_the_synthetic_one(self):
        index = json.loads((FIXTURES / "index.json").read_text(encoding="utf-8"))
        files = {e["file"] for url, e in index.items() if "fbcdn" in url}
        assert files == {"download/storage/head.jpg"}


# ── the add, end to end ────────────────────────────────────────────────────


class TestItNeedsAToken:
    def test_without_one_the_add_is_refused_before_any_job(self, client, auth, live, monkeypatch):
        def never(*_a, **_k):
            raise AssertionError("Mapillary was asked without a token")

        monkeypatch.setattr(mapillary.MapillaryService, "load", never)
        res = acquire(client, auth, SOURCE, "images", parameters=RECORDED)
        assert res.status_code == 428, res.get_data(as_text=True)
        text = json.dumps(res.get_json())
        assert "mapillary.token" in text and "mapillary.com/dashboard/developers" in text


class TestItBecomesACollection:
    def _add(self, client, auth, **parameters):
        res = acquire(client, auth, SOURCE, "images", parameters={**RECORDED, **parameters})
        assert res.status_code == 202, res.get_data(as_text=True)
        job = wait_for(client, auth, res.get_json()["jobId"], timeout=60)
        assert job["status"] == "completed", job
        return job["dataset"]

    def test_its_images_are_one_collection(self, client, keyed):
        dataset = self._add(client, keyed)
        assert dataset["format"] == "collection"
        assert dataset["title"] == "Street-level images, Lincoln Park"
        block = dataset["collection"]
        assert block["kind"] == "images" and block["fileCount"] == 6 and block["hasGps"]
        assert block["sourceId"] == SOURCE and block["provider"] == "mapillary"
        assert "CC BY-SA 4.0" in dataset["description"]

    def test_every_row_names_its_photographer_and_place(self, client, keyed):
        import geopandas as gpd

        dataset = self._add(client, keyed)
        index = gpd.read_parquet(dataset["path"])
        assert len(index) == 6
        assert index["creator"].notna().all() and index["image_id"].notna().all()
        assert index["mapillary_url"].str.startswith("https://www.mapillary.com/app/?pKey=").all()
        assert set(index["kind"]) == {"image"}
        assert index.geometry.notna().all()
        west, south, east, north = LINCOLN_PARK["box"]
        assert (index.geometry.x.between(west - 0.001, east + 0.001)).all()
        assert (index.geometry.y.between(south - 0.001, north + 0.001)).all()

    def test_a_node_reads_the_files(self, app, client, keyed, user_and_token):
        from utk_curio.backend.app.discovery.application.exec_collections import resolve_exec_collections
        from utk_curio.sandbox.util.collections import make_collection_helpers

        dataset = self._add(client, keyed)
        user, _token = user_and_token
        with app.app_context():
            from utk_curio.backend.app.users.models import User

            row = User.query.get(user.id)
            collections, media_dir = resolve_exec_collections(
                f'curio_load_collection("{dataset["id"]}")', str(user.id), user=row
            )
        assert set(collections[dataset["id"]]) == {"kind", "objects"}
        helpers = make_collection_helpers(lambda _id: dataset["path"], collections, media_dir)
        frame = helpers["curio_load_collection"](dataset["id"])
        assert frame["path"].notna().all()
        assert all(Path(p).is_file() for p in frame["path"])

    def test_the_browser_sees_its_photos(self, client, keyed):
        """The media route serves a downloaded collection's files: the details'
        thumbnails and Simple View's cards are drawn from it."""
        import pandas as pd

        dataset = self._add(client, keyed)
        file_id = pd.read_parquet(dataset["path"])["file_id"].iloc[0]
        for variant in ("thumb", "original"):
            res = client.get(f"/api/datasets/{dataset['id']}/media/{file_id}?variant={variant}", headers=keyed)
            assert res.status_code == 200, (variant, res.get_data(as_text=True))
            assert res.mimetype == "image/jpeg"

    def test_it_records_what_it_was_asked(self, client, keyed):
        provenance = self._add(client, keyed)["discoverySource"]
        assert provenance["sourceId"] == SOURCE and provenance["resourceId"] == "images"
        assert provenance["parameters"]["area"] == LINCOLN_PARK
        assert provenance["parameters"]["size"] == "256"
        assert provenance["parametersHash"]

    def test_the_same_add_again_asks_nothing(self, client, keyed, monkeypatch):
        first = self._add(client, keyed)

        def no_second_run(*_a, **_k):
            raise AssertionError("Mapillary was asked for an add already held")

        monkeypatch.setattr(mapillary.MapillaryService, "load", no_second_run)
        again = acquire(client, keyed, SOURCE, "images", parameters=RECORDED)
        assert again.status_code == 200
        assert again.get_json()["dataset"]["id"] == first["id"]

    def test_other_answers_are_another_dataset(self, client, keyed):
        first = self._add(client, keyed)
        second = self._add(client, keyed, imageType="panoramas", captured={"start": "2023-01-01"})
        assert second["id"] != first["id"]

    def test_the_token_is_in_nothing_it_stores(self, client, keyed):
        dataset = self._add(client, keyed)
        assert SECRET not in json.dumps(dataset)
        assert SECRET.split("|")[-1] not in Path(dataset["path"]).read_bytes().decode("latin-1")
        manifest = Path(dataset["path"]).parents[1] / "manifest.json"
        if manifest.is_file():
            assert SECRET not in manifest.read_text(encoding="utf-8")

    def test_an_area_is_required(self, client, keyed):
        res = acquire(client, keyed, SOURCE, "images", parameters={"size": "256"})
        assert res.status_code == 400


class TestMapFeatures:
    def test_they_are_one_geojson_table_in_longitude_and_latitude(self, client, keyed):
        res = acquire(client, keyed, SOURCE, "map-features", parameters={"area": LINCOLN_PARK})
        job = wait_for(client, keyed, res.get_json()["jobId"], timeout=60)
        assert job["status"] == "completed", job
        dataset = job["dataset"]
        assert dataset["format"] == "geojson" and dataset["featureCount"] == 205
        collection = json.loads(Path(dataset["path"]).read_text(encoding="utf-8"))
        lon, lat = collection["features"][0]["geometry"]["coordinates"]
        # Not moved from World Mercator, as Autark's layers are.
        assert -87.65 < lon < -87.63 and 41.91 < lat < 41.93
        assert collection["features"][0]["properties"]["object_value"]


def test_an_empty_answer_says_so(tmp_path):
    transport = _Answers(lambda url: {"data": []})
    service = mapillary.MapillaryService(_manifest(), transport=transport)
    answer = service.load(_manifest().resource("images"), {"area": LINCOLN_PARK}, tmp_path)
    assert answer.images == [] and answer.found == 0


def test_an_area_is_needed(tmp_path):
    service = mapillary.MapillaryService(_manifest(), transport=_Answers(lambda url: {"data": []}))
    with pytest.raises(DiscoveryError, match="needs an area"):
        service.load(_manifest().resource("images"), {}, tmp_path)
