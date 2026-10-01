"""OpenStreetMap through Autark: the service source, end to end.

The downloads run autk-db's own ``loadOsm`` in Node, as the source does in
production, against Overpass answers recorded for the Village of Golf,
Illinois, by name and for a box inside it (``fixtures/overpass``, made with
the loader's ``record`` mode). No
test opens a socket: the loader's fetch answers from that corpus, and a miss
fails naming the request.

The contract tests (what the loader is sent, Cancel, the time limit) put a
small shell script where ``node`` would be.
"""
from __future__ import annotations

import json
import shutil
import stat
import time
from pathlib import Path

import pytest

from utk_curio.backend.app.discovery.application.service_acquire import place_label, to_wgs84
from utk_curio.backend.app.discovery.domain import manifest as M
from utk_curio.backend.app.discovery.domain.errors import DiscoveryError
from utk_curio.backend.app.discovery.domain.manifest import load_source_manifest
from utk_curio.backend.app.discovery.providers import autark_osm, build_service
from utk_curio.backend.tests.test_discovery.conftest import FIXTURES, SHIPPED_ROOT, a_manifest
from utk_curio.backend.tests.test_discovery.test_acquire import acquire, wait_for

OSM = "source.osm.openstreetmap@1"
GOLF = {"names": {"geocodeArea": "Illinois", "areas": ["Golf"]}}
# A box inside Golf, [west, south, east, north]: about 1.8 km2.
GOLF_BOX = {"box": [-87.8, 42.05, -87.78, 42.06], "label": "Golf"}
NOWHERE = {"names": {"geocodeArea": "Illinois", "areas": ["Nowhere Land"]}}

ROOT_AUTK_DB = Path(__file__).resolve().parents[4] / "node_modules" / "@urban-toolkit" / "autk-db"
needs_node = pytest.mark.skipif(
    shutil.which("node") is None or not ROOT_AUTK_DB.is_dir(),
    reason="Node.js and the repo-root autk-db are needed (npm install at the repository root)",
)


@pytest.fixture()
def auth(user_and_token):
    _user, token = user_and_token
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def osm_home(tmp_path, monkeypatch):
    """A HOME holding Curio's copy of DuckDB's extensions, as launch seeds it,
    so autk-db's ``INSTALL spatial`` in the Node child reads it from disk."""
    from utk_curio import main as curio_main

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: home)
    curio_main.seed_duckdb_extensions()
    return home


@pytest.fixture()
def live(app, shipped_root, fixture_corpus, osm_home):
    return app


def _osm_manifest(**overrides):
    raw = a_manifest(
        provider={"type": "autark-osm", "baseUrl": M.AUTARK_OVERPASS_BASE},
        parameters=[{"id": "area", "type": "area", "label": "Area", "required": True, "accepts": ["names"]}],
        resources=[{"id": "parks", "name": "Parks", "kind": "table", "format": "geojson",
                    "options": {"layers": ["parks"]}}],
    )
    raw.pop("capabilities", None)
    raw.update(overrides)
    return raw


