"""The SAGE-IDOT rail crossings source, on the recorded corpus: no socket opens.

``scripts/record_discovery_fixtures.py --only idot`` listed the bucket on
data.urbantk.org live, 168,023 objects, a folder at a time as the listing reads
it: the crossings, each crossing's months, then each month's snapshots and each
crossing's data folder, each kept as one page of its first and last file. No
file beside those is listed, such as ``sample/``'s. Each monthly JSON Lines file is
indexed to a synthetic stand-in in the real files' format
(``fixtures/download/storage/idot/detections.jsonl``), and the one empty file
in the bucket, W06E's for March 2026, to an empty body. The ``records``
resource lists the same files as files for node code, whose add reads none of
them.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from utk_curio.backend.tests.test_discovery.test_storage_buckets import add, listing

SOURCE = "source.sage.idot-crossings@1"
JULY = "2025-07-01T00:00:00"

#: The months of data the recorded listing keeps: each crossing's first and last.
DATA_MONTHS = [
    ("W042", JULY), ("W042", "2025-12-01T00:00:00"),
    ("W065", JULY), ("W065", "2026-03-01T00:00:00"),
    ("W06E", JULY), ("W06E", "2026-03-01T00:00:00"),
]

#: How many months of snapshots each crossing has in the bucket.
SNAPSHOT_MONTHS = {"W042": 6, "W065": 9, "W06E": 8}


def row_id(resource: str, crossing: str, month: str) -> str:
    return f"{resource}@crossing={crossing};month={month}"


@pytest.fixture()
def auth(user_and_token):
    _user, token = user_and_token
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _fresh_listings():
    from utk_curio.backend.app.discovery.application import scan

    scan.listings.reset()
    yield
    scan.listings.reset()


def _added(client, auth, resource_id):
    job = add(client, auth, SOURCE, resource_id)
    assert job["status"] == "completed", job.get("error")
    return job["dataset"]


class TestTheListing:
    def test_each_crossings_month_is_a_row_of_each_resource(
        self, client, auth, app, shipped_root, fixture_corpus
    ):
        body = listing(client, auth, SOURCE)
        assert body["sources"][0]["status"] == "ok", body["sources"]
        rows = {r["resourceId"]: r for r in body["resources"]}
        snapshots = [r for r in rows.values() if r["resourceId"].startswith("snapshots@")]
        for crossing, months in SNAPSHOT_MONTHS.items():
            assert sum(r["resourceId"].startswith(f"snapshots@crossing={crossing};") for r in snapshots) == months
        # A row's name gives its month as the folder does; its id keeps the whole time.
        july = rows[row_id("snapshots", "W042", JULY)]
        assert (july["name"], july["kind"], july["fileCount"]) == ("Crossing snapshots · W042, 2025-07", "images", 2)
        for resource, name, kind in (
            ("detections", "Detections", "table"), ("frames", "Frames by model", "table"),
            ("records", "Detection records", "files"),
        ):
            assert {r for r in rows if r.startswith(f"{resource}@")} == {
                row_id(resource, crossing, month) for crossing, month in DATA_MONTHS
            }
            row = rows[row_id(resource, "W042", JULY)]
            assert (row["name"], row["kind"], row["fileCount"]) == (f"{name} · W042, 2025-07", kind, 1)
        # A files row has no preview, so no sample files to draw.
        assert rows[row_id("records", "W042", JULY)]["samples"] == []

    def test_a_month_over_the_default_download_limit_says_why(
        self, client, auth, app, shipped_root, fixture_corpus
    ):
        """Most months are over 1 GiB, the limit when the operator sets none;
        dev and stable take 2048 MB (``--discovery-max-download-mb``)."""
        rows = {r["resourceId"]: r for r in listing(client, auth, SOURCE)["resources"]}
        december = rows[row_id("detections", "W042", "2025-12-01T00:00:00")]
        assert december["acquirable"] is False
        assert "1,310,434,728 bytes" in december["unavailableReason"], december["unavailableReason"]
        assert rows[row_id("detections", "W042", JULY)]["unavailableReason"] is None

    def test_a_listing_past_its_folders_says_it_met_them(
        self, client, auth, app, shipped_root, fixture_corpus, monkeypatch
    ):
        """Its rows are in more folders than a bound of 5, and the page names
        that bound, not the files a row or a listing holds."""
        from utk_curio.backend.app.discovery.application import scan

        monkeypatch.setattr(scan, "MAX_FOLDERS", 5)
        body = listing(client, auth, SOURCE)
        assert body["truncated"] is True
        assert body.get("cutShort") == (
            "This source holds more files than are listed here: a listing reads the files of up to 5 folders."
        ), "the listing does not say which of its limits it met"

    def test_a_listing_past_its_files_says_it_met_them(
        self, client, auth, app, shipped_root, fixture_corpus, monkeypatch
    ):
        from utk_curio.backend.app.discovery.application import scan

        monkeypatch.setattr(scan, "MAX_LISTING_FILES", 10)
        body = listing(client, auth, SOURCE)
        assert body["truncated"] is True
        assert body.get("cutShort") == (
            "This source holds more files than are listed here: a listing holds up to 10 files, all its rows' together."
        ), "the listing does not say which of its limits it met"


class TestTheRecords:
    def test_a_months_records_are_its_file_left_in_the_bucket(self, client, auth, app, shipped_root, fixture_corpus):
        """A month's records add as a collection of its one JSON Lines file,
        indexed where it is: the add reads none of it, so a month over the
        download limit adds as well, and node code opens it from its row's path."""
        import pandas as pd

        rows = {r["resourceId"]: r for r in listing(client, auth, SOURCE)["resources"]}
        december = rows[row_id("records", "W042", "2025-12-01T00:00:00")]
        assert (december["acquirable"], december["unavailableReason"]) == (True, None)

        dataset = _added(client, auth, row_id("records", "W042", JULY))
        assert dataset["title"] == "Detection records · W042, 2025-07"
        assert (dataset["collection"]["kind"], dataset["collection"]["provider"]) == ("files", "s3")
        index = pd.read_parquet(dataset["path"])
        assert len(index) == 1
        row = index.iloc[0]
        assert (row["relpath"], row["kind"], row["ext"]) == ("W042/data/W042_2025_07.jsonl", "file", "jsonl")
        assert row["bytes"] == 717_568_766
        assert (row["crossing"], row["month"]) == ("W042", datetime(2025, 7, 1))
        # Nothing of the file was copied into the dataset.
        folder = Path(dataset["path"]).parents[1]
        assert (folder / "manifest.json").is_file() and not list(folder.rglob("*.jsonl"))


