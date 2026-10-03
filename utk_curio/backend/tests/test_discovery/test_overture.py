"""Overture Maps: a service that reads only the parts of remote GeoParquet
files an area needs.

The recorded corpus holds made-up files in Overture's layout, written by
``overture_fixture.py``: a catalog naming a release, collections and items,
and each file's byte ranges as the reader asks for them. No test opens a
socket, and no byte of Overture's is in the repository.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from utk_curio.backend.app.discovery.domain import manifest as M
from utk_curio.backend.app.discovery.domain.errors import DiscoveryError, ProviderError
from utk_curio.backend.app.discovery.domain.manifest import load_source_manifest
from utk_curio.backend.app.discovery.infrastructure.remote_parquet import RemoteParquet, SparseFile, Span
from utk_curio.backend.app.discovery.infrastructure.transport import FixtureDiscoveryTransport
from utk_curio.backend.app.discovery.providers import build_service, overture
from utk_curio.backend.tests.test_discovery import overture_fixture as F
from utk_curio.backend.tests.test_discovery.conftest import FIXTURES, SHIPPED_ROOT, a_manifest
from utk_curio.backend.tests.test_discovery.test_acquire import acquire, wait_for

SOURCE = "source.overture.maps@1"
AREA = {"box": F.TEST_BOX, "label": "Brás"}

#: The made-up buildings inside the box: file 0's first row group, and the
#: first two rows of its second.
INSIDE = [f"part-00000-b{i:02d}" for i in range(6)]


@pytest.fixture()
def auth(user_and_token):
    _user, token = user_and_token
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def live(app, shipped_root, fixture_corpus):
    return app


def _manifest():
    return load_source_manifest(SHIPPED_ROOT / SOURCE)


def _service(transport=None):
    return build_service(_manifest(), transport or FixtureDiscoveryTransport(FIXTURES))


def _file(name: str) -> Path:
    return F.ROOT / "files" / name


class _LocalFile:
    """A transport answering one file's ranges from disk, and keeping them."""

    def __init__(self, path: Path, *, whole: bool = False) -> None:
        self.blob = path.read_bytes()
        self.whole = whole
        self.ranges: list[str] = []

    def download(self, url, sink, *, max_bytes, credential=None, headers=None, progress=None, ceiling=None):
        self.ranges.append(headers["Range"])
        if self.whole:
            sink(self.blob)
            return None
        first, last = (int(v) for v in headers["Range"].removeprefix("bytes=").split("-"))
        sink(self.blob[first:last + 1])


# ── the manifest ───────────────────────────────────────────────────────────


def _overture(**overrides):
    raw = a_manifest(
        provider={"type": "overture", "baseUrl": "https://stac.overturemaps.org",
                  "options": {"dataHosts": [F.DATA_HOST]}},
        resources=[{"id": "buildings", "name": "Buildings", "kind": "table", "format": "parquet",
                    "options": {"theme": "buildings", "type": "building", "layer": "buildings"},
                    "parameters": [{"id": "area", "type": "area", "label": "Area", "required": True}]}],
    )
    raw.pop("capabilities", None)
    raw.update(overrides)
    return raw


class TestTheManifest:
    def test_the_shipped_source_is_a_service_of_geoparquet_tables(self):
        manifest = _manifest()
        assert manifest.is_service and manifest.provider.type == "overture"
        assert [(r.id, r.kind, r.dataset_format) for r in manifest.resources] == [
            ("buildings", "table", "parquet"), ("building-parts", "table", "parquet"),
            ("places", "table", "parquet"), ("road-segments", "table", "parquet"),
        ]
        assert not manifest.auth.needs_token

    def test_it_lists_the_hosts_its_files_come_from(self):
        raw = _overture(provider={"type": "overture", "baseUrl": "https://stac.overturemaps.org"})
        with pytest.raises(M.ManifestError, match="dataHosts"):
            M._parse_manifest(raw, where="manifest.json")

    def test_its_catalog_is_overtures(self):
        raw = _overture(provider={"type": "overture", "baseUrl": "https://stac.example.org",
                                  "options": {"dataHosts": [F.DATA_HOST]}})
        with pytest.raises(M.ManifestError, match="must be https://stac.overturemaps.org"):
            M._parse_manifest(raw, where="manifest.json")

    @pytest.mark.parametrize("options, message", [
        ({"type": "building"}, "options.theme"),
        ({"theme": "buildings"}, "options.type"),
        ({"theme": "Buildings!", "type": "building"}, "options.theme"),
        ({"theme": "buildings", "type": "building", "layer": "towers"}, "options.layer"),
        ({"theme": "buildings", "type": "building", "columns": ["id"]}, "reads no columns"),
    ])
    def test_a_resource_names_one_feature_type(self, options, message):
        raw = _overture()
        raw["resources"][0]["options"] = options
        with pytest.raises(M.ManifestError, match=message):
            M._parse_manifest(raw, where="manifest.json")

    def test_a_resource_is_a_geoparquet_table(self):
        raw = _overture()
        raw["resources"][0]["format"] = "geojson"
        with pytest.raises(M.ManifestError, match="format must be one of"):
            M._parse_manifest(raw, where="manifest.json")

    def test_the_area_is_a_box(self):
        raw = _overture()
        raw["resources"][0]["parameters"][0]["accepts"] = ["names"]
        with pytest.raises(M.ManifestError, match="cannot send"):
            M._parse_manifest(raw, where="manifest.json")

    def test_the_parameters_are_what_the_provider_reads(self):
        assert M.PROVIDER_PARAMETER_IDS["overture"] == overture.PARAMETER_IDS


