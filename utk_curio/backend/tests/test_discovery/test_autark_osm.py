"""OpenStreetMap through Autark: the service source, end to end.

The downloads run autk-db's own ``loadOsm`` in Node, as the source does in
production; only its requests to Overpass are answered for it
(``fixtures/overpass``). Golf, Illinois, by name gets the made-up answers of
``overpass_mock.py``, matched by what each query asks for; a box in Golf and a
box across Chicago's Loop get answers recorded with the loader's ``record``
mode. No test opens a socket, and a request with neither fails naming it.

The contract tests (what the loader is sent, Cancel, the time limit) put a
small shell script where ``node`` would be.
"""
from __future__ import annotations

import gzip
import json
import re
import shutil
import stat
import time
from pathlib import Path

import pytest

from utk_curio.backend.app.discovery.application.service_acquire import place_label, to_wgs84
from utk_curio.backend.app.discovery.domain import manifest as M
from utk_curio.backend.app.discovery.domain import osm_values
from utk_curio.backend.app.discovery.domain import parameters as P
from utk_curio.backend.app.discovery.domain.errors import DiscoveryError
from utk_curio.backend.app.discovery.domain.manifest import load_source_manifest
from utk_curio.backend.app.discovery.providers import autark_osm, build_service
from utk_curio.backend.tests.test_discovery import overpass_mock
from utk_curio.backend.tests.test_discovery.conftest import FIXTURES, SHIPPED_ROOT, a_manifest
from utk_curio.backend.tests.test_discovery.test_acquire import acquire, wait_for

OSM = "source.osm.openstreetmap@1"
GOLF = {"names": {"geocodeArea": "Illinois", "areas": ["Golf"]}}
# A box inside Golf, [west, south, east, north]: about 1.8 km2.
GOLF_BOX = {"box": [-87.8, 42.05, -87.78, 42.06], "label": "Golf"}
NOWHERE = {"names": {"geocodeArea": "Illinois", "areas": ["Nowhere Land"]}}
# A box across Chicago's Loop to Lake Shore Drive, about 0.27 km2: roads with
# speeds, lane counts and clearances.
LOOP_BOX = {"box": [-87.6295, 41.8805, -87.615, 41.8825], "label": "The Loop"}

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
        layers = {spec.id: spec.options["layers"] for spec in manifest.resources if "layers" in spec.options}
        for layer in M.AUTARK_OSM_LAYERS:
            assert layers[layer] == [layer]
        assert layers["all-layers"] == list(M.AUTARK_OSM_LAYERS)
        (area,) = manifest.declared_parameters("parks")
        assert area.required and area.accepts == ("box", "names")
        assert area.max_area_km2 == 25

    def test_it_ships_points_of_interest_and_features_by_tag(self):
        manifest = load_source_manifest(SHIPPED_ROOT / OSM)
        poi = manifest.resource("points-of-interest")
        assert poi.options["tags"] == [f"{key}=*" for key in sorted(
            ["amenity", "shop", "tourism", "leisure", "office", "craft", "healthcare", "historic"])]
        assert poi.tag_entries({}) == poi.options["tags"]
        by_tag = manifest.resource("features-by-tag")
        area, tags = manifest.declared_parameters("features-by-tag")
        assert area.id == "area" and tags.id == "tags" and tags.type == "tags" and tags.required
        assert {"amenity", "shop", "highway"} <= set(tags.suggestions)
        assert by_tag.tag_entries({"tags": ["shop=*"]}) == ["shop=*"]
        assert manifest.resource("parks").tag_entries({}) is None

    @pytest.mark.parametrize("resource, says", [
        ({"options": {"layers": ["parks"], "tags": ["amenity=*"]}}, "declares options.layers and options.tags"),
        ({"options": {}}, "must declare one of"),
        ({"options": {"tags": []}}, "1 to 16 tags"),
        ({"options": {"tags": ["amenity"]}}, "is not a tag"),
        ({"options": {}, "parameters": [{"id": "tags", "type": "tags", "label": "Tags"}]}, "required parameter of type tags"),
        ({"options": {}, "parameters": [{"id": "tags", "type": "text", "label": "Tags", "required": True}]},
         "required parameter of type tags"),
    ])
    def test_a_resource_asks_for_layers_or_tags(self, resource, says):
        raw = _osm_manifest(resources=[{"id": "x", "name": "X", "kind": "table", "format": "geojson", **resource}])
        with pytest.raises(M.ManifestError, match=says):
            M._parse_manifest(raw, where="manifest.json")

    def test_preset_tags_are_normalized(self):
        raw = _osm_manifest(resources=[{"id": "x", "name": "X", "kind": "table", "format": "geojson",
                                         "options": {"tags": ["shop=*", "amenity=cafe", "shop=books"]}}])
        (resource,) = M._parse_manifest(raw, where="manifest.json").resources
        assert resource.options["tags"] == ["amenity=cafe", "shop=*"]

    def test_tags_are_asked_by_a_resource_not_the_source(self):
        raw = _osm_manifest(parameters=[
            {"id": "area", "type": "area", "label": "Area", "accepts": ["names"]},
            {"id": "tags", "type": "tags", "label": "Tags"},
        ])
        with pytest.raises(M.ManifestError, match="tags is declared on the resource"):
            M._parse_manifest(raw, where="manifest.json")

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
        assert options["properties"]["tags"]["items"]["pattern"] == P.TAG_ENTRY_RE.pattern
        assert options["properties"]["tags"]["maxItems"] == P.MAX_TAGS
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

    def test_the_schema_takes_one_of_layers_or_tags(self):
        jsonschema = pytest.importorskip("jsonschema")
        schema = json.loads((Path(__file__).resolve().parents[4] / "docs/schemas/discovery-source.v1.json").read_text())
        validator = jsonschema.Draft202012Validator(schema)
        raw = json.loads((SHIPPED_ROOT / OSM / "manifest.json").read_text())
        poi = next(r for r in raw["resources"] if r["id"] == "points-of-interest")
        poi["options"]["layers"] = ["parks"]
        assert list(validator.iter_errors(raw))
        poi["options"] = {"tags": ['name="x"']}
        assert list(validator.iter_errors(raw))


