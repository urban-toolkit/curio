"""An Area on a remote GeoParquet file (#608): a Direct URL link or a bucket
row that points at one reads only the row groups that meet the Area.

The files are made up, written by ``remote_parquet_fixture.py``, and the
recorded corpus serves them one byte range at a time. No test opens a socket.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

import pytest

from utk_curio.backend.app.discovery.domain import manifest as M
from utk_curio.backend.app.discovery.infrastructure.remote_parquet import RemoteParquet
from utk_curio.backend.tests.test_discovery import remote_parquet_fixture as F
from utk_curio.backend.tests.test_discovery.conftest import FIXTURES, a_manifest, write_source
from utk_curio.backend.tests.test_discovery.test_acquire import acquire, wait_for

DIRECT = "source.curio.direct-url@1"
AREA = {"box": F.TEST_BOX}
#: The box as a dataset made for it is named.
PLACE = "-87.6400, 41.8700 to -87.6200, 41.8900"

AREA_DECLARATION = {
    "id": "area", "type": "area", "label": "Area", "accepts": ["box"],
    "description": "Keep only the rows inside a box.",
}


@pytest.fixture()
def auth(user_and_token):
    _user, token = user_and_token
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def calls(monkeypatch):
    """Every request the backend sends, answered by the recorded corpus."""
    from utk_curio.backend.app.discovery.infrastructure import transport

    monkeypatch.setenv(transport.ENV_FIXTURES, str(FIXTURES))
    monkeypatch.setenv("CURIO_TESTING", "1")
    shared = transport.FixtureDiscoveryTransport(FIXTURES)
    monkeypatch.setattr(transport, "build_transport", lambda **_: shared)
    return shared.calls


@pytest.fixture()
def live(app, shipped_root, calls):
    return calls


def _link(name: str) -> str:
    return f"{F.PORTAL}/{name}"


def _add(client, auth, source: str, resource: str, **body) -> dict:
    res = acquire(client, auth, source, resource, **body)
    assert res.status_code == 202, res.get_data(as_text=True)
    return wait_for(client, auth, res.get_json()["jobId"], timeout=60)


def _ranges(calls: list[str], url: str) -> list[str]:
    """The ranges asked of *url*, in order."""
    return [call.split(" ", 1)[1] for call in calls if call.startswith(f"{url} bytes=")]


def _file(local: str) -> Path:
    return F.ROOT / "files" / local


def _reads(local: str) -> tuple[list[str], list[str]]:
    """What the reader asks of a file once it knows its size: its tail and
    footer, and the span of each of its row groups."""
    path = _file(local)
    files = F._LocalFiles(path)
    remote = RemoteParquet(files, "x", path.stat().st_size, max_footer_bytes=1 << 20)
    groups = [remote.row_group_span(g).header for g in range(remote.metadata.num_row_groups)]
    return [f"bytes={first}-{last}" for first, last in files.asked], groups


# ── a Direct URL link ──────────────────────────────────────────────────────


class TestALink:
    def test_a_parquet_link_takes_an_area_and_another_link_does_not(self, client, auth, live):
        source = client.get(f"/api/discovery/sources/{DIRECT}", headers=auth).get_json()
        assert [p["id"] for p in source["parameters"]] == ["area"], "#608: the link form draws this Area"

        def asks(link: str) -> list[str]:
            res = client.get(
                f"/api/discovery/sources/{DIRECT}/resources/{quote(link, safe='')}", headers=auth
            )
            assert res.status_code == 200, res.get_data(as_text=True)
            return [p["id"] for p in res.get_json()["parameters"]]

        assert asks(_link("blocks.parquet")) == ["area"]
        assert asks(_link("crimes.csv")) == []

    def test_it_keeps_the_rows_that_meet_the_area(self, client, auth, live):
        import geopandas as gpd
        import pyarrow.parquet as pq

        job = _add(client, auth, DIRECT, _link("blocks.parquet"), parameters={"area": AREA})
        assert job["status"] == "completed", job
        dataset = job["dataset"]
        assert dataset["format"] == "parquet"
        assert dataset["title"] == f"blocks.parquet, {PLACE}"
        frame = gpd.read_parquet(dataset["path"])
        assert sorted(frame["id"]) == F.INSIDE_BLOCKS
        assert {"name", "floors", "notes", "bbox"} <= set(frame.columns)
        geo = json.loads(pq.read_metadata(dataset["path"]).metadata[b"geo"])
        west, south, east, north = geo["columns"]["geometry"]["bbox"]
        assert F.TEST_BOX[0] <= west < east <= F.TEST_BOX[2]
        assert F.TEST_BOX[1] <= south < north <= F.TEST_BOX[3]
        provenance = dataset["discoverySource"]
        assert provenance["parameters"] == {"area": AREA} and provenance["parametersHash"]

    def test_it_reads_only_the_row_groups_that_meet_the_area(self, client, auth, live):
        """#608: the file is asked for its size, its footer, and row groups 0
        and 1, the two whose box meets the area; never for groups 2 to 4."""
        job = _add(client, auth, DIRECT, _link("blocks.parquet"), parameters={"area": AREA})
        assert job["status"] == "completed", job
        footer, groups = _reads("blocks.parquet")
        assert _ranges(live, _link("blocks.parquet")) == ["bytes=0-0", *footer, groups[0], groups[1]]
        assert _link("blocks.parquet") not in live, "the whole file was downloaded"

    def test_the_same_link_and_area_again_asks_nothing_and_no_area_is_another_dataset(
        self, client, auth, live
    ):
        import pandas as pd

        first = _add(client, auth, DIRECT, _link("blocks.parquet"), parameters={"area": AREA})["dataset"]
        live.clear()
        again = acquire(client, auth, DIRECT, _link("blocks.parquet"), parameters={"area": AREA})
        assert again.status_code == 200, again.get_data(as_text=True)
        assert again.get_json()["dataset"]["id"] == first["id"]
        assert live == []
        whole = _add(client, auth, DIRECT, _link("blocks.parquet"), title="blocks.parquet")
        assert whole["status"] == "completed", whole
        assert whole["dataset"]["id"] != first["id"]
        assert len(pd.read_parquet(whole["dataset"]["path"])) == len(F.BLOCKS)

    def test_an_area_on_a_link_that_is_not_parquet_is_refused(self, client, auth, live):
        job = _add(client, auth, DIRECT, _link("crimes.csv"), parameters={"area": AREA})
        assert job["status"] == "failed"
        assert "GeoParquet" in job["error"], job["error"]
        assert not any(call.startswith(_link("crimes.csv")) for call in live), "the file was asked for"

    def test_a_server_that_does_not_send_parts_of_a_file_says_so(self, client, auth, live):
        job = _add(client, auth, DIRECT, _link(F.NO_RANGES), parameters={"area": AREA})
        assert job["status"] == "failed"
        assert "does not send parts of a file" in job["error"], job["error"]
        assert "without an Area" in job["error"]

    def test_a_file_with_no_box_column_is_read_and_kept_by_its_geometry(self, client, auth, live):
        import geopandas as gpd

        job = _add(client, auth, DIRECT, _link("plain.parquet"), parameters={"area": AREA})
        assert job["status"] == "completed", job
        assert sorted(gpd.read_parquet(job["dataset"]["path"])["id"]) == F.INSIDE_PLAIN
        _footer, groups = _reads("plain.parquet")
        assert _ranges(live, _link("plain.parquet"))[-3:] == groups, "every row group is read"

    def test_a_file_in_another_crs_is_read_in_it(self, client, auth, live):
        import geopandas as gpd

        job = _add(client, auth, DIRECT, _link("projected.parquet"), parameters={"area": AREA})
        assert job["status"] == "completed", job
        frame = gpd.read_parquet(job["dataset"]["path"])
        assert sorted(frame["id"]) == F.INSIDE_PROJECTED
        assert frame.crs.to_epsg() == 3857
        footer, groups = _reads("projected.parquet")
        assert _ranges(live, _link("projected.parquet")) == ["bytes=0-0", *footer, groups[0]]

    def test_a_parquet_file_with_no_geometry_is_refused(self, client, auth, live):
        job = _add(client, auth, DIRECT, _link("table.parquet"), parameters={"area": AREA})
        assert job["status"] == "failed"
        assert "not a GeoParquet file" in job["error"], job["error"]

    def test_an_area_with_nothing_in_it_says_so(self, client, auth, live):
        job = _add(client, auth, DIRECT, _link("blocks.parquet"),
                   parameters={"area": {"box": [0.0, 0.0, 0.1, 0.1]}})
        assert job["status"] == "failed"
        assert "has nothing in" in job["error"], job["error"]
        footer, _groups = _reads("blocks.parquet")
        assert _ranges(live, _link("blocks.parquet")) == ["bytes=0-0", *footer]


@pytest.fixture()
def small_links(app, discovery_dir, calls):
    """A link source whose download limit is under blocks.parquet's size, and
    over what its two row groups in the area and its footer take."""
    write_source(discovery_dir, "source.example.small-links@1", a_manifest(
        id="source.example.small-links", name="Small links",
        provider={"type": "direct", "baseUrl": ""},
        capabilities={"search": False, "formats": ["parquet"], "maxDownloadBytes": 100_000},
        parameters=[AREA_DECLARATION],
    ))
    return calls


class TestTheLimit:
    def test_an_area_needing_more_than_the_limit_is_refused_before_any_row_group(
        self, client, auth, small_links
    ):
        job = _add(client, auth, "source.example.small-links@1", _link("blocks.parquet"),
                   parameters={"area": AREA})
        assert job["status"] == "failed"
        assert "draw a smaller area" in job["error"], job["error"]
        footer, _groups = _reads("blocks.parquet")
        assert _ranges(small_links, _link("blocks.parquet")) == ["bytes=0-0", *footer]


# ── a bucket row ───────────────────────────────────────────────────────────

BUCKET_SOURCE = "source.example.parquet-bucket@1"

#: Under blocks/loop.parquet's size, and over what an add of the area reads.
BUCKET_LIMIT = 200_000


@pytest.fixture()
def bucket(app, discovery_dir, calls):
    from utk_curio.backend.app.discovery.application import scan

    scan.listings.reset()
    write_source(discovery_dir, BUCKET_SOURCE, {
        "id": "source.example.parquet-bucket", "name": "Parquet bucket", "version": "1.0.0",
        "compatibility": {"major": 1}, "description": "GeoParquet files.", "publisher": "Example",
        "provider": {"type": "s3", "baseUrl": F.BUCKET, "options": {}},
        "auth": {"mode": "public"},
        "capabilities": {"maxDownloadBytes": BUCKET_LIMIT},
        "parameters": [AREA_DECLARATION],
        "resources": [
            {"id": "blocks", "name": "Blocks", "kind": "table", "format": "parquet",
             "path": "blocks/loop.parquet"},
            {"id": "parts", "name": "Parts", "kind": "table", "format": "parquet",
             "path": "parts/{part}.parquet"},
        ],
    })
    yield calls
    scan.listings.reset()


def _rows(client, auth) -> dict[str, dict]:
    import time

    for _ in range(100):
        body = client.get(f"/api/discovery/sources/{BUCKET_SOURCE}/search", headers=auth).get_json()
        assert "sources" in body, body
        if body["sources"][0]["status"] != "scanning":
            assert body["sources"][0]["status"] == "ok", body["sources"]
            return {row["resourceId"]: row for row in body["resources"]}
        time.sleep(0.05)
    raise AssertionError("the scan never finished")


class TestABucketRow:
    def test_a_parquet_row_takes_an_area(self, client, auth, bucket):
        rows = _rows(client, auth)
        assert [p["id"] for p in rows["blocks"]["parameters"]] == ["area"]
        assert [p["id"] for p in rows["parts"]["parameters"]] == ["area"]

    def test_a_row_over_the_limit_stays_addable_for_an_area_and_is_refused_whole(self, client, auth, bucket):
        assert _file("blocks.parquet").stat().st_size > BUCKET_LIMIT
        row = _rows(client, auth)["blocks"]
        assert row["acquirable"] is True and not row.get("unavailableReason"), row
        whole = _add(client, auth, BUCKET_SOURCE, "blocks")
        assert whole["status"] == "failed"
        assert "the limit here is" in whole["error"], whole["error"]

    def test_an_area_reads_only_the_row_groups_that_meet_it(self, client, auth, bucket):
        import geopandas as gpd

        _rows(client, auth)
        job = _add(client, auth, BUCKET_SOURCE, "blocks", parameters={"area": AREA})
        assert job["status"] == "completed", job
        dataset = job["dataset"]
        assert sorted(gpd.read_parquet(dataset["path"])["id"]) == F.INSIDE_BLOCKS
        assert dataset["discoverySource"]["parameters"] == {"area": AREA}
        footer, groups = _reads("blocks.parquet")
        # The listing gave the file's size: it is never probed.
        assert _ranges(bucket, f"{F.BUCKET}/blocks/loop.parquet") == [*footer, groups[0], groups[1]]

    def test_the_same_row_and_area_again_asks_nothing(self, client, auth, bucket):
        _rows(client, auth)
        first = _add(client, auth, BUCKET_SOURCE, "blocks", parameters={"area": AREA})["dataset"]
        bucket.clear()
        again = acquire(client, auth, BUCKET_SOURCE, "blocks", parameters={"area": AREA})
        assert again.status_code == 200, again.get_data(as_text=True)
        assert again.get_json()["dataset"]["id"] == first["id"]
        assert bucket == []

    def test_several_files_are_read_for_the_area_and_combined_as_geoparquet_with_their_fields(
        self, client, auth, bucket
    ):
        import geopandas as gpd

        _rows(client, auth)
        job = _add(client, auth, BUCKET_SOURCE, "parts", parameters={"area": AREA})
        assert job["status"] == "completed", job
        frame = gpd.read_parquet(job["dataset"]["path"])
        assert sorted(frame["id"]) == sorted(F.INSIDE_BLOCKS + F.INSIDE_PLAIN)
        assert dict(zip(frame["id"], frame["part"])) == {
            **{i: "a" for i in F.INSIDE_BLOCKS}, **{i: "b" for i in F.INSIDE_PLAIN},
        }
        assert frame.crs.equals("OGC:CRS84", ignore_axis_order=True)
        assert set(frame.geometry.geom_type) == {"Polygon"}
        west, south, east, north = frame.total_bounds
        assert F.TEST_BOX[0] <= west < east <= F.TEST_BOX[2]
        assert F.TEST_BOX[1] <= south < north <= F.TEST_BOX[3]


# ── the manifest ───────────────────────────────────────────────────────────


def test_a_link_or_bucket_source_may_declare_an_area_and_a_folder_may_not(tmp_path):
    """#608: the Direct URL, S3 and Hugging Face providers read an area; a
    folder's files are read whole."""
    resources = [{"id": "blocks", "name": "Blocks", "kind": "table", "format": "parquet",
                  "path": "blocks/{part}.parquet"}]
    common = {"id": "source.example.x", "name": "X", "version": "1.0.0", "compatibility": {"major": 1},
              "description": "X.", "publisher": "X", "auth": {"mode": "public"},
              "parameters": [AREA_DECLARATION]}
    link = a_manifest(provider={"type": "direct", "baseUrl": ""}, parameters=[AREA_DECLARATION],
                      capabilities={"search": False, "formats": ["parquet"]})
    s3 = {**common, "provider": {"type": "s3", "baseUrl": F.BUCKET, "options": {}}, "resources": resources}
    hf = {**common, "provider": {"type": "huggingface", "baseUrl": "https://huggingface.co",
                                 "options": {"repo": "example/blocks"}}, "resources": resources}
    for raw in (link, s3, hf):
        manifest = M._parse_manifest(raw, where="manifest.json")
        assert [p.id for p in manifest.parameters] == ["area"]
    folder = {**common, "provider": {"type": "folder", "root": str(tmp_path)}, "resources": resources}
    with pytest.raises(M.ManifestError, match="reads no parameter named area"):
        M._parse_manifest(folder, where="manifest.json")


def test_the_corpus_is_written_from_its_module():
    """The ranges, the listings and their entries are what
    ``remote_parquet_fixture.py`` writes from the GeoParquet files committed."""
    index = json.loads(F.INDEX.read_text(encoding="utf-8"))
    for key, (name, body, entry) in F.documents().items():
        assert index.get(key) == entry, key
        assert (F.ROOT / name).read_bytes() == body, name
