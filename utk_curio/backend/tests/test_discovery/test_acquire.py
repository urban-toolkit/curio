"""Downloading a portal resource into the Data Catalog.

The whole point of this phase: what comes out the far end is an **ordinary
dataset**, so nothing downstream has to learn that portals exist. These run the
real stack - route, service, acquire, provider, format ladder, the datasets
importer - with only the socket replaced by the recorded corpus.
"""

from __future__ import annotations

import json
import time
from urllib.parse import urlsplit

import pytest


@pytest.fixture()
def auth(user_and_token):
    _user, token = user_and_token
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def live(app, shipped_root, fixture_corpus):
    return app


@pytest.fixture()
def failing(app, failing_source, fixture_corpus):
    """A direct-URL source whose resource ids ARE the recorded failure URLs."""
    return app


def wait_for(client, auth, job_id, *, timeout=10.0):
    """Poll a job to a terminal state, the way the page does."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/discovery/jobs/{job_id}", headers=auth).get_json()
        if body["status"] in ("completed", "failed", "refused", "cancelled"):
            return body
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never finished: {body}")


def acquire(client, auth, source, resource, **body):
    return client.post(
        f"/api/discovery/sources/{source}/resources/{resource}/acquire",
        headers=auth,
        json=body,
    )


CHICAGO = "source.cityofchicago.data-portal@1"
GEOSAMPA = "source.saopaulo.geosampa@1"


class TestItBecomesAnOrdinaryDataset:
    def test_a_csv_lands_in_the_data_catalog(self, client, auth, live):
        res = acquire(client, auth, CHICAGO, "ijzp-q8t2", format="csv")
        assert res.status_code == 202, res.get_data(as_text=True)
        job = wait_for(client, auth, res.get_json()["jobId"])
        assert job["status"] == "completed", job
        dataset = job["dataset"]
        assert dataset["format"] == "csv"
        assert dataset["rowCount"] == 2

    def test_it_is_a_normal_catalog_row_with_a_portable_loader(self, client, auth, live):
        """Nothing downstream needs to know it came from a portal: it has the
        same loader every imported dataset gets."""
        job = wait_for(
            client, auth,
            acquire(client, auth, CHICAGO, "ijzp-q8t2", format="csv").get_json()["jobId"],
        )
        dataset = job["dataset"]
        assert dataset["origin"] == "imported"
        snippet = dataset["loaderSnippet"]
        assert "curio_dataset_path(" in snippet["code"]
        assert "pd.read_csv" in snippet["code"]

    def test_it_shows_up_in_the_dataset_catalog_listing(self, client, auth, live):
        wait_for(
            client, auth,
            acquire(client, auth, CHICAGO, "ijzp-q8t2", format="csv").get_json()["jobId"],
        )
        listing = client.get("/api/datasets/catalog", headers=auth).get_json()
        rows = [r for r in listing["items"] if (r.get("discoverySource") or {})]
        assert rows, "the downloaded dataset should be in the Data Catalog"
        assert rows[0]["discoverySource"]["sourceId"] == CHICAGO

    def test_a_geojson_layer_lands_as_geojson(self, client, auth, live):
        job = wait_for(
            client, auth,
            acquire(
                client, auth, GEOSAMPA, "geoportal%3Abicicletario_paraciclo",
                format="geojson",
            ).get_json()["jobId"],
        )
        assert job["status"] == "completed", job
        assert job["dataset"]["format"] == "geojson"
        # The portal served it as application/json; the declared format is what
        # keeps it from being filed as a plain dict.
        assert job["dataset"]["featureCount"] == 1


class TestProvenance:
    def test_the_discovery_source_block_records_where_it_came_from(self, client, auth, live):
        job = wait_for(
            client, auth,
            acquire(client, auth, CHICAGO, "ijzp-q8t2", format="csv").get_json()["jobId"],
        )
        discovered = job["dataset"]["discoverySource"]
        assert discovered["sourceId"] == CHICAGO
        assert discovered["sourceName"] == "City of Chicago Data Portal"
        assert discovered["resourceId"] == "ijzp-q8t2"
        assert urlsplit(discovered["resourceUrl"]).path.endswith("/resource/ijzp-q8t2.csv")
        assert len(discovered["contentSha256"]) == 64
        assert discovered["fetchedAt"]

    def test_it_survives_a_round_trip_through_the_manifest(self, client, auth, live):
        """Written to disk and read back by the catalog scan, not just held in
        the response."""
        job = wait_for(
            client, auth,
            acquire(client, auth, CHICAGO, "ijzp-q8t2", format="csv").get_json()["jobId"],
        )
        dataset_id = job["dataset"]["id"]
        again = client.get(f"/api/datasets/{dataset_id}", headers=auth).get_json()
        assert again["discoverySource"]["resourceId"] == "ijzp-q8t2"

    def test_it_is_imported_not_a_new_origin(self, client, auth, live):
        """A fifth origin would ripple through labels, facets, filters and
        dedup for a distinction this block already carries."""
        job = wait_for(
            client, auth,
            acquire(client, auth, CHICAGO, "ijzp-q8t2", format="csv").get_json()["jobId"],
        )
        assert job["dataset"]["origin"] == "imported"


class TestIdempotency:
    def test_a_second_download_answers_from_what_you_hold(self, client, auth, live):
        first = wait_for(
            client, auth,
            acquire(client, auth, CHICAGO, "ijzp-q8t2", format="csv").get_json()["jobId"],
        )
        res = acquire(client, auth, CHICAGO, "ijzp-q8t2", format="csv")
        # 200 rather than 202: there is no work to do.
        assert res.status_code == 200
        body = res.get_json()
        assert body["alreadyPresent"] is True
        assert body["dataset"]["id"] == first["dataset"]["id"]

    def test_the_second_ask_reaches_no_portal_at_all(self, client, auth, live, monkeypatch):
        """The reason the resource id is recorded: re-clicking Download costs
        the portal nothing."""
        wait_for(
            client, auth,
            acquire(client, auth, CHICAGO, "ijzp-q8t2", format="csv").get_json()["jobId"],
        )
        from utk_curio.backend.app.discovery.infrastructure import transport as T

        def _boom(*a, **k):
            raise AssertionError("a held dataset must not be fetched again")

        monkeypatch.setattr(T.FixtureDiscoveryTransport, "download", _boom)
        res = acquire(client, auth, CHICAGO, "ijzp-q8t2", format="csv")
        assert res.status_code == 200 and res.get_json()["alreadyPresent"] is True

    def test_a_different_format_is_a_different_dataset(self, client, auth, live):
        """Holding the CSV is not holding the GeoJSON."""
        wait_for(
            client, auth,
            acquire(client, auth, CHICAGO, "ijzp-q8t2", format="csv").get_json()["jobId"],
        )
        res = acquire(client, auth, CHICAGO, "ijzp-q8t2", format="geojson")
        # No fixture for the geojson export, so it fails - but it TRIED, which
        # is the point: it was not short-circuited as already held.
        assert res.status_code == 202
        job = wait_for(client, auth, res.get_json()["jobId"])
        assert job["status"] == "failed"

    def test_refresh_forces_a_fetch_and_reports_unchanged(self, client, auth, live):
        first = wait_for(
            client, auth,
            acquire(client, auth, CHICAGO, "ijzp-q8t2", format="csv").get_json()["jobId"],
        )
        res = acquire(client, auth, CHICAGO, "ijzp-q8t2", format="csv", refresh=True)
        assert res.status_code == 202
        job = wait_for(client, auth, res.get_json()["jobId"])
        assert job["status"] == "completed"
        # Same bytes, so no second row: the download was paid for, a duplicate
        # dataset would not be.
        assert job["unchanged"] is True
        assert job["dataset"]["id"] == first["dataset"]["id"]


class TestFailuresAreTheUsersAnswer:
    def test_an_oversized_resource_says_so(self, client, auth, failing):
        job = wait_for(
            client, auth,
            acquire(client, auth, "source.test.fail@1", "https://portal.test/oversized.csv")
            .get_json()["jobId"],
        )
        assert job["status"] == "failed"
        assert "too large" in job["error"].lower() or "oversized" in job["error"].lower()

    def test_a_zip_that_is_not_a_zip_is_refused(self, client, auth, failing):
        """Its URL and its content type both say zip, and its bytes are CSV text.

        This test used to assert that any zip is refused. Curio now unpacks a
        zip, so it asserts what is still refused about this fixture: a body
        that claims to be an archive and is not one.
        """
        job = wait_for(
            client, auth,
            acquire(client, auth, "source.test.fail@1", "https://portal.test/archive.zip")
            .get_json()["jobId"],
        )
        assert job["status"] == "failed"
        assert "bytes are not a zip archive" in job["error"]

    def test_a_declared_length_over_the_bound_never_reads_a_body(self, client, auth, failing):
        job = wait_for(
            client, auth,
            acquire(client, auth, "source.test.fail@1", "https://portal.test/declares-huge.csv")
            .get_json()["jobId"],
        )
        assert job["status"] == "failed"
        assert "declares" in job["error"]

    def test_a_tif_that_is_not_a_tiff_is_refused(self, client, auth, failing):
        """Its URL and its content type both say TIFF, and its bytes are CSV text."""
        job = wait_for(
            client, auth,
            acquire(client, auth, "source.test.fail@1", "https://portal.test/not-a-tiff.tif")
            .get_json()["jobId"],
        )
        assert job["status"] == "failed"
        assert "is not a TIFF file" in job["error"]

    def test_an_unreachable_portal_fails_the_job_not_the_request(self, client, auth, failing):
        res = acquire(client, auth, "source.test.fail@1", "https://portal.test/timeout.csv")
        assert res.status_code == 202, "starting the job must still succeed"
        job = wait_for(client, auth, res.get_json()["jobId"])
        assert job["status"] == "failed"
        assert "timeout" in job["error"]


class TestASearchRowKnowsWhatYouAlreadyHold:
    """The badge that stops a user downloading the same thing twice.

    ``describe`` answered this from the start; search did not, so every row in
    a result list offered Download regardless of what the account held, and
    the only way to find out was to download it again. A browser run found it:
    the row never showed "In your Data Catalog".
    """

    def test_a_scoped_search_row_points_at_the_dataset_you_hold(
        self, client, auth, live
    ):
        before = client.get(
            f"/api/discovery/sources/{CHICAGO}/search?q=crimes", headers=auth
        ).get_json()["resources"]
        row = next(r for r in before if r["resourceId"] == "ijzp-q8t2")
        assert row["alreadyHeldDatasetId"] is None

        job = acquire(client, auth, CHICAGO, "ijzp-q8t2", format="csv").get_json()
        dataset_id = wait_for(client, auth, job["jobId"])["datasetId"]

        after = client.get(
            f"/api/discovery/sources/{CHICAGO}/search?q=crimes", headers=auth
        ).get_json()["resources"]
        row = next(r for r in after if r["resourceId"] == "ijzp-q8t2")
        assert row["alreadyHeldDatasetId"] == dataset_id

    def test_a_federated_row_knows_it_too(self, client, auth, live):
        job = acquire(client, auth, CHICAGO, "ijzp-q8t2", format="csv").get_json()
        dataset_id = wait_for(client, auth, job["jobId"])["datasetId"]

        rows = client.get("/api/discovery/search?q=crimes", headers=auth).get_json()[
            "resources"
        ]
        held = [r for r in rows if r["alreadyHeldDatasetId"]]
        assert [r["resourceId"] for r in held] == ["ijzp-q8t2"]
        assert held[0]["alreadyHeldDatasetId"] == dataset_id

    def test_another_account_is_not_told_what_you_hold(self, client, auth, live, app):
        """The index is the asking user's store, never a shared one."""
        job = acquire(client, auth, CHICAGO, "ijzp-q8t2", format="csv").get_json()
        wait_for(client, auth, job["jobId"])

        from utk_curio.backend.app.users import repositories as user_repo
        from utk_curio.backend.extensions import db

        with app.app_context():
            other = user_repo.create_user(username="someoneelse", name="Someone Else")
            token = user_repo.create_session(other.id).token
            db.session.commit()

        rows = client.get(
            f"/api/discovery/sources/{CHICAGO}/search?q=crimes",
            headers={"Authorization": f"Bearer {token}"},
        ).get_json()["resources"]
        assert all(r["alreadyHeldDatasetId"] is None for r in rows)


