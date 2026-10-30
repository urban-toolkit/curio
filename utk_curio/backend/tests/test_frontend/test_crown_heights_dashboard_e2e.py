"""Playwright E2E: komar41's Crown Heights example, two scenarios on an
equinox or a solstice, exercises the dashboard's sharing features.

``docs/examples/dataflows/crown-heights-1550-bedford-shadow.json`` compares
the shadow on Block 1259's open ground without and with the tower proposed at
1550 Bedford Avenue. Its dashboard pins the node that lists the day's sun
steps, whose Day radio is a visitor's control, the Map Editor node that adds
the tower, a map of each scenario's shadow and one of the shade the tower
adds that day, the plot of the block's shadow through the day under the day's
window, the plot of the block's time in shadow each day of 2027, a line per
scenario in its color on both, and the table of the shade the tower adds a
day, month by month. Each scenario casts its sun rays in three Autark compute
steps, which only a browser runs: two read the day, the third the year. On a
dashboard each visitor's own page runs those a run leaves it, after the
server has run the Python before them, once for everyone (#1117). A day
reaches the day's two; the year's run again only where the dashboard saved
nothing for its tiles.

* The owner runs the example, saves it and shares it. The Share menu copies
  the dashboard's link and the dataflow's, and opens the dashboard for the
  owner to lay out. A visitor with no session opens the link and sees the
  owner's results, with nothing run and no notice over them. Another day
  makes the day's sun steps again on the server, runs the day's four GPU
  steps in the visitor's page and the Python after them on the server, and
  the maps and the day's plot draw it; the year's plot and the table stay as
  they were. A second visitor who picks the same day gets the steps before
  the GPU steps as the first visitor's run kept them, runs the GPU steps in
  its own page, and reads what the first one read. The saved day brings the
  saved results back with no run. Another account opens the dataflow's link
  and sees the owner's results, read-only.
* The link dev serves works on this deployment too. The shared guest's copy of
  a shipped dataflow (``projects/seed.py``) has an id made from the example's
  file name, the same on every deployment. Opened at that link, a dashboard no
  one ran fills its tiles through a run, the year's GPU steps among them, and
  another day draws them again, the year's too since that copy saves
  nothing, making again only the day's sun steps among the steps before the
  GPU steps. While the run goes, the maps, the plots and the table say they
  are computing. In a browser with no WebGPU, they say which step could not
  run.
* A visitor in a private window goes through the four days. The page is served
  as dev serves it, DuckDB's module compressed on the fly with no length, and
  the browser's cache is the in-memory one a private window has: the three
  maps share one download of the module, each day's maps and plot draw it,
  the year's plot and the table stay as they were, and the page logs no
  error.

The numbers are the CPU reference's (``tests/_support/crown_heights.py``,
which ``test_scripts/test_bedford_shadow_example.py`` pins): the table's
months as the page shows them, and each day's minutes in shadow as the runs'
saved tables hold them. What the GPU draws here is what the CPU computes.

Run::

    CURIO_E2E_USE_EXISTING=1 pytest \\
        utk_curio/backend/tests/test_frontend/test_crown_heights_dashboard_e2e.py -v
"""
from __future__ import annotations

import gzip
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from utk_curio.backend.tests._support.crown_heights import (
    DURATIONS,
    FOUR_DAYS,
    MONTH_HEADER,
    MONTH_TOLERANCE_MIN,
    MONTHS,
    SUMMER,
    TOLERANCE_MIN,
    WINTER,
    average_and_sd,
)
from utk_curio.common import shared_constants

from . import diagnostics
from .test_dashboard_page_e2e import (
    CLIENT_ERROR_PATH,
    _NODES_STANDING_JS,
    _Visitor,
    _catalog_ids,
    _client_error_report,
    _enter,
    _files_read,
    _not_a_viewer_route,
    _project,
    _runs_started,
    _sent_results,
    _serve_hosted,
    _step_outputs,
    _steps_sent,
)
from .test_map_edits_e2e import _changed, _map_pixels, _wait_for_map_drawn, _wait_for_redraw
from .utils import (
    _COLOR_PIXELS_JS,
    CLOSEUP_MAX_DIFF_RATIO,
    CLOSEUP_PIXEL_THRESHOLD,
    REPO_ROOT,
    api_json,
    assert_vega_canvas_rendered,
    frame_nodes,
    held_server_nodes,
    hold_server_runs,
    keep_drawing,
    load_artifact_as_dict,
    node_locator,
    park_pointer,
    require_project_page,
    require_user_auth,
    require_webgpu,
    run_all_and_wait,
    save_dataflow,
    save_workflow_test_screenshot,
    stub_db_login,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

EXAMPLE = Path(REPO_ROOT, "docs", "examples", "dataflows", "crown-heights-1550-bedford-shadow.json")
NAME = "Crown Heights shade from 1550 Bedford Avenue"
STEM = "crown-heights-dashboard"
#: The namespace the example's builder makes its node ids in
#: (``scripts/build_example_bedford_shadow.py``): a node's id is its key's
#: uuid5. The test finds each node by its key, since the two scenarios' copies
#: share their titles.
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, f"https://curio.dev/examples/{NAME}")

#: The namespace of the ids the shared guest's copies of the shipped dataflows
#: get (``_EXAMPLES_NAMESPACE`` in ``projects/seed.py``), written out here: a
#: shared link is made with it, so a change to it breaks every link already
#: shared and must fail this test.
SHIPPED_IDS = uuid.UUID("a3f1c0d4-1111-4b8e-9a6e-c0ff33ee5eed")
#: The id in the link to the shipped copy of the example: the same on dev, on
#: any other deployment and here.
LINK_ID = str(uuid.uuid5(SHIPPED_IDS, "dataflows/crown-heights-1550-bedford-shadow"))

