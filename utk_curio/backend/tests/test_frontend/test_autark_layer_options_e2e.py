"""Map layers styled by autk-grammar's own layer options (autk-grammar 4.2).

A layer's ``title`` names it in the legend, a raster's cells and its legend's
labels follow its scheme, reversed by ``colorMapReverse`` and centered by
``colorMapCenter``, and a line drawn with ``width`` in one ``color`` is wider
than the default line. These replace Curio's own patches over the grammar
(``legendTitle`` and ``recolorRasters``), whose drawing they check through the
map: each test reads what the map canvas drew, in the frame that renders it,
and the legend autk-map writes over it, then compares each map node's
close-up with its baseline.

The raster is a JavaScript node's envelope of 64 by 48 cells of 60 m in UTM
zone 16N, each cell holding its column, 0 in the west to 63 in the east, so a
map shows the scheme from left to right. The lines are three of a Python
node's GeoDataFrame, about 2 km long near the Loop.

Two maps on one source draw twice each time the second is played: once from
the input the first map's run hands it, outside any run, and once more for
its own Play, on a new canvas that stays 300 by 150 until autk-map sizes it.
The scheme test's ``held`` case plays the order two CI failures had (runs
40818895965 and 40783748468, "the 300x150 map canvas is one colour"): the
reversed map is still drawing from its input when its Play is clicked, shows
Done after the click, and the Play's run reaches it only once that drawing
has been checked (``_LATE_PLAY_RUN_JS``).

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_autark_layer_options_e2e.py -v
"""
from __future__ import annotations

import base64
import json
import time
from io import BytesIO
from typing import TYPE_CHECKING

import pytest

from .utils import (
    assert_autark_map_drawn,
    frame_nodes,
    play_node,
    require_owner_view,
    require_project_page,
    require_user_auth,
    save_node_closeup,
    stub_login_and_enter_workflow,
    wait_for_node_done,
)
from .utils.node_drawings import _AUTK_MAP_PIXELS_IN_FRAME_JS

if TYPE_CHECKING:
    from .utils import FrontendPage

MAP_TYPE = "curio.builtin/autk-grammar"
JS_TYPE = "curio.builtin/js-computation"
PYTHON_TYPE = "curio.builtin/computation-analysis"
CLOSEUP_STEM = "autark-layer-options"

#: Columns of the raster: cell (row, col) holds col.
COLUMNS = 64

RAMP = '''const width = 64;
const height = 48;
const values = new Float32Array(width * height);
for (let row = 0; row < height; row++) {
    for (let col = 0; col < width; col++) values[row * width + col] = col;
}
return {
    dataType: 'raster',
    layerName: 'ramp',
    data: {
        type: 'FeatureCollection',
        bbox: [0, 0, 0, 0],
        grid: { crs: 'EPSG:32616', width, height, originX: 447000, originY: 4637000, resX: 60, resY: -60 },
        features: [{
            type: 'Feature',
            geometry: null,
            properties: {
                rasterResX: width,
                rasterResY: height,
                bands: [{ id: 'band_1', label: 'band_1' }],
                band_1: { float32le: Buffer.from(values.buffer).toString('base64') },
            },
        }],
    },
};
'''

LINES = '''import geopandas as gpd
from shapely.geometry import LineString

lines = [LineString([(-87.645, 41.875 + 0.004 * i), (-87.62, 41.875 + 0.004 * i)]) for i in range(3)]
return gpd.GeoDataFrame({"line": [0, 1, 2]}, geometry=lines, crs="EPSG:4326")
'''

#: d3's viridis at 0 and 1, RdBu at its middle, and the lines' color.
VIRIDIS_LOW = (68, 1, 84)
VIRIDIS_HIGH = (253, 231, 37)
RDBU_MIDDLE = (247, 247, 247)
LINE_COLOR = "#d62728"
LINE_RGB = (214, 39, 40)


def _ramp_layer(**options) -> dict:
    return {"map": {"layerRefs": [{"dataRef": "input_0", "getFnv": "band_1", **options}]}}


def _node(node_id: str, node_type: str, x: int, y: int, content: str) -> dict:
    return {
        "id": node_id, "type": node_type, "x": x, "y": y, "content": content,
        "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
    }