# ── reading part of a remote file ──────────────────────────────────────────


class TestTheRemoteFile:
    def test_it_reads_the_footer_and_then_only_the_row_groups_asked_for(self):
        path = _file("buildings-part-00000.parquet")
        transport = _LocalFile(path)
        remote = RemoteParquet(transport, "https://x.example/f.parquet", path.stat().st_size,
                               max_footer_bytes=1 << 20)
        assert remote.metadata.num_row_groups == 3
        table = remote.read_row_group(1)
        assert table.num_rows == 4
        assert table.column("id").to_pylist() == [f"part-00000-b{i:02d}" for i in range(4, 8)]
        span = remote.row_group_span(1)
        size = path.stat().st_size
        assert transport.ranges == [f"bytes={size - 8}-{size - 1}", f"bytes=0-{size - 1}", span.header]

    def test_the_row_groups_kept_are_those_whose_box_meets_the_area(self):
        path = _file("buildings-part-00000.parquet")
        remote = RemoteParquet(_LocalFile(path), "https://x.example/f.parquet", path.stat().st_size,
                               max_footer_bytes=1 << 20)
        assert remote.row_groups_meeting(F.TEST_BOX) == [0, 1]
        assert remote.row_groups_meeting([0.0, 0.0, 1.0, 1.0]) == []

    def test_a_server_that_ignores_the_range_is_refused(self):
        path = _file("buildings-part-00000.parquet")
        remote = RemoteParquet(_LocalFile(path, whole=True), "https://x.example/f.parquet",
                               path.stat().st_size, max_footer_bytes=1 << 20)
        with pytest.raises(ProviderError, match="asked https://x.example/f.parquet for 8 bytes"):
            remote.metadata

    def test_a_footer_longer_than_the_bound_is_refused(self):
        path = _file("buildings-part-00000.parquet")
        remote = RemoteParquet(_LocalFile(path), "https://x.example/f.parquet", path.stat().st_size,
                               max_footer_bytes=16)
        with pytest.raises(ProviderError, match="more than Curio reads"):
            remote.metadata

    def test_a_read_outside_the_bytes_fetched_fails_rather_than_asking_again(self):
        sparse = SparseFile(100)
        sparse.hold(10, b"x" * 10)
        sparse.seek(12)
        assert sparse.read(4) == b"xxxx"
        sparse.seek(18)
        with pytest.raises(ProviderError, match="not fetched"):
            sparse.read(4)

    def test_a_span_is_sent_as_an_inclusive_range(self):
        assert Span(10, 20).header == "bytes=10-19" and len(Span(10, 20)) == 10


# ── the service, against the made-up corpus ────────────────────────────────