CRIMES_CSV = (
    __import__("pathlib").Path(__file__).resolve().parent / "fixtures" / "download" / "crimes.csv"
)
CRIMES_URL = "https://data.cityofchicago.org/resource/ijzp-q8t2.csv"


def import_by_hand(client, auth, body: bytes, discovery_source: dict | None):
    """The card's Import: a file the person downloaded, and where it came from."""
    import io

    data = {"file": (io.BytesIO(body), "crimes.csv")}
    if discovery_source is not None:
        data["discoverySource"] = json.dumps(discovery_source)
    return client.post("/api/datasets/import", headers=auth, data=data,
                       content_type="multipart/form-data")


class TestOneDatasetWhicheverPathCameFirst:
    """A file downloaded by hand and the same file the Discovery Catalog fetched are
    one dataset, matched by the resource or by the bytes, in either order."""

    def test_a_hand_import_is_found_by_a_later_download(self, client, auth, live):
        manual = import_by_hand(client, auth, CRIMES_CSV.read_bytes(), {"resourceUrl": CRIMES_URL})
        assert manual.status_code == 201
        job = wait_for(
            client, auth,
            acquire(client, auth, CHICAGO, "ijzp-q8t2", format="csv").get_json()["jobId"],
        )
        assert job["status"] == "completed" and job["alreadyPresent"] is True
        assert job["dataset"]["id"] == manual.get_json()["id"]

    def test_a_download_is_found_by_a_later_hand_import(self, client, auth, live):
        job = wait_for(
            client, auth,
            acquire(client, auth, CHICAGO, "ijzp-q8t2", format="csv").get_json()["jobId"],
        )
        again = import_by_hand(client, auth, CRIMES_CSV.read_bytes(), {"resourceUrl": CRIMES_URL})
        assert again.status_code == 200
        assert again.get_json()["alreadyPresent"] is True
        assert again.get_json()["id"] == job["dataset"]["id"]

    def test_a_held_resource_is_found_by_its_coordinate(self, client, auth, live):
        job = wait_for(
            client, auth,
            acquire(client, auth, CHICAGO, "ijzp-q8t2", format="csv").get_json()["jobId"],
        )
        other = import_by_hand(client, auth, b"a,b\n1,2\n",
                               {"sourceId": CHICAGO, "resourceId": "ijzp-q8t2"})
        assert other.status_code == 200
        assert other.get_json()["id"] == job["dataset"]["id"]

    def test_every_remote_path_records_the_same_origin(self, client, auth, live):
        """The seam: both ways a remote file enters the Data Catalog run the one
        importer and leave the same origin fields, so either can be found by
        the other. Only the socket is fake here; nothing is injected."""
        import hashlib

        job = wait_for(
            client, auth,
            acquire(client, auth, CHICAGO, "ijzp-q8t2", format="csv").get_json()["jobId"],
        )
        other = b"x,y\n1,2\n"
        manual = import_by_hand(client, auth, other, {"resourceUrl": "https://a.example/xy.csv"})
        fetched = job["dataset"]["discoverySource"]
        by_hand = manual.get_json()["discoverySource"]
        for origin in (fetched, by_hand):
            assert {"resourceUrl", "fetchedAt", "contentSha256"} <= set(origin)
        assert fetched["contentSha256"] == hashlib.sha256(CRIMES_CSV.read_bytes()).hexdigest()
        assert by_hand["contentSha256"] == hashlib.sha256(other).hexdigest()
        assert by_hand["manual"] is True and "manual" not in fetched