#: The example's nodes, by builder key, with the title each one's header shows.
LABELS = {
    # The fixed context both scenarios read.
    "buildings": "Load existing buildings",
    "block": "Load Block 1259 outline",
    "streets": "Load streets",
    "steps": "List the day's sun steps",
    "year-steps": "List the year's sun steps",
    "ground": "Make open-ground grid",
    "map-area": "Map extent (keeps layers whole)",
    # Scenario 1, without the proposed building.
    "base-tower": "Prepare buildings for the GPU",
    "base-sun-rays": "Cast sun rays on the GPU",
    "base-block-rays": "Cast sun rays on Block 1259",
    "base-year-rays": "Cast sun rays on Block 1259 through the year",
    "base-shadow-cells": "Read shadow per cell",
    "base-block-steps": "Read shadow on the block per step",
    "base-block-days": "Read shadow on the block per day",
    "base-shadow-shown": "Keep shaded cells for the map",
    "base-shadow-map": "Map: without the proposed building",
    # Scenario 2, with it: the Map Editor node, then copies of scenario 1's chain.
    "add-building": "Add proposed tower (1550 Bedford Ave)",
    "tower": "Prepare buildings for the GPU",
    "sun-rays": "Cast sun rays on the GPU",
    "block-rays": "Cast sun rays on Block 1259",
    "year-rays": "Cast sun rays on Block 1259 through the year",
    "shadow-cells": "Read shadow per cell",
    "block-steps": "Read shadow on the block per step",
    "block-days": "Read shadow on the block per day",
    "shadow-shown": "Keep shaded cells for the map",
    "shadow-map": "Map: with the proposed building",
    # The comparison.
    "plot": "Plot: shadow on Block 1259 through the day",
    "year-plot": "Plot: shadow on Block 1259 each day of 2027",
    "compare": "Compare the scenarios by month",
    "summary-view": "Table: shade added on Block 1259 by month",
    "added": "Shade the tower adds",
    "added-shown": "Keep added shade for the map",
    "added-map": "Map: shade the tower adds",
}
#: The steps only a browser runs that read the day: each scenario's Autark
#: compute steps on WebGPU for its map and for the day's plot. They read only
#: what the server makes before them, so a run of a day leaves all four to the
#: page at once, and the start going on from them makes the rest.
PAGE_STEPS = ("base-sun-rays", "base-block-rays", "sun-rays", "block-rays")
#: Each scenario's compute step over the year's days, which no day reaches: a
#: run makes it only where the dashboard saved nothing for the tiles it feeds,
#: as on the shipped copy, on open and on each day.
YEAR_STEPS = ("base-year-rays", "year-rays")
#: What the server makes before the page's steps that the day does not reach:
#: the loads, the Map Editor's edits, the maps' extent, the open-ground grid,
#: the year's sun steps and each scenario's buildings for the GPU. Of the
#: steps before the page's, only the day's sun steps (``steps``) read the day.
DAY_BLIND = ("buildings", "block", "streets", "add-building", "map-area", "ground", "year-steps", "base-tower",
             "tower")
#: Of those, what the day's page steps read: the open-ground grid and each
#: scenario's buildings for the GPU. No tile reads them, so the page holds no
#: saved copy, and a run of a day hands them on, kept or made again.
PAGE_INPUTS = ("ground", "base-tower", "tower")
#: What the server makes after the day's page steps, from what the page made.
AFTER_PAGE = (
    "base-shadow-cells", "base-block-steps", "base-shadow-shown",
    "shadow-cells", "block-steps", "shadow-shown", "added", "added-shown",
)
#: What it makes after the year's: each scenario's days and the table's months.
AFTER_YEAR = ("base-block-days", "block-days", "compare")
#: The three maps: each scenario's shadow, and the shade the tower adds.
MAPS = ("base-shadow-map", "shadow-map", "added-map")
#: The tiles a run fills: the maps, the plots and the table.
TILES = (*MAPS, "plot", "year-plot", "summary-view")
#: The dashboard's pins: those tiles, the sun steps node, whose Day radio is a
#: visitor's control, and the Map Editor node that adds the tower.
PINNED = ("steps", "add-building", *TILES)

#: How long a run of the chain may take: the Python before the GPU steps, the
#: page's GPU steps, then the Python after them, on a busy GPU runner.
RUN_TIMEOUT_MS = 240000

#: What an Autark map's database asks of the backend on any page it draws on:
#: DuckDB's extensions, which Curio serves itself.
_EXTENSIONS_RE = re.compile(r"^GET /file/vendor/duckdb-extensions/")

#: What a tile with nothing yet says while a viewer's run makes it, title and
#: hint (``NODE_EMPTY_COPY["upstream-running"]``).
COMPUTING = ("Computing...", "Results will be shown here once they are ready.")

#: Before the page's own scripts: a browser with no WebGPU, as the
#: walkthroughs make one.
_NO_WEBGPU_JS = "Object.defineProperty(navigator, 'gpu', { configurable: true, value: undefined });"

#: The table node *id* draws, as text: its headers and each row's cells, or null.
_TABLE_JS = """(id) => {
    const node = document.querySelector('.react-flow__node[data-id="' + id + '"]');
    const table = node && node.querySelector('table');
    if (!table) return null;
    const text = (cell) => cell.textContent.trim();
    return {
        headers: Array.from(table.querySelectorAll('thead th')).map(text),
        rows: Array.from(table.querySelectorAll('tbody tr')).map(
            (row) => Array.from(row.querySelectorAll('td')).map(text)),
    };
}"""

#: The canvas the Vega-Lite node *id* draws on, as a PNG, or null.
#: Counts the WebGPU textures a page holds: created, less those destroyed.
#: Garbage collection frees a texture without its destroy(), so a texture a
#: page drops without destroying it stays counted, as it stays in the GPU's
#: memory until a collection the page cannot count on.
_LIVE_GPU_TEXTURES_JS = """(() => {
    if (typeof GPUDevice === 'undefined') return;
    let live = 0;
    const create = GPUDevice.prototype.createTexture;
    GPUDevice.prototype.createTexture = function (descriptor) {
        const texture = create.call(this, descriptor);
        live += 1;
        const destroy = texture.destroy;
        let gone = false;
        texture.destroy = function () {
            if (!gone) { gone = true; live -= 1; }
            return destroy.call(this);
        };
        return texture;
    };
    Object.defineProperty(window, '__curioLiveGpuTextures', { get: () => live });
})();"""

_PLOT_PIXELS_JS = """(id) => {
    const canvas = document.querySelector('#vega' + id + ' canvas');
    return canvas ? canvas.toDataURL('image/png') : null;
}"""


def _spec() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def _ids() -> dict[str, str]:
    """The example's node ids, by the keys in :data:`LABELS`: each key's id is
    in the example, its header shows the key's title, and the dashboard pins
    :data:`PINNED`."""
    nodes = {node["id"]: node for node in _spec()["dataflow"]["nodes"]}
    ids = {key: str(uuid.uuid5(NAMESPACE, key)) for key in LABELS}
    missing = sorted(key for key, node_id in ids.items() if node_id not in nodes)
    assert not missing, f"the example has no node of the keys {missing!r}"
    titles = {key: nodes[node_id].get("title") for key, node_id in ids.items()}
    retitled = {key: title for key, title in titles.items() if title != LABELS[key]}
    assert not retitled, f"the example titles these nodes otherwise: {retitled!r}"
    pinned = sorted(key for key, node_id in ids.items() if nodes[node_id].get("dashboardPinned"))
    assert pinned == sorted(PINNED), f"the example pins {pinned!r}, not {sorted(PINNED)!r}"
    return ids


def _colors() -> list[str]:
    """The scenarios' colors, in their order: each one draws its line on the plot."""
    colors = [scenario["color"] for scenario in _spec()["dataflow"].get("scenarios") or []]
    assert len(colors) == 2, f"the example has {len(colors)} scenarios, not two: {colors!r}"
    return colors


def _read_by_tiles(ids: dict[str, str]) -> set[str]:
    """What the pinned tiles read: every node a pinned node takes a data edge from."""
    pinned = {ids[key] for key in PINNED}
    return {
        edge["source"] for edge in _spec()["dataflow"]["edges"]
        if edge["target"] in pinned and edge.get("type") != "Interaction"
    }