class TestTheService:
    def test_it_keeps_the_rows_whose_box_meets_the_area(self, tmp_path):
        import geopandas as gpd

        [layer] = _service().load(_manifest().resource("buildings"), {"area": AREA}, tmp_path)
        assert layer.layer == "buildings" and layer.features == len(INSIDE)
        frame = gpd.read_parquet(layer.path)
        assert sorted(frame["id"]) == INSIDE
        assert set(frame.geometry.geom_type) == {"Polygon"}
        west, south, east, north = F.TEST_BOX
        minx, miny, maxx, maxy = frame.total_bounds
        assert west <= minx and maxx <= east and south <= miny and maxy <= north

    def test_it_keeps_overtures_columns_as_overture_names_them(self, tmp_path):
        import pyarrow.parquet as pq

        [layer] = _service().load(_manifest().resource("buildings"), {"area": AREA}, tmp_path)
        table = pq.read_table(layer.path)
        assert {"id", "names", "sources", "height", "subtype", "class", "geometry", "bbox"} <= set(table.column_names)
        row = table.slice(1, 1).to_pylist()[0]
        assert row["names"] == {"primary": "Building 1"}
        assert row["sources"] == [{"dataset": "Made up", "record_id": "part-00000-b01"}]

    def test_its_file_is_geoparquet_with_the_box_of_the_rows_kept(self, tmp_path):
        import pyarrow.parquet as pq

        [layer] = _service().load(_manifest().resource("buildings"), {"area": AREA}, tmp_path)
        geo = json.loads(pq.read_metadata(layer.path).metadata[b"geo"])
        assert geo["primary_column"] == "geometry"
        column = geo["columns"]["geometry"]
        assert column["encoding"] == "WKB" and column["covering"]["bbox"]["xmin"] == ["bbox", "xmin"]
        west, south, east, north = column["bbox"]
        assert F.TEST_BOX[0] <= west < east <= F.TEST_BOX[2]
        assert F.TEST_BOX[1] <= south < north <= F.TEST_BOX[3]

    def test_it_asks_only_for_the_files_and_row_groups_that_meet_the_area(self, tmp_path):
        transport = FixtureDiscoveryTransport(FIXTURES)
        _service(transport).load(_manifest().resource("buildings"), {"area": AREA}, tmp_path)
        ranges = [call for call in transport.calls if " bytes=" in call]
        assert not any("part-00001" in call for call in transport.calls), "a file outside the area was read"
        assert not any(call.endswith("/00001.json") for call in transport.calls)
        path = _file("buildings-part-00000.parquet")
        remote = RemoteParquet(_LocalFile(path), "x", path.stat().st_size, max_footer_bytes=1 << 20)
        groups = [remote.row_group_span(g).header for g in (0, 1, 2)]
        assert [call.split(" ", 1)[1] for call in ranges[2:]] == groups[:2], "only row groups 0 and 1"

    def test_it_reads_the_latest_release_and_its_license(self, tmp_path):
        service = _service()
        service.load(_manifest().resource("buildings"), {"area": AREA}, tmp_path)
        assert service.release == F.RELEASE and service.license == "ODbL-1.0"
        text = service.describe_download(_manifest().resource("buildings"), "Brás")
        assert F.RELEASE in text and "License: ODbL-1.0" in text

    def test_a_resource_with_a_subtype_keeps_only_it(self, tmp_path):
        import pyarrow.parquet as pq

        [layer] = _service().load(_manifest().resource("road-segments"), {"area": AREA}, tmp_path)
        assert layer.layer == "roads" and layer.features == 2
        assert set(pq.read_table(layer.path).column("subtype").to_pylist()) == {"road"}

    def test_an_area_needing_more_than_one_download_reads_is_refused_before_any_row_group(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(overture, "MAX_JOB_BYTES", 1)
        transport = FixtureDiscoveryTransport(FIXTURES)
        with pytest.raises(DiscoveryError, match="draw a smaller area"):
            _service(transport).load(_manifest().resource("buildings"), {"area": AREA}, tmp_path)
        assert len([call for call in transport.calls if " bytes=" in call]) == 2, "only the footer was read"

    def test_an_area_with_no_file_reads_no_file(self, tmp_path):
        transport = FixtureDiscoveryTransport(FIXTURES)
        [layer] = _service(transport).load(
            _manifest().resource("buildings"), {"area": {"box": [100.0, 0.0, 100.1, 0.1]}}, tmp_path
        )
        assert layer.features == 0 and not layer.path.exists()
        assert not any(" bytes=" in call for call in transport.calls)

    def test_a_file_on_a_host_the_source_does_not_list_is_refused(self, tmp_path):
        raw = json.loads((SHIPPED_ROOT / SOURCE / "manifest.json").read_text(encoding="utf-8"))
        raw["provider"]["options"]["dataHosts"] = ["files.example.org"]
        manifest = M._parse_manifest(raw, where="manifest.json")
        service = build_service(manifest, FixtureDiscoveryTransport(FIXTURES))
        with pytest.raises(ProviderError, match="host its source does not list"):
            service.load(manifest.resource("buildings"), {"area": AREA}, tmp_path)

    def test_a_collection_whose_boxes_are_out_of_order_is_refused(self, tmp_path):
        inner = FixtureDiscoveryTransport(FIXTURES)

        class Swapped:
            calls = inner.calls

            def json_get(self, url, **kwargs):
                body = inner.json_get(url, **kwargs)
                if url.endswith("/buildings/building/collection.json"):
                    collection = json.loads(body)
                    boxes = collection["extent"]["spatial"]["bbox"]
                    boxes[1], boxes[2] = boxes[2], boxes[1]
                    # The Brás box is now listed beside the German file's item.
                    boxes[2] = [-46.7, -23.6, -46.5, -23.4]
                    body = json.dumps(collection)
                return body

            def download(self, *args, **kwargs):
                return inner.download(*args, **kwargs)

        with pytest.raises(ProviderError, match="order Curio does not expect"):
            _service(Swapped()).load(_manifest().resource("buildings"), {"area": AREA}, tmp_path)

    def test_an_area_is_needed(self, tmp_path):
        with pytest.raises(DiscoveryError, match="needs an area"):
            _service().load(_manifest().resource("buildings"), {}, tmp_path)


def test_the_corpus_is_written_from_its_module():
    """The catalog, the ranges and their entries are what ``overture_fixture.py``
    writes from the GeoParquet files committed."""
    index = json.loads(F.INDEX.read_text(encoding="utf-8"))
    for key, (name, body, entry) in F.documents().items():
        assert index.get(key) == entry, key
        assert (F.ROOT / name).read_bytes() == body, name


# ── the add ────────────────────────────────────────────────────────────────


class TestItBecomesADataset:
    def _add(self, client, auth, resource="buildings"):
        res = acquire(client, auth, SOURCE, resource, parameters={"area": AREA})
        assert res.status_code == 202, res.get_data(as_text=True)
        job = wait_for(client, auth, res.get_json()["jobId"], timeout=60)
        assert job["status"] == "completed", job
        return job["dataset"]

    def test_buildings_land_as_one_geoparquet_dataset(self, client, auth, live):
        import geopandas as gpd

        dataset = self._add(client, auth)
        assert dataset["format"] == "parquet"
        assert dataset["title"] == "Buildings, Brás"
        assert dataset["layerName"] == "buildings"
        frame = gpd.read_parquet(dataset["path"])
        assert sorted(frame["id"]) == INSIDE

    def test_its_description_names_the_release_and_the_license(self, client, auth, live):
        dataset = self._add(client, auth)
        assert F.RELEASE in dataset["description"] and "ODbL-1.0" in dataset["description"]

    def test_an_autark_map_draws_it_as_buildings(self, client, auth, live):
        dataset = self._add(client, auth)
        assert 'df.metadata = {"layerType": "buildings"}' in dataset["loaderSnippet"]["code"]

    def test_it_records_what_it_was_asked(self, client, auth, live):
        provenance = self._add(client, auth)["discoverySource"]
        assert provenance["sourceId"] == SOURCE and provenance["resourceId"] == "buildings"
        assert provenance["parameters"] == {"area": AREA}

    def test_the_same_add_again_asks_nothing(self, client, auth, live, monkeypatch):
        first = self._add(client, auth)

        def no_second_run(*_a, **_k):
            raise AssertionError("Overture was asked for an add already held")

        monkeypatch.setattr(overture.OvertureService, "load", no_second_run)
        again = acquire(client, auth, SOURCE, "buildings", parameters={"area": AREA})
        assert again.status_code == 200
        assert again.get_json()["dataset"]["id"] == first["id"]

    def test_an_area_with_nothing_says_so(self, client, auth, live):
        res = acquire(client, auth, SOURCE, "buildings",
                      parameters={"area": {"box": [100.0, 0.0, 100.05, 0.05]}})
        job = wait_for(client, auth, res.get_json()["jobId"], timeout=60)
        assert job["status"] == "failed" and "has no buildings" in job["error"]

    def test_an_area_over_the_bound_is_refused_before_any_job(self, client, auth, live):
        res = acquire(client, auth, SOURCE, "buildings",
                      parameters={"area": {"box": [-47.0, -24.0, -46.0, -23.0]}})
        assert res.status_code == 400


def test_a_parquet_layer_of_an_autark_type_is_typed_in_its_loader():
    from utk_curio.backend.app.datasets.domain.catalog_item import loader_snippet

    typed = loader_snippet("parquet", "/x.parquet", "data.x", layer_type="roads")["code"]
    assert typed.endswith('\ndf.metadata = {"layerType": "roads"}')
    plain = loader_snippet("parquet", "/x.parquet", "data.x")["code"]
    assert "layerType" not in plain
