"""The Crown Heights shadow example on the CPU.

``docs/examples/dataflows/crown-heights-1550-bedford-shadow.json`` is written
by ``scripts/build_example_bedford_shadow.py``. It has two scenarios, without
and with the building proposed at 1550 Bedford Avenue. Its maps show one of
2027's equinoxes and solstices, and its year's plot and table every day of
2027. A day counts from 1.5 hours after its sunrise to 1.5 hours before its
sunset (suntime), in New York time, in 10-minute steps with astral's sun at
the middle of each, and only open ground counts.

Here the example's own Python nodes run on the shipped data as the sandbox
runs them (``call_as_node``, Curio's reference resolution, the Map Editor's
``curio_edit_features``), and its two GPU steps run as a NumPy mirror of their
WGSL march, in 32-bit floats. The mirror's minutes on Block 1259 for each of
the four days, and its table of the months, are the ones
``_support/crown_heights.py`` holds, which the dashboard e2e checks the GPU
against.

The example's node code imports suntime and astral when it runs, so this
module imports neither.
"""
from __future__ import annotations

import datetime
import importlib.util
import json
import re
import textwrap
import uuid
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from utk_curio.backend.tests._support.crown_heights import DURATIONS, FOUR_DAYS, MONTH_HEADER, MONTHS, minutes

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "scripts" / "build_example_bedford_shadow.py"
EXAMPLE = REPO_ROOT / "docs" / "examples" / "dataflows" / "crown-heights-1550-bedford-shadow.json"
DATA = REPO_ROOT / "datasets"
CELL = np.float32(3)
#: Sunrise and sunset at the site (40.6696 N, 73.9558 W) by NOAA's solar
#: equations, to the second, independent of suntime and astral.
NOAA = {
    "Spring equinox": ("2027-03-20T07:01:10-04:00", "2027-03-20T19:06:47-04:00"),
    "Summer solstice": ("2027-06-21T05:24:25-04:00", "2027-06-21T20:29:52-04:00"),
    "Fall equinox": ("2027-09-23T06:42:55-04:00", "2027-09-23T18:53:25-04:00"),
    "Winter solstice": ("2027-12-21T07:15:54-05:00", "2027-12-21T16:31:23-05:00"),
}
NUMBER = re.compile(r"-?\d+\.\d+")


@lru_cache(maxsize=None)
def _spec() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))["dataflow"]


def _id(key: str) -> str:
    """The node id the builder gives *key*."""
    namespace = uuid.uuid5(uuid.NAMESPACE_URL, f"https://curio.dev/examples/{_spec()['name']}")
    return str(uuid.uuid5(namespace, key))


def _node(key: str) -> dict:
    matches = [n for n in _spec()["nodes"] if n["id"] == _id(key)]
    assert matches, f"the example has no node {key!r}"
    return matches[0]


def _load_data(dataset_id, bounds=None, part=None):
    import geopandas as gpd

    path = DATA / f"{dataset_id}@1" / "data" / part
    return gpd.read_parquet(path) if path.suffix == ".parquet" else gpd.read_file(path)


def _run(key: str, *inputs, day: str | None = None):
    """Node *key*'s code, run on *inputs* as the sandbox runs it."""
    from utk_curio.backend.app.execution.workflow_spec import resolve_code_references
    from utk_curio.sandbox.util.feature_edits import edit_features
    from utk_curio.sandbox.util.input_layers import curio_layer
    from utk_curio.sandbox.util.input_names import call_as_node

    node = _node(key)
    widgets = [dict(w) for w in node["metadata"].get("widgets", [])]
    for widget in widgets:
        if day is not None and widget["name"] == "day":
            widget["value"] = day
    slots = list(range(len(inputs)))
    code = resolve_code_references(node["content"], widgets, "python", slots)
    namespace = {"curio_load_data": _load_data, "curio_edit_features": edit_features, "curio_layer": curio_layer}
    value = None if not inputs else inputs[0] if len(inputs) == 1 else list(inputs)
    return call_as_node(textwrap.indent(code, "    "), namespace, value, slots)


