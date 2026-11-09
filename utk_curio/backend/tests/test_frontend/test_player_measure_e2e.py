"""Throwaway (tmp/ branch only): what one update of the player's range costs.

A Simple View plays the one-second clip, linked by interaction edges to a
Vega-Lite chart and an Autark map over N points with t_s spread over the clip.
Each update is timed in the page (the branch's instrumentation pushes to
window.__curioPlayerMeasures), and the page's main-thread time is read through
CDP's Performance.getMetrics. The test always fails, with the numbers in its
message, to be read from the JUnit file.
"""

from __future__ import annotations

import json
import time

import pytest

from .test_player_linked_by_time_e2e import VIDEO, VIDEOS_CODE, _play_the_clip, _seek
from .utils import (
    dismiss_toasts,
    node_locator,
    require_owner_view,
    require_project_page,
    require_user_auth,
    require_webgpu,
    run_all_and_wait,
    stub_login_and_enter_workflow,
)

VIEW_ID = "player-view"


def _walk_code(n: int) -> str:
    return (
        "import geopandas as gpd\n"
        "from shapely.geometry import Point\n"
        "import random\n"
        f"n = {n}\n"
        "order = list(range(n))\n"
        "random.Random(7).shuffle(order)\n"
        "return gpd.GeoDataFrame(\n"
        '    {"label": [f"w{k}" for k in order], "t_s": [k / n for k in order], "level": [k % 7 for k in order]},\n'
        "    geometry=[Point(-87.64 + 0.01 * k / n, 41.88 + 0.002 * ((k * 7) % 10) / 10) for k in order],\n"
        '    crs="EPSG:4326",\n'
        ")\n"
    )


VEGA = json.dumps({
    "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
    "mark": {"type": "point", "filled": True},
    "encoding": {
        "x": {"field": "t_s", "type": "quantitative"},
        "y": {"field": "level", "type": "quantitative"},
        "color": {"condition": {"test": "datum.interacted === '1'", "value": "red"}, "value": "blue"},
    },
})
AUTARK = json.dumps({"map": {"layerRefs": [{"dataRef": "input_0", "isPick": True}]}})


