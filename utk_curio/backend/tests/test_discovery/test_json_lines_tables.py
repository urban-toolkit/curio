"""Adding a JSON Lines table (``"format": "jsonl"``) from a storage source:
each file read a line at a time into Parquet parts, combined in line order
with one type per column, the lines it skipped counted and said, and its
size bounded as every bucket table's is.

The real lines are cut, byte for byte, from SAGE-IDOT's detections on
data.urbantk.org (``data/sage-idot-lines.jsonl``): three lines of
detections, an error report, an upload and a line cut short."""

from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import pytest

from utk_curio.backend.app.discovery.application import combine_tables, json_lines
from utk_curio.backend.app.discovery.domain.errors import DownloadTooLarge
from utk_curio.backend.app.discovery.domain.manifest import load_source_manifest
from utk_curio.backend.tests.test_discovery.conftest import a_storage_manifest, write_files, write_source

SOURCE = "source.example.folder@1"
FIXTURE = (Path(__file__).resolve().parent / "data" / "sage-idot-lines.jsonl").read_bytes()
RELPATH = "W042/data/W042_2025_07.jsonl"

DETECTIONS = {
    "id": "detections", "name": "Detections", "kind": "table", "format": "jsonl",
    "path": "{crossing}/data/*_{year:int}_{month:int}.jsonl",
    "options": {
        "parse": ["value"],
        "columns": {"timestamp": "timestamp", "image_timestamp_ns": "value.image_timestamp_ns"},
        "unpack": [
            {"path": "value.models_results", "key": "model",
             "columns": {"inference_time_seconds": "inference_time_seconds"}},
            {"path": "detections",
             "columns": {"class": "class", "confidence": "confidence",
                         "x0": "bbox.0", "y0": "bbox.1", "x1": "bbox.2", "y1": "bbox.3"}},
        ],
    },
}

SKIPPED = (
    "3 of 6 lines skipped: "
    f"1 no list or object at value.models_results (first at line 4 of {RELPATH}); "
    f"1 value is not JSON text (first at line 5 of {RELPATH}); "
    f"1 not JSON (first at line 6 of {RELPATH})"
)


@pytest.fixture()
def auth(user_and_token):
    _user, token = user_and_token
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _fresh():
    from utk_curio.backend.app.discovery.application import scan

    scan.listings.reset()
    yield
    scan.listings.reset()


def a_source(discovery_dir, root, resources, **overrides):
    write_source(discovery_dir, SOURCE, a_storage_manifest(root, resources, **overrides))


def start(client, auth, resource_id, **body):
    return client.post(
        f"/api/discovery/sources/{SOURCE}/resources/{quote(resource_id, safe='')}/acquire",
        headers=auth, json=body,
    )


def finish(client, auth, res, timeout=30.0):
    assert res.status_code in (200, 202), res.get_data(as_text=True)
    if res.status_code == 200:
        return res.get_json()
    job_id = res.get_json()["jobId"]
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/discovery/jobs/{job_id}", headers=auth).get_json()
        if job["status"] in ("completed", "failed", "refused", "cancelled"):
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never finished")


def added(client, auth, resource_id, **body):
    job = finish(client, auth, start(client, auth, resource_id, **body))
    assert job.get("status") == "completed", job.get("error")
    return job


def a_log(discovery_dir, tmp_path, files: dict[str, str | bytes], **resource):
    """A folder of JSON Lines files under ``log/``, one per day, as one table."""
    root = write_files(tmp_path / "f", {f"log/{name}": data for name, data in files.items()})
    a_source(discovery_dir, root, [{
        "id": "log", "name": "Log", "kind": "table", "format": "jsonl", "path": "log/{day:date}.jsonl",
        **resource,
    }])


def jsonl(*records) -> str:
    return "".join(json.dumps(record) + "\n" for record in records)