class TestTheSnapshots:
    def test_a_snapshot_is_timed_by_its_name_in_nanoseconds(self, client, auth, app, shipped_root, fixture_corpus):
        import pandas as pd

        dataset = _added(client, auth, row_id("snapshots", "W042", JULY))
        index = pd.read_parquet(dataset["path"]).set_index("relpath")
        assert len(index) == 2
        row = index.loc["W042/images/2025_07/1752710404341667481-snapshot.jpg"]
        assert row["ns"] == 1752710404341667481
        assert row["taken_at"] == pd.Timestamp(1752710404341667481, unit="ns")
        assert (row["crossing"], row["month"]) == ("W042", datetime(2025, 7, 1))


class TestTheDetections:
    def test_one_row_per_detection_and_the_other_lines_counted(self, client, auth, app, shipped_root, fixture_corpus):
        import pandas as pd

        job = add(client, auth, SOURCE, row_id("detections", "W042", JULY))
        assert job["status"] == "completed", job.get("error")
        assert job["dataset"]["title"] == "Detections · W042, 2025-07"
        frame = pd.read_parquet(job["dataset"]["path"])
        assert list(frame.columns) == [
            "timestamp", "image_timestamp_ns", "model", "inference_time_seconds",
            "class", "confidence", "x0", "y0", "x1", "y1", "crossing", "month", "source_file",
        ]
        # The first image: one car for YOLOv5n, a car and a person for YOLOv8n,
        # nothing for YOLOv10n; the second: a car for each model.
        assert len(frame) == 6
        first = frame[frame["image_timestamp_ns"] == 1752721216492384585]
        assert sorted(zip(first["model"], first["class"])) == [
            ("YOLOv5n", "car"), ("YOLOv8n", "car"), ("YOLOv8n", "person"),
        ]
        assert frame["timestamp"].iloc[0] == pd.Timestamp("2025-07-17 03:00:16.492384585")
        assert set(frame["crossing"]) == {"W042"} and set(frame["month"]) == {datetime(2025, 7, 1)}
        # The upload line's value is a link, not JSON: skipped, and said so.
        note = "1 of 3 lines skipped: 1 value is not JSON text (first at line 2 of W042/data/W042_2025_07.jsonl)"
        assert job["note"] == note
        assert job["dataset"]["description"] == f"Read from W042/data/W042_2025_07.jsonl of SAGE-IDOT rail crossings; {note}."

    def test_one_row_per_image_and_model_also_when_it_saw_nothing(
        self, client, auth, app, shipped_root, fixture_corpus
    ):
        import pandas as pd

        frame = pd.read_parquet(_added(client, auth, row_id("frames", "W042", JULY))["path"])
        assert list(frame.columns) == [
            "timestamp", "image_timestamp_ns", "model", "total_objects", "counts",
            "inference_time_seconds", "crossing", "month", "source_file",
        ]
        assert len(frame) == 6
        nothing = frame[(frame["image_timestamp_ns"] == 1752721216492384585) & (frame["model"] == "YOLOv10n")]
        assert list(nothing["total_objects"]) == [0] and list(nothing["counts"]) == ["{}"]
        both = frame[(frame["image_timestamp_ns"] == 1752721216492384585) & (frame["model"] == "YOLOv8n")]
        assert list(both["counts"]) == ['{"car":1,"person":1}']

    def test_a_month_with_an_empty_file_fails_and_says_why(self, client, auth, app, shipped_root, fixture_corpus):
        job = add(client, auth, SOURCE, row_id("detections", "W06E", "2026-03-01T00:00:00"))
        assert job["status"] == "failed", job
        assert "no line of its file gave a row" in job["error"], job["error"]
