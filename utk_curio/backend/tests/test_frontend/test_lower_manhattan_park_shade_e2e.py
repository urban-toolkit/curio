"""Lower Manhattan's parks in the shadow of their towers, on the canvas, as
three scenarios (step 18 of the #914 plan: komar41's ShadowsAnywhere, re-made
on Curio's nodes).

The shipped test dataflow ``lower-manhattan-park-shade.json``: an Autark data
node reads OpenStreetMap's parks of a box, the Financial District to City
Hall, and the buildings of a box about 300 m larger on every side, up to the
extract's edge, from ``lower_mnt.osm.pbf``, which the backend serves, so the
run needs no network. Building heights, Open-air parks and Buildings around
parks are the context, with the Season, Distance from a park and Tall
building height Parameters. In
Existing, Towers removed and Height cap (whose Interaction nodes remove or cut
down the building parts Buildings around parks marks), Rasterize Buildings
(``curio.scout@1``) and Accumulated Shadow
(``model.scout.deep-umbra@1``) give the shadow, Shade per park measures it in
each park, and Autark maps draw the buildings in 3D and the shadow. Compare
Scenarios nodes chart each park's minutes of shadow in the three scenarios and
take each what-if's change in shadow, cell by cell and park by park, which
Autark maps after them draw.

Run All in the browser runs the whole dataflow:

1. Open-air parks hands on the 29 parks; Buildings around parks marks 527
   building parts; Towers removed hands on every other part, and Height cap
   every part, the marked ones 60 m tall.
2. The chart's stacked table holds each park's mean minutes of shadow in each
   scenario: on average over the parks within half a minute of the run
   ``test_lower_manhattan_park_shade.py`` pins, and in every park the least
   with the towers removed and the most as they are. Its bars draw in the three
   scenarios' colors.
3. Each what-if's change in shadow is a raster on the shadows' grid, 1024 by
   1280 cells in EPSG:3395, that takes shadow away on the whole, and each
   park's change in shade takes shadow away in every park. The Compare
   Scenarios nodes draw no map; the Autark map after each does.
4. Each scenario's buildings and shadow draw.

Every map's legend is titled as its layer is, and labels the color range it
shares with the maps of its kind: 0 to 550 m for the buildings, 0 to 720
minutes for the shadow, and -720 to 720 minutes, centered on no change, for
a change. The close-ups of the ten maps are the frames.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_lower_manhattan_park_shade_e2e.py -v
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import TYPE_CHECKING

from .test_compare_difference_e2e import (
    _OUTPUT_ARTIFACT_JS,
    _assert_difference_mapped,
    _assert_legend_reads,
    _assert_legend_title,
    _band,
)
from .test_compare_scenarios_e2e import _CHART_STATE_JS, _COLOR_PIXELS_JS
from .utils import (
    REPO_ROOT,
    api_json,
    assert_autark_map_drawn,
    assert_vega_canvas_rendered,
    frame_nodes,
    load_artifact_as_dict,
    node_locator,
    read_node_error_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_all_and_wait,
    save_node_closeup,
    stub_login_and_enter_workflow,
    wait_for_node_settled,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

DATAFLOW = Path(REPO_ROOT) / "docs" / "examples" / "dataflows" / "lower-manhattan-park-shade.json"
TEST_NAME = "test_three_scenarios_of_lower_manhattans_park_shade_are_charted_and_mapped"
PACKAGES = ("curio.scout@1", "model.scout.deep-umbra@1")
#: The scenarios, in the order the chart reads them, and the key of their nodes.
SCENARIOS = (("existing", "Existing", "existing"), ("towers-removed", "Towers removed", "removed"),
             ("height-cap", "Height cap", "capped"))
PARKS = 29
BUILDING_ROWS = 2688
MARKED_ROWS = 527
TALL_HEIGHT_M = 60
GRID = (1024, 1280)
#: Each scenario's mean over the parks of their mean minutes of shadow in
#: summer, from the run test_lower_manhattan_park_shade.py pins.
MEAN_OVER_PARKS = {"existing": 272.06, "towers-removed": 143.09, "height-cap": 219.03}
MINUTES = 0.5
#: The diverging schemes the maps of a change use: a legend labels their middle too.
DIVERGING = {"interpolateRdBu", "interpolateRdYlBu"}


def _saved_output(page, node_id: str) -> dict:
    artifact = page.evaluate(_OUTPUT_ARTIFACT_JS, node_id)
    assert artifact, f"{node_id} shows no saved output"
    return load_artifact_as_dict(artifact)


def _rows(page, node_id: str) -> list[dict]:
    """The rows of the layer *node_id* handed on, each its properties."""
    stored = _saved_output(page, node_id)
    assert stored["dataType"] == "geodataframe", f"{node_id} handed on {stored['dataType']}"
    return [feature["properties"] for feature in stored["data"]["features"]]


def _raster(page, node_id: str) -> dict:
    """The raster envelope *node_id* handed on."""
    stored = _saved_output(page, node_id)
    envelope = stored.get("data") if stored.get("dataType") == "dict" else stored
    assert envelope["dataType"] == "raster", f"{node_id} handed on {stored.get('dataType')}"
    return envelope


def _assert_chart_drew(page, node_id: str, colors: list[str]) -> None:
    """The grouped bars compiled with no problem, and the canvas holds the
    three scenarios' colors."""
    deadline = time.time() + 60
    state = None
    while time.time() < deadline:
        state = page.evaluate(_CHART_STATE_JS, [node_id, "grouped-bar"])
        if state in ("drawn", "problem"):
            break
        page.wait_for_timeout(250)
    problem = node_locator(page, node_id).locator("[data-compare-chart-problem]").all_inner_texts()
    assert state == "drawn", f"the grouped bars' compile ended {state!r}: {problem}"
    assert_vega_canvas_rendered(page, node_id, timeout=30000)
    counts = None
    deadline = time.time() + 15
    while time.time() < deadline:
        counts = page.evaluate(_COLOR_PIXELS_JS, [node_id, colors])
        if counts and all(count >= 30 for count in counts):
            return
        page.wait_for_timeout(250)
    raise AssertionError(f"the chart does not draw the three scenarios' colors {colors}: pixels {counts}")