class TestTheDetectionsOfSageIdot:
    def test_each_detection_is_a_row_and_each_line_left_out_is_counted(
        self, client, auth, app, discovery_dir, tmp_path
    ):
        root = write_files(tmp_path / "idot", {RELPATH: FIXTURE})
        a_source(discovery_dir, root, [DETECTIONS])
        job = added(client, auth, "detections")
        frame = pd.read_parquet(job["dataset"]["path"])
        assert list(frame.columns) == [
            "timestamp", "image_timestamp_ns", "model", "inference_time_seconds", "class", "confidence",
            "x0", "y0", "x1", "y1", "crossing", "year", "month", "source_file",
        ]
        assert list(frame["model"]) == ["YOLOv5n", "YOLOv8n", "YOLOv10n", "YOLOv5n", "YOLOv8n"]
        assert list(frame["class"]) == ["car", "car", "car", "person", "car"]
        assert str(frame["image_timestamp_ns"].dtype) == "int64"
        assert list(frame["image_timestamp_ns"]) == [1752721216492384585] * 3 + [1752721225101747549] * 2
        assert frame.iloc[0][["x0", "y0", "x1", "y1"]].tolist() == [
            81.07574462890625, 861.7494506835938, 356.38250732421875, 977.5149536132812,
        ]
        assert frame.iloc[3]["inference_time_seconds"] == 1.8471455574035645
        assert set(frame["crossing"]) == {"W042"} and set(frame["year"]) == {2025} and set(frame["month"]) == {7}
        assert set(frame["source_file"]) == {RELPATH}
        assert job["dataset"]["rowCount"] == 5 and job["dataset"]["format"] == "parquet"
        assert job["note"] == SKIPPED
        assert job["stageMessage"] == f"Added to your Data Catalog; {SKIPPED}"
        assert job["dataset"]["description"] == f"Read from {RELPATH} of Example Folder; {SKIPPED}."

    def test_a_file_whose_lines_give_no_row_fails_saying_why(self, client, auth, app, discovery_dir, tmp_path):
        lines = FIXTURE.split(b"\n")
        root = write_files(tmp_path / "idot", {RELPATH: lines[3] + b"\n" + lines[4] + b"\n"})
        a_source(discovery_dir, root, [DETECTIONS])
        job = finish(client, auth, start(client, auth, "detections"))
        assert job["status"] == "failed"
        assert job["error"] == (
            "Detections: no line of its file gave a row; 2 of 2 lines skipped: "
            f"1 no list or object at value.models_results (first at line 1 of {RELPATH}); "
            f"1 value is not JSON text (first at line 2 of {RELPATH})"
        )

    def test_an_empty_file_fails_saying_so(self, client, auth, app, discovery_dir, tmp_path):
        root = write_files(tmp_path / "idot", {RELPATH: b""})
        a_source(discovery_dir, root, [DETECTIONS])
        job = finish(client, auth, start(client, auth, "detections"))
        assert job["status"] == "failed"
        assert job["error"] == "Detections: no line of its file gave a row"

    def test_with_no_options_each_line_is_a_row_of_its_fields(self, client, auth, app, discovery_dir, tmp_path):
        root = write_files(tmp_path / "idot", {RELPATH: FIXTURE})
        a_source(discovery_dir, root, [{**DETECTIONS, "options": {}}])
        job = added(client, auth, "detections")
        frame = pd.read_parquet(job["dataset"]["path"])
        assert list(frame.columns)[:3] == ["timestamp", "name", "value"]
        assert list(frame["name"]) == [
            "object.detections.all", "object.detections.all", "object.detections.all", "plugin.error", "upload",
        ]
        assert frame["meta.filename"].isna().all()
        assert frame.iloc[0]["value"].startswith('{"image_timestamp_ns": 1752721216492384585, ')
        assert job["note"] == f"1 of 6 lines skipped: 1 not JSON (first at line 6 of {RELPATH})"


