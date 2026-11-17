"""Example 31, the SAGE-IDOT rail crossings, run in process on the recorded corpus.

Each test runs the example's own node code, from
``docs/examples/31-sage-idot-rail-crossings.json``, its widget references
written as a run writes them, on its circles' inputs as the sandbox runs node
code (``input_names.call_as_node``): the team's two files through
``curio_load_data``, and the bucket's files through the sandbox's own
``curio_load_collection`` and ``curio_derived_file``, over a folder that holds
the corpus's copies of them as **Cache files** keeps a collection's files.
``scripts/record_discovery_fixtures.py`` writes the copies: each team day of
records, thinned to every snapshot's image and every 300th other with a few
lines of the days beside it, and the six snapshots of the half hour the
Frames tile shows first, made smaller. No socket opens.

Where the Cities in Motion workshop team's code (isalva2/cities-in-motion-video)
computed something differently, the test pins the example's number: an exact
fit at W042's four control points, zones in square metres, light from astral
rather than fixed hours, YOLO26n's boxes joined to the snapshots by their
names, and occupancy, which the team did not build.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import textwrap
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = REPO_ROOT / "docs" / "examples" / "31-sage-idot-rail-crossings.json"
CORPUS = Path(__file__).resolve().parent / "test_discovery" / "fixtures" / "download" / "storage" / "idot" / "example"
PACKAGE = REPO_ROOT / "packages" / "curio.builtin@1"
CHICAGO = ZoneInfo("America/Chicago")

#: The half hour the Frames tile shows first, as the corpus records it: W042's
#: busiest with the Settings tile's defaults, in nanoseconds in UTC.
FRAMES_FROM, FRAMES_TO = 1_754_773_200_000_000_000, 1_754_775_000_000_000_000


def _dataflow() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))["dataflow"]


@pytest.fixture(autouse=True)
def spatial_join_module(tmp_path):
    """The built-in package's module, staged as the sandbox stages it, for
    the Spatial Join node."""
    from utk_curio.sandbox.util.package_modules import importable
    from utk_curio.sandbox.util.staging import stage_package_modules

    run = tmp_path / "run-example-31"
    run.mkdir()
    staged = stage_package_modules({"root": str(PACKAGE / "sources"), "names": ["spatial_join"]}, str(run))
    with importable(str(run / staged["root"]), staged["names"]):
        yield


class Run:
    """The example's nodes, each run once on its inputs, with the Settings
    node's widgets at their defaults but for *settings*."""

    def __init__(self, folder: Path, **settings):
        import pandas as pd

        from utk_curio.sandbox.util.collections import make_collection_helpers

        flow = _dataflow()
        self.nodes = {node["id"]: node for node in flow["nodes"]}
        self.inputs: dict[str, dict[int, str]] = {}
        for edge in flow["edges"]:
            slot = 0 if edge["targetHandle"] == "in" else int(edge["targetHandle"].split("_")[1])
            self.inputs.setdefault(edge["target"], {})[slot] = edge["source"]
        self.settings = settings
        self.catalog = {}
        for ref in flow["datasets"]:
            root = REPO_ROOT / "datasets" / ref["dirName"]
            self.catalog[ref["datasetId"]] = (root, json.loads((root / "manifest.json").read_text(encoding="utf-8")))
        # Where Cache files keeps a collection's files: <file id>.<ext>.
        objects = folder / "objects"
        objects.mkdir()
        collections = {}
        for dataset_id, (root, manifest) in self.catalog.items():
            if manifest["format"] != "collection":
                continue
            collections[dataset_id] = {"kind": manifest["collection"]["kind"], "objects": str(objects)}
            for row in pd.read_parquet(root / manifest["dataFile"]).itertuples():
                copy = CORPUS / row.name
                if copy.is_file():
                    os.symlink(copy, objects / f"{row.file_id}.{row.ext}")
        self.media = folder / "media"
        self.media.mkdir()
        self.helpers = make_collection_helpers(
            lambda dataset_id: str(self.catalog[dataset_id][0] / self.catalog[dataset_id][1]["dataFile"]),
            collections, str(self.media),
        )
        self.results: dict[str, object] = {}
        self.printed: dict[str, str] = {}

    def load_data(self, dataset_id):
        import pandas as pd

        root, manifest = self.catalog[dataset_id]
        return pd.read_csv(root / manifest["dataFile"])

    def __getitem__(self, name):
        """What the node *name* (its id after ``idot-``) returns, run on its inputs."""
        node_id = f"idot-{name}"
        if node_id not in self.results:
            wired = self.inputs.get(node_id, {})
            self.results[node_id] = self.call(name, [self[wired[slot][len("idot-"):]] for slot in sorted(wired)])
        return self.results[node_id]

    def call(self, name, values):
        """The node *name*'s own code, on *values*, one per circle."""
        from utk_curio.backend.app.execution.code_references import resolve_references
        from utk_curio.sandbox.util.input_names import call_as_node

        node = self.nodes[f"idot-{name}"]
        widgets = [
            {**widget, "value": self.settings[widget["name"]]} if widget["name"] in self.settings else widget
            for widget in node.get("metadata", {}).get("widgets", [])
        ]
        slots = list(range(len(values)))
        code, problems = resolve_references(node["content"], widgets, "python", [{"slot": slot} for slot in slots])
        assert problems == [], problems
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            result = call_as_node(
                textwrap.indent(code, "    "), {"curio_load_data": self.load_data, **self.helpers},
                values[0] if len(values) == 1 else (values or None), slots or None,
            )
        self.printed[name] = printed.getvalue()
        return result


