"""Playwright E2E: the Street Vision example opens, resolves and runs (#233).

The report: the package nodes in the "Street-level computer vision" example sat
on "Loading node…" indefinitely, and "connections involving these nodes also
fail to render". Both symptoms had one cause: the example's lockfile did not
declare ``curio.streetvision``, so no layer could name the package the nodes
needed. The placeholder could not tell "the registry has not caught up" from
"nothing provides this", so it showed the first message forever; and because it
rendered no ``<Handle>`` children, React Flow had no port bounds to attach edges
to and dropped every edge touching one (``error008``).

The package needs only onnxruntime now, so opening the example installs it and
its nodes resolve. The placeholder is still what a node of a missing package
gets, so it is pinned on the same graph with the package swapped for one that
exists nowhere.

Route 1 is run for real: the committed Mapillary sample through DDRNet23-Slim,
the model that ships with Curio, with no network.

Run::

    CURIO_E2E_USE_EXISTING=1 pytest \
        utk_curio/backend/tests/test_frontend/test_streetvision_example_e2e.py -v
"""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import TYPE_CHECKING

import pytest

from .utils import (
    REPO_ROOT,
    VEGA_CANVAS_PROBE_JS,
    api_json,
    dismiss_toasts,
    node_locator,
    read_node_error_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_all_and_wait,
    run_node_and_wait,
    stub_login_and_enter_workflow,
    wait_for_node_settled,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

EXAMPLE = "10-street-vision-cv-analysis.json"
SEGMENTATION = "curio.streetvision/image-segmentation"
#: A package no catalog holds, so its nodes can only ever be placeholders.
MISSING_PACKAGE_TYPE = "curio.nowhere/image-segmentation"

PHOTOS = "5988175e-84aa-4964-84de-aba7d55cf122"
ROUTE_ONE = "4067fb98-3ed5-497a-97a5-41a98ce1085b"
ROUTE_ONE_VIEW = "5d2ac264-58a5-431d-83cd-d6785c6fd176"
SAMPLE_PHOTOS = 40
#: The three Vega-Lite charts: route one's map and bars, route two's bars.
CHARTS = (
    "8aaff248-9894-4ca8-b9a3-3b79216ce592",
    "1aa27f1a-5ed7-4872-a413-ce6fd1eb2c6b",
    "e5a27c3f-8d4b-4f16-a9e2-0b3c4d5e6f78",
)


def _example_spec() -> dict:
    path = os.path.join(REPO_ROOT, "docs", "examples", EXAMPLE)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _segmentation_ids(spec: dict) -> list[str]:
    return [n["id"] for n in spec["dataflow"]["nodes"] if n["type"] == SEGMENTATION]


def _open(page, app_frontend, current_server, spec: dict):
    require_project_page()
    require_user_auth()
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Street Vision Reader",
        username=f"sv_{uuid.uuid4().hex[:10]}",
        project_name="Street-level computer vision",
        project_spec=spec,
    )
    require_owner_view(page)
    page.wait_for_selector(".react-flow__node", timeout=45000)
    dismiss_toasts(page)
    page.curio_session = session
    return page


@pytest.fixture()
def street_vision_canvas(app_frontend: "FrontendPage", current_server, page):
    return _open(page, app_frontend, current_server, _example_spec())


@pytest.fixture()
def missing_package_canvas(app_frontend: "FrontendPage", current_server, page):
    spec = _example_spec()
    for node in spec["dataflow"]["nodes"]:
        if node["type"] == SEGMENTATION:
            node["type"] = MISSING_PACKAGE_TYPE
    spec["dataflow"]["packages"] = []
    return _open(page, app_frontend, current_server, spec)


def _wait_for_edges(page, expected: int) -> int:
    page.wait_for_function(
        "(n) => document.querySelectorAll('.react-flow__edge').length >= n",
        arg=expected,
        timeout=45000,
    )
    return page.locator(".react-flow__edge").count()


def test_the_example_declares_the_package_its_nodes_need():
    """The data half, asserted against the shipped file.

    An empty lockfile is what started the whole failure, and it is invisible in
    the UI - so it is worth pinning here beside the behaviour it caused.
    """
    spec = _example_spec()
    assert "curio.streetvision@1" in spec["dataflow"]["packages"], (
        "example 10 must declare the package its nodes reference, or nothing "
        "downstream can resolve them (#233)"
    )


def test_opening_the_example_installs_its_package(street_vision_canvas, current_server):
    page = street_vision_canvas
    token = page.curio_session["token"]
    deadline = time.monotonic() + 300
    names: set = set()
    while time.monotonic() < deadline:
        installed = api_json(f"{current_server}/api/packages", token) or {}
        names = {p.get("dirName") for p in installed.get("packages", [])}
        if "curio.streetvision@1" in names:
            break
        page.wait_for_timeout(2000)
    assert "curio.streetvision@1" in names, (
        f"opening example 10 did not install the package it declares: {sorted(names)}"
    )

    node_ids = _segmentation_ids(_example_spec())
    assert len(node_ids) == 2, "the example should carry two Image Segmentation nodes"
    for node_id in node_ids:
        node = node_locator(page, node_id)
        node.wait_for(state="visible", timeout=45000)
        node.locator("[data-curio-node-output]").wait_for(state="visible", timeout=120000)
        assert node.locator('[data-testid="unresolved-node"]').count() == 0
    assert page.get_by_text("Loading node…").count() == 0