def _layers(**frames) -> dict:
    """What an Autark compute step hands on: its layers, by name, as the
    browser posts them."""
    return {"dataType": "outputs", "data": [
        {"dataType": "geodataframe", "layerName": name, "data": json.loads(frame.to_json())}
        for name, frame in frames.items()
    ]}


def _march(px, py, sx, sy, cot, heights, tallest):
    """The WGSL march (``march`` in the builder), in 32-bit floats: whether
    the ray from each point toward its sun passes under a roof. *sx*, *sy*
    and *cot* are one sun for every point, or one sun per point."""
    rows, cols = heights.shape
    sx, sy, cot = (np.broadcast_to(np.asarray(value, np.float32), px.shape) for value in (sx, sy, cot))
    limit = tallest * cot
    shaded = np.zeros(len(px), bool)
    walking = np.arange(len(px))
    half = CELL / np.float32(2)
    t = half
    while walking.size:
        walking = walking[t <= limit[walking]]
        col = np.floor((px[walking] + sx[walking] * t) / CELL).astype(np.int64)
        row = np.floor((py[walking] + sy[walking] * t) / CELL).astype(np.int64)
        # The shader stops a ray where it leaves the grid; it never comes back.
        inside = (col >= 0) & (row >= 0) & (col < cols) & (row < rows)
        walking, col, row = walking[inside], col[inside], row[inside]
        hit = heights[row, col] * cot[walking] > t
        shaded[walking[hit]] = True
        walking = walking[~hit]
        t = np.float32(t + half)
    return shaded


def _grid(prepared):
    first = prepared.iloc[0]
    return (np.asarray(first["heights"], dtype=np.float32), np.float32(first["tallest"]),
            np.asarray(first["spots"], dtype=np.float32))


def _cells_pass(ground, prepared, steps) -> dict:
    """The mirror of "Cast sun rays on the GPU": minutes in shadow per cell."""
    heights, tallest, _ = _grid(prepared)
    x, y = ground["x"].to_numpy(np.float32), ground["y"].to_numpy(np.float32)
    own = heights[np.floor(y / CELL).astype(int), np.floor(x / CELL).astype(int)]
    total = np.zeros(len(ground), np.float32)
    for east, north, cot, length in steps["steps"].iloc[0]:
        shaded = _march(x, y, np.float32(east), np.float32(north), np.float32(cot), heights, tallest)
        total += np.where(shaded, np.float32(length), np.float32(0))
    cells = ground.copy()
    cells["shadow_min"] = np.where(own > 0, np.float32(-1), total).astype(float)
    return _layers(input_0=cells, input_1=prepared, input_2=steps)


def _block_pass(steps, prepared) -> dict:
    """The mirror of "Cast sun rays on Block 1259": the share of its open
    ground in shadow at each step, many steps at once."""
    heights, tallest, spots = _grid(prepared)
    suns = steps[["east", "north", "cot"]].to_numpy(np.float32)
    shares = []
    for start in range(0, len(suns), 1500):
        chunk = suns[start:start + 1500]
        shaded = _march(np.tile(spots[:, 0], len(chunk)), np.tile(spots[:, 1], len(chunk)),
                        *(np.repeat(chunk[:, k], len(spots)) for k in range(3)), heights, tallest)
        dark = shaded.reshape(len(chunk), len(spots)).sum(axis=1).astype(np.float32)
        shares += (np.float32(100) * dark / np.float32(max(len(spots), 1))).astype(float).tolist()
    marked = steps.copy()
    marked["share"] = shares
    return _layers(input_0=marked, input_1=prepared)


@lru_cache(maxsize=None)
def _inputs():
    """The fixed context: the loads, the edited buildings and the ground."""
    buildings = _run("buildings")
    block = _run("block")
    edited = _run("add-building", buildings)
    ground = _run("ground", buildings, block)
    return buildings, block, edited, ground


@lru_cache(maxsize=None)
def _prepared():
    buildings, _block, edited, ground = _inputs()
    return {"without": _run("base-tower", buildings, ground), "with": _run("tower", edited, ground)}


#: Each scenario's prefix of its nodes' keys.
PREFIX = {"without": "base-", "with": ""}


