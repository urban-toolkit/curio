"""Example 31, the SAGE-IDOT rail crossings, run in the browser and on its dashboard.

The example's data stay in a bucket, which no e2e stack mounts, so its owner
first caches the files of its six bucket collections from the Data Catalog
drawer, as on a Curio that mounts no bucket: **Cache files** copies them from
the recorded corpus, which holds a thinned copy of each team day's records and
six real snapshots, made smaller, of the half hour its Frames tile shows
first. Then Run All runs every node, the Frames cards give each snapshot's
time and every model's count, the Autark map draws the ground, and the
dashboard shows its eight tiles. A visitor with no account who picks another
camera on the Settings tile reruns the tiles below it on the server, and the
Frames tile shows that camera's half hour.

A visitor's Frames cards show their pictures once #1522 serves a pinned Simple
View's derived images to a viewer with no account; the captions, which this
test reads, come with the tile's rows.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect

from .test_dashboard_page_e2e import _CHART_PIXELS_JS, _Visitor, _open_dashboard, _pick, _serve_hosted
from .utils import (
    REPO_ROOT,
    assert_autark_map_drawn,
    assert_vega_canvas_rendered,
    cache_bucket_collections,
    dismiss_toasts,
    node_locator,
    park_pointer,
    require_owner_view,
    require_project_page,
    require_user_auth,
    require_webgpu,
    run_all_and_wait,
    save_dataflow,
    save_workflow_test_screenshot,
    stub_login_and_enter_workflow,
    wait_for_node_done,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

EXAMPLE = Path(REPO_ROOT, "docs", "examples", "31-sage-idot-rail-crossings.json")
STEM = "31-sage-idot-rail-crossings"
SETTINGS = "idot-settings"
FRAMES = "idot-frames-view"
GROUND = "idot-ground-map"
CHARTS = ("idot-zone-occupancy-chart", "idot-per-hour-chart", "idot-confidence-chart", "idot-by-model-chart",
          "idot-agreement-chart")
#: The dashboard's eight tiles.
TILES = {SETTINGS, FRAMES, GROUND, *CHARTS}
#: How long a run of the whole example may take on a loaded runner.
RUN_TIMEOUT_MS = 600000

#: The Frames cards on the corpus, with the Settings tile's defaults: W042's
#: busiest half hour, 4:00 to 4:30 PM in Chicago, YOLOv8n's boxes drawn.
W042_CAPTIONS = [
    ["taken_at: 16:00:14", "v5n · v8n: 2 · 2", "v10n · 26n: 2 · 3"],
    ["taken_at: 16:05:03", "v5n · v8n: 3 · 5", "v10n · 26n: 3 · 6"],
    ["taken_at: 16:10:02", "v5n · v8n: 3 · 3", "v10n · 26n: 3 · 3"],
    ["taken_at: 16:15:03", "v5n · v8n: 3 · 2", "v10n · 26n: 3 · 5"],
    ["taken_at: 16:20:02", "v5n · v8n: 2 · 4", "v10n · 26n: 3 · 5"],
    ["taken_at: 16:25:02", "v5n · v8n: 2 · 2", "v10n · 26n: 2 · 2"],
]
#: And with W065 picked: its busiest half hour, 12:30 to 1:00 AM.
W065 = "W065 · Aug 17, 2025"
W065_CAPTIONS = [
    ["taken_at: 00:30:02", "v5n · v8n: 1 · 1", "v10n · 26n: 1 · 1"],
    ["taken_at: 00:35:03", "v5n · v8n: 0 · 3", "v10n · 26n: 0 · 3"],
    ["taken_at: 00:40:01", "v5n · v8n: 0 · 0", "v10n · 26n: 0 · 0"],
    ["taken_at: 00:45:02", "v5n · v8n: 1 · 1", "v10n · 26n: 1 · 1"],
    ["taken_at: 00:50:03", "v5n · v8n: 1 · 2", "v10n · 26n: 2 · 2"],
    ["taken_at: 00:55:02", "v5n · v8n: 0 · 0", "v10n · 26n: 0 · 0"],
]

#: Each Frames card's caption, a line per column, in card order.
_CAPTIONS_JS = """(id) => [...document.querySelectorAll('[id^="imageBox_content_' + id + '_"]')].map(
    (card) => [...card.querySelectorAll('span')].map((line) => line.textContent.trim()))"""


def _spec() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def _captions(page) -> list[list[str]]:
    return page.evaluate(_CAPTIONS_JS, FRAMES)


def _frames_read(page, captions: list[list[str]], *, timeout: float = RUN_TIMEOUT_MS) -> None:
    """The Frames tile's cards read *captions*."""
    try:
        page.wait_for_function(f"([id, want]) => JSON.stringify(({_CAPTIONS_JS})(id)) === JSON.stringify(want)",
                               arg=[FRAMES, captions], timeout=timeout, polling=500)
    except PlaywrightTimeoutError:
        raise AssertionError(f"the Frames cards read {_captions(page)!r}, not {captions!r}") from None


