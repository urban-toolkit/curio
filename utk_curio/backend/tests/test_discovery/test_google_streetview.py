"""Google Street View: a keyed service whose key goes as ``key=``.

Built and tested with no Google key. The corpus (``fixtures/google-streetview``)
is written from Google's documented answer shapes, not recorded; see its
README. What the key itself does is tested on the real transport, with
``requests`` stood in for: it reaches the request sent, and nothing returned,
raised or stored.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from utk_curio.backend.app.discovery.domain import manifest as M
from utk_curio.backend.app.discovery.domain.errors import DiscoveryError, ProviderError
from utk_curio.backend.app.discovery.domain.manifest import load_source_manifest
from utk_curio.backend.app.discovery.infrastructure import credentials
from utk_curio.backend.app.discovery.infrastructure import transport as T
from utk_curio.backend.app.discovery.providers import build_service, google_streetview as gsv
from utk_curio.backend.tests.test_discovery.conftest import FIXTURES, SHIPPED_ROOT, a_manifest
from utk_curio.backend.tests.test_discovery.test_acquire import acquire, wait_for

SOURCE = "source.google.street-view@1"
LINCOLN_PARK = {"box": [-87.642, 41.918, -87.639, 41.92], "label": "Lincoln Park"}
#: What the written corpus answers; see ASKS in scripts/write_streetview_fixtures.py.
WRITTEN = {"area": LINCOLN_PARK, "spacing": 60, "maxImages": 20}
DENIED = {"area": {"box": [-87.632, 41.91, -87.631, 41.911], "label": "Old Town"}, "spacing": 60, "maxImages": 4}
SECRET = "AIzaCurioTestKey-0123456789abcdefghijk"


@pytest.fixture()
def auth(user_and_token):
    _user, token = user_and_token
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def live(app, shipped_root, fixture_corpus):
    return app


@pytest.fixture()
def keyed(client, auth, live):
    res = client.patch("/api/auth/me", headers=auth, json={"google_maps_api_key": SECRET})
    assert res.status_code == 200, res.get_data(as_text=True)
    return auth


def _manifest():
    return load_source_manifest(SHIPPED_ROOT / SOURCE)


def _values(raw):
    from utk_curio.backend.app.discovery.domain import parameters as P

    return P.validate_values(_manifest().declared_parameters("images"), raw)


class TestTheManifest:
    def test_the_shipped_source_sends_its_key_as_google_documents(self):
        manifest = _manifest()
        assert manifest.is_service and manifest.provider.type == "google-streetview"
        assert (manifest.auth.scheme, manifest.auth.param_name) == ("query", "key")
        assert manifest.auth.secret_id == "google.maps-key" and manifest.auth.needs_token
        assert [(r.id, r.kind, r.dataset_format) for r in manifest.resources] == [("images", "images", "collection")]

    @pytest.mark.parametrize("kind, base", [
        ("google-streetview", "https://maps.example.net"),
        ("mapillary", "https://graph.example.net"),
    ])
    def test_its_api_host_is_fixed(self, kind, base):
        """A person's key goes to the service and nowhere a manifest could point it."""
        options = {"imageHosts": ["fbcdn.net"]} if kind == "mapillary" else {}
        raw = a_manifest(provider={"type": kind, "baseUrl": base, "options": options},
                         resources=[{"id": "images", "name": "Images", "kind": "images",
                                     "options": {"endpoint": "images"} if kind == "mapillary" else {}}])
        raw.pop("capabilities", None)
        with pytest.raises(M.ManifestError, match="baseUrl must be"):
            M._parse_manifest(raw, where="manifest.json")

    def test_the_parameters_are_what_the_provider_reads(self):
        assert M.PROVIDER_PARAMETER_IDS["google-streetview"] == gsv.PARAMETER_IDS


class TestTheGrid:
    def test_points_are_spacing_apart_inside_the_box(self):
        west, south, east, north = LINCOLN_PARK["box"]
        points = gsv.grid([west, south, east, north], 60)
        assert len(points) == len(set(points)) == 12
        assert all(south < lat < north and west < lon < east for lat, lon in points)

    def test_the_same_box_asks_the_same_points(self):
        assert gsv.grid(LINCOLN_PARK["box"], 60) == gsv.grid(LINCOLN_PARK["box"], 60)

    def test_a_tight_spacing_is_capped(self, tmp_path):
        asked = []

        class Zero:
            def json_get(self, url, **kwargs):
                asked.append(url)
                return json.dumps({"status": "ZERO_RESULTS"})

        service = gsv.GoogleStreetViewService(_manifest(), transport=Zero())
        answer = service.load(_manifest().resource("images"),
                              _values({"area": {"box": [-87.652, 41.908, -87.64, 41.92]}, "spacing": 10}), tmp_path)
        assert answer.images == [] and len(asked) == gsv.MAX_POINTS