def _edge(source: str, target: str) -> dict:
    return {
        "id": f"reactflow__edge-{source}out-{target}in",
        "source": source, "target": target, "sourceHandle": "out", "targetHandle": "in",
    }


def _flow(name: str, source: tuple[str, str, str], maps: dict[str, dict]) -> dict:
    """*source* (id, type, code) feeding one Autark map node per entry of *maps*."""
    source_id, source_type, code = source
    nodes = [_node(source_id, source_type, 120, 160, code)]
    for index, (map_id, document) in enumerate(maps.items()):
        nodes.append(_node(map_id, MAP_TYPE, 820, 40 + 560 * index, json.dumps(document, indent=2)))
    edges = [_edge(source_id, map_id) for map_id in maps]
    return {"dataflow": {"name": name, "task": "", "nodes": nodes, "edges": edges}}


def _enter(page, app_frontend, current_server, *, username: str, spec: dict) -> None:
    require_project_page()
    require_user_auth()
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Autark Layer Options",
        username=username,
        project_name=spec["dataflow"]["name"],
        project_spec=spec,
    )
    require_owner_view(page)


def _draw(page, map_id: str, attach_as: str) -> None:
    """Run the map node and its source, and wait for a drawn map."""
    play_node(page, map_id)
    wait_for_node_done(page, map_id, node_type=MAP_TYPE)
    frame_nodes(page, [map_id])
    assert_autark_map_drawn(page, map_id, timeout=60000, attach_as=attach_as)


def _canvas(page, map_id: str):
    """The node's map canvas as an RGB image, read in the frame that renders it."""
    from PIL import Image

    frame_nodes(page, [map_id])
    url = page.evaluate(_AUTK_MAP_PIXELS_IN_FRAME_JS, map_id)
    assert url, f"Autark node {map_id} has no map canvas"
    return Image.open(BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGB")


def _drawn_box(image) -> tuple[int, int, int, int]:
    """The box of the pixels that differ from the map's background, its top-left corner."""
    from PIL import Image, ImageChops

    channels = ImageChops.difference(image, Image.new("RGB", image.size, image.getpixel((0, 0)))).split()
    moved = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2])
    box = moved.point(lambda v: 255 if v > 8 else 0).getbbox()
    assert box, f"the {image.size[0]}x{image.size[1]} map canvas is one colour: nothing was drawn"
    return box


def _column_color(image, box, column: int) -> tuple[int, int, int]:
    """The mean color of a 5 by 5 patch at the middle of the raster's *column*."""
    left, top, right, bottom = box
    x = round(left + (column + 0.5) / COLUMNS * (right - left))
    y = round((top + bottom) / 2)
    patch = [image.getpixel((x + dx, y + dy)) for dx in range(-2, 3) for dy in range(-2, 3)]
    return tuple(round(sum(p[i] for p in patch) / len(patch)) for i in range(3))


def _distance(a, b) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


# The legend autk-map writes over the node's map: its title, the labels under
# its color bar with their places, and the bar's colors, left to right.
_LEGEND_JS = """(id) => {
    const node = document.querySelector(`.react-flow__node[data-id="${id}"]`);
    const legend = node && node.querySelector('#autkMapLegend');
    if (!legend) return null;
    return {
        visible: legend.style.visibility !== 'hidden',
        title: legend.firstElementChild ? legend.firstElementChild.textContent : null,
        labels: [...legend.querySelectorAll('svg text')].map((t) => [t.textContent, Number(t.getAttribute('x'))]),
        colors: [...legend.querySelectorAll('svg rect')].map((r) => r.style.fill),
    };
}"""


def _legend(page, map_id: str, labels: int) -> dict:
    """The node's legend once it shows *labels* labels."""
    deadline = time.monotonic() + 30
    shown = None
    while time.monotonic() < deadline:
        shown = page.evaluate(_LEGEND_JS, map_id)
        if shown and shown["visible"] and len(shown["labels"]) >= labels:
            return shown
        page.wait_for_timeout(250)
    raise AssertionError(f"Autark node {map_id}'s legend never showed {labels} labels: {shown!r}")


def _label_values(legend: dict) -> list[float]:
    # d3 writes a minus as U+2212.
    return [float(text.replace("−", "-").replace(",", "")) for text, _ in legend["labels"]]


def _rgb(css: str) -> tuple[int, ...]:
    return tuple(int(part) for part in css[css.index("(") + 1:css.index(")")].split(","))