class TestTheManifest:
    def test_the_shipped_source_is_a_service_with_one_resource_per_layer(self):
        manifest = load_source_manifest(SHIPPED_ROOT / OSM)
        assert manifest.is_service and not manifest.is_storage
        assert manifest.capabilities.formats == ("geojson",)
        layers = {spec.id: spec.options["layers"] for spec in manifest.resources}
        for layer in M.AUTARK_OSM_LAYERS:
            assert layers[layer] == [layer]
        assert layers["all-layers"] == list(M.AUTARK_OSM_LAYERS)
        (area,) = manifest.declared_parameters("parks")
        assert area.required and area.accepts == ("box", "names")
        assert area.max_area_km2 == 25

    def test_a_minimal_one_parses(self):
        parsed = M._parse_manifest(_osm_manifest(), where="manifest.json")
        assert [r.id for r in parsed.resources] == ["parks"]

    def test_it_must_name_autk_dbs_overpass(self):
        raw = _osm_manifest(provider={"type": "autark-osm", "baseUrl": "https://overpass.example"})
        with pytest.raises(M.ManifestError, match="must be https://overpass-api.de"):
            M._parse_manifest(raw, where="manifest.json")

    def test_it_must_declare_resources(self):
        raw = _osm_manifest()
        raw.pop("resources")
        with pytest.raises(M.ManifestError, match="declares what it can be asked for"):
            M._parse_manifest(raw, where="manifest.json")

    def test_a_service_resource_has_no_path(self):
        raw = _osm_manifest(resources=[{"id": "parks", "name": "Parks", "kind": "table", "format": "geojson",
                                         "path": "parks.geojson", "options": {"layers": ["parks"]}}])
        with pytest.raises(M.ManifestError, match="path only applies to a storage resource"):
            M._parse_manifest(raw, where="manifest.json")

    @pytest.mark.parametrize("layers", [[], ["parks", "parks"], ["forests"], "parks"])
    def test_its_layers_are_autarks_without_repeats(self, layers):
        raw = _osm_manifest(resources=[{"id": "x", "name": "X", "kind": "table", "format": "geojson",
                                         "options": {"layers": layers}}])
        with pytest.raises(M.ManifestError, match="options.layers must list Autark layers"):
            M._parse_manifest(raw, where="manifest.json")

    def test_it_lands_as_geojson(self):
        raw = _osm_manifest(resources=[{"id": "x", "name": "X", "kind": "table", "format": "csv",
                                         "options": {"layers": ["parks"]}}])
        with pytest.raises(M.ManifestError, match="format must be one of"):
            M._parse_manifest(raw, where="manifest.json")

    def test_it_takes_a_box_and_named_areas(self):
        """autk-db's loadOsm takes both (Autark #107), so the manifest may offer both."""
        raw = _osm_manifest(parameters=[{"id": "area", "type": "area", "label": "Area", "accepts": ["box", "names"]}])
        (area,) = M._parse_manifest(raw, where="manifest.json").parameters
        assert area.accepts == ("box", "names")

    def test_a_portal_may_not_offer_names(self):
        raw = a_manifest(provider={"type": "socrata", "baseUrl": "https://portal.example"},
                         parameters=[{"id": "area", "type": "area", "label": "Area", "accepts": ["names"]}])
        with pytest.raises(M.ManifestError, match="accepts names, which a socrata source cannot send"):
            M._parse_manifest(raw, where="manifest.json")

    def test_the_schema_says_the_same(self):
        schema = json.loads((Path(__file__).resolve().parents[4] / "docs/schemas/discovery-source.v1.json").read_text())
        options = schema["properties"]["resources"]["items"]["properties"]["options"]
        assert options["properties"]["layers"]["items"]["enum"] == sorted(M.AUTARK_OSM_LAYERS)
        provider_rules = schema["properties"]["provider"]["allOf"]
        assert {"properties": {"baseUrl": {"const": M.AUTARK_OVERPASS_BASE}}} in [r["then"] for r in provider_rules]

    def test_the_schema_refuses_a_path_on_a_service_resource(self):
        jsonschema = pytest.importorskip("jsonschema")
        schema = json.loads((Path(__file__).resolve().parents[4] / "docs/schemas/discovery-source.v1.json").read_text())
        validator = jsonschema.Draft202012Validator(schema)
        raw = json.loads((SHIPPED_ROOT / OSM / "manifest.json").read_text())
        assert not list(validator.iter_errors(raw))
        raw["resources"][0]["path"] = "parks.geojson"
        assert list(validator.iter_errors(raw))


class TestItsRowsNeedNoNetwork:
    def test_the_page_lists_what_the_manifest_declares(self, client, auth, live):
        body = client.get(f"/api/discovery/sources/{OSM}/search", headers=auth).get_json()
        rows = {r["resourceId"]: r for r in body["resources"]}
        assert list(rows) == ["buildings", "roads", "parks", "water", "surface", "all-layers"]
        assert rows["parks"]["formats"] == ["geojson"]
        assert rows["parks"]["parameters"][0]["accepts"] == ["box", "names"]
        assert body["sources"] == [{"sourceId": "source.osm.openstreetmap", "status": "ok", "count": 6}]

    def test_the_source_row_says_service(self, client, auth, live):
        row = client.get(f"/api/discovery/sources/{OSM}", headers=auth).get_json()
        assert row["kind"] == "service"
        assert row["baseUrl"] == M.AUTARK_OVERPASS_BASE

    def test_a_federated_search_finds_them_and_the_agents_do_not(self, client, auth, live):
        found = client.get("/api/discovery/search?q=buildings", headers=auth).get_json()
        assert ("source.osm.openstreetmap", "buildings") in {
            (r["sourceId"], r["resourceId"]) for r in found["resources"]
        }
        from utk_curio.backend.app.discovery.service import DiscoveryService

        portals_only = DiscoveryService("1").search_all(q="buildings", include_storage=False)
        assert all(r["sourceId"] != "source.osm.openstreetmap" for r in portals_only["resources"])

    def test_a_resource_describes_its_layers(self, client, auth, live):
        detail = client.get(f"/api/discovery/sources/{OSM}/resources/all-layers", headers=auth).get_json()
        assert detail["extra"]["layers"] == list(M.AUTARK_OSM_LAYERS)
        assert detail["license"] == "ODbL 1.0"


