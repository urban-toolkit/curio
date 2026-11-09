"""Playwright E2E: a video played in Simple View lights the rows walked up to where it stands.

Simple View plays a collection's video in its card, and what the player has
played, from the video's start to where it stands, is a selection: an interval
over ``t_s``, the time in the video in seconds, sent over Simple View's
interaction edge as a brush on a time axis sends its interval. The view at the
other end matches its own rows against it with the code a brush's interval
goes through, and lights each row whose ``t_s`` is in the range: on a map the
points walked so far, on a chart the bars up to now. Nothing is redrawn.

The video is the example storage source's one-second clip (``clip_01.mp4``,
ten frames at 10 fps, in ``data.curio.storage-survey``). The rows are a walk's
points, one every 0.1 s, handed over in a shuffled order. Each step asserts
the exact rows lit, which only matching each row's time against the range
gives:

* the rows at the first positions are other points than the first walked, so
  matching by row position lights the wrong ones;
* the point exactly where the player stands is lit, and so is every point
  before it, not that point alone;
* a seek back lights fewer points, so keeping what was played before fails;
* while the video plays, the lit points grow, and where it stops, they stop.

One test per kind of view at the other end: a Vega-Lite chart, and an Autark
map whose points layer is the one that picks (autk-map draws a highlight on
that layer only). Each takes a close-up of that view before the video plays
and after a seek, and checks that the view was not drawn again for it.

The Autark test skips without a WebGPU adapter unless
``CURIO_REQUIRE_HARDWARE_WEBGPU=1`` (CI's GPU job).

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_player_linked_by_time_e2e.py -v
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from .test_keyed_selection_between_charts_e2e import _RED_BARS_JS
from .utils import (
    dismiss_toasts,
    frame_node,
    node_locator,
    require_owner_view,
    require_project_page,
    require_user_auth,
    require_webgpu,
    run_all_and_wait,
    save_node_closeup,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

STEM = "player-linked-by-time"
VIDEOS_ID = "player-videos"
VIEW_ID = "player-view"
WALK_ID = "player-walk"
TARGET_ID = "player-target"

#: The clip Simple View plays: one second long.
CLIP = "clip_01.mp4"
#: The order the walk's points are handed over in: point k was walked k / 10 s in.
ORDER = [7, 2, 9, 0, 5, 10, 3, 8, 1, 6, 4]
LABELS = [f"w{k}" for k in ORDER]

VIDEOS_CODE = (
    "import pandas as pd\n"
    "\n"
    'collection = curio_load_collection("data.curio.storage-survey")\n'
    'videos = collection[collection["kind"] == "video"]\n'
    'return pd.DataFrame(videos.drop(columns="geometry", errors="ignore"))\n'
)

WALK_CODE = (
    "import geopandas as gpd\n"
    "from shapely.geometry import Point\n"
    "\n"
    "# A walk's points, one every 0.1 s, handed over in a shuffled order, about\n"
    "# 165 m apart: autk-map draws a point as a disc 64 m in radius.\n"
    f"order = {json.dumps(ORDER)}\n"
    "return gpd.GeoDataFrame(\n"
    "    {\n"
    '        "label": [f"w{k}" for k in order],\n'
    '        "t_s": [k / 10 for k in order],\n'
    '        "level": [3 + k % 4 for k in order],\n'
    "    },\n"
    "    geometry=[Point(-87.64 + k * 0.002, 41.88 + (k % 2) * 0.0005) for k in order],\n"
    '    crs="EPSG:4326",\n'
    ")\n"
)

# A bar per point, in the order they were walked, red where a selection marks it.
VEGA_WALK = json.dumps({
    "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
    "mark": {"type": "bar"},
    "encoding": {
        "x": {"field": "label", "type": "ordinal", "sort": {"field": "t_s"}},
        "y": {"field": "level", "type": "quantitative"},
        "color": {"condition": {"test": "datum.interacted === '1'", "value": "red"}, "value": "blue"},
    },
}, indent=2)

# The walk's points on an Autark map, on the layer that picks.
AUTARK_WALK = json.dumps({"map": {"layerRefs": [{"dataRef": "input_0", "isPick": True}]}}, indent=2)

VEGA = "curio.builtin/vis-vega"
AUTARK = "curio.builtin/autk-grammar"


def _walked_up_to(at: float) -> list[str]:
    """The points walked by *at* seconds in, sorted."""
    return sorted(f"w{k}" for k in ORDER if k / 10 <= at)


def _assert_fixture_tells_ways_apart() -> None:
    """The steps' expected lights differ from what a wrong way of reading the player lights."""
    at_positions = sorted(LABELS[: len(_walked_up_to(0.4))])
    assert at_positions != _walked_up_to(0.4), (
        f"the first rows handed over are {at_positions}: the fixture no longer tells a match by "
        "row position from one by time"
    )
    assert _walked_up_to(0.4) != ["w4"], "the fixture no longer tells a range from the point where the player stands"
    assert _walked_up_to(0.25) != _walked_up_to(0.75), "a seek back would light what a seek forward lit"