class TestTheDownloadNeverPassesThroughMemory:
    def test_the_temp_file_is_moved_not_read(self, client, auth, live, monkeypatch):
        """The staged download is handed to the Data Catalog as a file.

        Reading it back into memory is what capped a download at the size of a
        comfortable allocation.
        """
        from pathlib import Path

        original = Path.read_bytes

        def guarded(self):
            if self.name.endswith(".part"):
                raise AssertionError(f"{self} was read into memory")
            return original(self)

        monkeypatch.setattr(Path, "read_bytes", guarded)
        job = wait_for(
            client, auth,
            acquire(client, auth, CHICAGO, "ijzp-q8t2", format="csv").get_json()["jobId"],
        )
        assert job["status"] == "completed", job
        assert job["dataset"]["rowCount"] == 2


# ── archives (#608) ─────────────────────────────────────────────────────────
#
# Every file below is served by the recorded corpus at https://portal.test/<name>
# and downloaded through the shipped Direct URL source, the way a pasted link is.

DIRECT = "source.curio.direct-url@1"
ARCHIVES = (
    __import__("pathlib").Path(__file__).resolve().parent / "fixtures" / "download" / "archives"
)


def fetch(client, auth, name: str, **body) -> dict:
    """Download https://portal.test/<name> through the Direct URL source."""
    res = acquire(client, auth, DIRECT, f"https://portal.test/{name}", **body)
    assert res.status_code == 202, res.get_data(as_text=True)
    return wait_for(client, auth, res.get_json()["jobId"], timeout=90.0)