@pytest.fixture()
def run(tmp_path):
    return Run(tmp_path)


# ── The camera and its zones on the ground ──────────────────────────────────


@pytest.mark.parametrize(
    "camera,points,fit_error",
    [("W042 · Aug 9, 2025", 4, 0.0), ("W065 · Aug 17, 2025", 6, 0.5474), ("W06E · Dec 2, 2025", 5, 0.5020)],
)
def test_each_homography_fits_its_control_points_in_float64(tmp_path, camera, points, fit_error):
    """W042's four control points give a homography that puts each exactly
    where it lies; with more, the least squares fit misses them by a half
    metre on average."""
    fitted = Run(tmp_path, camera=camera)["camera-on-the-ground"]
    assert fitted["control_points"] == points
    assert fitted["fit_error_m"] == pytest.approx(fit_error, abs=1e-4)
    if points == 4:
        assert fitted["largest_error_m"] < 1e-6


def test_the_zones_on_the_ground_are_measured_in_square_metres(run):
    """Each zone's corners in pixels go through the homography to UTM zone 16N,
    so its area is in square metres, not in the pixels of a figure."""
    zones = run["zones-on-the-ground"]
    assert zones.crs.to_epsg() == 26916
    assert {zone: round(area, 2) for zone, area in zip(zones["zone"], zones["area_m2"])} == {
        "Westbound, before the crossing": 279.02,
        "Westbound, after the crossing": 133.59,
        "Eastbound, after the crossing": 158.23,
        "Eastbound, before the crossing": 186.63,
    }
    assert list(zones["before_the_crossing"]) == [True, False, False, True]


def test_the_light_of_w042s_day_is_astrals_dawn_sunrise_sunset_and_dusk(run):
    """2025-08-09 in UTC runs from 19:00 on 8 August to 19:00 on 9 August in
    Chicago: day until sunset, twilight until dusk, night until dawn, twilight
    until sunrise, then day, each change where astral puts it at the camera."""
    from astral import Observer
    from astral.sun import dawn, dusk, sunrise, sunset

    camera = run["camera-on-the-ground"]
    observer = Observer(latitude=camera["latitude"], longitude=camera["longitude"])

    def at(event, day):
        return event(observer, date(2025, 8, day), tzinfo=CHICAGO).strftime("%Y-%m-%dT%H:%M:%SZ")

    light = run["light"]
    assert list(zip(light["from"], light["to"], light["light"])) == [
        ("2025-08-08T19:00:00Z", at(sunset, 8), "day"),
        (at(sunset, 8), at(dusk, 8), "twilight"),
        (at(dusk, 8), at(dawn, 9), "night"),
        (at(dawn, 9), at(sunrise, 9), "twilight"),
        (at(sunrise, 9), "2025-08-09T19:00:00Z", "day"),
    ]
    # The team's fixed hours call it night from 17:00 and day only from 9:00.
    assert list(light["span"]) == ["19:00 to 19:59", "19:59 to 20:30", "20:30 to 05:22", "05:22 to 05:53",
                                   "05:53 to 19:00"]


# ── The records and the snapshots ───────────────────────────────────────────


def test_records_of_the_day_reads_the_day_alone(run):
    """The corpus's copy keeps three lines of each day beside W042's: the
    bisection starts after the day before's and stops before the next day's."""
    day_start = int(datetime(2025, 8, 9, tzinfo=timezone.utc).timestamp()) * 10**9
    lines = [json.loads(line) for line in (CORPUS / "W042_2025_08.jsonl").read_text(encoding="utf-8").splitlines()]
    images = [json.loads(line["value"])["image_timestamp_ns"] for line in lines
              if line["name"] == "object.detections.all" and line["timestamp"].startswith("2025-08-09")]
    assert lines[0]["timestamp"].startswith("2025-08-08") and lines[-1]["timestamp"].startswith("2025-08-10")

    records = run["records-of-the-day"]
    assert sorted(records["image_timestamp_ns"].unique()) == sorted(images)
    assert records["image_timestamp_ns"].between(day_start, day_start + 86_400 * 10**9 - 1).all()
    assert set(records["model"]) == {"YOLOv5n", "YOLOv8n", "YOLOv10n"}
    # An image a model saw nothing in keeps one row with no class.
    empty = records[records["class"].isna()]
    assert len(empty) and empty[["x0", "y0", "x1", "y1", "confidence"]].isna().all().all()
    assert "W042 on 2025-08-09: 906,444 bytes from 1,587, 375 images" in run.printed["records-of-the-day"]