def _node(node_id, node_type, x, y, content):
    return {"id": node_id, "type": node_type, "x": x, "y": y, "content": content,
            "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []}}


def _spec(n: int) -> dict:
    name = f"Player measure {n}"
    return {"dataflow": {
        "name": name, "task": "", "timestamp": 1789193389280, "provenance_id": name,
        "nodes": [
            _node("player-videos", "curio.builtin/data-loading", 0, 0, VIDEOS_CODE),
            _node(VIEW_ID, "curio.builtin/vis-simple", 650, 0, ""),
            _node("walk", "curio.builtin/data-loading", 0, 600, _walk_code(n)),
            _node("chart", "curio.builtin/vis-vega", 650, 600, VEGA),
            _node("map", "curio.builtin/autk-grammar", 1300, 600, AUTARK),
        ],
        "edges": [
            {"id": "e1", "source": "player-videos", "target": VIEW_ID},
            {"id": "e2", "source": "walk", "target": "chart"},
            {"id": "e3", "source": "walk", "target": "map"},
            {"id": "i1", "type": "Interaction", "source": VIEW_ID, "target": "chart",
             "sourceHandle": "in/out", "targetHandle": "in/out"},
            {"id": "i2", "type": "Interaction", "source": VIEW_ID, "target": "map",
             "sourceHandle": "in/out", "targetHandle": "in/out"},
        ],
    }}


def _task_s(cdp) -> dict:
    metrics = {m["name"]: m["value"] for m in cdp.send("Performance.getMetrics")["metrics"]}
    return {k: metrics.get(k, 0.0) for k in ("TaskDuration", "ScriptDuration", "LayoutDuration", "RecalcStyleDuration")}


def _delta(after: dict, before: dict) -> dict:
    return {k: round((after[k] - before[k]) * 1000, 1) for k in after}


def _measures(page) -> list:
    return page.evaluate("() => (window.__curioPlayerMeasures || []).slice()")


def _summary(values: list[float]) -> dict:
    if not values:
        return {}
    ordered = sorted(values)
    return {
        "n": len(values),
        "median": round(ordered[len(ordered) // 2], 1),
        "p90": round(ordered[int(len(ordered) * 0.9) - 1 if len(ordered) >= 10 else -1], 1),
        "max": round(ordered[-1], 1),
        "first": round(values[0], 1),
    }


@pytest.mark.parametrize("n", [900, 10000])
def test_measure_one_update(app_frontend, current_server, page, n):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    spec = _spec(n)
    stub_login_and_enter_workflow(
        page, frontend_url=app_frontend.base_url, backend_url=current_server,
        name=spec["dataflow"]["name"], username=f"player_measure_{n}",
        project_name=spec["dataflow"]["name"], project_spec=spec,
    )
    require_owner_view(page)
    for node in spec["dataflow"]["nodes"]:
        node_locator(page, node["id"]).wait_for(state="visible", timeout=45000)
    require_webgpu(page)
    run_all_and_wait(page, timeout_ms=240000)
    dismiss_toasts(page)
    # Not read through __curio_mapState, which would read the layer's rows
    # back before the first update does (drawnRowsOf).
    page.locator("#autk-grammar-map-map").wait_for(state="attached", timeout=60000)
    page.wait_for_timeout(5000)
    page.locator("#vegachart canvas").first.wait_for(state="attached", timeout=60000)

    cdp = page.context.new_cdp_session(page)
    cdp.send("Performance.enable")
    # The first updates after the map drew: the clip's own start, at a click.
    page.evaluate("() => { window.__curioPlayerMeasures = []; }")
    _play_the_clip(page)
    page.wait_for_timeout(1500)
    first_updates = [m for m in _measures(page) if m["kind"] == "autark"][:3]
    page.evaluate("() => { window.__curioPlayerMeasures = []; }")

    # Seeks, each left to land on both views before the next.
    times = [0.3, 0.7, 0.35, 0.75, 0.4, 0.8, 0.45, 0.85, 0.5, 0.9, 0.55, 0.6, 0.65, 0.2, 0.25, 0.15, 0.95, 0.1, 0.05, 0.5]
    before = _task_s(cdp)
    started = time.monotonic()
    for at in times:
        count = len(_measures(page))
        _seek(page, at)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            done = _measures(page)[count:]
            kinds = {m["kind"] for m in done}
            if {"autark", "vega"} <= kinds:
                break
            page.wait_for_timeout(20)
        page.wait_for_timeout(300)
    seek_wall = time.monotonic() - started
    after = _task_s(cdp)
    seeks = _measures(page)

    # The same length of wall time with nothing told.
    idle_before = _task_s(cdp)
    page.wait_for_timeout(int(seek_wall * 1000))
    idle = _delta(_task_s(cdp), idle_before)

    # Five seconds of real play, looped, at speed 1.
    page.evaluate("() => { window.__curioPlayerMeasures = []; }")
    play_before = _task_s(cdp)
    page.evaluate(
        "(s) => { const v = document.querySelector(s); v.loop = true; v.playbackRate = 1; return v.play(); }", VIDEO)
    page.wait_for_timeout(5000)
    quality = page.evaluate(
        "(s) => { const v = document.querySelector(s); v.pause(); const q = v.getVideoPlaybackQuality();"
        " return {dropped: q.droppedVideoFrames, total: q.totalVideoFrames}; }", VIDEO)
    play = _delta(_task_s(cdp), play_before)
    played = _measures(page)

    def of(kind, key, measures):
        return [m[key] for m in measures if m["kind"] == kind]

    tells = of("tell", "at", seeks)
    autark_starts = of("autark", "start", seeks)
    lag = []
    for told in tells:
        later = [s for s in autark_starts if s >= told]
        if later:
            lag.append(later[0] - told)
    result = {
        "n": n,
        "first_autark_updates": [{k: round(m[k], 1) for k in ("total", "drawn", "match")} for m in first_updates],
        "seeks": len(times),
        "seek_wall_s": round(seek_wall, 1),
        "seek_task_ms": _delta(after, before),
        "idle_task_ms": idle,
        "autark_total_ms": _summary(of("autark", "total", seeks)),
        "autark_drawnRowsOf_ms": _summary(of("autark", "drawn", seeks)),
        "autark_match_ms": _summary(of("autark", "match", seeks)),
        "vega_sync_ms": _summary(of("vega", "sync", seeks)),
        "vega_total_ms": _summary(of("vega", "total", seeks)),
        "tell_to_autark_ms": _summary(lag),
        "play_5s": {"tells": len(of("tell", "at", played)), "task_ms": play, "video": quality,
                    "autark_total_ms": _summary(of("autark", "total", played)),
                    "vega_total_ms": _summary(of("vega", "total", played))},
    }
    raise AssertionError("PLAYER-MEASURE " + json.dumps(result))