@lru_cache(maxsize=None)
def _year():
    return _run("year-steps")


@lru_cache(maxsize=None)
def _steps(day: str):
    return _run("steps", day=day)


def _year_pass(year, prepared) -> dict:
    """The mirror of "Cast sun rays on Block 1259 through the year": each
    day's minutes in shadow on the block's open ground, on average, added up
    step by step in 32-bit floats as the shader adds them."""
    heights, tallest, spots = _grid(prepared)
    steps = np.asarray(year["steps"].iloc[0], dtype=np.float32)
    shaded = np.zeros(len(steps), np.float32)
    for start in range(0, len(steps), 1500):
        chunk = steps[start:start + 1500]
        hits = _march(np.tile(spots[:, 0], len(chunk)), np.tile(spots[:, 1], len(chunk)),
                      *(np.repeat(chunk[:, k], len(spots)) for k in range(3)), heights, tallest)
        shaded[start:start + len(chunk)] = hits.reshape(len(chunk), len(spots)).sum(axis=1)
    count = np.float32(max(len(spots), 1))
    days = []
    for first, many in zip(year["first_step"], year["step_count"]):
        dark = np.float32(0)
        for s in range(first, first + many):
            dark = np.float32(dark + np.float32(steps[s, 3] * shaded[s]) / count)
        days.append(float(dark))
    marked = year.copy()
    marked["shadow_min"] = days
    return _layers(input_0=marked, input_1=prepared)


@lru_cache(maxsize=None)
def _days(scenario: str):
    """The scenario's time in shadow on the block, a row per day of the year,
    from its compute step over the year's days."""
    return _run(PREFIX[scenario] + "block-days", _year_pass(_year(), _prepared()[scenario]))


@lru_cache(maxsize=None)
def _day(day: str):
    """Each scenario's per-step table and per-cell shadow on *day*."""
    *_rest, ground = _inputs()
    steps = _steps(day)
    out = {}
    for scenario, prefix in PREFIX.items():
        prepared = _prepared()[scenario]
        out[scenario] = {
            "steps": _run(prefix + "block-steps", _block_pass(steps, prepared)),
            "cells": _run(prefix + "shadow-cells", _cells_pass(ground, prepared, steps)),
        }
    return out


def _same(built, shipped, where="dataflow"):
    """*built* is *shipped*, but for the last digits of coordinates."""
    assert type(built) is type(shipped), f"{where}: {type(built).__name__} vs {type(shipped).__name__}"
    if isinstance(built, dict):
        assert built.keys() == shipped.keys(), f"{where}: keys {sorted(built.keys() ^ shipped.keys())}"
        for key in built:
            _same(built[key], shipped[key], f"{where}.{key}")
    elif isinstance(built, list):
        assert len(built) == len(shipped), f"{where}: {len(built)} items vs {len(shipped)}"
        for i, (a, b) in enumerate(zip(built, shipped)):
            _same(a, b, f"{where}[{i}]")
    elif isinstance(built, float):
        assert built == pytest.approx(shipped, abs=1e-6), where
    elif isinstance(built, str):
        # Node code writes the proposed building's corners as numbers in text.
        assert NUMBER.split(built) == NUMBER.split(shipped), where
        for a, b in zip(NUMBER.findall(built), NUMBER.findall(shipped)):
            assert float(a) == pytest.approx(float(b), abs=1e-6), f"{where}: {a} vs {b}"
    else:
        assert built == shipped, where


def _clock(text: str, day: str) -> datetime.datetime:
    """A clock time as the example writes it ("8:46 AM EST") on *day*'s date."""
    time, noon, zone = text.split()
    hour, minute = (int(part) for part in time.split(":"))
    hour = hour % 12 + (12 if noon == "PM" else 0)
    sunrise = datetime.datetime.fromisoformat(NOAA[day][0])
    assert zone == ("EDT" if sunrise.utcoffset() == datetime.timedelta(hours=-4) else "EST"), text
    return sunrise.replace(hour=hour, minute=minute, second=0)


def _builder():
    spec = importlib.util.spec_from_file_location("_scripts_build_example_bedford_shadow", SCRIPT)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    return builder