def _months_read(page, table_id: str, *, timeout_ms: int = RUN_TIMEOUT_MS) -> list[list[str]]:
    """Wait until the table shows its twelve months, and return its rows,
    which are the CPU reference's: the same headers, the months in order, and
    each month's average and standard deviation the whole minutes of a figure
    within ``MONTH_TOLERANCE_MIN`` of the CPU's. Where the CPU finds no shade
    added all month, the table reads "0 ± 0 min"."""
    deadline = time.time() + timeout_ms / 1000
    while True:
        shown = page.evaluate(_TABLE_JS, table_id)
        rows = (shown or {}).get("rows") or []
        if len(rows) == len(MONTHS):
            break
        if time.time() >= deadline:
            raise AssertionError(f"the table never showed the twelve months: it shows {shown!r}")
        page.wait_for_timeout(500)
    assert shown["headers"] == ["Month", MONTH_HEADER], f"the table's headers are {shown['headers']!r}"
    assert [row[0] for row in rows] == [month["Month"] for month in MONTHS], f"the table's rows are {rows!r}"
    # The table rounds to whole minutes, half a minute at most, on top of what
    # the GPU's figure may differ by.
    allowed = MONTH_TOLERANCE_MIN + 0.5
    off = []
    for (name, cell), month in zip(rows, MONTHS):
        average, sd = average_and_sd(cell)
        if abs(average - month["average"]) > allowed or abs(sd - month["sd"]) > allowed:
            off.append(f"{name}: {cell}, the CPU's {month['average']} ± {month['sd']} min")
        if month["average"] == 0 and cell != "0 ± 0 min":
            off.append(f"{name}: {cell}, where the CPU finds no shade added")
    assert not off, f"the table's months sit more than {allowed} min from the CPU's: {off!r}"
    return rows


def _stored_table(path: str) -> dict[str, list]:
    """A run's saved table, by column, as the sandbox holds it."""
    stored = load_artifact_as_dict(path)
    assert stored["dataType"] == "dataframe", f"{path} holds a {stored['dataType']}, not a table"
    return stored["data"]


def _day_reads(outputs: dict[str, str], ids: dict[str, str], row: dict) -> dict[str, list]:
    """What a run made of *row*'s day from what the page's GPU steps sent: each
    scenario's table of the share of the block in shadow at each step, which
    the day's plot draws. It names the day and its window as the CPU does, and
    adds up to each scenario's minutes in shadow within ``TOLERANCE_MIN`` of
    the CPU's, Added being what With adds to Without. Returns each table's
    shares, by key."""
    got, shares = {}, {}
    for header, key in zip(DURATIONS, ("base-block-steps", "block-steps")):
        table = _stored_table(outputs[ids[key]])
        window = {(day, start, end) for day, start, end in zip(table["day"], table["window_from"], table["window_to"])}
        assert window == {(row["Day"], row["From"], row["To"])}, (
            f"{LABELS[key]} ({key}) names {window!r}, not {row['Day']} counted from {row['From']} to {row['To']}"
        )
        got[header] = sum(share / 100 * minutes for share, minutes in zip(table["share"], table["minutes"]))
        shares[key] = table["share"]
    got["Added"] = got[DURATIONS[1]] - got[DURATIONS[0]]
    off = {
        header: f"{got[header]:.2f} min, the CPU's {row[header]}"
        for header in DURATIONS if abs(got[header] - row[header]) > TOLERANCE_MIN
    }
    assert not off, f"{row['Day']} on the GPU sits more than {TOLERANCE_MIN} min from the CPU's: {off!r}"
    return shares


def _page_story(page, console: list[str], reported: list[str]) -> str:
    """Where each node of *page* stands, every browser error it reported to
    the monitor and what it logged last, for a failure to report."""
    try:
        standing = page.evaluate(_NODES_STANDING_JS)
    except Exception as exc:  # noqa: BLE001 - the story is told with what can be read
        standing = [f"could not be read: {exc}"]
    return (
        "\nThe page's nodes:\n  " + "\n  ".join(standing or ["none"])
        + "\nWhat the page reported to the monitor as browser errors:\n  " + "\n  ".join(reported or ["nothing"])
        + "\nThe page's last messages:\n  " + "\n  ".join(console[-40:] or ["none"])
    )


def _ran(starts: list) -> dict[str, str]:
    """The output of every step the runs of *starts* finished, by node id, a
    later run's over an earlier one's. Each start is the backend's answer to a
    page starting a viewer's run, as a response listener caught it; the run's
    events are read again from the backend, which replays a run whole, with
    the token the start answered. A start that needed no run has none. Not the
    page's own stream: the page may end one early, and Playwright then never
    says it finished."""
    header = shared_constants.read("dashboardRuns")["runTokenHeader"]
    texts = []
    for start in starts:
        answer = start.json()
        if not answer.get("runId"):
            continue
        url = f"{start.url.split('?', 1)[0]}/{answer['runId']}/stream"
        asked = urllib.request.Request(url, headers={header: answer["token"]})
        with urllib.request.urlopen(asked, timeout=RUN_TIMEOUT_MS / 1000) as stream:
            texts.append(stream.read().decode("utf-8"))
    outputs: dict[str, str] = {}
    for run in _step_outputs(SimpleNamespace(streams=texts)):
        outputs.update(run)
    return outputs


def _year_reads(outputs: dict[str, str], ids: dict[str, str]) -> None:
    """What a run made of the year from what the page's GPU steps sent: each
    scenario's table of its days, which the year's plot draws, a row for each
    of 2027's 365 days. On each of the four days its minutes in shadow are the
    CPU's within ``TOLERANCE_MIN``."""
    for header, key in zip(DURATIONS, ("base-block-days", "block-days")):
        table = _stored_table(outputs[ids[key]])
        assert len(table["date"]) == 365 and table["date"][0] == "2027-01-01", (
            f"{LABELS[key]} ({key}) holds {len(table['date'])} days from {table['date'][:1]!r}"
        )
        by_date = dict(zip(table["date"], table["shadow_min"]))
        off = {
            row["Day"]: f"{by_date[row['Date']]:.2f} min, the CPU's {row[header]}"
            for row in FOUR_DAYS if abs(by_date[row["Date"]] - row[header]) > TOLERANCE_MIN
        }
        assert not off, f"{LABELS[key]} ({key}) sits more than {TOLERANCE_MIN} min from the CPU's: {off!r}"


def _day(page, steps_id: str, day: str):
    """The radio button of *day* on the sun steps node's tile: its Day widget,
    which the dashboard shows as a visitor's control."""
    return node_locator(page, steps_id).get_by_role("radio", name=day, exact=True)


def _pick_day(page, steps_id: str, day: str) -> None:
    radio = _day(page, steps_id, day)
    expect(radio).to_be_enabled(timeout=20000)
    radio.check()


def _map_canvas(map_id: str) -> str:
    return f"#autk-grammar-map-{map_id}"