class TestItsRowsNeedNoNetwork:
    def test_the_page_lists_what_the_manifest_declares(self, client, auth, live):
        body = client.get(f"/api/discovery/sources/{OSM}/search", headers=auth).get_json()
        rows = {r["resourceId"]: r for r in body["resources"]}
        assert list(rows) == ["buildings", "roads", "parks", "water", "surface",
                              "points-of-interest", "features-by-tag", "all-layers"]
        assert rows["parks"]["formats"] == ["geojson"]
        assert rows["parks"]["parameters"][0]["accepts"] == ["box", "names"]
        assert [p["id"] for p in rows["features-by-tag"]["parameters"]] == ["area", "tags"]
        assert rows["features-by-tag"]["parameters"][1]["suggestions"][:2] == ["amenity", "shop"]
        assert body["sources"] == [{"sourceId": "source.osm.openstreetmap", "status": "ok", "count": 8}]

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
        poi = client.get(f"/api/discovery/sources/{OSM}/resources/points-of-interest", headers=auth).get_json()
        assert "amenity=*" in poi["extra"]["tags"] and "layers" not in poi["extra"]


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

    def test_features_by_tag_needs_its_tags(self, client, auth, live):
        res = acquire(client, auth, OSM, "features-by-tag", parameters={"area": LOOP_BOX})
        assert res.status_code == 400
        assert "Tags is required" in res.get_json()["error"]

    @pytest.mark.parametrize("entry", ['name="x"', "amenity", "a[b]=c", "name=a\\b"])
    def test_a_tag_that_would_break_the_query_is_refused(self, client, auth, live, entry):
        res = acquire(client, auth, OSM, "features-by-tag", parameters={"area": LOOP_BOX, "tags": [entry]})
        assert res.status_code == 400
        assert "is not a tag" in res.get_json()["error"]


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
        assert dataset["featureCount"] == len(_mock_parks())
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

    def test_buildings_are_one_row_per_osm_element(self, client, auth, live):
        """Golf's buildings by name, with nothing cut: each building way or
        relation of the answer is one row, none merged, none lost."""
        job = wait_for(client, auth, acquire(client, auth, OSM, "buildings", parameters={"area": GOLF})
                       .get_json()["jobId"], timeout=180)
        assert job["status"] == "completed", job
        dataset = job["dataset"]
        features = json.loads(Path(dataset["path"]).read_text())["features"]
        elements = [(f["properties"]["osm_type"], f["properties"]["osm_id"]) for f in features]
        assert len(elements) == len(set(elements))
        expected = _mock_buildings()
        assert set(elements) == set(expected)
        assert dataset["featureCount"] == len(features)
        by_element = {(f["properties"]["osm_type"], f["properties"]["osm_id"]): f["properties"] for f in features}
        for feature in features:
            properties = feature["properties"]
            assert feature["geometry"]["type"] in ("Polygon", "MultiPolygon")
            assert "parts" not in properties and "__autk_layer" not in properties
            assert isinstance(properties["building_id"], int)
            tags = expected[(properties["osm_type"], properties["osm_id"])]
            assert {key: properties[key] for key in tags} == {
                key: osm_values.number(key, value) if key in osm_values.NUMERIC_KEYS else value
                for key, value in tags.items()
            }
        # The house and the part that shares its wall belong to one Autark building.
        assert by_element[("way", 303)]["building_id"] == by_element[("way", 304)]["building_id"]
        assert by_element[("way", 303)]["building_id"] != by_element[("way", 301)]["building_id"]

    def test_every_feature_names_its_osm_element(self, client, auth, live):
        job = wait_for(client, auth, acquire(client, auth, OSM, "all-layers", parameters={"area": GOLF})
                       .get_json()["jobId"], timeout=180)
        assert job["status"] == "completed", job
        listing = client.get("/api/datasets/catalog", headers=auth).get_json()["items"]
        members = {d["layerName"]: d for d in listing
                   if (d.get("discoverySource") or {}).get("resourceId") == "all-layers"}
        recorded = {(e["type"], e["id"]) for answer in _answers() for e in answer}
        for layer, dataset in members.items():
            features = json.loads(Path(dataset["path"]).read_text())["features"]
            assert features, layer
            if layer == "surface":
                # The land inside the boundary: no OpenStreetMap element, and no tag, is behind it.
                assert all(not f["properties"] for f in features)
                continue
            elements = [(f["properties"]["osm_type"], f["properties"]["osm_id"]) for f in features]
            assert len(elements) == len(set(elements)), layer
            assert set(elements) <= recorded, layer
            if layer == "roads":
                assert {kind for kind, _ in elements} == {"way"}
        parks = json.loads(Path(members["parks"]["path"]).read_text())["features"]
        assert {f["properties"]["osm_type"] for f in parks} == {"way", "relation"}

    def test_numeric_tags_are_numbers(self, client, auth, live):
        """Roads across the Loop: the speeds, lane counts and clearances its
        ways carry land as numbers, in km/h and metres, and read as numeric
        columns; other tags stay text."""
        gpd = pytest.importorskip("geopandas")
        import pandas as pd

        job = wait_for(client, auth, acquire(client, auth, OSM, "roads", parameters={"area": LOOP_BOX})
                       .get_json()["jobId"], timeout=120)
        assert job["status"] == "completed", job
        frame = gpd.read_file(job["dataset"]["path"])
        for column in ("maxspeed", "lanes", "lanes:forward", "lanes:backward", "maxheight", "layer", "width"):
            assert pd.api.types.is_numeric_dtype(frame[column]), column
        assert set(frame["ref"].dropna()) == {"US 41"}

        rows = frame.set_index("osm_id")
        tags = {e["id"]: e["tags"] for answer in _answers() for e in answer
                if e["type"] == "way" and e["id"] in rows.index}
        assert len(tags) == len(rows)
        checked = 0
        for osm_id, way in tags.items():
            if way.get("maxspeed", "").endswith(" mph"):
                assert rows.at[osm_id, "maxspeed"] == round(int(way["maxspeed"].split()[0]) * 1.609344, 2)
                checked += 1
            if "lanes" in way:
                assert rows.at[osm_id, "lanes"] == int(way["lanes"])
                checked += 1
            if "maxheight" in way:
                feet_inches = re.fullmatch(r"(\d+)'(\d+)\"", way["maxheight"])
                if feet_inches:
                    feet, inches = map(int, feet_inches.groups())
                    assert rows.at[osm_id, "maxheight"] == round(feet * 0.3048 + inches * 0.0254, 2)
                else:
                    assert pd.isna(rows.at[osm_id, "maxheight"]), way["maxheight"]
                checked += 1
        assert checked >= 20

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

    def _tag_download(self, client, auth, resource, values, title_prefix):
        """Download a tag resource; its datasets by layer name, checked as one group."""
        job = wait_for(client, auth, acquire(client, auth, OSM, resource, parameters=values)
                       .get_json()["jobId"], timeout=120)
        assert job["status"] == "completed", job
        listing = client.get("/api/datasets/catalog", headers=auth).get_json()["items"]
        members = [d for d in listing if (d.get("discoverySource") or {}).get("resourceId") == resource]
        assert len({d.get("groupId") for d in members}) == 1
        for dataset in members:
            assert dataset["title"] == f"{title_prefix} ({dataset['layerName']})"
        return {d["layerName"]: json.loads(Path(d["path"]).read_text())["features"] for d in members}

    def _assert_layers(self, layers, expected):
        assert set(layers) == {geometry for geometry, elements in expected.items() if elements}
        for geometry, features in layers.items():
            assert {(f["properties"]["osm_type"], f["properties"]["osm_id"]) for f in features} == expected[geometry]
            for feature in features:
                assert (feature["properties"]["osm_type"] == "node") == (geometry == "points")
                assert "__autk_layer" not in feature["properties"]

    def test_points_of_interest_land_as_points_lines_and_polygons(self, client, auth, live):
        layers = self._tag_download(client, auth, "points-of-interest", {"area": LOOP_BOX},
                                    "Points of interest, The Loop")
        preset = load_source_manifest(SHIPPED_ROOT / OSM).resource("points-of-interest").options["tags"]
        self._assert_layers(layers, _mock_tag_layers("loop-points-of-interest", preset))
        parking = next(f for f in layers["polygons"] if f["properties"]["osm_id"] == 7101)
        assert parking["properties"]["capacity"] == 120
        assert next(f for f in layers["points"] if f["properties"]["osm_id"] == 7001)["geometry"]["type"] == "Point"

    def test_features_by_tag_land_as_points_lines_and_polygons(self, client, auth, live):
        tags = ["railway=*", "highway=*"]
        layers = self._tag_download(client, auth, "features-by-tag", {"area": LOOP_BOX, "tags": tags},
                                    "Features tagged highway=*, railway=*, The Loop")
        self._assert_layers(layers, _mock_tag_layers("loop-streets-and-rails", tags))
        # A closed service road is a line; a pedestrian area=yes plaza is a polygon.
        assert ("way", 7404) in {(f["properties"]["osm_type"], f["properties"]["osm_id"]) for f in layers["polylines"]}
        assert [f["properties"]["osm_id"] for f in layers["polygons"]] == [7403]
        # The crossing is a vertex of State Street and keeps its own tags.
        crossing = next(f for f in layers["points"] if f["properties"]["osm_id"] == 7402)
        assert crossing["properties"]["highway"] == "crossing"
        state_street = next(f for f in layers["polylines"] if f["properties"]["osm_id"] == 7401)
        assert (state_street["properties"]["lanes"], state_street["properties"]["maxspeed"]) == (4, 48.28)

    def test_points_of_interest_for_named_areas_stay_inside_them(self, client, auth, live):
        """The mock answers Golf's tag query only when it names Golf's boundary
        relation, as autk-db asks since the named-area scoping fix."""
        layers = self._tag_download(client, auth, "points-of-interest", {"area": GOLF},
                                    "Points of interest, Golf (Illinois)")
        preset = load_source_manifest(SHIPPED_ROOT / OSM).resource("points-of-interest").options["tags"]
        self._assert_layers(layers, _mock_tag_layers("golf-points-of-interest", preset))

    def test_the_same_tags_in_another_order_run_nothing(self, client, auth, live, monkeypatch):
        values = {"area": LOOP_BOX, "tags": ["highway=*", "railway=*"]}
        first = wait_for(client, auth, acquire(client, auth, OSM, "features-by-tag", parameters=values)
                         .get_json()["jobId"], timeout=120)
        assert first["status"] == "completed", first

        def no_second_run(*_a, **_k):
            raise AssertionError("the loader ran for an add already held")

        monkeypatch.setattr(autark_osm.AutarkOsmService, "load", no_second_run)
        again = acquire(client, auth, OSM, "features-by-tag",
                        parameters={"area": LOOP_BOX, "tags": ["railway=*", "highway=*", "highway=primary"]})
        assert again.status_code == 200
        assert again.get_json()["alreadyPresent"] is True

    def test_tags_with_no_feature_say_so(self, client, auth, live):
        job = wait_for(client, auth, acquire(client, auth, OSM, "features-by-tag",
                                             parameters={"area": LOOP_BOX, "tags": ["man_made=lighthouse"]})
                       .get_json()["jobId"], timeout=120)
        assert job["status"] == "failed"
        assert "OpenStreetMap has no features tagged man_made=lighthouse in The Loop" in job["error"]


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

    def test_tags_are_sent_as_one_autk_db_tag_set(self, tmp_path, service):
        if not ROOT_AUTK_DB.is_dir():
            pytest.skip("the repo-root autk-db is needed to resolve its entry")
        seen = tmp_path / "request.json"
        node = _fake_node(tmp_path, f"cat > '{seen}'\necho '__CURIO_OSM_RESULT__ {{\"ok\":true,\"layers\":[]}}'\n")
        values = {"area": GOLF_BOX, "tags": ["amenity=cafe", "shop=*"]}
        service.load(service.manifest.resource("features-by-tag"), values, tmp_path, node=node)
        request = json.loads(seen.read_text())
        assert request["layers"] == []
        assert request["tagSets"] == [
            {"name": "tags", "tags": [{"key": "amenity", "value": "cafe"}, {"key": "shop"}]},
        ]
        service.load(service.manifest.resource("points-of-interest"), {"area": GOLF_BOX}, tmp_path, node=node)
        (tag_set,) = json.loads(seen.read_text())["tagSets"]
        assert [tag["key"] for tag in tag_set["tags"]] == sorted(
            ["amenity", "shop", "tourism", "leisure", "office", "craft", "healthcare", "historic"])
        service.load(service.manifest.resource("parks"), {"area": GOLF_BOX}, tmp_path, node=node)
        assert json.loads(seen.read_text())["tagSets"] == []

    def test_a_tag_entry_is_checked_before_node_starts(self, tmp_path, service):
        if not ROOT_AUTK_DB.is_dir():
            pytest.skip("the repo-root autk-db is needed to resolve its entry")
        ran = tmp_path / "ran"
        node = _fake_node(tmp_path, f"touch '{ran}'\necho '__CURIO_OSM_RESULT__ {{\"ok\":true,\"layers\":[]}}'\n")
        with pytest.raises(DiscoveryError, match="is not a tag"):
            service.load(service.manifest.resource("features-by-tag"),
                         {"area": GOLF_BOX, "tags": ['name="x"];out;']}, tmp_path, node=node)
        assert not ran.exists()

    def test_a_layer_it_was_not_asked_for_is_refused(self, tmp_path, service):
        if not ROOT_AUTK_DB.is_dir():
            pytest.skip("the repo-root autk-db is needed to resolve its entry")
        work = tmp_path / "work"
        work.mkdir()
        (work / "x.geojson").write_text("{}")
        answer = json.dumps({"ok": True, "layers": [{"layer": "lines", "file": str(work / "x.geojson"), "features": 1}]})
        node = _fake_node(tmp_path, f"cat > /dev/null\necho '__CURIO_OSM_RESULT__ {answer}'\n")
        with pytest.raises(DiscoveryError, match="not asked for: lines"):
            service.load(service.manifest.resource("points-of-interest"), {"area": GOLF_BOX}, work, node=node)

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