def _node(node_id: str, node_type: str, x: int, y: int, content: str) -> dict:
    return {
        "id": node_id, "type": node_type, "x": x, "y": y, "content": content,
        "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
    }


def _edge(source: str, target: str) -> dict:
    return {"id": f"reactflow__edge-{source}out-{target}in", "source": source, "target": target}


def _interaction(source: str, target: str) -> dict:
    return {
        "id": f"reactflow__edge-{source}in/out-{target}in/out", "type": "Interaction",
        "source": source, "target": target, "sourceHandle": "in/out", "targetHandle": "in/out",
    }


def _spec(name: str, target: tuple[str, str]) -> dict:
    return {"dataflow": {
        "name": name, "task": "", "timestamp": 1789193389280, "provenance_id": name,
        "nodes": [
            _node(VIDEOS_ID, "curio.builtin/data-loading", 0, 0, VIDEOS_CODE),
            _node(VIEW_ID, "curio.builtin/vis-simple", 650, 0, ""),
            _node(WALK_ID, "curio.builtin/data-loading", 0, 600, WALK_CODE),
            _node(TARGET_ID, target[0], 650, 600, target[1]),
        ],
        "edges": [
            _edge(VIDEOS_ID, VIEW_ID),
            _edge(WALK_ID, TARGET_ID),
            _interaction(VIEW_ID, TARGET_ID),
        ],
    }}


def _open(page, app_frontend, current_server, *, username: str, spec: dict, autark: bool) -> None:
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name=spec["dataflow"]["name"],
        username=username,
        project_name=spec["dataflow"]["name"],
        project_spec=spec,
    )
    require_owner_view(page)
    for node in spec["dataflow"]["nodes"]:
        node_locator(page, node["id"]).wait_for(state="visible", timeout=45000)
    if autark:
        require_webgpu(page)
    run_all_and_wait(page, timeout_ms=180000)
    dismiss_toasts(page)


#: The player's element, inside Simple View's card.
VIDEO = f'.react-flow__node[data-id="{VIEW_ID}"] video'


def _play_the_clip(page) -> None:
    """Play the clip from its card and stop it once it is loaded, so seeks drive its time."""
    can_play = page.evaluate("() => document.createElement('video').canPlayType('video/mp4; codecs=\"avc1.42E01E\"')")
    assert can_play, "this browser plays no H.264 MP4, so Simple View cannot play the clip"
    frame_node(page, VIEW_ID)
    node_locator(page, VIEW_ID).get_by_role("button", name=f"Play {CLIP}").click()
    page.wait_for_function(
        "(selector) => { const v = document.querySelector(selector); return !!v && v.readyState >= 1; }",
        arg=VIDEO, timeout=60000,
    )
    page.evaluate("(selector) => document.querySelector(selector).pause()", VIDEO)


_SEEK_JS = """async ([selector, at]) => {
    const video = document.querySelector(selector);
    await new Promise((resolve) => {
        video.addEventListener('seeked', resolve, { once: true });
        video.currentTime = at;
    });
    return video.currentTime;
}"""


def _seek(page, at: float) -> None:
    stands = page.evaluate(_SEEK_JS, [VIDEO, at])
    assert stands == at, f"a seek to {at} s left the player at {stands} s"


# Whether the view's canvas is the one it drew before: a view drawn again draws
# on a new canvas.
_KEEP_CANVAS_JS = """(selector) => {
    window.__curioPlayerTarget = document.querySelector(selector);
    return !!window.__curioPlayerTarget;
}"""
_SAME_CANVAS_JS = """(selector) => {
    const kept = window.__curioPlayerTarget;
    return !!kept && kept.isConnected && kept === document.querySelector(selector);
}"""


def _wait_for_lit(page, read, expected: list[str], what: str, *, timeout_ms: int = 30000) -> None:
    deadline = time.monotonic() + timeout_ms / 1000
    lit = read(page)
    while lit != sorted(expected) and time.monotonic() < deadline:
        page.wait_for_timeout(200)
        lit = read(page)
    assert lit == sorted(expected), f"{what}: the view lights {lit!r}, not {sorted(expected)!r}"