def catalog_items(client, auth, **params) -> list[dict]:
    return client.get("/api/datasets/catalog", headers=auth, query_string=params).get_json()["items"]


def sha256_of(name: str) -> str:
    import hashlib

    return hashlib.sha256((ARCHIVES / name).read_bytes()).hexdigest()


def gtfs_layers(client, auth) -> dict[str, dict]:
    items = [
        i for i in catalog_items(client, auth)
        if str(i.get("groupId") or "").startswith("gtfs.x")
    ]
    assert len({i["groupId"] for i in items}) == 1, items
    return {i["layerName"]: i for i in items}


class TestArchivesAreUnpacked:
    def test_a_gzipped_csv_lands_as_its_csv(self, client, auth, live):
        """LODES publishes each table as one gzipped CSV."""
        from pathlib import Path

        job = fetch(client, auth, "il_wac_S000_JT00_2022.csv.gz")
        assert job["status"] == "completed", job
        dataset = job["dataset"]
        assert dataset["format"] == "csv"
        assert dataset["rowCount"] == 3
        assert dataset["path"].endswith(".csv")
        assert Path(dataset["path"]).read_text(encoding="utf-8").startswith("w_geocode,C000")
        # Where it came from is the archive: the same link and the same bytes
        # are the same download.
        discovered = dataset["discoverySource"]
        assert discovered["sourceId"] == DIRECT
        assert discovered["resourceUrl"] == "https://portal.test/il_wac_S000_JT00_2022.csv.gz"
        assert discovered["contentSha256"] == sha256_of("il_wac_S000_JT00_2022.csv.gz")

    def test_a_zip_of_one_geotiff_lands_as_the_geotiff(self, client, auth, live):
        """A GHSL tile is a zip holding one GeoTIFF and its documentation."""
        from pathlib import Path

        job = fetch(client, auth, "ghsl_tile.zip")
        assert job["status"] == "completed", job
        dataset = job["dataset"]
        assert dataset["format"] == "geotiff"
        assert Path(dataset["path"]).read_bytes()[:4] in (b"II*\x00", b"MM\x00*")

    def test_an_archive_served_as_octet_stream_is_known_by_its_bytes(self, client, auth, live):
        """No suffix and a generic content type: the zip signature decides."""
        job = fetch(client, auth, "files-7731")
        assert job["status"] == "completed", job
        assert job["dataset"]["format"] == "geotiff"

    def test_a_zipped_shapefile_lands_as_geoparquet_in_4326(self, client, auth, live):
        """A TIGER/Line file: the .shp with its .dbf, .shx, .prj and .cpg, in a
        projected coordinate system, and metadata beside it."""
        import geopandas as gpd

        job = fetch(client, auth, "tl_2022_17_tabblock20.zip")
        assert job["status"] == "completed", job
        dataset = job["dataset"]
        assert dataset["format"] == "parquet"
        frame = gpd.read_parquet(dataset["path"])
        assert frame.crs.to_epsg() == 4326
        assert list(frame["GEOID20"]) == ["170318391001000", "170318391001001"]
        west, south, east, north = frame.total_bounds
        assert -87.64 < west < east < -87.62 and 41.88 < south < north < 41.89

    def test_a_gtfs_feed_lands_as_one_group_of_layers(self, client, auth, live):
        import geopandas as gpd
        import pandas as pd

        job = fetch(client, auth, "google_transit.zip")
        assert job["status"] == "completed", job
        assert job["dataset"]["importedDatasetCount"] == 7

        layers = gtfs_layers(client, auth)
        assert set(layers) == {
            "agency", "calendar", "routes", "shapes", "stop_times", "stops", "trips",
        }
        for name, item in layers.items():
            assert item["format"] == "parquet", name
            assert item["title"] == f"google_transit ({name})"
            assert item["discoverySource"]["sourceId"] == DIRECT
            assert item["discoverySource"]["contentSha256"] == sha256_of("google_transit.zip")

        # Stops are points; ids keep their leading zeros, and a stop GTFS
        # allows without coordinates keeps its row with no geometry.
        stops = gpd.read_parquet(layers["stops"]["path"])
        assert stops.crs.to_epsg() == 4326
        assert list(stops["stop_id"]) == ["0042", "0043", "0100"]
        assert list(stops.geometry.geom_type[:2]) == ["Point", "Point"]
        assert stops.geometry.iloc[2] is None
        assert (stops.geometry.iloc[0].x, stops.geometry.iloc[0].y) == (-87.630886, 41.885737)

        # Shapes are lines, one per shape_id, in shape_pt_sequence order read
        # as a number (2, 5, 10); a shape of one point is not a line.
        shapes = gpd.read_parquet(layers["shapes"]["path"])
        assert list(shapes["shape_id"]) == ["S01"]
        assert list(shapes.geometry.iloc[0].coords) == [
            (-87.630886, 41.885737), (-87.629, 41.8857), (-87.627835, 41.88574),
        ]

        # Every other table is a table, read as text.
        routes = pd.read_parquet(layers["routes"]["path"])
        assert routes["route_id"].tolist() == ["007"]
        assert "geometry" not in routes.columns
        stop_times = pd.read_parquet(layers["stop_times"]["path"])
        assert stop_times["trip_id"].tolist() == ["0001", "0001"]
        assert stop_times["stop_sequence"].tolist() == [1, 2]

        # The Data Catalog shows the feed as one GTFS entry.
        grouped = catalog_items(client, auth, groupOsm="true")
        group_id = layers["stops"]["groupId"]
        group = next(i for i in grouped if i["id"] == group_id)
        assert group["format"] == "gtfs"
        assert group["title"] == "google_transit"
        assert sorted(group["groupLayerIds"]) == sorted(i["id"] for i in layers.values())

    def test_a_gtfs_feed_in_one_top_folder_is_found(self, client, auth, live):
        """Some feeds are zipped with their folder; macOS litter is skipped.

        Titled as the Direct URL page titles a pasted link, by its last
        segment: the group is named without the .zip."""
        job = fetch(client, auth, "feed.zip", title="feed.zip")
        assert job["status"] == "completed", job
        layers = gtfs_layers(client, auth)
        assert set(layers) == {"agency", "routes", "stops"}
        assert layers["stops"]["title"] == "feed (stops)"