class TestTheWrittenCorpus:
    def _load(self, tmp_path, raw=WRITTEN):
        service = build_service(_manifest(), T.FixtureDiscoveryTransport(FIXTURES))
        return service.load(_manifest().resource("images"), _values(raw), tmp_path)

    def test_panoramas_are_found_once_and_the_search_stops_when_it_has_enough(self, tmp_path):
        answer = self._load(tmp_path)
        assert answer.found == 5
        panos = {image.columns["pano_id"] for image in answer.images}
        assert panos == {f"CurioFixturePano{n:02d}" for n in range(1, 6)}

    def test_one_image_per_panorama_and_heading(self, tmp_path):
        answer = self._load(tmp_path)
        pairs = [(i.columns["pano_id"], i.columns["heading"]) for i in answer.images]
        assert len(pairs) == len(set(pairs)) == 19
        assert {h for _p, h in pairs} == {0, 90, 180, 270}

    def test_googles_placeholder_is_not_kept(self, tmp_path):
        answer = self._load(tmp_path)
        assert answer.skipped == 1
        assert ("CurioFixturePano03", 180) not in {(i.columns["pano_id"], i.columns["heading"]) for i in answer.images}

    def test_each_row_says_where_and_when(self, tmp_path):
        image = self._load(tmp_path).images[0]
        columns = image.columns
        assert columns["captured"].startswith("2019-") and columns["copyright"] == "© Google"
        assert -87.643 < columns["gps_lon"] < -87.638 and 41.917 < columns["gps_lat"] < 41.92
        assert (columns["fov"], columns["pitch"]) == (90, 0)
        assert image.path.is_file() and image.size >= gsv.PLACEHOLDER_BYTES

    def test_a_refused_key_says_googles_reason(self, tmp_path):
        with pytest.raises(ProviderError, match="The provided API key is invalid"):
            self._load(tmp_path, DENIED)

    def test_no_url_in_the_corpus_holds_a_key(self):
        index = json.loads((FIXTURES / "index.json").read_text(encoding="utf-8"))
        mine = [url for url, e in index.items() if str(e.get("file", "")).startswith("google-streetview/")]
        assert mine and all("key=" not in url for url in mine)


class _Wire:
    def __init__(self, routes):
        self.routes = routes
        self.sent = []

    def __call__(self, method, url, **kwargs):
        self.sent.append(url)
        base = url.split("&key=")[0].split("?key=")[0]
        status, headers, body = self.routes.get(base, self.routes.get("*"))
        return _Response(status, headers, body)


class _Response:
    def __init__(self, status, headers, body):
        self.status_code, self.headers, self._body = status, dict(headers), body

    def iter_content(self, chunk_size=8192):
        yield self._body

    def close(self):
        pass


@pytest.fixture()
def wire(monkeypatch):
    import requests

    from utk_curio.backend.app.common import egress_policy

    monkeypatch.setattr(egress_policy, "_default_resolver", lambda host: ["93.184.216.34"])

    def _install(routes):
        fake = _Wire(routes)
        monkeypatch.setattr(requests, "request", fake)
        return fake

    return _install