class TestTheAnswersAreChecked:
    def test_an_area_is_required(self, client, auth, live):
        res = acquire(client, auth, OSM, "parks")
        assert res.status_code == 400
        assert "Area" in res.get_json()["error"]

    def test_a_box_over_the_limit_is_refused(self, client, auth, live):
        # About 9 km by 11 km: over the source's 25 km2.
        res = acquire(client, auth, OSM, "parks", parameters={"area": {"box": [-87.9, 42.0, -87.8, 42.1]}})
        assert res.status_code == 400
        assert "25" in res.get_json()["error"]

    def test_a_name_that_would_break_the_query_is_refused(self, client, auth, live):
        res = acquire(client, auth, OSM, "parks",
                      parameters={"area": {"names": {"geocodeArea": "Illinois", "areas": ['Golf"];out;']}}})
        assert res.status_code == 400


@needs_node
class TestItBecomesDatasets:
    def test_one_layer_is_one_geojson_dataset_in_wgs84(self, client, auth, live):
        res = acquire(client, auth, OSM, "parks", parameters={"area": GOLF})
        assert res.status_code == 202, res.get_data(as_text=True)
        job = wait_for(client, auth, res.get_json()["jobId"], timeout=120)
        assert job["status"] == "completed", job
        dataset = job["dataset"]
        assert dataset["format"] == "geojson"
        assert dataset["title"] == "Parks, Golf (Illinois)"
        assert dataset["featureCount"] == 11
        assert not dataset.get("groupId")
        collection = json.loads(Path(dataset["path"]).read_text())
        lons = [p[0] for f in collection["features"] for p in _positions(f["geometry"])]
        lats = [p[1] for f in collection["features"] for p in _positions(f["geometry"])]
        # Golf, Illinois: about 87.79 W, 42.06 N.
        assert -87.82 < min(lons) and max(lons) < -87.77
        assert 42.04 < min(lats) and max(lats) < 42.07
        assert "__autk_layer" not in collection and "bbox" not in collection

    def test_a_box_downloads_what_is_inside_it(self, client, auth, live):
        job = wait_for(client, auth, acquire(client, auth, OSM, "parks", parameters={"area": GOLF_BOX})
                       .get_json()["jobId"], timeout=120)
        assert job["status"] == "completed", job
        dataset = job["dataset"]
        assert dataset["title"] == "Parks, Golf"
        assert dataset["featureCount"] == 32
        collection = json.loads(Path(dataset["path"]).read_text())
        west, south, east, north = GOLF_BOX["box"]
        # Cropped to the box, as autk-db crops a named area's layers to its boundary.
        for feature in collection["features"]:
            for lon, lat, *_ in _positions(feature["geometry"]):
                assert west - 1e-6 <= lon <= east + 1e-6 and south - 1e-6 <= lat <= north + 1e-6

    def test_it_records_what_it_was_narrowed_by(self, client, auth, live):
        job = wait_for(client, auth, acquire(client, auth, OSM, "parks", parameters={"area": GOLF})
                       .get_json()["jobId"], timeout=120)
        provenance = job["dataset"]["discoverySource"]
        assert provenance["sourceId"] == OSM and provenance["resourceId"] == "parks"
        assert provenance["parameters"] == {"area": GOLF}
        assert provenance["parametersHash"]

    def test_all_layers_are_one_layer_group(self, client, auth, live):
        job = wait_for(client, auth, acquire(client, auth, OSM, "all-layers", parameters={"area": GOLF})
                       .get_json()["jobId"], timeout=180)
        assert job["status"] == "completed", job
        assert job["dataset"]["importedDatasetCount"] == 5
        listing = client.get("/api/datasets/catalog", headers=auth).get_json()["items"]
        members = [d for d in listing if (d.get("discoverySource") or {}).get("resourceId") == "all-layers"]
        groups = {d.get("groupId") for d in members}
        assert len(groups) == 1 and next(iter(groups)).startswith("osm.x")
        assert sorted(d.get("layerName") for d in members) == sorted(M.AUTARK_OSM_LAYERS)
        assert {d["title"] for d in members} >= {"OpenStreetMap, Golf (Illinois) (buildings)"}

    def test_the_same_add_again_runs_nothing(self, client, auth, live, monkeypatch):
        first = wait_for(client, auth, acquire(client, auth, OSM, "parks", parameters={"area": GOLF})
                         .get_json()["jobId"], timeout=120)

        def no_second_run(*_a, **_k):
            raise AssertionError("the loader ran for an add already held")

        monkeypatch.setattr(autark_osm.AutarkOsmService, "load", no_second_run)
        again = acquire(client, auth, OSM, "parks", parameters={"area": GOLF})
        assert again.status_code == 200
        assert again.get_json()["dataset"]["id"] == first["dataset"]["id"]

    def test_a_name_with_no_boundary_fails_with_autarks_own_words(self, client, auth, live):
        job = wait_for(client, auth, acquire(client, auth, OSM, "parks", parameters={"area": NOWHERE})
                       .get_json()["jobId"], timeout=120)
        assert job["status"] == "failed"
        assert 'No administrative boundary found in OSM for: "Nowhere Land"' in job["error"]

    def test_an_unrecorded_request_fails_loudly(self, client, auth, live):
        area = {"names": {"geocodeArea": "Illinois", "areas": ["Winnetka"]}}
        job = wait_for(client, auth, acquire(client, auth, OSM, "parks", parameters={"area": area})
                       .get_json()["jobId"], timeout=120)
        assert job["status"] == "failed"
        assert "no recorded Overpass answer" in job["error"]

    def test_more_geojson_than_the_ceiling_is_refused(self, client, auth, live, monkeypatch):
        monkeypatch.setattr(autark_osm, "MAX_OUTPUT_BYTES", 1024)
        job = wait_for(client, auth, acquire(client, auth, OSM, "parks", parameters={"area": GOLF})
                       .get_json()["jobId"], timeout=120)
        assert job["status"] == "failed"
        assert "more than 0 MB of GeoJSON" in job["error"]


