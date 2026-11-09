"""The SideSeeing street captures source, on the recorded corpus: no socket opens.

``scripts/record_discovery_fixtures.py --only sideseeing`` recorded the
bucket's listing on data.urbantk.org: the two West Loop walks of 2026-10-26,
each a folder named by when it began in Chicago. Each CSV the source declares
is indexed to a synthetic stand-in with the real file's header
(``fixtures/download/storage/sideseeing/``), so its add runs here too.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from utk_curio.backend.tests.test_discovery.test_storage_buckets import add, listing

SOURCE = "source.sideseeing.street-captures@1"

#: Each walk's folder, the local time it names, and when the walk began in
#: UTC as its metadata.json records it (``time.buttonStartDateTime``).
WALKS = {
    "2026-10-26-15-45-51-706": (datetime(2026, 10, 26, 15, 45, 51, 706000), datetime(2026, 10, 26, 20, 45, 51, 706000)),
    "2026-10-26-16-03-17-016": (datetime(2026, 10, 26, 16, 3, 17, 16000), datetime(2026, 10, 26, 21, 3, 17, 16000)),
}

#: Each table resource and the header of the files it reads.
TABLES = {
    "gps": ["datetime_utc", "gps_interval", "accuracy", "latitude", "longitude"],
    "sensors-one": ["timestamp_nano", "datetime_utc", "name", "axis_x", "accuracy"],
    "sensors-three": ["timestamp_nano", "datetime_utc", "name", "axis_x", "axis_y", "axis_z", "accuracy"],
    "sensors-three-uncalibrated": [
        "timestamp_nano", "datetime_utc", "name", "axis_x", "axis_y", "axis_z",
        "delta_x", "delta_y", "delta_z", "accuracy",
    ],
    "battery": ["datetime_utc", "battery_microamperes"],
    "cell": ["datetime_utc", "cellular_network"],
}


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
    def test_each_walk_gives_a_video_its_records_and_its_tables(
        self, client, auth, app, shipped_root, fixture_corpus
    ):
        body = listing(client, auth, SOURCE)
        assert body["sources"][0]["status"] == "ok", body["sources"]
        rows = {r["resourceId"]: r for r in body["resources"]}
        assert list(rows) == ["walks", "records", *TABLES]
        assert (rows["walks"]["kind"], rows["walks"]["fileCount"]) == ("videos", 2)
        assert (rows["records"]["kind"], rows["records"]["fileCount"]) == ("files", 4)
        # A files row has no preview, so no sample files to draw.
        assert rows["records"]["samples"] == []
        for resource_id in TABLES:
            assert (rows[resource_id]["kind"], rows[resource_id]["fileCount"]) == ("table", 2), resource_id
        # Each walk's wifi.csv is no CSV DuckDB reads (its second column holds
        # unquoted commas), so no resource takes it.
        assert body["unmatched"] == 2


class TestTheWalks:
    def test_a_walk_is_timed_by_when_it_began_in_chicago(self, client, auth, app, shipped_root, fixture_corpus):
        import pandas as pd

        dataset = _added(client, auth, "walks")
        index = pd.read_parquet(dataset["path"]).set_index("relpath")
        assert len(index) == 2
        for folder, (local, utc) in WALKS.items():
            row = index.loc[f"chicago/west-loop/{folder}/video.mp4"]
            assert row["kind"] == "video"
            # The folder's name as it is written, and that time in UTC.
            assert row["began"] == local
            assert row["taken_at"] == utc
        assert dataset["collection"]["provider"] == "s3"

    def test_its_records_are_files_for_node_code_timed_like_its_video(
        self, client, auth, app, shipped_root, fixture_corpus
    ):
        import pandas as pd

        index = pd.read_parquet(_added(client, auth, "records")["path"])
        assert set(index["kind"]) == {"file"}
        assert sorted(zip(index["began"], index["record"])) == sorted(
            (local, record) for local, _utc in WALKS.values() for record in ("anonymization", "metadata")
        )
        for _folder, (local, utc) in WALKS.items():
            assert set(index.loc[index["began"] == local, "taken_at"]) == {utc}


class TestTheTables:
    @pytest.mark.parametrize("resource_id", list(TABLES))
    def test_each_lands_with_the_walk_as_a_column(
        self, client, auth, app, shipped_root, fixture_corpus, resource_id
    ):
        import pandas as pd

        frame = pd.read_parquet(_added(client, auth, resource_id)["path"])
        assert list(frame.columns) == TABLES[resource_id] + ["began", "source_file"]
        # Three rows from each walk's stand-in, each walk named by its start.
        assert sorted(frame["began"].value_counts().items()) == [(local, 3) for local, _utc in WALKS.values()]

    def test_a_tables_walk_joins_its_video(self, client, auth, app, shipped_root, fixture_corpus):
        import pandas as pd

        videos = pd.read_parquet(_added(client, auth, "walks")["path"])
        track = pd.read_parquet(_added(client, auth, "gps")["path"])
        joined = track.merge(videos[["began", "relpath", "taken_at"]], on="began", how="left")
        assert joined["relpath"].notna().all()
        assert len(joined) == len(track)

    def test_its_utc_times_read_back_in_the_data_catalog(self, client, auth, app, shipped_root, fixture_corpus):
        """``datetime_utc`` is written ``...Z``, which lands as a time in UTC."""
        import pandas as pd

        dataset = _added(client, auth, "gps")
        frame = pd.read_parquet(dataset["path"])
        assert str(frame["datetime_utc"].dt.tz) == "UTC"
        assert frame["datetime_utc"].iloc[0] == pd.Timestamp("2026-10-26T21:03:21.474Z")
        preview = client.get(f"/api/datasets/{dataset['id']}/preview?rowLimit=2", headers=auth).get_json()
        assert not preview.get("unsupported"), preview.get("message")
        assert preview["totalRows"] == 6 and len(preview["rows"]) == 2
        assert all(row["datetime_utc"] for row in preview["rows"])
