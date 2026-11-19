"""A ``sql`` source drawn on a map and plotted, in the colors, titles and ticks its plots set.

An Autark node's data section loads four zones of the Chicago Loop, in
EPSG:3395 metres, each with its riders, saves them as a new table with a
``sql`` source (``busy``, drawn as polygons, its rows ordered by their
riders) and drops the table it read them from. It hands ``busy`` alone on to
three nodes:

- a map, which draws it;
- a bar chart colored by its riders in ``interpolateViridis`` over
  ``colorMapRange`` [0, 100], its axes titled by ``axisLabels`` and its y
  ticks formatted by ``tickFormats``: the zone with no riders is drawn in the
  scheme's first color and the zone with 100 in its last, the titles read
  "Zone" and "Riders" and show (autk-plot leaves an axis title's fill to the
  page, and an axis of d3 fills its group with none), and every number of the
  y axis has one decimal;
- a bar chart that selects its last row with ``selection``, in the page's
  ``markColor`` and ``highlightColor``: one bar in the highlight color, the
  others in the mark color. Nothing comes into it, so the node keeps the
  selection its document writes.

Both charts write the same ``markColor`` and ``highlightColor``: autk-plot
keeps one of each for the page, and each node's run sets them.

The map and the charts need WebGPU, so this test runs on CI's GPU job.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_autark_sql_and_plot_keys_e2e.py -v
"""
from __future__ import annotations

import json
import re
import time
from typing import TYPE_CHECKING