def _maps_drawn(page, ids: dict[str, str], what: str, *, frame: bool = False) -> None:
    """Each of the three maps holds a whole drawing of its layers: mostly
    opaque and steady (``_wait_for_map_drawn``) and more than a background's
    few colours, as ``assert_autark_map_drawn`` asks. Both read the canvas in
    the frame that draws it: a map left idle, as the canvas leaves its maps
    after a Run All, reads back blank otherwise (#1125). With *frame*, on a
    canvas, each map is framed on its own before it is read."""
    for key in MAPS:
        if frame:
            frame_nodes(page, [ids[key]])
        _wait_for_map_drawn(page, ids[key], what)
        colours = len(set(_map_pixels(page, ids[key]).getdata()))
        assert colours > 8, f"the map {key} after {what} holds {colours} colours: a background, not a map"


def _keep_drawing_maps(page, ids: dict[str, str]) -> dict:
    """Each map as it draws now, its canvas kept so that a redraw is told by a
    new one (``_wait_for_redraw``)."""
    drawn = {}
    for key in MAPS:
        drawn[key] = _map_pixels(page, ids[key])
        keep_drawing(page, _map_canvas(ids[key]))
    return drawn


def _maps_redrew(page, ids: dict[str, str], what: str) -> dict:
    """Each map once it drew again after *what*, as it draws now."""
    drawn = {}
    for key in MAPS:
        _wait_for_redraw(page, ids[key], what)
        drawn[key] = _map_pixels(page, ids[key])
    return drawn


def _plot_drew(page, plot_id: str, colors: list[str]) -> None:
    """The plot drew, its canvas holding each of *colors*, a scenario's line."""
    assert_vega_canvas_rendered(page, plot_id, timeout=60000)
    counts = None
    deadline = time.time() + 15
    while time.time() < deadline:
        counts = page.evaluate(_COLOR_PIXELS_JS, [plot_id, colors])
        if counts and all(count >= 30 for count in counts):
            return
        page.wait_for_timeout(250)
    raise AssertionError(f"the plot does not draw each scenario's color {colors}: pixels {counts}")


def _plot_redrew(page, plot_id: str, before: str | None, colors: list[str] | None = None) -> None:
    """The plot drew again, not what it drew *before*; with *colors*, a line
    in each scenario's color."""
    page.wait_for_function(
        "([id, before]) => {"
        " const canvas = document.querySelector('#vega' + id + ' canvas');"
        " return !!canvas && canvas.toDataURL('image/png') !== before; }",
        arg=[plot_id, before],
        timeout=90000,
        polling=500,
    )
    if colors:
        _plot_drew(page, plot_id, colors)
    else:
        assert_vega_canvas_rendered(page, plot_id, timeout=60000)


def _shows_winter(
    page, ids: dict[str, str], colors: list[str], what: str, *,
    on_canvas: bool = False, timeout_ms: int = RUN_TIMEOUT_MS,
) -> None:
    """The page shows the winter solstice, the day the example is saved with,
    and the year: the table reads the CPU's months, each map holds a drawing,
    and each plot draws both scenarios' lines, which part where the tower
    shades the block. On a canvas each map, then each plot, is framed before
    it is read."""
    _months_read(page, ids["summary-view"], timeout_ms=timeout_ms)
    _maps_drawn(page, ids, what, frame=on_canvas)
    for key in ("plot", "year-plot"):
        if on_canvas:
            frame_nodes(page, [ids[key]])
        _plot_drew(page, ids[key], colors)


def _page_steps(asked: list[str]) -> list[str]:
    """The node of each step the page sent what it made of, sorted."""
    return sorted(line.rsplit("/steps/", 1)[1].split("?", 1)[0] for line in _steps_sent(asked))


def _start_answers(visitor: "_Visitor") -> list[tuple[int, str | None]]:
    """How each start of a viewer's run was answered: its status, and the id of
    the run to follow (none when the values need no run)."""
    answers = []
    for line in visitor.answered:
        asked, _, answer = line.partition(" -> ")
        if not (asked.startswith("POST ") and asked.endswith("/dashboard/runs")):
            continue
        status, _, body = answer.partition(" ")
        try:
            run_id = json.loads(body).get("runId")
        except ValueError:
            run_id = None
        answers.append((int(status) if status.isdigit() else 0, run_id))
    return answers


def _beyond_viewer_runs(visitor: "_Visitor") -> list[str]:
    """What the visitor's page asked beyond a viewer's run and DuckDB's extensions."""
    return [line for line in _not_a_viewer_route(visitor.asked) if not _EXTENSIONS_RE.match(line)]


def _ran_since(visitor: "_Visitor", earlier: int) -> list[dict[str, str]]:
    """The step outputs of the runs the visitor's page followed after its first *earlier*."""
    return _step_outputs(visitor)[earlier:]


def _tile_says(page, node_id: str, reason: str, *words: str | re.Pattern, timeout_ms: int) -> None:
    """The tile of *node_id* shows only its notice for *reason*, which reads each of *words*."""
    notice = node_locator(page, node_id).locator(f'[data-curio-node-empty="{reason}"]')
    for said in words:
        expect(notice).to_contain_text(said, timeout=timeout_ms)


#: Before the page's own scripts: every change of each tile's empty state, in
#: order, as the page makes it. A state that lasts a frame is caught too,
#: where a poll would miss it (on dev, 10-25, a visitor read "Run the node
#: feeding this one" for 12 ms).
_EMPTY_STATES_JS = """(() => {
    window.__curioEmptyStates = [];
    const last = {};
    const look = () => {
        for (const node of document.querySelectorAll('.react-flow__node')) {
            const id = node.getAttribute('data-id');
            const empty = node.querySelector('[data-curio-node-empty]');
            const reason = empty ? empty.getAttribute('data-curio-node-empty') : null;
            if (last[id] !== reason) {
                last[id] = reason;
                window.__curioEmptyStates.push([id, reason]);
            }
        }
    };
    new MutationObserver(look).observe(document, {
        subtree: true, childList: true, attributes: true, attributeFilter: ['data-curio-node-empty'],
    });
})();"""


def _tile_said(page, node_id: str) -> list[str | None]:
    """Every empty state the tile of *node_id* showed since the page opened, in
    order (null: none, as when it shows what it made)."""
    return [reason for said_by, reason in page.evaluate("() => window.__curioEmptyStates || []") if said_by == node_id]


def _until_held(backend: str, visitor: "_Visitor") -> None:
    """Until a step of a run on *backend* waits for the hold to end."""
    deadline = time.time() + 60
    while held_server_nodes(backend) < 1:
        if time.time() >= deadline:
            raise AssertionError("the run on open never reached a step on the server" + visitor.story())
        visitor.page.wait_for_timeout(250)


