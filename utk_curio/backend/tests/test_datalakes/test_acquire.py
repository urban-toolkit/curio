"""Downloading a portal resource into the Data Catalog.

The whole point of this phase: what comes out the far end is an **ordinary
dataset**, so nothing downstream has to learn that portals exist. These run the
real stack - route, service, acquire, provider, format ladder, the datasets
importer - with only the socket replaced by the recorded corpus.
"""

from __future__ import annotations

import json
import time

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
        body = client.get(f"/api/datalakes/jobs/{job_id}", headers=auth).get_json()
        if body["status"] in ("completed", "failed", "refused", "cancelled"):
            return body
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never finished: {body}")


def acquire(client, auth, source, resource, **body):
    return client.post(
        f"/api/datalakes/sources/{source}/resources/{resource}/acquire",
        headers=auth,
        json=body,
    )


CHICAGO = "lake.cityofchicago.data-portal@1"
GEOSAMPA = "lake.saopaulo.geosampa@1"


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
        rows = [r for r in listing["items"] if (r.get("lakeSource") or {})]
        assert rows, "the downloaded dataset should be in the Data Catalog"
        assert rows[0]["lakeSource"]["lakeId"] == CHICAGO

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
    def test_the_lake_source_block_records_where_it_came_from(self, client, auth, live):
        job = wait_for(
            client, auth,
            acquire(client, auth, CHICAGO, "ijzp-q8t2", format="csv").get_json()["jobId"],
        )
        lake = job["dataset"]["lakeSource"]
        assert lake["lakeId"] == CHICAGO
        assert lake["lakeName"] == "City of Chicago Data Portal"
        assert lake["resourceId"] == "ijzp-q8t2"
        assert lake["resourceUrl"].endswith("ijzp-q8t2.csv")
        assert len(lake["contentSha256"]) == 64
        assert lake["fetchedAt"]

    def test_it_survives_a_round_trip_through_the_manifest(self, client, auth, live):
        """Written to disk and read back by the catalog scan, not just held in
        the response."""
        job = wait_for(
            client, auth,
            acquire(client, auth, CHICAGO, "ijzp-q8t2", format="csv").get_json()["jobId"],
        )
        dataset_id = job["dataset"]["id"]
        again = client.get(f"/api/datasets/{dataset_id}", headers=auth).get_json()
        assert again["lakeSource"]["resourceId"] == "ijzp-q8t2"

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
        from utk_curio.backend.app.datalakes.infrastructure import transport as T

        def _boom(*a, **k):
            raise AssertionError("a held dataset must not be fetched again")

        monkeypatch.setattr(T.FixtureLakeTransport, "download", _boom)
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
            acquire(client, auth, "lake.test.fail@1", "https://portal.test/oversized.csv")
            .get_json()["jobId"],
        )
        assert job["status"] == "failed"
        assert "too large" in job["error"].lower() or "oversized" in job["error"].lower()

    def test_an_archive_is_refused_with_advice(self, client, auth, failing):
        job = wait_for(
            client, auth,
            acquire(client, auth, "lake.test.fail@1", "https://portal.test/archive.zip")
            .get_json()["jobId"],
        )
        assert job["status"] == "failed"
        assert "archive" in job["error"]

    def test_a_declared_length_over_the_bound_never_reads_a_body(self, client, auth, failing):
        job = wait_for(
            client, auth,
            acquire(client, auth, "lake.test.fail@1", "https://portal.test/declares-huge.csv")
            .get_json()["jobId"],
        )
        assert job["status"] == "failed"
        assert "declares" in job["error"]

    def test_an_unreachable_portal_fails_the_job_not_the_request(self, client, auth, failing):
        res = acquire(client, auth, "lake.test.fail@1", "https://portal.test/timeout.csv")
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
            f"/api/datalakes/sources/{CHICAGO}/search?q=crimes", headers=auth
        ).get_json()["resources"]
        row = next(r for r in before if r["resourceId"] == "ijzp-q8t2")
        assert row["alreadyHeldDatasetId"] is None

        job = acquire(client, auth, CHICAGO, "ijzp-q8t2", format="csv").get_json()
        dataset_id = wait_for(client, auth, job["jobId"])["datasetId"]

        after = client.get(
            f"/api/datalakes/sources/{CHICAGO}/search?q=crimes", headers=auth
        ).get_json()["resources"]
        row = next(r for r in after if r["resourceId"] == "ijzp-q8t2")
        assert row["alreadyHeldDatasetId"] == dataset_id

    def test_a_federated_row_knows_it_too(self, client, auth, live):
        job = acquire(client, auth, CHICAGO, "ijzp-q8t2", format="csv").get_json()
        dataset_id = wait_for(client, auth, job["jobId"])["datasetId"]

        rows = client.get("/api/datalakes/search?q=crimes", headers=auth).get_json()[
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
            f"/api/datalakes/sources/{CHICAGO}/search?q=crimes",
            headers={"Authorization": f"Bearer {token}"},
        ).get_json()["resources"]
        assert all(r["alreadyHeldDatasetId"] is None for r in rows)


CRIMES_CSV = (
    __import__("pathlib").Path(__file__).resolve().parent / "fixtures" / "download" / "crimes.csv"
)
CRIMES_URL = "https://data.cityofchicago.org/resource/ijzp-q8t2.csv"


def import_by_hand(client, auth, body: bytes, lake_source: dict | None):
    """The card's Import: a file the person downloaded, and where it came from."""
    import io

    data = {"file": (io.BytesIO(body), "crimes.csv")}
    if lake_source is not None:
        data["lakeSource"] = json.dumps(lake_source)
    return client.post("/api/datasets/import", headers=auth, data=data,
                       content_type="multipart/form-data")


class TestOneDatasetWhicheverPathCameFirst:
    """A file downloaded by hand and the same file the Data Lake fetched are
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
                               {"lakeId": CHICAGO, "resourceId": "ijzp-q8t2"})
        assert other.status_code == 200
        assert other.get_json()["id"] == job["dataset"]["id"]