from .utils import (
    assert_autark_map_drawn,
    assert_autark_plot_drawn,
    play_node,
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_login_and_enter_workflow,
    wait_for_node_done,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

AUTARK_TYPE = "curio.builtin/autk-grammar"

#: The zones' south-west corner, in EPSG:3395 metres; each zone is a square
#: 400 m a side, 500 m east of the one before.
LOOP = (-9755000.0, 5106000.0)
ZONES = [("A", 0), ("B", 25), ("C", 50), ("D", 100)]

#: autk-plot's scheme of numbers for this chart and its ends, the colors of
#: the lowest and the highest riders over [0, 100]: d3's interpolateViridis
#: at 0 and at 1.
VIRIDIS_LOW = (68, 1, 84)
VIRIDIS_HIGH = (253, 231, 37)
#: The page's mark and highlight colors, which both charts write.
MARK_COLOR = "#2ca02c"
HIGHLIGHT_COLOR = "#d62728"
#: A drawn color matches an expected one when each channel is this close.
CLOSE = 12

DATA = [
    {
        "type": "geojson", "outputTableName": "zones", "coordinateFormat": "EPSG:3395",
        "geojsonObject": {"type": "FeatureCollection", "features": [
            {
                "type": "Feature", "properties": {"zone": zone, "riders": riders},
                "geometry": {"type": "Polygon", "coordinates": [[
                    [LOOP[0] + 500 * i, LOOP[1]], [LOOP[0] + 500 * i + 400, LOOP[1]],
                    [LOOP[0] + 500 * i + 400, LOOP[1] + 400], [LOOP[0] + 500 * i, LOOP[1] + 400],
                    [LOOP[0] + 500 * i, LOOP[1]],
                ]]},
            }
            for i, (zone, riders) in enumerate(ZONES)
        ]},
    },
    {
        "type": "sql", "outputTableName": "busy", "layerType": "polygons",
        "query": "SELECT properties->>'zone' AS zone, CAST(properties->>'riders' AS INTEGER) AS riders, geometry "
                 "FROM zones ORDER BY riders",
    },
    {"type": "drop", "dataRef": "zones"},
]

MAP = {"map": {"layerRefs": [{
    "dataRef": "busy", "getFnv": "riders", "colorMapInterpolator": "interpolateViridis", "colorMapRange": [0, 100],
}]}}
COLORED_CHART = {"plot": {
    "dataRef": "busy", "mark": "bar", "axis": ["zone", "riders"], "color": "riders",
    "colorMapInterpolator": "interpolateViridis", "colorMapRange": [0, 100],
    "axisLabels": ["Zone", "Riders"], "tickFormats": [",d", ".1f"],
    "markColor": MARK_COLOR, "highlightColor": HIGHLIGHT_COLOR,
}}
SELECTED_CHART = {"plot": {
    "dataRef": "busy", "mark": "bar", "axis": ["zone", "riders"],
    "selection": [3], "markColor": MARK_COLOR, "highlightColor": HIGHLIGHT_COLOR,
}}

# What a chart of an Autark node drew: each bar's fill as the page paints it,
# each tick's text, and each axis title's text, fill and opacity, read in the
# chart's own pane (autkViews' viewElementId).
_CHART_JS = """(id) => {
    const pane = document.getElementById('autk-grammar-plot-' + id);
    if (!pane) return null;
    const style = (element) => getComputedStyle(element);
    return {
        bars: [...pane.querySelectorAll('.autkMark')].map((bar) => style(bar).fill),
        ticks: [...pane.querySelectorAll('.tick text')].map((text) => text.textContent.trim()),
        titles: [...pane.querySelectorAll('.axis-label')].map((title) => ({
            text: title.textContent.trim(),
            fill: style(title).fill,
            opacity: style(title).opacity,
            visibility: style(title).visibility,
        })),
    };
}"""


def _rgb(text: str) -> tuple[int, ...] | None:
    """The red, green and blue of a computed color, ``rgb(r, g, b)``."""
    found = re.match(r"rgba?\((\d+),\s*(\d+),\s*(\d+)", text or "")
    return tuple(int(part) for part in found.groups()) if found else None


def _hex(color: str) -> tuple[int, ...]:
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def _near(drawn, expected) -> bool:
    return drawn is not None and all(abs(a - b) <= CLOSE for a, b in zip(drawn, expected))


def _chart(page, node_id: str, holds, what: str, *, timeout: float = 30000) -> dict:
    """What *node_id*'s chart drew once *holds* is true of it; fails naming *what* otherwise."""
    deadline = time.monotonic() + timeout / 1000
    while True:
        drawn = page.evaluate(_CHART_JS, node_id)
        if drawn is not None and holds(drawn):
            return drawn
        assert time.monotonic() < deadline, f"{what}: Autark node {node_id}'s chart holds {drawn}"
        page.wait_for_timeout(500)


def _node(node_id: str, x: int, y: int, document: dict) -> dict:
    return {
        "id": node_id, "type": AUTARK_TYPE, "x": x, "y": y, "content": json.dumps(document, indent=2),
        "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
    }


def _edge(source: str, target: str) -> dict:
    return {
        "id": f"reactflow__edge-{source}out-{target}in",
        "source": source, "target": target, "sourceHandle": "out", "targetHandle": "in",
    }


def test_a_sql_table_is_drawn_and_plotted_in_the_scheme_titles_ticks_and_selection_its_charts_set(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    loader, drawer, colored, selected = "sql-zones", "sql-map", "sql-colored-chart", "sql-selected-chart"
    spec = {"dataflow": {"name": "AutarkSqlAndPlotKeys", "task": "", "nodes": [
        _node(loader, 120, 160, {"data": DATA}),
        _node(drawer, 820, 40, MAP),
        _node(colored, 820, 560, COLORED_CHART),
        _node(selected, 1520, 560, SELECTED_CHART),
    ], "edges": [_edge(loader, drawer), _edge(loader, colored), _edge(loader, selected)]}}
    require_project_page()
    require_user_auth()
    errors: list[str] = []
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Autark SQL and Plot Keys",
        username="autark_sql_plot_keys",
        project_name=spec["dataflow"]["name"],
        project_spec=spec,
    )
    require_owner_view(page)

    # The table the query saved, drawn on a map. Plays the data node first.
    play_node(page, drawer)
    wait_for_node_done(page, drawer, node_type=AUTARK_TYPE)
    assert_autark_map_drawn(page, drawer, timeout=60000, attach_as="a sql source's table on an Autark map")

    # Its bars in viridis over [0, 100]: no riders in the first color, 100 in the last.
    play_node(page, colored)
    wait_for_node_done(page, colored, node_type=AUTARK_TYPE)
    assert_autark_plot_drawn(page, colored)
    chart = _chart(page, colored, lambda drawn: len(drawn["bars"]) == len(ZONES), "four bars")
    fills = [_rgb(fill) for fill in chart["bars"]]
    assert any(_near(fill, VIRIDIS_LOW) for fill in fills) and any(_near(fill, VIRIDIS_HIGH) for fill in fills), (
        f"the bars are {chart['bars']}: colorMapInterpolator and colorMapRange put 0 riders at {VIRIDIS_LOW} "
        f"and 100 at {VIRIDIS_HIGH}"
    )
    # Its axes titled by axisLabels, and each title shows.
    titles = chart["titles"]
    assert sorted(title["text"] for title in titles) == ["Riders", "Zone"], f"the axis titles are {titles}"
    hidden = [title for title in titles if title["fill"] in ("none", "", None)
              or title["visibility"] == "hidden" or float(title["opacity"] or 1) == 0]
    assert not hidden, f"these axis titles do not show: {hidden}"
    # Its y axis's numbers with one decimal, as tickFormats' ".1f" writes them.
    numbers = [tick for tick in chart["ticks"] if re.fullmatch(r"-?[\d.,]+", tick)]
    assert len(numbers) >= 2 and all(re.fullmatch(r"-?\d+\.\d", tick) for tick in numbers), (
        f"the y axis reads {numbers}, not numbers with one decimal"
    )

    # The selected chart: its last row in the highlight color, the others in the mark color.
    play_node(page, selected)
    wait_for_node_done(page, selected, node_type=AUTARK_TYPE)
    assert_autark_plot_drawn(page, selected)
    highlight, mark = _hex(HIGHLIGHT_COLOR), _hex(MARK_COLOR)

    def selection_shown(drawn: dict) -> bool:
        fills = [_rgb(fill) for fill in drawn["bars"]]
        return (len(fills) == len(ZONES) and sum(_near(fill, highlight) for fill in fills) == 1
                and sum(_near(fill, mark) for fill in fills) == len(ZONES) - 1)

    _chart(page, selected, selection_shown, f"one bar in {HIGHLIGHT_COLOR} and the others in {MARK_COLOR}")
    # It stays so once the node is settled: nothing came in to clear it.
    page.wait_for_timeout(1000)
    _chart(page, selected, selection_shown, "the selection the document writes, kept with nothing coming in")
    assert not [e for e in errors if "[autk-grammar] node error" in e], errors