def test_yolo26ns_boxes_join_the_snapshots_by_their_names(run):
    """Keira's CSV names each box's snapshot by its name in nanoseconds
    (timestamps_ns), the same value as the records' image_timestamp_ns: every
    one of W042's 924 boxes joins a snapshot of the day, and Models on the
    snapshots keeps those of the chosen classes at the chosen confidence."""
    keira = run["yolo26n"]
    w042 = keira[keira["dataset"] == "W042_08-09-2025"]
    assert len(keira) == 3016 and len(w042) == 924
    assert w042["timestamps_ns"].isin(run["snapshots-of-the-day"]["ns"]).all()

    boxes = run["models-on-the-snapshots"]
    kept = w042[w042["class"].isin(run["settings"]["classes"]) & (w042["confidence"] >= 0.5)]
    assert (boxes["model"] == "YOLO26n").sum() == len(kept) == 509
    assert boxes["model"].value_counts().to_dict() == {"YOLO26n": 509, "YOLOv8n": 352, "YOLOv10n": 350, "YOLOv5n": 287}


def test_each_ground_point_stands_at_its_boxs_bottom_center(run):
    """A ground point is its box's bottom center, ((x0 + x1) / 2, y1), through
    the homography: the same point the box's corners give, not its center."""
    import numpy as np

    points = run["on-the-ground"]
    h = np.array(run["camera-on-the-ground"]["h"])
    first = points.iloc[0]
    u, v, w = h @ np.array([(first["x0"] + first["x1"]) / 2, first["y1"], 1.0])
    assert (first["easting_m"], first["northing_m"]) == pytest.approx((u / w, v / w), abs=1e-6)
    assert points.crs.to_epsg() == 26916
    assert set(points["class"]) <= set(run["settings"]["classes"]) and "traffic light" not in set(points["class"])


# ── Occupancy, a made case ──────────────────────────────────────────────────


def _made_occupancy(run, model):
    """Zone occupancy's own code on a made case: two zones of 50 and 200 m²,
    three images in the minute of 08:00 in Chicago, one of them empty, and
    two at 08:01."""
    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import Point, box

    def ns(minute, second):
        moment = datetime(2025, 8, 9, 8, minute, second, tzinfo=CHICAGO)
        return int(moment.timestamp()) * 10**9

    images = [ns(0, 3), ns(0, 6), ns(0, 9), ns(1, 3), ns(1, 6)]
    records = pd.DataFrame({
        "image_timestamp_ns": images + [ns(0, 30)],
        "model": [model] * 5 + ["another model"],
        "class": ["car", "car", None, "car", "car", "car"],
    })
    zones = gpd.GeoDataFrame({"zone": ["A", "B"], "area_m2": [50.0, 200.0]},
                             geometry=[box(0, 0, 5, 10), box(10, 0, 30, 10)], crs=26916)
    inside = gpd.GeoDataFrame({
        # Three objects in A at 08:00, one in B; two in A at 08:01.
        "image_timestamp_ns": [images[0], images[0], images[1], images[1], images[3], images[4]],
        "zone": ["A", "A", "A", "B", "A", "A"],
    }, geometry=[Point(1, 1)] * 6, crs=26916)
    snapshots = pd.DataFrame({"ns": [images[0], images[3]]})
    return run.call("zone-occupancy", [{"model": model}, records, snapshots, zones, inside])


def test_zone_occupancy_counts_objects_per_image_per_100_m2_and_every_image(run):
    occupancy = _made_occupancy(run, "YOLOv8n")
    got = {(clock, zone): (objects, images, round(value, 4))
           for clock, zone, objects, images, value in occupancy[
               ["clock", "zone", "objects", "images", "per_image_per_100_m2"]].itertuples(index=False)}
    assert got == {
        # The empty image counts: 3 objects over 3 images over 50 m².
        ("08:00", "A"): (3, 3, 2.0),
        ("08:00", "B"): (1, 3, round(1 / 3 / 200 * 100, 4)),
        ("08:01", "A"): (2, 2, 2.0),
        ("08:01", "B"): (0, 2, 0.0),
    }
    assert list(occupancy["time"].unique()) == ["2025-08-09T08:00:00Z", "2025-08-09T08:01:00Z"]