def _assert_ramp_runs(image, box, low, high, what: str) -> None:
    """The raster's west columns are drawn in *low* and its east ones in *high*."""
    west, east = _column_color(image, box, 3), _column_color(image, box, COLUMNS - 4)
    assert _distance(west, low) < 60 and _distance(east, high) < 60, (
        f"{what}: the raster's west reads {west} and its east {east}, not about {low} and {high} "
        f"(box {box} in {image.size})"
    )


#: How long the held case's Play run waits, once the map shows Done from its
#: own drawing, for that drawing to be read before it goes on anyway. A wait
#: for the run itself reads nothing until the run ends, so it meets this one.
LATE_RUN_AFTER_DONE_MS = 10000

#: How long the database of the Play run's own drawing is held: its canvas
#: stays 300 by 150 and blank meanwhile, as autk-map sizes it only once its
#: layers are loaded.
LATE_DATABASE_MS = 10000

# Before the app's own scripts, for the held case: the order both CI failures
# had, made to happen every time. *map* is the map node played second.
#
# 1. A read of an output while no run holds the run guard is the map drawing
#    from the input the first map's run handed it. It is held until the page
#    asks for the next run, the Play's: the map is still drawing when its Play
#    is clicked, and shows Done after the click.
# 2. That run's stream is held until the map, Done, has its sized canvas read
#    (a check of the drawing it shows), or until LATE_RUN_AFTER_DONE_MS after
#    it shows Done. Only then does the run draw the map again: on a new
#    canvas, as every draw does.
# 3. That drawing's database is autk-db's DuckDB worker, which starts from a
#    blob. Its messages are held for LATE_DATABASE_MS, so the new canvas stays
#    300 by 150 and blank.
#
# window.__curioTestLatePlay records what was held, for the guard below.
_LATE_PLAY_RUN_JS = r"""(map, afterDoneMs, databaseMs) => {
    const state = window.__curioTestLatePlay = {
        heldReads: 0, streamHeld: false, doneWhileHeld: false, streamRelease: null, heldDatabases: 0,
    };
    const realFetch = window.fetch.bind(window);
    const runActive = () => !!document.querySelector('[data-run-active="true"]');
    const status = () => {
        const el = document.querySelector(`.react-flow__node[data-id="${map}"] [data-curio-node-status]`);
        return el ? el.getAttribute('data-curio-node-status') : null;
    };
    let phase = 'reads';
    const reads = [];
    let release = null;
    let holdDatabase = false;

    window.fetch = (input, init) => {
        const url = typeof input === 'string' ? input : String((input && input.url) || input || '');
        const method = String((init && init.method) || (input && input.method) || 'GET').toUpperCase();
        if (phase === 'reads' && /\/outputs\/get\?/.test(url) && !runActive()) {
            state.heldReads += 1;
            return new Promise((resolve, reject) => {
                reads.push(() => realFetch(input, init).then(resolve, reject));
            });
        }
        if (phase === 'reads' && reads.length > 0 && method === 'POST'
            && /\/api\/projects\/[^/?]+\/runs$/.test(url)) {
            phase = 'stream';
            reads.splice(0).forEach((send) => send());
        } else if (phase === 'stream' && /\/api\/runs\/[^/?]+\/stream/.test(url)) {
            phase = 'database';
            state.streamHeld = true;
            return new Promise((resolve, reject) => {
                let timer = null;
                const watch = setInterval(() => {
                    if (timer !== null || status() !== 'done') return;
                    state.doneWhileHeld = true;
                    timer = setTimeout(() => { if (release) release('time'); }, afterDoneMs);
                }, 100);
                release = (why) => {
                    release = null;
                    clearInterval(watch);
                    if (timer !== null) clearTimeout(timer);
                    state.streamRelease = why;
                    holdDatabase = true;
                    realFetch(input, init).then(resolve, reject);
                };
            });
        }
        return realFetch(input, init);
    };

    const toDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function (...args) {
        const url = toDataURL.apply(this, args);
        if (release && this.id === `autk-grammar-map-${map}` && status() === 'done'
            && !(this.width === 300 && this.height === 150)) {
            state.doneWhileHeld = true;
            release('read');
        }
        return url;
    };

    const RealWorker = window.Worker;
    if (typeof RealWorker !== 'function') return;
    const Holding = function (url, options) {
        const worker = options === undefined ? new RealWorker(url) : new RealWorker(url, options);
        if (holdDatabase && String(url).startsWith('blob:')) {
            holdDatabase = false;
            state.heldDatabases += 1;
            const post = worker.postMessage.bind(worker);
            const queued = [];
            let held = true;
            worker.postMessage = (...args) => {
                if (held) queued.push(args);
                else post(...args);
            };
            setTimeout(() => {
                held = false;
                queued.splice(0).forEach((args) => post(...args));
            }, databaseMs);
        }
        return worker;
    };
    Holding.prototype = RealWorker.prototype;
    window.Worker = Holding;
}"""


