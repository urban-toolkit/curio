"""A collection's ``time``: a capture's name, or ``{capture, unit, timezone}``.

A date or strftime capture is each file's time as written, or, with a
``timezone``, a local time there that the index converts to UTC. An int
capture is a time with a ``unit``: seconds, milliseconds or nanoseconds since
1970, in UTC. The two layouts below are the ones the object was made for: the
IDOT crossings' snapshots, named by their epoch time in nanoseconds, and the
SideSeeing walks, in folders named by their start in Chicago's local time.
"""

from __future__ import annotations

import copy
import io
import json
from datetime import datetime
from pathlib import Path

import pytest

from utk_curio.backend.app.discovery.application import index_collection, scan
from utk_curio.backend.app.discovery.domain import manifest as M
from utk_curio.backend.app.discovery.domain.templates import CAPTURE_NAME_RE, TemplateError, compile_template
from utk_curio.backend.app.discovery.providers.folder import FolderStorage
from utk_curio.backend.tests.test_discovery.conftest import (
    a_storage_manifest,
    write_files,
    write_source,
)
from utk_curio.backend.tests.test_discovery.test_storage_sources import add, wait_for

SCHEMA_PATH = Path(__file__).resolve().parents[4] / "docs" / "schemas" / "discovery-source.v1.json"

SNAPSHOTS = {
    "id": "snapshots", "name": "Crossing snapshots", "kind": "images",
    "path": "{crossing}/images/{month:%Y_%m}/{ns:int}-snapshot.jpg",
    "time": {"capture": "ns", "unit": "ns"},
}
WALKS = {
    "id": "walks", "name": "Walk videos", "kind": "videos",
    "path": "chicago/west-loop/{began:%Y-%m-%d-%H-%M-%S-%f}/video.mp4",
    "time": {"capture": "began", "timezone": "America/Chicago"},
}
RECORDINGS = {
    "id": "noise", "name": "Noise recordings", "kind": "audio",
    "path": "noise/{sensor}/{recorded:%Y%m%d_%H%M%S}.wav", "time": "recorded",
}


def parse(raw):
    return M._parse_manifest(raw, where="manifest.json")


def the_resource(resource):
    return parse(a_storage_manifest("/srv/x", [resource])).resources[0]


def a_jpeg() -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (4, 2), (200, 30, 30)).save(out, "JPEG")
    return out.getvalue()


def indexed(tmp_path, resource, files) -> dict:
    """The index rows of *files* under *resource*, by the file's folder."""
    root = write_files(tmp_path / "source", files)
    manifest = parse(a_storage_manifest(root, [resource]))
    provider = FolderStorage(manifest)
    group = scan.scan(manifest, provider).groups[0]
    rows = index_collection.build_rows(manifest, provider, group.spec, group.files)
    return {row["relpath"].split("/")[-2]: row for row in rows}