def _layer(dataflow: dict, node_id: str) -> dict:
    """The one layer the map *node_id* draws, as its document writes it."""
    (layer,) = json.loads(next(n for n in dataflow["nodes"] if n["id"] == node_id)["content"])["map"]["layerRefs"]
    return layer


def _assert_legend_shows_its_range(page, dataflow: dict, map_id: str) -> None:
    """The map's legend is titled as its layer is, and labels the color range
    the maps beside it share: its ends, and on a diverging scheme its middle."""
    layer = _layer(dataflow, map_id)
    _assert_legend_title(page, map_id, layer["title"])
    low, high = layer["colorMapRange"]
    middle = layer.get("colorMapCenter", (low + high) / 2)
    diverging = layer["colorMapInterpolator"] in DIVERGING
    _assert_legend_reads(page, map_id, (low, middle, high) if diverging else (low, high))


def test_three_scenarios_of_lower_manhattans_park_shade_are_charted_and_mapped(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
    record_property,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    spec = json.loads(DATAFLOW.read_text(encoding="utf-8"))
    dataflow = spec["dataflow"]
    nodes = {node["id"]: node for node in dataflow["nodes"]}
    colors = [scenario["color"] for scenario in dataflow["scenarios"]]
    assert [scenario["id"] for scenario in dataflow["scenarios"]] == [s[0] for s in SCENARIOS]
    maps = [n for n, node in nodes.items()
            if node["type"] == "curio.builtin/autk-grammar" and n != "park-shade-layers"]
    assert len(maps) == 10, maps

    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Park Shade",
        username="park_shade_e2e",
        project_name=dataflow["name"],
        project_spec=spec,
    )
    require_owner_view(page)
    store = [p.get("dirName") for p in api_json(f"{current_server}/api/packages", session["token"])["packages"]]
    missing = [package for package in PACKAGES if package not in store]
    assert not missing, f"{missing} are not in the account's store {store}: start the stack --with-examples"
    for node_id in nodes:
        node_locator(page, node_id).wait_for(state="attached", timeout=45000)

    run_all_and_wait(page, timeout_ms=600000)
    for node_id, node in nodes.items():
        if node["type"] == "curio.builtin/parameter":
            continue
        status = wait_for_node_settled(page, node_id, node_type=node["type"], timeout_ms=180000)
        assert status == "done", (
            f"{node['type']} {node_id} ended {status}: {read_node_error_text(node_locator(page, node_id))}"
        )

    # 1. The parks, the marked parts and the levers.
    assert len(_rows(page, "park-shade-parks")) == PARKS
    marked = _rows(page, "park-shade-around")
    assert len(marked) == BUILDING_ROWS and sum(1 for row in marked if row["around_park"]) == MARKED_ROWS
    removed = _rows(page, "park-shade-removed-lever")
    assert len(removed) == BUILDING_ROWS - MARKED_ROWS and not any(row["around_park"] for row in removed)
    capped = _rows(page, "park-shade-capped-lever")
    assert len(capped) == BUILDING_ROWS
    assert all(row["height"] == TALL_HEIGHT_M for row in capped if row["around_park"]), "Height cap left a part uncut"

    # 2. Each park's minutes in each scenario, and the bars in their colors.
    stacked = _rows(page, "park-shade-chart")
    means: dict = {}
    for row in stacked:
        means.setdefault(row["scenario"], {})[row["park"]] = row["mean_min"]
    assert sorted(means) == sorted(s[0] for s in SCENARIOS) and all(len(m) == PARKS for m in means.values()), means
    over_parks = {scenario: sum(m.values()) / len(m) for scenario, m in means.items()}
    record_property("mean over the parks (minutes)", json.dumps({"ours": over_parks, "pinned": MEAN_OVER_PARKS}))
    assert all(abs(over_parks[key] - MEAN_OVER_PARKS[key]) <= MINUTES for key in MEAN_OVER_PARKS), (
        f"mean over the parks, ours {over_parks}, pinned {MEAN_OVER_PARKS}"
    )
    for park, existing in means["existing"].items():
        assert means["towers-removed"][park] < means["height-cap"][park] < existing, park
    frame_nodes(page, ["park-shade-chart"])
    _assert_chart_drew(page, "park-shade-chart", colors)

    # 3. Each what-if's change, in shadow and in each park, mapped after it.
    for scenario, name, key in SCENARIOS[1:]:
        change, change_map = f"park-shade-{key}-change", f"park-shade-{key}-change-map"
        envelope = _raster(page, change)
        grid = envelope["data"]["grid"]
        assert (grid["crs"], grid["width"], grid["height"]) == ("EPSG:3395", *GRID), grid
        cells = [v for v in _band(envelope) if not math.isnan(v)]
        mean_change = sum(cells) / len(cells)
        record_property(f"change in shadow, {name} (minutes)",
                        json.dumps({"min": min(cells), "max": max(cells), "mean": mean_change}))
        assert min(cells) < -100 and mean_change < 0, (name, min(cells), mean_change)
        assert -720 <= min(cells) and max(cells) <= 720, (name, min(cells), max(cells))
        frame_nodes(page, [change, change_map])
        _assert_difference_mapped(page, change, change_map, f"the change in shadow under {name}")
        _assert_legend_shows_its_range(page, dataflow, change_map)
        save_node_closeup(page, f"park-shade-change-map-{scenario}", change_map, test_name=TEST_NAME, sweep_toasts=True)

        park_change, park_map = f"park-shade-{key}-park-change", f"park-shade-{key}-park-change-map"
        rows = _rows(page, park_change)
        assert len(rows) == PARKS and all(row["change"] == "changed" and row["mean_min"] < 0 for row in rows), (
            name, [(row["park"], row["change"], row["mean_min"]) for row in rows]
        )
        frame_nodes(page, [park_change, park_map])
        _assert_difference_mapped(page, park_change, park_map, f"each park's change in shade under {name}")
        _assert_legend_shows_its_range(page, dataflow, park_map)
        save_node_closeup(page, f"park-shade-park-change-map-{scenario}", park_map, test_name=TEST_NAME,
                          sweep_toasts=True)

    # 4. Each scenario's buildings and shadow.
    for scenario, _name, key in SCENARIOS:
        for what in ("buildings-map", "shadow-map"):
            map_id = f"park-shade-{key}-{what}"
            frame_nodes(page, [map_id])
            assert_autark_map_drawn(page, map_id, timeout=60000, attach_as=f"the {scenario} {what}")
            _assert_legend_shows_its_range(page, dataflow, map_id)
            save_node_closeup(page, f"park-shade-{what}-{scenario}", map_id, test_name=TEST_NAME, sweep_toasts=True)