def _fake_node(tmp_path: Path, body: str) -> str:
    """A stand-in for ``node``: called as ``<it> autark_osm.mjs`` with the request on stdin."""
    script = tmp_path / "fake-node"
    script.write_text("#!/bin/sh\n" + body)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


@pytest.fixture()
def service(monkeypatch):
    """The source's service as a process with no recorded corpus builds it.

    The CI container sets ``CURIO_DISCOVERY_FIXTURES`` for every test, so the
    variable is cleared here rather than assumed absent."""
    from utk_curio.backend.app.discovery.infrastructure import transport

    monkeypatch.delenv(transport.ENV_FIXTURES, raising=False)
    return build_service(load_source_manifest(SHIPPED_ROOT / OSM))


class TestTheLoaderContract:
    def test_it_is_sent_the_names_the_layers_and_curios_user_agent(self, tmp_path, service):
        from utk_curio.sandbox.util.node_runtime import OVERPASS_USER_AGENT

        if not ROOT_AUTK_DB.is_dir():
            pytest.skip("the repo-root autk-db is needed to resolve its entry")
        seen = tmp_path / "request.json"
        node = _fake_node(tmp_path, f"cat > '{seen}'\necho '__CURIO_OSM_RESULT__ {{\"ok\":true,\"layers\":[]}}'\n")
        spec = service.manifest.resource("all-layers")
        assert service.load(spec, {"area": GOLF}, tmp_path, node=node) == []
        request = json.loads(seen.read_text())
        assert request["queryArea"] == GOLF["names"]
        assert request["layers"] == list(M.AUTARK_OSM_LAYERS)
        assert request["userAgent"] == OVERPASS_USER_AGENT
        assert request["autkDbUrl"].startswith("file://") and request["autkDbUrl"].endswith("/dist/node.js")
        assert request["fixtures"] is None

    def test_a_test_rig_sends_it_the_recorded_overpass_answers(self, tmp_path, fixture_corpus):
        """Behind the transport's own gate: the corpus it would answer from,
        and the Overpass answers inside it."""
        if not ROOT_AUTK_DB.is_dir():
            pytest.skip("the repo-root autk-db is needed to resolve its entry")
        service = build_service(load_source_manifest(SHIPPED_ROOT / OSM))
        seen = tmp_path / "request.json"
        node = _fake_node(tmp_path, f"cat > '{seen}'\necho '__CURIO_OSM_RESULT__ {{\"ok\":true,\"layers\":[]}}'\n")
        service.load(service.manifest.resource("parks"), {"area": GOLF}, tmp_path, node=node)
        assert json.loads(seen.read_text())["fixtures"] == str(FIXTURES / "overpass")

    def test_a_box_is_sent_as_autk_dbs_bbox(self, tmp_path, service):
        if not ROOT_AUTK_DB.is_dir():
            pytest.skip("the repo-root autk-db is needed to resolve its entry")
        seen = tmp_path / "request.json"
        node = _fake_node(tmp_path, f"cat > '{seen}'\necho '__CURIO_OSM_RESULT__ {{\"ok\":true,\"layers\":[]}}'\n")
        service.load(service.manifest.resource("parks"), {"area": GOLF_BOX}, tmp_path, node=node)
        assert json.loads(seen.read_text())["queryArea"] == {"bbox": GOLF_BOX["box"]}

    def test_its_stages_reach_the_job(self, tmp_path, service):
        if not ROOT_AUTK_DB.is_dir():
            pytest.skip("the repo-root autk-db is needed to resolve its entry")
        node = _fake_node(tmp_path, "cat > /dev/null\necho '__CURIO_OSM_STAGE__ querying-osm-server'\n"
                                    "echo '__CURIO_OSM_STAGE__ processing-osm-data'\n"
                                    "echo '__CURIO_OSM_RESULT__ {\"ok\":true,\"layers\":[]}'\n")
        stages = []
        service.load(service.manifest.resource("parks"), {"area": GOLF}, tmp_path, stage=stages.append, node=node)
        assert stages == ["Asking OpenStreetMap…", "Building the layers…"]

    def test_cancel_kills_it(self, tmp_path, service):
        if not ROOT_AUTK_DB.is_dir():
            pytest.skip("the repo-root autk-db is needed to resolve its entry")
        # The stand-in starts a child of its own, as node's would be: a stop
        # must take it too, or its open pipes hold the job.
        node = _fake_node(tmp_path, "cat > /dev/null\nsleep 30 &\nwait\n")
        started = time.monotonic()
        with pytest.raises(autark_osm.Cancelled):
            service.load(service.manifest.resource("parks"), {"area": GOLF}, tmp_path,
                         cancelled=lambda: time.monotonic() - started > 0.5, node=node)
        assert time.monotonic() - started < 5

    def test_the_time_limit_stops_it_and_says_so(self, tmp_path, service, monkeypatch):
        if not ROOT_AUTK_DB.is_dir():
            pytest.skip("the repo-root autk-db is needed to resolve its entry")
        monkeypatch.setattr(autark_osm, "MAX_SECONDS", 1)
        node = _fake_node(tmp_path, "cat > /dev/null\nsleep 30\n")
        started = time.monotonic()
        with pytest.raises(DiscoveryError, match="took longer than 0 minutes"):
            service.load(service.manifest.resource("parks"), {"area": GOLF}, tmp_path, node=node)
        assert time.monotonic() - started < 6

    def test_an_exit_without_an_answer_says_what_it_printed(self, tmp_path, service):
        if not ROOT_AUTK_DB.is_dir():
            pytest.skip("the repo-root autk-db is needed to resolve its entry")
        node = _fake_node(tmp_path, "cat > /dev/null\necho 'Error: boom' >&2\nexit 3\n")
        with pytest.raises(DiscoveryError, match="ended without an answer: Error: boom"):
            service.load(service.manifest.resource("parks"), {"area": GOLF}, tmp_path, node=node)

    def test_a_file_outside_its_folder_is_refused(self, tmp_path, service):
        if not ROOT_AUTK_DB.is_dir():
            pytest.skip("the repo-root autk-db is needed to resolve its entry")
        outside = tmp_path / "elsewhere.geojson"
        outside.write_text("{}")
        work = tmp_path / "work"
        work.mkdir()
        answer = json.dumps({"ok": True, "layers": [{"layer": "parks", "file": str(outside), "features": 1}]})
        node = _fake_node(tmp_path, f"cat > /dev/null\necho '__CURIO_OSM_RESULT__ {answer}'\n")
        with pytest.raises(DiscoveryError, match="wrote outside its folder"):
            service.load(service.manifest.resource("parks"), {"area": GOLF}, work, node=node)