def _late_play_run_script(map_id: str) -> str:
    """``_LATE_PLAY_RUN_JS`` as an init script for the map node *map_id*."""
    return f"({_LATE_PLAY_RUN_JS})({json.dumps(map_id)}, {LATE_RUN_AFTER_DONE_MS}, {LATE_DATABASE_MS});"


def _assert_the_play_ran_late(page) -> None:
    """The held case held what it plays: the map's drawing from its input
    waited for the Play, the map read Done while the Play's run was held, and
    the run's own drawing started its database late. Without these the case
    would pass without the order the CI failures had."""
    held = page.evaluate("() => window.__curioTestLatePlay || null")
    assert held and held["heldReads"] >= 1 and held["streamHeld"] and held["doneWhileHeld"] \
        and held["heldDatabases"] == 1, f"the held case did not hold the steps it plays: {held!r}"


def test_a_layer_title_names_its_legend(app_frontend: "FrontendPage", current_server: str, page):
    """autk-grammar's ``title`` is the layer's id in autk-map, which titles the
    legend with it; with no title the legend reads ``input_0``."""
    ramp, titled = "titled-ramp", "titled-map"
    _enter(page, app_frontend, current_server, username="autark_layer_title", spec=_flow(
        "AutarkLayerTitle", (ramp, JS_TYPE, RAMP),
        {titled: _ramp_layer(colorMapInterpolator="interpolateViridis", title="Ramp value (column)")},
    ))

    _draw(page, titled, "a titled raster layer")
    legend = _legend(page, titled, 2)
    assert legend["title"] == "Ramp value (column)", f"the legend reads {legend['title']!r}"

    save_node_closeup(page, CLOSEUP_STEM, titled, test_name="titled_legend", sweep_toasts=True)


@pytest.mark.parametrize("play_run", ["prompt", "held"])
def test_raster_cells_and_legend_labels_follow_the_scheme(
    app_frontend: "FrontendPage", current_server: str, page, play_run,
):
    """The cells are drawn in the scheme the layer names, every cell with a
    value opaque, and the legend's labels run from the lowest value to the
    highest under the scheme's colors. ``colorMapReverse`` turns the cells and
    the labels around: the highest value takes the scheme's first color.

    *play_run* ``held`` has the reversed map's Play run reach the map late,
    in the order two CI failures had (``_LATE_PLAY_RUN_JS``): the map is still
    drawing from its input when its Play is clicked and shows Done after the
    click, and the run draws it again once that drawing has been read."""
    ramp, plain, reversed_ = "scheme-ramp", "scheme-map", "reversed-map"
    if play_run == "held":
        page.add_init_script(_late_play_run_script(reversed_))
    _enter(page, app_frontend, current_server, username="autark_raster_scheme", spec=_flow(
        "AutarkRasterScheme", (ramp, JS_TYPE, RAMP),
        {
            plain: _ramp_layer(colorMapInterpolator="interpolateViridis"),
            reversed_: _ramp_layer(colorMapInterpolator="interpolateViridis", colorMapReverse=True),
        },
    ))

    _draw(page, plain, "a raster in viridis")
    image = _canvas(page, plain)
    _assert_ramp_runs(image, _drawn_box(image), VIRIDIS_LOW, VIRIDIS_HIGH, "viridis")
    legend = _legend(page, plain, 2)
    assert _label_values(legend) == [0, 63], legend["labels"]
    assert _distance(_rgb(legend["colors"][0]), VIRIDIS_LOW) < 20, legend["colors"][:1]

    _draw(page, reversed_, "a raster in reversed viridis")
    image = _canvas(page, reversed_)
    _assert_ramp_runs(image, _drawn_box(image), VIRIDIS_HIGH, VIRIDIS_LOW, "reversed viridis")
    legend = _legend(page, reversed_, 2)
    assert _label_values(legend) == [63, 0], legend["labels"]
    # The bar keeps the scheme's order: its first color is the highest value's.
    assert _distance(_rgb(legend["colors"][0]), VIRIDIS_LOW) < 20, legend["colors"][:1]

    if play_run == "held":
        _assert_the_play_ran_late(page)
    else:
        # The close-ups come once every map is checked, so a missing baseline
        # never hides a map that drew wrong. The held case draws the same
        # maps, later, and takes none.
        save_node_closeup(page, CLOSEUP_STEM, plain, test_name="raster_scheme", sweep_toasts=True)
        save_node_closeup(page, CLOSEUP_STEM, reversed_, test_name="raster_scheme_reversed", sweep_toasts=True)