def _answers():
    """Each Overpass answer the loader can get here, recorded or mock, as its element list."""
    root = FIXTURES / "overpass"
    for key, entry in json.loads((root / "index.json").read_text()).items():
        if key.startswith("POST "):
            yield json.loads(gzip.decompress((root / entry["file"]).read_bytes())).get("elements", [])
    for rule in overpass_mock.RULES:
        yield rule["elements"]


#: autk-db's building values it leaves out, and its park values (autk-db ``consts.ts``).
EXCLUDED_BUILDINGS = {"shed", "garage", "garages", "carport", "hut", "kiosk", "toilets", "service",
                      "transformer_tower", "sty", "container"}
PARKS = {
    "leisure": {"dog_park", "park", "playground", "recreation_ground"},
    "landuse": {"wood", "grass", "forest", "orchard", "village_green", "vineyard", "cemetery", "meadow"},
    "natural": {"wood", "grass", "grassland", "forest", "scrub", "heath", "meadow"},
}


def _mock_elements(rule: str, keep) -> dict[tuple[str, int], dict[str, str]]:
    """The tagged ways and relations of a mock answer that ``keep`` takes: ``{(type, id): tags}``."""
    return {
        (e["type"], e["id"]): e["tags"]
        for e in overpass_mock.rule(rule)["elements"]
        if e["type"] in ("way", "relation") and e.get("tags") and keep(e["tags"])
    }