def _shipped_edits() -> list:
    """The edits the shipped Map Editor node makes, read back from its code."""
    import ast

    code = _node("add-building")["content"]
    tree = ast.parse("def node():\n" + textwrap.indent(code, "    "))
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "curio_edit_features")
    return ast.literal_eval(call.args[1])


def test_the_builder_writes_the_shipped_example(monkeypatch):
    # The proposed building's outlines come from GEOS, whose versions keep
    # different vertices along the same edges; the next test compares their
    # shapes. Here the builder writes everything else from the shipped ones.
    builder = _builder()
    monkeypatch.setattr(builder, "massing", _shipped_edits)
    _same(builder.build(), json.loads(EXAMPLE.read_text(encoding="utf-8")))


def test_the_builder_draws_the_proposed_building_the_example_ships():
    import geopandas as gpd
    import shapely
    from shapely.geometry import shape

    built, shipped = _builder().massing(), _shipped_edits()
    assert len(built) == len(shipped) == 2
    for mine, theirs in zip(built, shipped):
        assert {k: v for k, v in mine.items() if k != "geometry"} == {k: v for k, v in theirs.items() if k != "geometry"}
        # In New York's state plane, in feet. GEOS builds differ in the last
        # digits and in where an outline starts, and an overlay of two
        # outlines that close may refuse to run, so they are compared by
        # distance: no point of either lies 0.1 ft from the other (the
        # builder rounds to 1e-7 degrees, under 0.05 ft here).
        a, b = gpd.GeoSeries([shape(mine["geometry"]), shape(theirs["geometry"])], crs=4326).to_crs(2263)
        assert a.is_valid and b.is_valid, (mine["label"], shapely.is_valid_reason(a), shapely.is_valid_reason(b))
        apart = shapely.hausdorff_distance(a, b, densify=0.01)
        assert apart < 0.1, (mine["label"], apart)


@pytest.mark.parametrize("day", list(NOAA))
def test_a_day_counts_from_an_hour_and_a_half_after_sunrise_to_an_hour_and_a_half_before_sunset(day):
    steps = _steps(day)
    sunrise, sunset = (datetime.datetime.fromisoformat(moment) for moment in NOAA[day])
    start, end = _clock(steps["window_from"].iloc[0], day), _clock(steps["window_to"].iloc[0], day)
    margin = datetime.timedelta(hours=1.5)
    assert abs(start - (sunrise + margin)) <= datetime.timedelta(minutes=2), (day, start)
    assert abs(end - (sunset - margin)) <= datetime.timedelta(minutes=2), (day, end)
    # Ten-minute steps, the last one shorter, cover the window and no more.
    lengths = steps["minutes"].to_numpy()
    assert (lengths > 0).all() and (lengths <= 10).all() and (lengths[:-1] == 10).all()
    assert lengths.sum() == pytest.approx((end - start).total_seconds() / 60, abs=1)
    assert (steps["cot"] > 0).all(), "the sun is up at every step"
    assert set(steps["day"]) == {day}
    # The first point carries every step for the GPU step that walks the day.
    whole = steps["steps"].iloc[0]
    assert np.allclose(whole, steps[["east", "north", "cot", "minutes"]].to_numpy())
    assert steps["steps"].iloc[1:].isna().all()
    # The year's node cuts the day as the day's node does, so the day's plot
    # and the year's plot and table read the same day.
    year = _year()
    of_year = year[year["date"] == NOAA[day][0][:10]].iloc[0]
    first, many = of_year["first_step"], of_year["step_count"]
    assert np.array_equal(np.asarray(year["steps"].iloc[0][first:first + many]), whole)
    assert (of_year["window_from"], of_year["window_to"]) == (steps["window_from"].iloc[0], steps["window_to"].iloc[0])