class TestTheLayersMoveToWgs84:
    def test_a_position_moves_from_world_mercator(self):
        """Checked against World Mercator's own inverse, worked here: longitude
        is x over the WGS84 semi-major axis; latitude is the iteration on the
        ellipsoid's eccentricity."""
        import math

        x, y = -9755845.07458293, 5112597.178500475
        a, e = 6378137.0, 0.0818191908426215
        t = math.exp(-y / a)
        phi = math.pi / 2 - 2 * math.atan(t)
        for _ in range(10):
            phi = math.pi / 2 - 2 * math.atan(t * ((1 - e * math.sin(phi)) / (1 + e * math.sin(phi))) ** (e / 2))
        moved = to_wgs84({"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"name": "x"},
             "geometry": {"type": "Point", "coordinates": [x, y]}},
        ]})
        lon, lat = moved["features"][0]["geometry"]["coordinates"]
        assert lon == pytest.approx(math.degrees(x / a), abs=1e-7)
        assert lat == pytest.approx(math.degrees(phi), abs=1e-7)
        # The Chicago Riverwalk, where this point came from.
        assert (round(lon, 2), round(lat, 2)) == (-87.64, 41.87)

    def test_geometry_types_and_properties_are_kept(self):
        building = {
            "type": "Feature",
            "properties": {"building_id": 7, "parts": [{"height": 12}]},
            "geometry": {"type": "GeometryCollection", "geometries": [
                {"type": "Polygon", "coordinates": [[[0, 0], [1000, 0], [1000, 1000], [0, 0]]]},
                {"type": "LineString", "coordinates": [[0, 0], [10, 10]]},
            ]},
            "bbox": [0, 0, 1000, 1000],
        }
        moved = to_wgs84({"type": "FeatureCollection", "features": [building], "bbox": [1, 2, 3, 4],
                          "__autk_layer": "buildings"})
        assert set(moved) == {"type", "features"}
        (feature,) = moved["features"]
        assert feature["properties"] == building["properties"]
        assert "bbox" not in feature
        kinds = [g["type"] for g in feature["geometry"]["geometries"]]
        assert kinds == ["Polygon", "LineString"]
        ring = feature["geometry"]["geometries"][0]["coordinates"][0]
        assert len(ring) == 4 and ring[0] == [0.0, 0.0]

    def test_a_feature_without_geometry_stays_without(self):
        moved = to_wgs84({"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {}, "geometry": None},
        ]})
        assert moved["features"][0]["geometry"] is None

    def test_the_place_is_named_for_the_title(self):
        assert place_label({"area": GOLF}) == "Golf (Illinois)"
        assert place_label({"area": GOLF_BOX}) == "Golf"
        assert place_label({"area": {"box": GOLF_BOX["box"]}}) == "-87.8000, 42.0500 to -87.7800, 42.0600"
        assert place_label({"area": {"names": {"geocodeArea": "Chicago", "areas": ["Loop", "Near North Side"]}}}) == (
            "Loop, Near North Side (Chicago)"
        )


def _positions(geometry):
    if geometry is None:
        return []
    if geometry["type"] == "GeometryCollection":
        return [p for g in geometry["geometries"] for p in _positions(g)]

    def walk(coords):
        if coords and isinstance(coords[0], (int, float)):
            yield coords
        else:
            for part in coords:
                yield from walk(part)

    return list(walk(geometry["coordinates"]))


def test_the_recorded_corpus_is_where_the_tests_look():
    assert autark_osm.fixtures_for(str(FIXTURES)) == FIXTURES / "overpass"
    index = json.loads((FIXTURES / "overpass" / "index.json").read_text())
    assert "GET https://overpass-api.de/api/status" in index
    for entry in index.values():
        assert (FIXTURES / "overpass" / entry["file"]).is_file()