def _tiles_drew(page) -> None:
    """Each chart drew, the map drew, and the Frames tile shows its six cards."""
    for chart in CHARTS:
        assert_vega_canvas_rendered(page, chart, timeout=RUN_TIMEOUT_MS)
    assert_autark_map_drawn(page, GROUND, timeout=RUN_TIMEOUT_MS)
    expect(node_locator(page, FRAMES).locator(f'[id^="imageBox_content_{FRAMES}_"]')).to_have_count(6, timeout=60000)


def test_the_example_runs_on_its_cached_files_and_its_dashboard_follows_a_visitors_camera(
    app_frontend: "FrontendPage", current_server, page, browser, monkeypatch,
):
    require_project_page()
    require_user_auth()
    spec = _spec()
    page.emulate_media(reduced_motion="reduce")
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="SAGE-IDOT owner",
        username=f"idot_{uuid.uuid4().hex[:8]}",
        project_name=spec["dataflow"]["name"],
        project_spec=spec,
    )
    require_owner_view(page)
    page.wait_for_selector(".react-flow__node", timeout=45000)
    dismiss_toasts(page)
    require_webgpu(page)
    project_id = session["project"]["id"]

    # The six collections whose files are in the bucket, cached from the corpus.
    datasets = [ref["datasetId"] for ref in spec["dataflow"]["datasets"]]
    cached = cache_bucket_collections(page, datasets)
    assert sorted(cached) == sorted(d for d in datasets if d.startswith("data.sage.")), cached

    # Run All runs every node, each to Done.
    run_all_and_wait(page, timeout_ms=RUN_TIMEOUT_MS)
    for node in spec["dataflow"]["nodes"]:
        wait_for_node_done(page, node["id"], node_type=node["type"].split("/")[-1], timeout_ms=RUN_TIMEOUT_MS)
    _tiles_drew(page)
    _frames_read(page, W042_CAPTIONS)
    save_dataflow(page)

    # The owner's dashboard: the eight tiles, drawn from the saved outputs.
    _open_dashboard(page, app_frontend.base_url, project_id)
    tiles = page.locator(".react-flow__node")
    expect(tiles).to_have_count(len(TILES), timeout=45000)
    assert {tiles.nth(i).get_attribute("data-id") for i in range(len(TILES))} == TILES
    _tiles_drew(page)
    _frames_read(page, W042_CAPTIONS)
    park_pointer(page)
    save_workflow_test_screenshot(page, STEM, test_name="dashboard", sweep_toasts=True)
    page.goto("about:blank")

    # A visitor with no account picks W065: the tiles below Settings run again.
    hosted = _serve_hosted(app_frontend, current_server, monkeypatch)
    visitor = _Visitor(browser, current_server)
    try:
        visitor.opens(hosted, project_id)
        visitor.waits_for("the saved tiles", lambda: _tiles_drew(visitor.page))
        visitor.waits_for("W042's frames", lambda: _frames_read(visitor.page, W042_CAPTIONS))
        occupancy = visitor.page.evaluate(_CHART_PIXELS_JS, CHARTS[0])
        camera = _pick(visitor.page, SETTINGS, W065)
        expect(camera).to_be_enabled(timeout=20000)
        camera.check()
        visitor.waits_for("W065's frames", lambda: _frames_read(visitor.page, W065_CAPTIONS))
        visitor.waits_for_runs(1, timeout_ms=RUN_TIMEOUT_MS)
        visitor.waits_for("the tiles of W065", lambda: _tiles_drew(visitor.page))
        assert visitor.page.evaluate(_CHART_PIXELS_JS, CHARTS[0]) != occupancy, (
            "the occupancy chart did not draw W065's day" + visitor.story()
        )
        park_pointer(visitor.page)
        save_workflow_test_screenshot(visitor.page, STEM, test_name="visitor-w065", sweep_toasts=True)
    finally:
        visitor.close()