def test_the_year_counts_every_day_of_2027_alike():
    year = _year()
    assert list(year["date"]) == [(datetime.date(2027, 1, 1) + datetime.timedelta(days=n)).isoformat()
                                  for n in range(365)]
    # Every step of the year on the first day's point, each day's after the
    # one before's.
    steps = np.asarray(year["steps"].iloc[0])
    assert year["steps"].iloc[1:].isna().all()
    assert list(year["first_step"]) == [0, *np.cumsum(year["step_count"])[:-1]]
    assert year["step_count"].sum() == len(steps) == 20332
    # About 6 hours of 10-minute steps on the shortest days, 12 on the longest.
    assert year["step_count"].min() == 38 and year["step_count"].max() == 73
    assert (steps[:, 2] > 0).all(), "the sun is up at every step"
    for date, first, many, window in zip(year["date"], year["first_step"], year["step_count"], year["window_min"]):
        lengths = steps[first:first + many, 3]
        assert (lengths > 0).all() and (lengths <= 10).all() and (lengths[:-1] == 10).all(), date
        assert lengths.sum() == pytest.approx(window), date


def test_the_ground_is_open_and_the_block_spots_lie_on_it():
    import shapely

    buildings, _block, _edited, ground = _inputs()
    first = ground.iloc[0]
    roofs = buildings.to_crs(f"EPSG:{int(first['epsg'])}")
    centres = shapely.points(first["grid_west"] + ground["x"], first["grid_south"] + ground["y"])
    inside = shapely.STRtree(roofs.geometry.values).query(centres, predicate="within")[0]
    assert len(inside) == 0, "a ground cell lies under an existing building"
    assert ground["on_block"].sum() > 500
    _heights, _tallest, spots = _grid(_prepared()["without"])
    on_block = ground[ground["on_block"] == 1][["x", "y"]].to_numpy(dtype=np.float32)
    assert {tuple(s) for s in spots} == {tuple(c) for c in on_block}


def test_without_the_proposed_building_no_part_of_it_stands_and_with_it_both_parts_do():
    _buildings, _block, edited, ground = _inputs()
    without, with_building = (_grid(_prepared()[scenario])[0] for scenario in ("without", "with"))
    first = ground.iloc[0]
    tower = edited[edited["status"] != "Existing"].to_crs(f"EPSG:{int(first['epsg'])}")
    assert len(tower) == 2
    changed = without != with_building
    assert changed.any()
    assert (without[changed] < with_building[changed]).all(), "the proposed building only adds height"
    assert set(np.unique(with_building[changed])) <= {np.float32(round(h, 2)) for h in tower["height"]}
    assert with_building.max() >= np.float32(56.4)


def test_each_gpu_step_needs_at_most_eight_storage_buffers():
    computes = [n for n in _spec()["nodes"] if n["type"] == "curio.builtin/autk-grammar" and '"compute"' in n["content"]]
    assert len(computes) == 6, "three GPU steps in each scenario"
    for node in computes:
        for step in json.loads(node["content"])["compute"]:
            batched = [u for u in step.get("uniforms", {}).values()
                       if isinstance(u, dict) and u.get("fromFeature", {}).get("iterate") == "batched"]
            buffers = len(step["attributes"]) + len(step.get("uniformMatrices", {})) + len(batched) + 1
            assert buffers <= 8, f"{node['title']} needs {buffers} storage buffers; WebGPU's default is 8"


def test_two_scenarios_share_no_node_and_the_map_editor_edits_a_map_of_its_own():
    spec = _spec()
    scenarios = {s["id"]: set(s["nodes"]) for s in spec["scenarios"]}
    assert list(scenarios) == ["without", "with"]
    assert not scenarios["without"] & scenarios["with"]
    editor = _id("add-building")
    assert editor in scenarios["with"]
    linked = [e["target"] for e in spec["edges"] if e.get("type") == "Interaction" and e["source"] == editor]
    assert linked == [_id("shadow-map")] and linked[0] in scenarios["with"]