def _mock_buildings() -> dict[tuple[str, int], dict[str, str]]:
    """Golf's mock buildings that autk-db keeps (``process-osm/pipeline.ts``)."""
    def building(tags):
        def kept(key):
            return key in tags and tags[key] not in EXCLUDED_BUILDINGS
        return kept("building") or kept("building:part") or tags.get("type") == "building"

    return _mock_elements("golf-buildings", building)


#: autk-db's closed-way rule for tag sets: a closed way is a polygon unless it
#: says area=no, or is one of these without area=yes.
LINEAR_KEYS = ("highway", "barrier", "railway", "waterway")


def _tag_geometry(element: dict) -> str | None:
    """The layer autk-db puts a matching element in, or None for a relation it leaves out."""
    tags = element.get("tags") or {}
    if element["type"] == "node":
        return "points"
    if element["type"] == "relation":
        return "polygons" if tags.get("type") == "multipolygon" else None
    nodes = element["nodes"]
    closed = len(nodes) > 3 and nodes[0] == nodes[-1]
    linear = tags.get("area") == "no" or (any(k in tags for k in LINEAR_KEYS) and tags.get("area") != "yes")
    return "polygons" if closed and not linear else "polylines"


def _mock_tag_layers(rule: str, entries: list[str]) -> dict[str, set[tuple[str, int]]]:
    """The elements of a mock answer with any of the tag entries, by the layer each lands in."""
    filters = [P.parse_tag_entry(entry) for entry in entries]
    layers: dict[str, set[tuple[str, int]]] = {"points": set(), "polylines": set(), "polygons": set()}
    for element in overpass_mock.rule(rule)["elements"]:
        tags = element.get("tags") or {}
        if not any(key in tags and (value is None or tags[key] == value) for key, value in filters):
            continue
        geometry = _tag_geometry(element)
        if geometry:
            layers[geometry].add((element["type"], element["id"]))
    return layers


def _mock_parks() -> dict[tuple[str, int], dict[str, str]]:
    """Golf's mock parks, by autk-db's park values."""
    return _mock_elements("golf-parks-and-water", lambda tags: any(tags.get(k) in v for k, v in PARKS.items()))


def test_the_recorded_corpus_is_where_the_tests_look():
    assert autark_osm.fixtures_for(str(FIXTURES)) == FIXTURES / "overpass"
    index = json.loads((FIXTURES / "overpass" / "index.json").read_text())
    assert "GET https://overpass-api.de/api/status" in index
    for entry in index.values():
        assert (FIXTURES / "overpass" / entry["file"]).is_file()


def test_the_mock_answers_are_written_from_their_module():
    """``fixtures/overpass/mock.json`` is what ``overpass_mock.py`` writes."""
    assert json.loads(overpass_mock.MOCK_FILE.read_text()) == overpass_mock.mock_document()