def _play_and_stop(page, read, before: list[str]) -> None:
    """Play from where the player stands, slowed down, until the lit points
    grow past *before* while it still plays; then stop it there and check the
    lit points are those walked up to where it stopped."""
    page.evaluate(
        "(selector) => { const v = document.querySelector(selector); v.playbackRate = 0.0625; return v.play(); }",
        VIDEO,
    )
    deadline = time.monotonic() + 30
    grew = False
    while time.monotonic() < deadline:
        lit = read(page) or []
        playing = page.evaluate("(selector) => !document.querySelector(selector).paused", VIDEO)
        if set(lit) > set(before):
            assert playing, f"the lit points grew to {lit!r} only once the clip had ended"
            grew = True
            break
        assert playing, f"the clip ended while the view still lit {lit!r}, nothing past {before!r}"
        page.wait_for_timeout(100)
    assert grew, f"while the clip played, the view kept lighting {read(page)!r}"
    stopped = page.evaluate(
        "(selector) => { const v = document.querySelector(selector); v.pause(); return v.currentTime; }",
        VIDEO,
    )
    _wait_for_lit(page, read, _walked_up_to(stopped), f"Stopped at {stopped} s")


def _steps(page, read, *, canvas: str, closeup: str) -> None:
    """The steps both tests take, reading the view at the other end with *read*."""
    _wait_for_lit(page, read, [], "Before the clip plays")
    save_node_closeup(page, STEM, TARGET_ID, test_name=f"{closeup}_before_playing", sweep_toasts=True)
    assert page.evaluate(_KEEP_CANVAS_JS, canvas), f"the view has no canvas {canvas}"

    _play_the_clip(page)
    _seek(page, 0.75)
    _wait_for_lit(page, read, _walked_up_to(0.75), "Sought to 0.75 s")
    _seek(page, 0.25)
    _wait_for_lit(page, read, _walked_up_to(0.25), "Sought back to 0.25 s")
    _seek(page, 0.4)
    _wait_for_lit(page, read, _walked_up_to(0.4), "Sought to 0.4 s, where point w4 was walked")
    save_node_closeup(page, STEM, TARGET_ID, test_name=f"{closeup}_at_0_4_s", sweep_toasts=True)

    _play_and_stop(page, read, _walked_up_to(0.4))
    assert page.evaluate(_SAME_CANVAS_JS, canvas), "the view was drawn again for the player's range"


def _vega_lit(page) -> list[str] | None:
    """The points the Vega-Lite chart shows red, sorted. Its bars go in the
    order the points were walked."""
    red = page.evaluate(_RED_BARS_JS, [TARGET_ID, len(ORDER)])
    return None if red is None else sorted(f"w{k}" for k, lit in enumerate(red) if lit)


_MAP_LIT_JS = """async (id) => {
    const state = window.__curio_mapState ? await window.__curio_mapState(id) : null;
    const table = state && state.input_0;
    if (!table) return null;
    return { pick: table.pick, drawn: table.drawn, lit: table.lit.map((p) => p.label) };
}"""


def _wait_for_walk_drawn(page) -> None:
    """Wait until the map draws every point of the walk, as autk-map holds
    the layer: a map of points alone draws two colours, too few for
    ``assert_autark_map_drawn``, which looks for a map's many."""
    deadline = time.monotonic() + 60
    state = page.evaluate(_MAP_LIT_JS, TARGET_ID)
    while not (state and state["drawn"] == len(ORDER)) and time.monotonic() < deadline:
        page.wait_for_timeout(500)
        state = page.evaluate(_MAP_LIT_JS, TARGET_ID)
    assert state and state["drawn"] == len(ORDER), f"the map draws {state!r}, not the walk's {len(ORDER)} points"


def _autark_lit(page) -> list[str] | None:
    """The points the Autark map lights, sorted."""
    state = page.evaluate(_MAP_LIT_JS, TARGET_ID)
    if state is None:
        return None
    assert state["pick"], "the walk's layer is not the one that picks, where autk-map draws a highlight"
    return sorted(state["lit"])


def test_a_video_played_in_simple_view_lights_the_rows_walked_up_to_now_in_a_vega_lite_chart(
    app_frontend: "FrontendPage", current_server: str, page,
):
    _assert_fixture_tells_ways_apart()
    spec = _spec("Player linked to Vega-Lite", (VEGA, VEGA_WALK))
    _open(page, app_frontend, current_server, username="player_vega", spec=spec, autark=False)
    page.locator(f"#vega{TARGET_ID} canvas").first.wait_for(state="attached", timeout=60000)
    _steps(page, _vega_lit, canvas=f"#vega{TARGET_ID} canvas", closeup="vega")


def test_a_video_played_in_simple_view_lights_the_points_walked_up_to_now_on_an_autark_map(
    app_frontend: "FrontendPage", current_server: str, page,
):
    _assert_fixture_tells_ways_apart()
    spec = _spec("Player linked to Autark", (AUTARK, AUTARK_WALK))
    _open(page, app_frontend, current_server, username="player_autark", spec=spec, autark=True)
    _wait_for_walk_drawn(page)
    _steps(page, _autark_lit, canvas=f"#autk-grammar-map-{TARGET_ID}", closeup="autark")