@pytest.mark.xdist_group("crown-heights-sharing")
def test_the_owner_shares_the_crown_heights_dashboard_and_each_visitor_tries_a_day(
    app_frontend: "FrontendPage", current_server, page, browser, monkeypatch,
):
    require_project_page()
    require_user_auth()
    ids = _ids()
    colors = _colors()
    page_steps = sorted(ids[key] for key in PAGE_STEPS)

    # The owner runs the example on the canvas and saves it, which saves the
    # outputs the pinned tiles read.
    session = _enter(page, app_frontend, current_server, prefix="crown_owner", spec=_spec())
    require_webgpu(page)
    project_id = session["project"]["id"]
    run_all_and_wait(page, timeout_ms=300000)
    # The winter solstice, the saved day, as the CPU reference computes it.
    _shows_winter(page, ids, colors, "the owner's Run All", on_canvas=True)
    save_dataflow(page)
    recorded = {output["node_id"] for output in _project(current_server, session["token"], project_id)["outputs"]}
    read_by_tiles = _read_by_tiles(ids)
    assert read_by_tiles <= recorded, (
        f"the save recorded {sorted(recorded)!r}, not every output the pinned tiles read {sorted(read_by_tiles)!r}"
    )

    # The Share menu: the dashboard's link, the dataflow's link, and the
    # dashboard opened for the owner, who may lay it out.
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    page.get_by_test_id("share-menu-btn").click(force=True)
    page.get_by_text("Copy dashboard link", exact=True).click()
    dashboard_link = page.evaluate("() => navigator.clipboard.readText()")
    assert dashboard_link == f"{app_frontend.base_url}/dashboard/{project_id}", dashboard_link
    page.get_by_test_id("share-menu-btn").click(force=True)
    page.get_by_text("Copy dataflow link", exact=True).click()
    dataflow_link = page.evaluate("() => navigator.clipboard.readText()")
    assert dataflow_link == f"{app_frontend.base_url}/dataflow/{project_id}", dataflow_link
    page.get_by_test_id("share-menu-btn").click(force=True)
    with page.context.expect_page() as popup:
        page.get_by_test_id("open-dashboard-link").click()
    owners_tab = popup.value
    owners_tab.wait_for_url(re.compile(rf"/dashboard/{project_id}$"), timeout=30000)
    owners_tab.get_by_test_id("edit-layout-btn").wait_for(state="visible", timeout=45000)
    _shows_winter(owners_tab, ids, colors, "the owner opened the dashboard")
    owners_tab.close()
    # Off the canvas first: it can still save on its way out.
    page.goto("about:blank")
    before = _project(current_server, session["token"], project_id)
    catalog_before = _catalog_ids(current_server, session["token"], project_id)
    hosted = _serve_hosted(app_frontend, current_server, monkeypatch)

    first = _Visitor(browser, current_server)
    try:
        # The copied link, on the page server as the hosted stacks serve it.
        first.opens(hosted, project_id)
        first.waits_for(
            "the owner's results",
            lambda: _shows_winter(first.page, ids, colors, "the link opened", timeout_ms=90000),
        )
        assert _runs_started(first.asked) == [] and _files_read(first.asked) == set(), (
            "the dashboard ran or read outputs to show the owner's results, which the page carries" + first.story()
        )
        expect(_day(first.page, ids["steps"], WINTER["Day"])).to_be_checked(timeout=30000)
        # The tiles alone: no notice over them about what a visitor may do.
        expect(first.page.get_by_test_id("shared-view-banner")).to_have_count(0)
        assert not re.search(r"shared dashboard|not saved", first.page.locator("body").inner_text(), re.I), (
            "the dashboard tells a visitor what its changes do" + first.story()
        )
        assert first.page.get_by_test_id("edit-layout-btn").count() == 0, "a visitor may lay out the owner's dashboard"
        tower = node_locator(first.page, ids["add-building"])
        expect(tower.locator('li[data-edit-op="add"]')).to_have_count(2, timeout=30000)
        expect(tower.get_by_role("button", name=re.compile(r"^Delete edit"))).to_have_count(0)
        expect(tower.get_by_test_id("interaction-commit")).to_have_count(0)
        park_pointer(first.page)
        save_workflow_test_screenshot(first.page, STEM, test_name="shared", sweep_toasts=True)

        winter_maps = _keep_drawing_maps(first.page, ids)
        winter_plot = first.page.evaluate(_PLOT_PIXELS_JS, ids["plot"])
        months = _months_read(first.page, ids["summary-view"])
        _pick_day(first.page, ids["steps"], SUMMER["Day"])
        summer_maps: dict = {}
        first.waits_for(
            "the maps for the summer solstice",
            lambda: summer_maps.update(_maps_redrew(first.page, ids, "the day changed")),
        )
        for key in MAPS:
            moved = _changed(winter_maps[key], summer_maps[key])
            assert moved > 0.005, (
                f"{LABELS[key]} for the summer solstice differs from the winter solstice's in {moved:.2%} of its "
                "pixels" + first.story()
            )
        # In summer the tower's shadow never reaches the block, so the two
        # lines are one and the one drawn last hides the other: the plot's
        # colors are checked on the winter solstice.
        first.waits_for(
            "the plot for the summer solstice", lambda: _plot_redrew(first.page, ids["plot"], winter_plot),
        )
        park_pointer(first.page)
        save_workflow_test_screenshot(first.page, STEM, test_name="summer", sweep_toasts=True)
        save_workflow_test_screenshot(
            first.page,
            STEM,
            test_name="summer-change-map",
            pixel_threshold=CLOSEUP_PIXEL_THRESHOLD,
            max_diff_ratio=CLOSEUP_MAX_DIFF_RATIO,
            clip_selector=f'.react-flow__node[data-id="{ids["added-map"]}"]',
            sweep_toasts=True,
            closeup=True,
        )

        first.waits_for_runs(2, timeout_ms=RUN_TIMEOUT_MS)
        assert len(_runs_started(first.asked)) == 2, (
            "a day started other than a run and the start going on from the GPU steps it left to the page"
            + first.story()
        )
        assert _page_steps(first.asked) == page_steps, (
            "the page did not send what it made of each of the four GPU steps, once" + first.story()
        )
        before_gpu, after_gpu = _step_outputs(first)
        assert ids["steps"] in before_gpu, (
            f"the run before the GPU steps did not make the day's sun steps: it ran {before_gpu!r}" + first.story()
        )
        # What the day does not reach runs only if the owner's save did not
        # keep it (here, each scenario's buildings for the GPU), or if the
        # page's steps read it: the page cannot read the owner's saved
        # open-ground grid, so the run hands it on.
        saved = [key for key in DAY_BLIND if ids[key] in recorded]
        reran = [
            key for key in saved
            if key not in PAGE_INPUTS and (ids[key] in before_gpu or ids[key] in after_gpu)
        ]
        assert not reran, f"a day ran {reran!r} again, which it does not reach" + first.story()
        unsent = [key for key in PAGE_INPUTS if ids[key] not in before_gpu]
        assert not unsent, (
            f"the run before the GPU steps did not hand the page {unsent!r}, which they read: "
            f"it ran {before_gpu!r}" + first.story()
        )
        unsaved = [key for key in DAY_BLIND if key not in saved and ids[key] not in before_gpu]
        assert not unsaved, (
            f"the run before the GPU steps did not make {unsaved!r}, which the owner's save did not keep: "
            f"it ran {before_gpu!r}" + first.story()
        )
        unmade = [key for key in AFTER_PAGE if ids[key] not in after_gpu]
        assert not unmade, (
            f"the run after the GPU steps did not make {unmade!r}: it ran {after_gpu!r}" + first.story()
        )
        # The day is the CPU's, and the year no day reaches stays as it was:
        # its GPU steps, its days and months are not made again, its plot
        # still draws both lines and the table shows what it showed.
        summer_shares = _day_reads(after_gpu, ids, SUMMER)
        yearly = [key for key in (*YEAR_STEPS, *AFTER_YEAR) if ids[key] in before_gpu or ids[key] in after_gpu]
        assert not yearly, f"a day ran {yearly!r} again, which read the year" + first.story()
        first.waits_for("the year's plot", lambda: _plot_drew(first.page, ids["year-plot"], colors))
        assert _months_read(first.page, ids["summary-view"]) == months, "the table changed with the day" + first.story()
        first_sent = _sent_results(first)
        first_read = _files_read(first.asked)
        assert _beyond_viewer_runs(first) == [], (
            "the dashboard asked the server for more than a viewer's run" + first.story()
        )
    finally:
        first.close()

    second = _Visitor(browser, current_server)
    try:
        second.opens(hosted, project_id)
        second.waits_for(
            "the owner's results",
            lambda: _shows_winter(second.page, ids, colors, "the link opened", timeout_ms=90000),
        )
        opened_maps = _keep_drawing_maps(second.page, ids)
        opened_plot = second.page.evaluate(_PLOT_PIXELS_JS, ids["plot"])
        _pick_day(second.page, ids["steps"], SUMMER["Day"])
        second.waits_for("the maps for the summer solstice", lambda: _maps_redrew(second.page, ids, "the day changed"))
        second.waits_for(
            "the plot for the summer solstice", lambda: _plot_redrew(second.page, ids["plot"], opened_plot),
        )
        summer_plot = second.page.evaluate(_PLOT_PIXELS_JS, ids["plot"])
        second.waits_for_runs(2, timeout_ms=RUN_TIMEOUT_MS)
        assert _page_steps(second.asked) == page_steps, (
            "the second page did not run the four GPU steps itself" + second.story()
        )
        before_gpu_2, after_gpu_2 = _step_outputs(second)
        assert _day_reads(after_gpu_2, ids, SUMMER) == summer_shares, (
            "two visitors' pages made the summer solstice otherwise" + second.story()
        )
        # The steps before the GPU steps run once for everyone: the second
        # visitor's run hands on what the first one's kept, and runs none of
        # what the owner saved.
        for key in ("steps", *DAY_BLIND):
            assert before_gpu_2.get(ids[key]) == before_gpu.get(ids[key]), (
                f"{LABELS[key]} ({key}) gave the second visitor's summer solstice {before_gpu_2.get(ids[key])!r}, "
                f"not what the first visitor's run kept, {before_gpu.get(ids[key])!r}" + second.story()
            )
        for key in AFTER_PAGE:
            assert after_gpu_2.get(ids[key]) not in (None, after_gpu[ids[key]]), (
                f"{LABELS[key]} ({key}) handed the second visitor what the first visitor's page made" + second.story()
            )
        second_read = _files_read(second.asked)
        assert not second_read & first_sent, (
            f"the second page read {sorted(second_read & first_sent)!r}, what the first page sent" + second.story()
        )
        assert second_read & first_read, (
            "the second page read none of the outputs kept from the first visitor's run" + second.story()
        )

        # The saved day brings the owner's results back, with no run.
        for key in MAPS:
            keep_drawing(second.page, _map_canvas(ids[key]))
        _pick_day(second.page, ids["steps"], WINTER["Day"])
        back_maps: dict = {}
        second.waits_for(
            "the saved maps again", lambda: back_maps.update(_maps_redrew(second.page, ids, "the day went back")),
        )
        for key in MAPS:
            back = _changed(opened_maps[key], back_maps[key])
            assert back <= 0.01, (
                f"{LABELS[key]} for the saved day differs from the one the page opened with in {back:.2%}"
                + second.story()
            )
        second.waits_for(
            "the saved plot again", lambda: _plot_redrew(second.page, ids["plot"], summer_plot, colors),
        )
        assert _months_read(second.page, ids["summary-view"]) == months, "the table changed with the day" + second.story()
        # The page asks, and the server answers that the saved values need no
        # run: the page follows no run and runs no GPU step.
        second.waits_for_runs(3, timeout_ms=RUN_TIMEOUT_MS)
        assert _start_answers(second)[2:] == [(200, None)], (
            f"the saved day was answered {_start_answers(second)[2:]!r}, not with no run" + second.story()
        )
        assert len(second.streams) == 2, "the saved day ran again" + second.story()
        assert _page_steps(second.asked) == page_steps, "the saved day ran the GPU steps again" + second.story()
        assert _beyond_viewer_runs(second) == [], (
            "the dashboard asked the server for more than a viewer's run" + second.story()
        )
    finally:
        second.close()

    # Another account opens the dataflow's link: the owner's results, read-only.
    other_ctx = browser.new_context()
    try:
        other = other_ctx.new_page()
        stub_db_login(
            other,
            frontend_url=app_frontend.base_url,
            backend_url=current_server,
            username=f"crown_other_{uuid.uuid4().hex[:8]}",
            name="Someone Else",
        )
        other.goto(dataflow_link)
        other.get_by_test_id("shared-view-banner").wait_for(timeout=45000)
        _shows_winter(
            other, ids, colors, "another account opened the dataflow's link", on_canvas=True, timeout_ms=90000,
        )
    finally:
        other_ctx.close()

    after = _project(current_server, session["token"], project_id)
    assert after["spec"] == before["spec"], "a visitor's run changed the owner's dataflow"
    assert after["outputs"] == before["outputs"], "a visitor's run changed the dataflow's recorded outputs"
    assert _catalog_ids(current_server, session["token"], project_id) == catalog_before, (
        "a visitor's run added to the Data Catalog"
    )