class TestArchivesThatAreRefused:
    def test_an_archive_curio_does_not_unpack_is_refused_before_any_request(
        self, client, auth, live, monkeypatch
    ):
        from utk_curio.backend.app.discovery.infrastructure import transport as T

        def _never(*_a, **_k):
            raise AssertionError("a .7z must be refused before anything is downloaded")

        monkeypatch.setattr(T.FixtureDiscoveryTransport, "download", _never)
        job = fetch(client, auth, "bundle.7z")
        assert job["status"] == "failed"
        assert "does not unpack" in job["error"]
        assert "one data file, a shapefile or a GTFS feed" in job["error"]

    def test_one_known_only_by_its_content_type_is_refused_before_its_body(
        self, client, auth, live, monkeypatch
    ):
        """No suffix to go by, so the refusal waits for the headers, and comes
        before a single body byte reaches the disk."""
        from utk_curio.backend.app.discovery.infrastructure import transport as T

        original = T.FixtureDiscoveryTransport.download
        received: list[int] = []

        def spying(self, url, sink, **kwargs):
            def counting(chunk):
                received.append(len(chunk))
                sink(chunk)

            return original(self, url, counting, **kwargs)

        monkeypatch.setattr(T.FixtureDiscoveryTransport, "download", spying)
        job = fetch(client, auth, "export")
        assert job["status"] == "failed"
        assert "tar" in job["error"] and "does not unpack" in job["error"]
        assert received == []

    def test_several_data_files_are_refused_naming_them(self, client, auth, live):
        job = fetch(client, auth, "two_tables.zip")
        assert job["status"] == "failed"
        assert "a.csv" in job["error"] and "b.csv" in job["error"]
        assert "one data file, a shapefile or a GTFS feed" in job["error"]