class TestTheKeyOnTheWire:
    """``key=`` is added to the request the transport sends, and to nothing
    the transport hands back."""

    URL = "https://maps.googleapis.com/maps/api/streetview?size=640x640&pano=P&heading=0&fov=90&pitch=0"
    KEY = f"?key={SECRET}"

    def test_the_slot_becomes_a_query_credential(self, app, db, user_and_token):
        user, _ = user_and_token
        user.google_maps_api_key = SECRET
        db.session.commit()
        assert credentials.credential_header(user, _manifest()) == f"?key={SECRET}"

    def test_the_request_sent_carries_it(self, wire):
        fake = wire({"*": (200, {"Content-Length": "4"}, b"\xff\xd8\xff\xd9")})
        T.HttpDiscoveryTransport().download(self.URL, lambda b: None, max_bytes=100, credential=self.KEY)
        assert parse_qs(urlsplit(fake.sent[0]).query)["key"] == [SECRET]

    def test_what_comes_back_does_not(self, wire):
        wire({"*": (200, {"Content-Length": "4"}, b"\xff\xd8\xff\xd9")})
        result = T.HttpDiscoveryTransport().download(self.URL, lambda b: None, max_bytes=100, credential=self.KEY)
        assert result.url == self.URL and result.final_url == self.URL
        assert SECRET not in json.dumps(result.audit) and SECRET not in repr(result)

    def test_a_listing_sends_it_and_returns_no_trace(self, wire):
        url = "https://maps.googleapis.com/maps/api/streetview/metadata?location=41.9%2C-87.6&radius=30"
        fake = wire({"*": (200, {"Content-Type": "application/json"}, b'{"status": "ZERO_RESULTS"}')})
        body, headers = T.HttpDiscoveryTransport().get_page(url, credential=self.KEY)
        assert SECRET in fake.sent[0]
        assert SECRET not in body and SECRET not in json.dumps(headers)

    def test_a_failure_does_not_name_it(self, monkeypatch):
        import requests

        from utk_curio.backend.app.common import egress_policy

        monkeypatch.setattr(egress_policy, "_default_resolver", lambda host: ["93.184.216.34"])

        def unreachable(method, url, **kwargs):
            raise requests.ConnectionError(f"Max retries exceeded with url: {url}")

        monkeypatch.setattr(requests, "request", unreachable)
        with pytest.raises(T.DiscoveryTransportError) as exc:
            T.HttpDiscoveryTransport().download(self.URL, lambda b: None, max_bytes=100, credential=self.KEY)
        assert SECRET not in str(exc.value) and "<key>" in str(exc.value)
        # Nothing carries the original, whose message names the keyed URL: a
        # logged traceback walks __context__ and __cause__.
        assert exc.value.__cause__ is None and exc.value.__context__ is None
        with pytest.raises(T.DiscoveryTransportError) as exc:
            T.HttpDiscoveryTransport().get_page(self.URL, credential=self.KEY)
        assert SECRET not in str(exc.value)
        assert exc.value.__cause__ is None and exc.value.__context__ is None

    def test_it_reaches_no_other_host(self):
        seen = []

        class Spy:
            def download(self, url, sink, *, max_bytes, credential=None, **kwargs):
                seen.append(credential)

        bound = T.CredentialedTransport(Spy(), self.KEY, hosts=("maps.googleapis.com",))
        bound.download("https://elsewhere.example/x.jpg", lambda b: None, max_bytes=1)
        bound.download(self.URL, lambda b: None, max_bytes=1)
        assert seen == [None, self.KEY]


class TestItBecomesACollection:
    def test_without_a_key_the_add_is_refused(self, client, auth, live):
        res = acquire(client, auth, SOURCE, "images", parameters=WRITTEN)
        assert res.status_code == 428
        assert "google.maps-key" in json.dumps(res.get_json())

    def test_its_images_are_one_collection(self, client, keyed):
        import geopandas as gpd

        res = acquire(client, keyed, SOURCE, "images", parameters=WRITTEN)
        job = wait_for(client, keyed, res.get_json()["jobId"], timeout=60)
        assert job["status"] == "completed", job
        dataset = job["dataset"]
        assert dataset["format"] == "collection" and dataset["title"] == "Street View images, Lincoln Park"
        assert dataset["collection"]["fileCount"] == 19 and dataset["collection"]["hasGps"]
        assert "Google Maps Platform Terms" in dataset["description"]
        index = gpd.read_parquet(dataset["path"])
        assert set(index["pano_id"]) == {f"CurioFixturePano{n:02d}" for n in range(1, 6)}
        assert SECRET not in json.dumps(job) and SECRET not in Path(dataset["path"]).read_bytes().decode("latin-1")

    def test_a_refused_key_fails_the_job_with_googles_reason(self, client, keyed):
        res = acquire(client, keyed, SOURCE, "images", parameters=DENIED)
        job = wait_for(client, keyed, res.get_json()["jobId"], timeout=60)
        assert job["status"] == "failed"
        assert "The provided API key is invalid" in job["error"]
        assert SECRET not in json.dumps(job)

    def test_a_size_over_googles_most_is_refused(self, tmp_path):
        service = gsv.GoogleStreetViewService(_manifest(), transport=None)
        with pytest.raises(DiscoveryError, match="up to 640x640"):
            service.load(_manifest().resource("images"), {"area": LINCOLN_PARK, "size": "1024x1024"}, tmp_path)