def test_a_centered_scale_puts_its_center_at_the_schemes_middle(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """``colorMapCenter`` 20 colors the cells over 20 less and 20 plus the
    farthest value's distance to it, -23 to 63, so column 20 takes RdBu's
    middle, nearly white, and the legend's middle label, at the bar's middle,
    reads 20. Over the values' own range, 0 to 63, column 20 is a light red."""
    ramp, centered = "centered-ramp", "centered-map"
    _enter(page, app_frontend, current_server, username="autark_raster_center", spec=_flow(
        "AutarkRasterCenter", (ramp, JS_TYPE, RAMP),
        {centered: _ramp_layer(colorMapInterpolator="interpolateRdBu", colorMapCenter=20)},
    ))

    _draw(page, centered, "a raster centered on 20")
    image = _canvas(page, centered)
    box = _drawn_box(image)
    middle = _column_color(image, box, 20)
    assert _distance(middle, RDBU_MIDDLE) < 30, (
        f"column 20 is drawn {middle}, not RdBu's middle {RDBU_MIDDLE} (box {box} in {image.size})"
    )
    legend = _legend(page, centered, 3)
    assert _label_values(legend) == [-23, 20, 63], legend["labels"]
    (_, first), (_, mid), (_, last) = legend["labels"]
    assert abs(mid - (first + last) / 2) < 1, legend["labels"]
    save_node_closeup(page, CLOSEUP_STEM, centered, test_name="raster_centered", sweep_toasts=True)


def test_lines_drawn_with_a_width_are_wider_than_the_default_line(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """Two maps of the same lines in one ``color``: one at autk-map's default
    width, one at ``width`` 60 m. The wide map holds several times the line's
    pixels, and both draw in the color the layer names."""
    lines, thin, wide = "styled-lines", "thin-lines-map", "wide-lines-map"
    _enter(page, app_frontend, current_server, username="autark_line_width", spec=_flow(
        "AutarkLineWidth", (lines, PYTHON_TYPE, LINES),
        {
            thin: {"map": {"layerRefs": [{"dataRef": "input_0", "color": LINE_COLOR}]}},
            wide: {"map": {"layerRefs": [{"dataRef": "input_0", "color": LINE_COLOR, "width": 60}]}},
        },
    ))

    def line_pixels(map_id: str) -> int:
        """The pixels in the lines' color, once the map has drawn some (30 s at most)."""
        deadline = time.monotonic() + 30
        while True:
            image = _canvas(page, map_id)
            count = sum(1 for pixel in image.getdata() if _distance(pixel, LINE_RGB) < 60)
            if count > 0 or time.monotonic() >= deadline:
                return count
            page.wait_for_timeout(500)

    for map_id in (thin, wide):
        play_node(page, map_id)
        wait_for_node_done(page, map_id, node_type=MAP_TYPE)
    at_default, at_width = line_pixels(thin), line_pixels(wide)
    assert at_default > 0, f"the default-width map drew no pixel in {LINE_COLOR}"
    assert at_width > 2.5 * at_default, (
        f"the lines 60 m wide cover {at_width} pixels, not well over the {at_default} of the default width"
    )
    save_node_closeup(page, CLOSEUP_STEM, thin, test_name="lines_default_width", sweep_toasts=True)
    save_node_closeup(page, CLOSEUP_STEM, wide, test_name="lines_wide", sweep_toasts=True)