class TestReadingAFileInParts:
    def test_rows_keep_their_line_order_across_parts_and_files(
        self, client, auth, app, discovery_dir, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(json_lines, "ROWS_PER_PART", 3)
        parts: list[int] = []
        real = json_lines.read

        def counting(*args, **kwargs):
            written = real(*args, **kwargs)
            parts.append(len(written))
            return written

        monkeypatch.setattr(json_lines, "read", counting)
        a_log(discovery_dir, tmp_path, {
            "2024-01-01.jsonl": jsonl(*({"n": n} for n in range(10))),
            "2024-01-02.jsonl": jsonl(*({"n": n} for n in range(10, 17))),
        })
        frame = pd.read_parquet(added(client, auth, "log")["dataset"]["path"])
        assert parts == [4, 3]
        assert list(frame["n"]) == list(range(17))
        assert list(frame["day"].astype(str)) == ["2024-01-01"] * 10 + ["2024-01-02"] * 7

    def test_a_column_takes_one_type_whatever_each_part_held(
        self, client, auth, app, discovery_dir, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(json_lines, "ROWS_PER_PART", 2)
        a_log(discovery_dir, tmp_path, {"2024-01-01.jsonl": jsonl(
            {"v": None, "t": 1, "big": 1, "flag": True, "score": 0.5},
            {"v": None, "t": 2, "big": 2, "flag": False, "score": 0.25},
            {"v": 1, "t": 3, "big": 2 ** 64, "flag": None, "score": 1.5},
            {"v": 2, "t": "x", "big": 3, "flag": True, "score": False},
            {"v": 2.5, "t": 4, "big": 4, "flag": 1, "score": 2.0},
            {"v": 3, "t": 5, "big": 5, "flag": False, "score": 3.5},
        )})
        frame = pd.read_parquet(added(client, auth, "log")["dataset"]["path"])
        assert str(frame["v"].dtype) == "float64"
        assert frame["v"].tolist()[2:] == [1.0, 2.0, 2.5, 3.0] and frame["v"].isna().tolist()[:2] == [True, True]
        assert frame["t"].tolist() == ["1", "2", "3", "x", "4", "5"]
        assert frame["big"].tolist() == ["1", "2", "18446744073709551616", "3", "4", "5"]
        assert frame["flag"].tolist() == ["true", "false", None, "true", "1", "false"]
        # Arrow alone would read [1.5, false] as [1.5, 0.0].
        assert frame["score"].tolist() == ["0.5", "0.25", "1.5", "false", "2.0", "3.5"]

    def test_a_line_over_the_bound_is_skipped_and_the_rest_read(
        self, client, auth, app, discovery_dir, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(json_lines, "MAX_LINE_BYTES", 64)
        a_log(discovery_dir, tmp_path, {"2024-01-01.jsonl": jsonl({"n": 1}, {"n": "x" * 200}, {"n": 3})})
        job = added(client, auth, "log")
        assert list(pd.read_parquet(job["dataset"]["path"])["n"]) == [1, 3]
        assert job["note"] == "1 of 3 lines skipped: 1 longer than 64 bytes (first at line 2 of log/2024-01-01.jsonl)"

    def test_blank_lines_and_line_ends_are_not_lines_that_were_skipped(
        self, client, auth, app, discovery_dir, tmp_path
    ):
        a_log(discovery_dir, tmp_path, {"2024-01-01.jsonl": b'{"n": 1}\r\n\r\n  \n{"n": 2}\r\n\n{"n": 3}'})
        job = added(client, auth, "log")
        assert list(pd.read_parquet(job["dataset"]["path"])["n"]) == [1, 2, 3]
        assert job.get("note") is None
        assert job["dataset"]["description"] == "Read from log/2024-01-01.jsonl of Example Folder."

    def test_a_cancelled_add_stops_reading(self, tmp_path, monkeypatch):
        from utk_curio.backend.app.discovery.application.storage_acquire import Cancelled
        from utk_curio.backend.app.discovery.domain import json_rows

        monkeypatch.setattr(json_lines, "LINES_PER_CHECK", 2)
        path = tmp_path / "a.jsonl"
        path.write_text(jsonl(*({"n": n} for n in range(5))), encoding="utf-8")
        with pytest.raises(Cancelled):
            json_lines.read(path, "a.jsonl", json_rows.read_options({}), tmp_path, "part", json_lines.Skipped(),
                            cancelled=lambda: True)


class TestFromABucket:
    """A bucket's file is copied under the download limit, as every bucket
    table's is, read from the copy, and the copy removed once its rows are
    in parts."""

    def bucket_manifest(self, discovery_dir, tmp_path, files, **capabilities):
        from utk_curio.backend.tests.test_discovery.test_storage_add_path import MemoryBucket

        write_source(discovery_dir, SOURCE, a_storage_manifest(
            tmp_path, [DETECTIONS],
            provider={"type": "s3", "baseUrl": "https://bucket.example", "options": {}},
            **({"capabilities": capabilities} if capabilities else {}),
        ))
        return load_source_manifest(discovery_dir / SOURCE), MemoryBucket(files)

    def an_acquire(self, bucket, installed: list):
        from utk_curio.backend.app.discovery.application.storage_acquire import StorageAcquire

        def install_path(path, filename, fmt, **kwargs):
            installed.append({"filename": filename, "format": fmt, "frame": pd.read_parquet(path), **kwargs})
            return {"id": f"d{len(installed)}", "format": fmt}

        return StorageAcquire(
            user_key="guest", storage_for=lambda _manifest: bucket, install_path=install_path,
            import_layers=lambda *a, **k: {}, find_held=lambda *a: None,
        )

    def test_its_copy_is_read_into_parts_then_removed(self, app, discovery_dir, tmp_path, monkeypatch):
        manifest, bucket = self.bucket_manifest(discovery_dir, tmp_path, {RELPATH: FIXTURE})
        seen: dict = {}
        real = combine_tables.combine

        def watching(spec, files, *, stage, tmp, **kwargs):
            def staging(found, into, index):
                parts = stage(found, into, index)
                seen["copy left"] = (into / f"part-{index:06d}.jsonl").exists()
                seen["parts"] = [part.exists() for part in parts]
                return parts

            return real(spec, files, stage=staging, tmp=tmp, **kwargs)

        monkeypatch.setattr(combine_tables, "combine", watching)
        installed: list = []
        result = self.an_acquire(bucket, installed).acquire(manifest, "detections")
        assert seen == {"copy left": False, "parts": [True]}
        assert len(installed[0]["frame"]) == 5
        assert result["note"] == SKIPPED

    def test_a_file_over_the_download_limit_is_refused_before_it_is_read(self, app, discovery_dir, tmp_path):
        from utk_curio.backend.app.discovery.application import scan
        from utk_curio.backend.app.discovery.application.storage_acquire import add_refusal

        manifest, bucket = self.bucket_manifest(
            discovery_dir, tmp_path, {RELPATH: FIXTURE}, maxDownloadBytes=len(FIXTURE) - 1,
        )
        words = f"{RELPATH} is {len(FIXTURE):,} bytes; the limit here is {len(FIXTURE) - 1:,}"
        files = [f for group in scan.scan(manifest, bucket).groups for f in group.files]
        assert add_refusal(manifest, manifest.resources[0], files) == words
        with pytest.raises(DownloadTooLarge, match=words):
            self.an_acquire(bucket, []).acquire(manifest, "detections")

    def test_files_over_what_one_add_reads_from_a_bucket_are_refused(
        self, app, discovery_dir, tmp_path, monkeypatch
    ):
        manifest, bucket = self.bucket_manifest(discovery_dir, tmp_path, {
            RELPATH: FIXTURE, "W042/data/W042_2025_08.jsonl": FIXTURE,
        })
        monkeypatch.setattr(combine_tables, "MAX_COMBINED_REMOTE_BYTES", 2 * len(FIXTURE) - 1)
        with pytest.raises(DownloadTooLarge, match=(
            f"these files total {2 * len(FIXTURE):,} bytes; one combined table is limited to {2 * len(FIXTURE) - 1:,}"
        )):
            self.an_acquire(bucket, []).acquire(manifest, "detections")