def test_every_edge_renders(street_vision_canvas):
    """The missing-connections half, on the example as shipped."""
    expected = len(_example_spec()["dataflow"]["edges"])
    rendered = _wait_for_edges(street_vision_canvas, expected)
    assert rendered >= expected, f"only {rendered} of {expected} edges rendered (#233)"


def test_a_missing_package_says_so_and_keeps_its_edges(missing_package_canvas):
    page = missing_package_canvas
    node_ids = _segmentation_ids(_example_spec())
    for node_id in node_ids:
        node = node_locator(page, node_id)
        node.wait_for(state="visible", timeout=45000)
        # `Loading node…` is the right message only while the registry might
        # still deliver. It never will here, and the card has to say so.
        node.locator('[data-testid="unresolved-node"]').wait_for(
            state="visible", timeout=45000
        )
        assert node.get_by_text("Missing node package").count() > 0
        assert node.get_by_text("Nowhere", exact=False).count() > 0
    assert page.get_by_text("Loading node…").count() == 0, (
        "a node is still on the indefinite placeholder (#233)"
    )

    # The edges were in React Flow's state the whole time; they had nowhere
    # to attach, because the placeholder rendered no handles.
    expected = len(_example_spec()["dataflow"]["edges"])
    rendered = _wait_for_edges(page, expected)
    assert rendered >= expected, (
        f"only {rendered} of {expected} edges rendered - the nodes without "
        f"descriptors are probably not emitting handles again (#233)"
    )


def test_route_one_segments_the_sample_with_the_shipped_model(street_vision_canvas):
    page = street_vision_canvas
    node_locator(page, ROUTE_ONE).locator("[data-curio-node-output]").wait_for(
        state="visible", timeout=300000
    )
    run_node_and_wait(page, PHOTOS, node_type="data-loading", timeout_ms=180000)
    text = run_node_and_wait(page, ROUTE_ONE, node_type="image-segmentation",
                             timeout_ms=180000)
    assert "Saved to file" in text, f"Image Segmentation did not finish: {text!r}"

    # One card per photo, each with the photo and its overlay. An overlay the
    # backend cannot serve holds an empty slot instead of an <img>.
    view = node_locator(page, ROUTE_ONE_VIEW)
    cards = view.locator(f'[id^="imageBox_content_{ROUTE_ONE_VIEW}_"]')
    cards.first.wait_for(state="visible", timeout=60000)
    assert cards.count() == SAMPLE_PHOTOS
    page.wait_for_function(
        "([id, n]) => document.querySelectorAll(`[id^='imageBox_content_${id}_'] img`).length >= n",
        arg=[ROUTE_ONE_VIEW, 2 * SAMPLE_PHOTOS],
        timeout=90000,
    )
    # The results lead each row, so they are what the caption shows.
    caption = view.inner_text() or ""
    assert "dominant_class:" in caption and "vegetation_pct:" in caption, caption[:400]


# Every toast the page shows, from a MutationObserver on the toast region, as
# test_computed_json_output_e2e.py records them: a toast is gone 5 s later.
_TOAST_RECORDER_JS = r"""() => {
    if (window.__curioToastLog) return "already";
    const region = document.querySelector('[aria-label="Notifications"]');
    if (!region) return "no toast region";
    window.__curioToastLog = [];
    const record = () => {
        region.querySelectorAll('.toast').forEach((t) => {
            const text = (t.textContent || '').trim();
            if (text && !window.__curioToastLog.includes(text)) window.__curioToastLog.push(text);
        });
    };
    new MutationObserver(record).observe(region, { childList: true, subtree: true });
    record();
    return "ok";
}"""


def test_run_all_draws_every_chart_without_an_empty_render(street_vision_canvas):
    """Run All over the whole example: every chart draws, and none says 0 rows.

    The report: on dev, after a Run All, a chart said "rendered nothing: 0 rows
    arrived at this node" while the photos and a chart were on screen. Played
    node by node, as the workflow suite plays it, each chart compiles after
    its Spatial Join has answered; Run All moves on by levels.
    """
    page = street_vision_canvas
    for node_id in _segmentation_ids(_example_spec()):
        node_locator(page, node_id).locator("[data-curio-node-output]").wait_for(
            state="visible", timeout=300000
        )
    page.wait_for_selector('[aria-label="Notifications"]', state="attached", timeout=20000)
    assert page.evaluate(_TOAST_RECORDER_JS) in ("ok", "already")

    run_all_and_wait(page, timeout_ms=600000)
    # A chart whose rows land after the run still redraws; give it the time.
    page.wait_for_timeout(5000)

    charts = {}
    for chart in CHARTS:
        status = wait_for_node_settled(page, chart, node_type="VIS_VEGA", timeout_ms=120000)
        probe = page.evaluate(VEGA_CANVAS_PROBE_JS, f"vega{chart}") or {}
        charts[chart] = {
            "status": status,
            "drew": bool(probe.get("nonBlank")),
            "error": (read_node_error_text(node_locator(page, chart)) or "") if status == "error" else "",
        }
    toasts = page.evaluate("() => window.__curioToastLog || []")
    empty_renders = [t for t in toasts if "rendered nothing" in t]

    expected = {chart: {"status": "done", "drew": True, "error": ""} for chart in CHARTS}
    assert (charts, empty_renders) == (expected, []), json.dumps(
        {"charts": charts, "empty-render toasts": empty_renders, "all toasts": toasts}, indent=2
    )