class TestTheManifest:
    def test_a_number_with_a_unit_is_a_time(self):
        spec = the_resource(SNAPSHOTS)
        assert (spec.time, spec.time_unit, spec.time_zone) == ("ns", "ns", None)

    @pytest.mark.parametrize("unit", ["s", "ms", "ns"])
    def test_each_unit_is_read(self, unit):
        spec = the_resource({**SNAPSHOTS, "time": {"capture": "ns", "unit": unit}})
        assert spec.time_unit == unit

    def test_a_strftime_capture_with_a_time_zone_is_a_time(self):
        spec = the_resource(WALKS)
        assert (spec.time, spec.time_unit, spec.time_zone) == ("began", None, "America/Chicago")

    def test_a_date_capture_takes_a_time_zone_too(self):
        spec = the_resource({"id": "d", "name": "D", "kind": "images", "path": "{day:date}/{n}.jpg",
                             "time": {"capture": "day", "timezone": "Europe/Lisbon"}})
        assert (spec.time, spec.time_zone) == ("day", "Europe/Lisbon")

    def test_an_object_with_only_a_capture_is_the_name(self):
        assert the_resource({**RECORDINGS, "time": {"capture": "recorded"}}) == the_resource(RECORDINGS)

    def test_a_name_is_read_as_before(self):
        spec = the_resource(RECORDINGS)
        assert (spec.time, spec.time_unit, spec.time_zone) == ("recorded", None, None)

    @pytest.mark.parametrize(
        "path, time, reason",
        [
            # A unit on a date capture.
            ("{day:date}/{n}.jpg", {"capture": "day", "unit": "s"}, "unit applies to an int capture"),
            ("{t:%Y%m%d_%H%M%S}.jpg", {"capture": "t", "unit": "ms"}, "unit applies to an int capture"),
            # A time zone on an int capture.
            ("{ns:int}.jpg", {"capture": "ns", "unit": "ns", "timezone": "America/Chicago"},
             "timezone applies to a date or strftime capture"),
            ("{ns:int}.jpg", {"capture": "ns", "timezone": "UTC"}, "timezone applies to a date or strftime capture"),
            # An unknown zone, a zone spelled in another case among them.
            ("{t:%Y%m%d}.jpg", {"capture": "t", "timezone": "America/Chicag"}, "is not a time zone"),
            ("{t:%Y%m%d}.jpg", {"capture": "t", "timezone": "america/chicago"}, "is not a time zone"),
            ("{t:%Y%m%d}.jpg", {"capture": "t", "timezone": "Mars/Phobos"}, "is not a time zone"),
            ("{t:%Y%m%d}.jpg", {"capture": "t", "timezone": "../etc/passwd"}, "is not a time zone"),
            ("{t:%Y%m%d}.jpg", {"capture": "t", "timezone": ""}, "is not a time zone"),
            ("{t:%Y%m%d}.jpg", {"capture": "t", "timezone": -6}, "is not a time zone"),
            # An object naming no capture.
            ("{ns:int}.jpg", {"unit": "ns"}, "capture must name a capture"),
            ("{ns:int}.jpg", {"capture": " ", "unit": "ns"}, "capture must name a capture"),
            ("{ns:int}.jpg", {"capture": "missing", "unit": "ns"}, "date or strftime capture"),
            # A number with no unit, or with one Curio does not read.
            ("{ns:int}.jpg", "ns", "a time only with a unit"),
            ("{ns:int}.jpg", {"capture": "ns"}, "a time only with a unit"),
            ("{ns:int}.jpg", {"capture": "ns", "unit": "us"}, "unit must be one of"),
            # A key the object does not have.
            ("{ns:int}.jpg", {"capture": "ns", "unit": "ns", "zone": "UTC"}, "it has no zone"),
            # Neither a name nor an object.
            ("{ns:int}.jpg", ["ns"], "a capture's name, or an object"),
            # Text is no time, named or in an object.
            ("{n}.jpg", "n", "date or strftime capture"),
            ("{n}.jpg", {"capture": "n", "timezone": "UTC"}, "date or strftime capture"),
        ],
    )
    def test_a_bad_time_is_refused(self, path, time, reason):
        with pytest.raises(M.ManifestError, match=reason):
            the_resource({"id": "pics", "name": "Pics", "kind": "images", "path": path, "time": time})

    def test_a_table_takes_no_time_in_either_form(self):
        table = {"id": "t", "name": "T", "kind": "table", "format": "csv", "path": "{day:date}.csv"}
        for time in ("day", {"capture": "day", "timezone": "UTC"}):
            with pytest.raises(M.ManifestError, match="time only applies to a collection"):
                the_resource({**table, "time": time})

    def test_a_machine_with_no_zone_database_says_so(self, monkeypatch):
        # ``frozenset()`` is empty: a machine whose database lists no zone.
        monkeypatch.setattr(M, "_time_zones", frozenset)
        with pytest.raises(M.ManifestError, match="no time zone database"):
            the_resource(WALKS)

    def test_both_layouts_round_trip_and_a_name_stays_a_name(self):
        m = parse(a_storage_manifest("/srv/x", [SNAPSHOTS, WALKS, {**RECORDINGS, "time": {"capture": "recorded"}}]))
        written = M.build_manifest_dict(m)
        assert [r["time"] for r in written["resources"]] == [SNAPSHOTS["time"], WALKS["time"], "recorded"]
        assert parse(written) == m