def test_what_the_pinned_tiles_read_fits_the_page_a_shared_dashboard_carries():
    """A shared dashboard carries the saved outputs its tiles read in its
    page, up to ``DEFAULT_PAYLOAD_LIMIT_BYTES``; past it the page is refused
    and a visitor sees no tile. On the winter solstice, when the most open
    ground is in shadow, what the pinned tiles read stays under half of it,
    the scenario maps' cells gathered into classes."""
    from utk_curio.backend.app.projects.dashboard_payload import DEFAULT_PAYLOAD_LIMIT_BYTES

    buildings, block, edited, _ground = _inputs()
    day = _day("Winter solstice")
    added = _run("added", day["without"]["cells"], day["with"]["cells"])
    read = {
        "base-shadow-shown": _run("base-shadow-shown", day["without"]["cells"]),
        "shadow-shown": _run("shadow-shown", day["with"]["cells"]),
        "added-shown": _run("added-shown", added, edited),
        "buildings": buildings, "add-building": edited, "block": block, "streets": _run("streets"),
        "map-area": _run("map-area", buildings), "steps": _steps("Winter solstice"),
        "base-block-steps": day["without"]["steps"], "block-steps": day["with"]["steps"],
        "base-block-days": _days("without"), "block-days": _days("with"),
        "compare": _run("compare", _days("without"), _days("with")),
    }
    sizes = {key: len(frame.to_json().encode("utf-8")) for key, frame in read.items()}
    assert sum(sizes.values()) < DEFAULT_PAYLOAD_LIMIT_BYTES / 2, sizes


@pytest.mark.parametrize("row", FOUR_DAYS, ids=["spring", "summer", "fall", "winter"])
def test_the_cpu_march_gives_the_four_days_their_rows(row):
    day = row["Day"]
    scenarios = _day(day)
    assert row["Date"] == NOAA[day][0][:10]
    of_year = {scenario: _days(scenario).set_index("date").loc[row["Date"]] for scenario in PREFIX}
    # The day's window, as its plot shows it, and the time it counts.
    first = scenarios["with"]["steps"].iloc[0]
    assert (first["day"], first["window_from"], first["window_to"]) == (row["Day"], row["From"], row["To"])
    assert round(of_year["with"]["window_min"]) == minutes(row["Time counted"])
    got = {"Without the proposed building": of_year["without"]["shadow_min"],
           "With the proposed building": of_year["with"]["shadow_min"],
           "Added": of_year["with"]["shadow_min"] - of_year["without"]["shadow_min"]}
    for header in DURATIONS:
        assert got[header] == pytest.approx(row[header], abs=0.05), header
    for scenario in PREFIX:
        # The year's plot says the day's time in shadow as it rounds.
        assert minutes(of_year[scenario]["in_shadow"]) == round(of_year[scenario]["shadow_min"]), scenario
        # The day's plot draws the steps the year's row adds up, but for the
        # last digits: the year's step adds them in 32-bit floats.
        steps = scenarios[scenario]["steps"]
        dark = float((steps["share"] / 100 * steps["minutes"]).sum())
        assert dark == pytest.approx(of_year[scenario]["shadow_min"], abs=0.01), scenario
    # The map's step and the block's step march alike: the cells of the block
    # gain on average what the block's steps add.
    cells = {scenario: scenarios[scenario]["cells"] for scenario in PREFIX}
    added = _run("added", cells["without"], cells["with"])
    assert (added["added_min"] >= 0).all(), "the proposed building only adds shade"
    assert added.loc[added["on_block"] == 1, "added_min"].mean() == pytest.approx(got["Added"], abs=0.05)


def test_the_cpu_march_gives_the_months_the_dashboard_pins():
    table = _run("compare", _days("without"), _days("with"))
    assert list(table.columns) == ["Month", MONTH_HEADER]
    assert table.to_dict("records") == [{k: row[k] for k in ("Month", MONTH_HEADER)} for row in MONTHS]
    # The figures before the table rounds them, which the e2e holds the
    # GPU's to.
    both = _days("without")[["date", "shadow_min"]].merge(
        _days("with")[["date", "shadow_min"]], on="date", suffixes=("_without", "_with"))
    added = both["shadow_min_with"] - both["shadow_min_without"]
    assert (added >= 0).all(), "the proposed building only adds shade"
    for row, (_month, month) in zip(MONTHS, added.groupby(pd.to_datetime(both["date"]).dt.month), strict=True):
        assert month.mean() == pytest.approx(row["average"], abs=0.01), row["Month"]
        assert float(np.std(month)) == pytest.approx(row["sd"], abs=0.01), row["Month"]