class TestUnpackingIsBounded:
    def test_a_member_outside_the_archive_is_refused(self, client, auth, live):
        job = fetch(client, auth, "slip.zip")
        assert job["status"] == "failed"
        assert "'..'" in job["error"]

    def test_a_symbolic_link_is_refused(self, client, auth, live):
        job = fetch(client, auth, "link.zip")
        assert job["status"] == "failed"
        assert "symbolic link" in job["error"]

    def test_an_archive_inside_an_archive_is_refused(self, client, auth, live):
        job = fetch(client, auth, "nested.zip")
        assert job["status"] == "failed"
        assert "another archive" in job["error"]

    def test_a_member_that_expands_beyond_any_data_file_is_refused(self, client, auth, live):
        """2 MiB of one repeated line in 2 KiB: a thousand to one."""
        job = fetch(client, auth, "bomb.zip")
        assert job["status"] == "failed"
        assert "expands more than" in job["error"]

    def test_the_unpacked_bytes_are_counted_and_capped(self, client, auth, live, monkeypatch):
        monkeypatch.setattr(
            "utk_curio.backend.app.discovery.application.archives.MAX_UNPACKED_BYTES", 64
        )
        job = fetch(client, auth, "il_wac_S000_JT00_2022.csv.gz")
        assert job["status"] == "failed"
        assert "unpacks to more than 64 bytes" in job["error"]

    def test_the_member_count_is_capped(self, client, auth, live, monkeypatch):
        monkeypatch.setattr(
            "utk_curio.backend.app.discovery.application.archives.MAX_ARCHIVE_MEMBERS", 3
        )
        job = fetch(client, auth, "google_transit.zip")
        assert job["status"] == "failed"
        assert "7 files, more than the 3" in job["error"]