class TestTheSchema:
    """``docs/schemas/discovery-source.v1.json`` declares ``time`` as the
    validator reads it."""

    @pytest.fixture(scope="class")
    def forms(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        return schema, schema["properties"]["resources"]["items"]["properties"]["time"]["oneOf"]

    def test_both_forms_name_a_capture_as_the_validator_does(self, forms):
        _schema, (name, given) = forms
        assert name["pattern"] == given["properties"]["capture"]["pattern"] == CAPTURE_NAME_RE.pattern
        assert given["required"] == ["capture"]
        assert given["additionalProperties"] is False

    def test_the_units_and_the_zone_shape_are_the_validators(self, forms):
        _schema, (_name, given) = forms
        assert given["properties"]["unit"]["enum"] == sorted(M.TIME_UNITS)
        assert given["properties"]["timezone"]["pattern"] == M._TIME_ZONE_RE.pattern

    def test_every_key_the_validator_writes_is_declared(self, forms):
        _schema, (_name, given) = forms
        written = M.build_manifest_dict(parse(a_storage_manifest("/srv/x", [SNAPSHOTS, WALKS])))
        keys = set().union(*(entry["time"] for entry in written["resources"]))
        assert keys == set(given["properties"])

    def test_the_schema_takes_and_refuses_what_the_validator_does(self, forms):
        jsonschema = pytest.importorskip("jsonschema")
        schema, _forms = forms
        validator = jsonschema.Draft202012Validator(schema)
        good = a_storage_manifest("/srv/x", [SNAPSHOTS, WALKS, RECORDINGS])
        assert not list(validator.iter_errors(good))
        parse(good)
        bad_times = [
            (0, {"unit": "ns"}),
            (0, {"capture": "ns", "unit": "ns", "zone": "UTC"}),
            (0, {"capture": "ns", "unit": "us"}),
            (1, {"capture": "began", "unit": "s", "timezone": "America/Chicago"}),
            (1, {"capture": "began", "timezone": "America Chicago"}),
        ]
        for index, time in bad_times:
            raw = copy.deepcopy(good)
            raw["resources"][index]["time"] = time
            assert list(validator.iter_errors(raw)), time
            with pytest.raises(M.ManifestError):
                parse(raw)


class TestAFractionOfASecond:
    """``%f`` in a date capture: 1 to 6 digits of a second, as Python's
    ``strptime`` reads them, ``016`` being 16 milliseconds."""

    @pytest.mark.parametrize(
        "folder, microsecond",
        [
            ("2026-10-26-16-03-17-5", 500_000),
            ("2026-10-26-16-03-17-016", 16_000),
            ("2026-10-26-16-03-17-016250", 16_250),
        ],
    )
    def test_one_to_six_digits_are_the_fraction(self, folder, microsecond):
        template = compile_template("{began:%Y-%m-%d-%H-%M-%S-%f}/video.mp4")
        began = template.match(f"{folder}/video.mp4")["began"]
        assert began == datetime(2026, 10, 26, 16, 3, 17, microsecond)

    def test_seven_digits_are_no_fraction_strptime_reads(self):
        template = compile_template("{began:%Y-%m-%d-%H-%M-%S-%f}/video.mp4")
        assert template.match("2026-10-26-16-03-17-0162501/video.mp4") is None

    def test_a_capture_without_it_reads_whole_seconds_as_before(self):
        template = compile_template("{began:%Y-%m-%d-%H-%M-%S}/video.mp4")
        assert template.match("2026-10-26-16-03-17/video.mp4")["began"] == datetime(2026, 10, 26, 16, 3, 17)
        assert template.match("2026-10-26-16-03-17-016/video.mp4") is None

    def test_it_is_used_once(self):
        with pytest.raises(TemplateError, match="uses %f twice"):
            compile_template("{t:%H%M%S_%f_%f}.jpg")

    def test_a_walk_starts_at_its_millisecond_in_utc(self, tmp_path):
        walks = ("2026-10-26-16-03-17-016", "2026-10-26-16-03-17-5", "2026-10-26-16-03-17-016250")
        rows = indexed(tmp_path, WALKS, {f"chicago/west-loop/{w}/video.mp4": b"not a video" for w in walks})
        assert {w: str(rows[w]["taken_at"]) for w in walks} == {
            "2026-10-26-16-03-17-016": "2026-10-26 21:03:17.016000",
            "2026-10-26-16-03-17-5": "2026-10-26 21:03:17.500000",
            "2026-10-26-16-03-17-016250": "2026-10-26 21:03:17.016250",
        }

    def test_without_it_the_milliseconds_stay_a_field_of_their_own(self, tmp_path):
        resource = {**WALKS, "path": "chicago/west-loop/{began:%Y-%m-%d-%H-%M-%S}-{ms:int}/video.mp4"}
        row = indexed(tmp_path, resource, {
            "chicago/west-loop/2026-10-26-16-03-17-016/video.mp4": b"not a video",
        })["2026-10-26-16-03-17-016"]
        assert (row["taken_at"], row["ms"]) == (datetime(2026, 10, 26, 21, 3, 17), 16)


class TestTheIndex:
    def test_a_nanosecond_name_is_its_utc_time_and_stays_a_number(self, tmp_path):
        rows = indexed(tmp_path, SNAPSHOTS, {
            "W042/images/2025_07/1752710404341667481-snapshot.jpg": a_jpeg(),
        })
        row = rows["2025_07"]
        assert str(row["taken_at"]) == "2025-07-17 00:00:04.341667481"
        assert row["ns"] == 1752710404341667481 and type(row["ns"]) is int
        # The image was read, and its time is its name's.
        assert (row["width"], row["height"]) == (4, 2) and "probe_error" not in row

    @pytest.mark.parametrize(
        "unit, name, expected",
        [
            ("s", "1752710404", "2025-07-17 00:00:04"),
            ("ms", "1752710404341", "2025-07-17 00:00:04.341000"),
            ("ns", "1752710404341667481", "2025-07-17 00:00:04.341667481"),
        ],
    )
    def test_each_unit_reads_since_1970_in_utc(self, tmp_path, unit, name, expected):
        resource = {"id": "s", "name": "S", "kind": "images", "path": "{at:int}/x.jpg",
                    "time": {"capture": "at", "unit": unit}}
        row = indexed(tmp_path, resource, {f"{name}/x.jpg": a_jpeg()})[name]
        assert str(row["taken_at"]) == expected

    def test_a_number_past_what_a_time_holds_leaves_the_time_empty(self, tmp_path):
        resource = {"id": "s", "name": "S", "kind": "images", "path": "{at:int}/x.jpg",
                    "time": {"capture": "at", "unit": "s"}}
        rows = indexed(tmp_path, resource, {"99999999999999/x.jpg": a_jpeg(), "1752710404/x.jpg": a_jpeg()})
        assert rows["99999999999999"].get("taken_at") is None
        assert rows["99999999999999"]["at"] == 99999999999999
        assert str(rows["1752710404"]["taken_at"]) == "2025-07-17 00:00:04"

    def test_a_chicago_time_is_its_utc_time_on_both_sides_of_a_clock_change(self, tmp_path):
        """Chicago's clocks went back on 2026-11-01 and forward on 2026-03-08."""
        walks = (
            "2026-10-26-16-03-17-016",  # daylight time, UTC-5
            "2026-11-02-16-03-17-016",  # standard time, UTC-6
            "2026-11-01-01-30-00-000",  # the hour the clocks show twice: its first pass
            "2026-03-08-02-30-00-000",  # the hour the clocks skip: read with the offset before
        )
        rows = indexed(tmp_path, WALKS, {f"chicago/west-loop/{w}/video.mp4": b"not a video" for w in walks})
        assert {w: rows[w]["taken_at"] for w in walks} == {
            "2026-10-26-16-03-17-016": datetime(2026, 10, 26, 21, 3, 17, 16000),
            "2026-11-02-16-03-17-016": datetime(2026, 11, 2, 22, 3, 17, 16000),
            "2026-11-01-01-30-00-000": datetime(2026, 11, 1, 6, 30),
            "2026-03-08-02-30-00-000": datetime(2026, 3, 8, 8, 30),
        }
        # The path's own field keeps what the path says, Chicago's clock.
        assert rows["2026-10-26-16-03-17-016"]["began"] == datetime(2026, 10, 26, 16, 3, 17, 16000)

    def test_a_date_in_a_zone_starts_at_its_local_midnight(self, tmp_path):
        resource = {"id": "d", "name": "D", "kind": "images", "path": "{day:date}/x.jpg",
                    "time": {"capture": "day", "timezone": "America/Chicago"}}
        row = indexed(tmp_path, resource, {"2024-05-01/x.jpg": a_jpeg()})["2024-05-01"]
        assert row["taken_at"] == datetime(2024, 5, 1, 5, 0)

    @pytest.mark.parametrize("time", ["recorded", {"capture": "recorded"}])
    def test_a_name_is_the_time_as_written_as_before(self, tmp_path, time):
        """No unit and no zone: the capture's own value, a Python datetime."""
        files = {"noise/sensor_01/20240501_060000.wav": b"not a recording"}
        row = indexed(tmp_path, {**RECORDINGS, "time": time}, files)["sensor_01"]
        assert type(row["recorded_at"]) is datetime
        assert row["recorded_at"] == row["recorded"] == datetime(2024, 5, 1, 6, 0)


SOURCE = "source.example.folder@1"


@pytest.fixture()
def auth(user_and_token):
    _user, token = user_and_token
    return {"Authorization": f"Bearer {token}"}


def test_an_added_collection_keeps_the_nanoseconds(client, auth, app, discovery_dir, tmp_path):
    """Through the add and the index's Parquet file, as a node reads it."""
    import pandas as pd

    scan.listings.reset()
    root = write_files(tmp_path / "idot", {
        "W042/images/2025_07/1752710404341667481-snapshot.jpg": a_jpeg(),
        "W042/images/2025_07/1752710704352071203-snapshot.jpg": a_jpeg(),
    })
    write_source(discovery_dir, SOURCE, a_storage_manifest(root, [SNAPSHOTS]))
    res = add(client, auth, "snapshots", source=SOURCE)
    assert res.status_code == 202, res.get_data(as_text=True)
    job = wait_for(client, auth, res.get_json()["jobId"])
    assert job["status"] == "completed", job.get("error")
    index = pd.read_parquet(job["dataset"]["path"]).sort_values("ns")
    assert [str(t) for t in index["taken_at"]] == [
        "2025-07-17 00:00:04.341667481", "2025-07-17 00:05:04.352071203",
    ]
    assert str(index["ns"].dtype) == "int64"
    assert list(index["ns"]) == [1752710404341667481, 1752710704352071203]
    assert index["probe_error"].isna().all()
    scan.listings.reset()