def test_yolo26ns_occupancy_counts_the_snapshots_in_bins_of_5_minutes(run):
    """YOLO26n looked at the snapshots alone: its images are the snapshots,
    one every 5 minutes, and its bins are 5 minutes long."""
    occupancy = _made_occupancy(run, "YOLO26n")
    assert set(zip(occupancy["clock"], occupancy["zone"], occupancy["images"], occupancy["objects"])) == {
        ("08:00", "A", 2, 5), ("08:00", "B", 2, 1),
    }


# ── The frames and the models on the snapshots ──────────────────────────────


def test_the_busiest_half_hour_is_the_one_the_corpus_keeps_snapshots_of(run):
    """With the Settings tile's defaults, the half hour whose snapshots show
    the most objects before the crossing: the corpus records its six."""
    window = run["half-hour"].iloc[0]
    assert window["label"] == "Busiest, 4:00 PM to 4:30 PM"
    assert (window["from"], window["to"]) == ("2025-08-09T16:00:00Z", "2025-08-09T16:30:00Z")
    assert (window["from_ns"], window["to_ns"]) == (FRAMES_FROM, FRAMES_TO)
    snapshots = run["snapshots-of-the-day"]
    shown = snapshots[(snapshots["ns"] >= FRAMES_FROM) & (snapshots["ns"] < FRAMES_TO)]
    assert len(shown) == 6 and shown["path"].notna().all()


def test_a_chosen_half_hour_is_read_on_the_cameras_day(tmp_path):
    """7:00 PM is the first half hour of an August day, which starts at 19:00
    the evening before in Chicago."""
    window = Run(tmp_path, frames_from="7:00 PM")["half-hour"].iloc[0]
    assert (window["from"], window["label"]) == ("2025-08-08T19:00:00Z", "7:00 PM to 7:30 PM")


def test_frames_draw_the_half_hours_snapshots_with_every_models_count(run):
    from PIL import Image

    frames = run["frames"]
    assert list(frames.columns) == ["thumbnail", "taken_at", "v5n · v8n", "v10n · 26n"]
    assert frames.drop(columns="thumbnail").to_dict("records") == [
        {"taken_at": "16:00:14", "v5n · v8n": "2 · 2", "v10n · 26n": "2 · 3"},
        {"taken_at": "16:05:03", "v5n · v8n": "3 · 5", "v10n · 26n": "3 · 6"},
        {"taken_at": "16:10:02", "v5n · v8n": "3 · 3", "v10n · 26n": "3 · 3"},
        {"taken_at": "16:15:03", "v5n · v8n": "3 · 2", "v10n · 26n": "3 · 5"},
        {"taken_at": "16:20:02", "v5n · v8n": "2 · 4", "v10n · 26n": "3 · 5"},
        {"taken_at": "16:25:02", "v5n · v8n": "2 · 2", "v10n · 26n": "2 · 2"},
    ]
    pictures = sorted(run.media.rglob("*.png"))
    assert len(pictures) == 6
    for picture in pictures:
        with Image.open(picture) as drawn:
            assert drawn.size == (960, 720)
    # The pictures' tag names the settings they were drawn with.
    assert all("@0-frames" in url for url in frames["thumbnail"])


def test_agreement_finds_each_models_own_boxes(run):
    agreement = run["agreement"]
    diagonal = agreement[agreement["model"] == agreement["other"]]
    assert list(diagonal["share"]) == [1.0, 1.0, 1.0, 1.0]
    assert len(agreement) == 16 and agreement["share"].between(0, 1).all()


def test_agreement_needs_the_same_class_and_an_iou_of_one_half(run):
    """A box another model finds is one of the same class on the same
    snapshot that overlaps it by an intersection over union of 0.5 or more."""
    import pandas as pd

    rows = [
        # Snapshot 1: B's box covers half of A's (IoU 0.5); C's 0.4 of it.
        (1, "YOLOv5n", "car", 0, 0, 10, 10), (1, "YOLOv8n", "car", 0, 0, 10, 5), (1, "YOLOv10n", "car", 0, 0, 10, 4),
        # Snapshot 2: the same box, but a truck to YOLO26n.
        (2, "YOLOv5n", "car", 0, 0, 10, 10), (2, "YOLO26n", "truck", 0, 0, 10, 10),
    ]
    boxes = pd.DataFrame(rows, columns=["image_timestamp_ns", "model", "class", "x0", "y0", "x1", "y1"])
    agreement = run.call("agreement", [boxes])
    share = {(one, other): value for one, other, value in agreement[["model", "other", "share"]].itertuples(index=False)}
    assert share["YOLOv5n", "YOLOv8n"] == 0.5  # found on snapshot 1, not on 2
    assert share["YOLOv5n", "YOLOv10n"] == 0.0
    assert share["YOLOv5n", "YOLO26n"] == 0.0
    assert share["YOLOv8n", "YOLOv5n"] == 1.0