@pytest.mark.xdist_group("crown-heights-link")
def test_the_crown_heights_dashboard_link_dev_shares_works_on_this_deployment_too(
    app_frontend: "FrontendPage", current_server, browser, monkeypatch,
):
    require_project_page()
    require_user_auth()
    ids = _ids()
    colors = _colors()
    page_steps = sorted(ids[key] for key in PAGE_STEPS)
    # No one ran the shipped copy, so its run on open makes the year too.
    open_steps = sorted(ids[key] for key in (*PAGE_STEPS, *YEAR_STEPS))

    # The shared guest's copy, seeded as dev seeds it: by the first listing
    # since the start (here, since the last test emptied the database).
    guest = api_json(f"{current_server}/api/auth/signin/guest", "", method="POST", payload={})["token"]
    api_json(f"{current_server}/api/projects", guest)
    copy = api_json(f"{current_server}/api/projects/{LINK_ID}", guest)
    assert copy["spec"]["dataflow"]["name"] == NAME, copy["spec"]["dataflow"].get("name")
    assert not copy["outputs"], "the shipped copy has saved outputs, which no one ran"
    hosted = _serve_hosted(app_frontend, current_server, monkeypatch)

    visitor = _Visitor(browser, current_server)
    try:
        visitor.ctx.add_init_script(_EMPTY_STATES_JS)
        # No one ran it, so its tiles fill through a run: the server, the
        # page's four GPU steps, then the server again. Held at its first
        # step, the run leaves the maps, the plot and the table saying they
        # are computing, not that a node is left to run.
        hold_server_runs(current_server, True)
        try:
            visitor.opens(hosted, LINK_ID)
            require_webgpu(visitor.page)
            _until_held(current_server, visitor)
            for key in TILES:
                visitor.waits_for(
                    f"{LABELS[key]} computing",
                    lambda key=key: _tile_says(
                        visitor.page, ids[key], "upstream-running", *COMPUTING, timeout_ms=60000,
                    ),
                )
        finally:
            # A hold left standing would stop every later run on this backend.
            hold_server_runs(current_server, False)
        visitor.waits_for("what the run made", lambda: _shows_winter(visitor.page, ids, colors, "the link opened"))
        # From the page's opening to what the run made, the maps, the plot and
        # the table said only that they were computing: never a node to run, a
        # play to press, nor what an input just arrived is not.
        for key in TILES:
            said = _tile_said(visitor.page, ids[key])
            assert set(said) <= {"upstream-running", None}, (
                f"{LABELS[key]} said {said!r} before what the run made" + visitor.story()
            )
        visitor.waits_for_runs(2, timeout_ms=RUN_TIMEOUT_MS)
        assert len(_runs_started(visitor.asked)) == 2, (
            "opening the link started other than one run and its sequel" + visitor.story()
        )
        assert _page_steps(visitor.asked) == open_steps, (
            "the page did not run each of the six GPU steps, once" + visitor.story()
        )
        opened = _step_outputs(visitor)
        unmade = [key for key in ("steps", *DAY_BLIND) if ids[key] not in opened[0]]
        assert not unmade, f"the run on open did not make {unmade!r} before the GPU steps: it ran {opened[0]!r}"
        unmade = [key for key in (*AFTER_PAGE, *AFTER_YEAR) if ids[key] not in opened[1]]
        assert not unmade, f"the run on open did not make {unmade!r} after the GPU steps: it ran {opened[1]!r}"
        # What the page's GPU steps made of the day and of the year is the CPU's.
        _day_reads(opened[1], ids, WINTER)
        _year_reads(opened[1], ids)

        opened_maps = _keep_drawing_maps(visitor.page, ids)
        opened_plot = visitor.page.evaluate(_PLOT_PIXELS_JS, ids["plot"])
        months = _months_read(visitor.page, ids["summary-view"])
        _pick_day(visitor.page, ids["steps"], SUMMER["Day"])
        summer_maps: dict = {}
        visitor.waits_for(
            "the maps for the summer solstice",
            lambda: summer_maps.update(_maps_redrew(visitor.page, ids, "the day changed")),
        )
        for key in MAPS:
            moved = _changed(opened_maps[key], summer_maps[key])
            assert moved > 0.005, (
                f"{LABELS[key]} for the summer solstice differs from the winter solstice's in {moved:.2%} of its "
                "pixels" + visitor.story()
            )
        visitor.waits_for(
            "the plot for the summer solstice", lambda: _plot_redrew(visitor.page, ids["plot"], opened_plot),
        )
        visitor.waits_for_runs(4, timeout_ms=RUN_TIMEOUT_MS)
        assert len(_runs_started(visitor.asked)) == 4, (
            "a day started other than one run and its sequel" + visitor.story()
        )
        # This copy saves nothing, so a day's run makes every tile's steps
        # again, the year's among them.
        assert _page_steps(visitor.asked) == sorted(open_steps * 2), (
            "the page did not run each of the six GPU steps once for the day" + visitor.story()
        )
        # Only the sun steps read the day: everything else before the GPU
        # steps is what the run on open kept, handed on again or not asked for.
        changed, after_day = _ran_since(visitor, 2)
        assert changed.get(ids["steps"]) not in (None, opened[0][ids["steps"]]), (
            "the day's sun steps were not made again for the summer solstice" + visitor.story()
        )
        for key in DAY_BLIND:
            assert changed.get(ids[key]) in (None, opened[0][ids[key]]), (
                f"{LABELS[key]} ({key}) ran again for the summer solstice, which it does not read" + visitor.story()
            )
        # The day is the CPU's, and the year, made again, reads as before.
        _day_reads(after_day, ids, SUMMER)
        _year_reads(after_day, ids)
        visitor.waits_for("the year's plot", lambda: _plot_drew(visitor.page, ids["year-plot"], colors))
        assert _months_read(visitor.page, ids["summary-view"]) == months, "the table changed with the day" + visitor.story()
        assert _beyond_viewer_runs(visitor) == [], (
            "the dashboard asked the server for more than a viewer's run" + visitor.story()
        )
        # Through the day's run too, the tiles kept what they showed.
        for key in TILES:
            said = _tile_said(visitor.page, ids[key])
            assert set(said) <= {"upstream-running", None}, f"{LABELS[key]} said {said!r}" + visitor.story()
    finally:
        visitor.close()

    # A browser with no WebGPU: the run on open stops at the GPU steps, and
    # the maps, the plots and the table say which step could not run, with
    # nothing to press. Which of the six the page names is the first it
    # tried, so any of their titles will do.
    stopped = re.compile("|".join(
        sorted({re.escape(f'"{LABELS[key]}" could not run in this browser.') for key in (*PAGE_STEPS, *YEAR_STEPS)})
    ))
    blind = _Visitor(browser, current_server)
    try:
        blind.ctx.add_init_script(_NO_WEBGPU_JS)
        blind.ctx.add_init_script(_EMPTY_STATES_JS)
        blind.opens(hosted, LINK_ID)
        for key in TILES:
            blind.waits_for(
                f"{LABELS[key]} saying why it has nothing",
                lambda key=key: _tile_says(
                    blind.page, ids[key], "upstream-stopped", stopped, timeout_ms=RUN_TIMEOUT_MS,
                ),
            )
        blind.waits_for_runs(1, timeout_ms=RUN_TIMEOUT_MS)
        # Computing, then why: no map or plot more tries to draw than the page
        # ran its GPU steps, and no tile said a node was left to run.
        blind.page.wait_for_timeout(2000)
        for key in TILES:
            said = _tile_said(blind.page, ids[key])
            assert set(said) <= {"upstream-running", "upstream-stopped", None} and said[-1] == "upstream-stopped", (
                f"{LABELS[key]} said {said!r}" + blind.story()
            )
        assert len(_runs_started(blind.asked)) == 1, (
            "the run started again past a step the page could not run" + blind.story()
        )
        assert _steps_sent(blind.asked) == [], "the page sent a GPU step it could not run" + blind.story()
        assert _beyond_viewer_runs(blind) == [], (
            "the dashboard asked the server for more than a viewer's run" + blind.story()
        )
    finally:
        blind.close()

    after = api_json(f"{current_server}/api/projects/{LINK_ID}", guest)
    assert after["spec"] == copy["spec"], "a visitor's run changed the shipped copy"
    assert not after["outputs"], "a visitor's run saved outputs to the shipped copy"


#: Headers that belong to one connection, which a proxy does not pass on.
_HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer",
    "trailers", "transfer-encoding", "upgrade",
})


class _CompressingProxy:
    """The page server behind a proxy that compresses WebAssembly on the fly,
    as dev's does (Caddy, zstd): the module arrives with no Content-Length,
    so Chromium hands requests made at once to one cache write, and a cache
    that cannot hold DuckDB's 36 MB module fails the joined ones
    (net::ERR_CACHE_WRITE_FAILURE). Everything else passes as the page server
    answers it. GET only: the page asks the backend at its own address
    (``window.__CURIO_BACKEND_URL__``, conftest.py)."""

    def __init__(self, upstream: str):
        upstream = upstream.rstrip("/")

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):  # noqa: N802 - http.server's name
                asked = urllib.request.Request(upstream + self.path, headers={"Accept": self.headers.get("Accept", "*/*")})
                try:
                    with urllib.request.urlopen(asked, timeout=180) as answer:
                        status, headers, body = answer.status, answer.headers.items(), answer.read()
                except urllib.error.HTTPError as error:
                    status, headers, body = error.code, error.headers.items(), error.read()
                passed = [(key, value) for key, value in headers
                          if key.lower() not in _HOP_BY_HOP and key.lower() != "content-length"]
                self.send_response(status)
                for key, value in passed:
                    self.send_header(key, value)
                if status == 200 and self.path.split("?", 1)[0].endswith(".wasm"):
                    packed = gzip.compress(body, compresslevel=1)
                    self.send_header("Content-Encoding", "gzip")
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    for start in range(0, len(packed), 1 << 16):
                        chunk = packed[start:start + (1 << 16)]
                        self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
                    self.wfile.write(b"0\r\n\r\n")
                    return
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> str:
        self._thread.start()
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def __exit__(self, *exc) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.mark.xdist_group("crown-heights-link")
def test_a_visitor_in_a_private_window_goes_through_the_four_days(
    app_frontend: "FrontendPage", current_server, browser, monkeypatch, request,
):
    """The shipped copy's dashboard as dev serves it, in a browser context
    with no routes, so its HTTP cache works, in memory, as a private window's
    (the other visits here route the page's requests, which turns the cache
    off). It opens on the winter solstice with its three maps drawn, which
    takes one download of DuckDB's module for them all, and what its run made
    of the day and of the year is the CPU's. Then each day in the order the
    Day radio lists them, ending on the winter solstice again: what the day's
    runs made of it is the CPU's, the three maps and the day's plot draw it,
    the year's plot draws on and the table keeps the CPU's months, and the
    page logs no error. Back on the winter solstice, the page holds no more
    GPU textures than it opened with: each map drawn again destroys the one
    before with all its textures (autark#120, the shared SSAO textures). A
    response listener, not a route, reads each run's stream, so the cache
    stays on."""
    require_project_page()
    require_user_auth()
    ids = _ids()
    colors = _colors()
    # The shared guest's copy, seeded as dev seeds it (see the test above).
    guest = api_json(f"{current_server}/api/auth/signin/guest", "", method="POST", payload={})["token"]
    api_json(f"{current_server}/api/projects", guest)
    hosted = _serve_hosted(app_frontend, current_server, monkeypatch)

    with _CompressingProxy(hosted) as proxied:
        ctx = browser.new_context()
        ctx.add_init_script(_LIVE_GPU_TEXTURES_JS)
        page = ctx.new_page()
        diagnostics.watch_browser_log(page)
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        console: list[str] = []
        page.on("console", lambda message: console.append(f"[{message.type}] {message.text}"[:300]))
        reported: list[str] = []
        page.on("request", lambda request: (
            reported.append(_client_error_report(request.post_data))
            if request.method == "POST" and urlsplit(request.url).path.endswith(CLIENT_ERROR_PATH)
            else None
        ))
        starts: list = []
        page.on("response", lambda response: (
            starts.append(response)
            if response.request.method == "POST" and urlsplit(response.url).path.endswith("/dashboard/runs")
            else None
        ))
        try:
            page.goto(f"{proxied}/dashboard/{LINK_ID}", wait_until="domcontentloaded")
            page.get_by_test_id("open-dataflow-link").wait_for(state="visible", timeout=45000)
            require_webgpu(page)
            _shows_winter(page, ids, colors, "the link opened in a private window")
            on_open = _ran(starts)
            _day_reads(on_open, ids, WINTER)
            _year_reads(on_open, ids)
            read = len(starts)
            opened = _keep_drawing_maps(page, ids)
            textures_on_open = page.evaluate("() => window.__curioLiveGpuTextures")
            plot = page.evaluate(_PLOT_PIXELS_JS, ids["plot"])
            months = _months_read(page, ids["summary-view"])
            for row in FOUR_DAYS:
                day = row["Day"]
                _pick_day(page, ids["steps"], day)
                drawn = _maps_redrew(page, ids, f"the {day.lower()} picked")
                for key in MAPS:
                    apart = _changed(opened[key], drawn[key])
                    if row is WINTER:
                        assert apart <= 0.01, (
                            f"{LABELS[key]} back on the winter solstice differs from the one the page opened "
                            f"with in {apart:.2%} of its pixels"
                        )
                    else:
                        assert apart > 0.005, (
                            f"{LABELS[key]} for the {day.lower()} differs from the winter solstice's in only "
                            f"{apart:.2%} of its pixels"
                        )
                _plot_redrew(page, ids["plot"], plot, colors)
                # What the day's runs made of it, or, for the day the page
                # opened on, what the run on open made if the day needed no
                # run. This copy saves nothing, so a day's run makes the
                # year's tiles again too: they must read as before.
                made = _ran(starts[read:])
                read = len(starts)
                if not made:
                    assert row is WINTER, f"the {day.lower()} drew with no run"
                    made = on_open
                _day_reads(made, ids, row)
                _year_reads(made, ids)
                _plot_drew(page, ids["year-plot"], colors)
                assert _months_read(page, ids["summary-view"]) == months, f"the table changed for the {day.lower()}"
                _keep_drawing_maps(page, ids)
                plot = page.evaluate(_PLOT_PIXELS_JS, ids["plot"])
            assert not errors, f"the page logged errors while the days changed: {errors!r}"
            textures_back = page.evaluate("() => window.__curioLiveGpuTextures")
            assert textures_back <= textures_on_open, (
                f"back on the winter solstice the page holds {textures_back} GPU textures, "
                f"{textures_on_open} when it opened: the maps drawn again left textures behind"
            )
        except Exception as failure:
            # The harness records its own page, about:blank here, so this
            # window's screenshot, nodes and log go with the failure, and the
            # message says where each node stood.
            written = diagnostics.capture(
                page, os.path.join(diagnostics.failure_dir(request.node.nodeid), "private-window"),
            )
            answered = any(path.endswith("screenshot.png") for path in written)
            story = _page_story(page, console, reported) if answered else "\nThe page did not answer a screenshot."
            if isinstance(failure, AssertionError):
                raise AssertionError(f"{failure}{story}") from failure
            print(story)
            raise
        finally:
            ctx.close()
