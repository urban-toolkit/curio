"""Record a narrated screencast of Curio's features in the e2e Chromium.

This is not a regression test. It reuses the e2e harness because that harness
already knows how to boot the whole stack (``curio_servers``), how to launch the
browser the AUTK/WebGPU nodes need (``browser_type_launch_args`` points at the
system Chrome), and how to drive the canvas without fighting React Flow. What it
produces is a video, not an assertion.

It is skipped unless ``CURIO_TOUR=1``, so a normal ``pytest test_frontend/`` run
never spends ten minutes recording.

Run::

    # from utk_curio/backend, with PYTHONPATH=<repo root>
    CURIO_TOUR=1 pytest tests/test_frontend/test_feature_tour_video.py -s --headed

Environment:

===========================  ==================================================
``CURIO_TOUR=1``             required; otherwise the module skips
``CURIO_TOUR_SCENES``        comma-separated scene ids to record (default: all)
``CURIO_TOUR_OUT``           output directory (default ``.curio/tour/``)
``CURIO_TOUR_SPEED``         pacing multiplier, >1 is faster (default 1.0)
===========================  ==================================================

Scene ids, in order: see ``SCENES`` at the bottom of this file.

The AI provider:

The ``aisettings`` scene types a base URL, an API key and a model into AI
Settings on camera, and ``agentrun`` then asks a real question of that endpoint.
Curio ships no provider of its own, and the account the tour signs up starts
with none, so this is not decoration: without it every agent surface refuses to
run.

The endpoint and model default to the constants below; **the key is never one of
them**. It is read from ``.curio/tour-provider.json`` (``.curio/`` is
gitignored) or ``CURIO_TOUR_LLM_API_KEY``, so recording the tour never requires
a credential in the repository::

    {"baseUrl": "https://…/", "model": "…", "apiKey": "sk-…"}

With no key the two scenes that need a live provider show their surface, say so
in a caption and skip the call - a recording of an agent erroring is worse than
one that admits it is unconfigured.

A scene that raises is reported and the tour carries on to the next one, so a
single broken step still yields a usable video. The test then fails at the end
with the list of scenes that broke - the recording is a deliverable either way,
but a silently truncated tour is not. ``agentrun`` is the one scene that talks
to a remote model, so it is also the one most likely to be the scene that broke.
"""
from __future__ import annotations

import json
import os
import re
import sys
import traceback
from dataclasses import dataclass, field
from typing import Callable

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect

from .tour import REPO_ROOT, VIDEO_SIZE, Tour, finalize_video, out_dir, speed
from .utils import (
    accept_confirm_dialog,
    CANVAS_DROP_TARGET,
    _DRAG_TO_CANVAS_JS,
    activate_header_icon,
    canvas_nodes,
    close_tools_palette,
    connect_nodes,
    dismiss_toasts,
    drag_to_canvas,
    node_locator,
    open_tools_palette,
    run_node_and_wait,
    set_node_code,
    stub_db_login,
    wait_for_projects_page,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("CURIO_TOUR") != "1",
    reason="feature-tour recording only runs with CURIO_TOUR=1",
)

# ---------------------------------------------------------------------------
# Fixtures for the tour: content the scenes lean on
# ---------------------------------------------------------------------------

USER_NAME = "Ada Urbanist"
USER_LOGIN = "ada_urbanist"
USER_PASSWORD = "curio-tour-2026"

# The CSV hub dataset the authoring e2e tests use: three rows, two numeric
# columns, and a generated loader that only needs pandas - so the "run it" beat
# is a couple of seconds rather than a geopandas import.
DATASET_ID = "data.urbanlab.acs-neighborhood-profile"
DATASET_TITLE = "ACS Neighborhood Profile"

# The only package a tour may install: it declares no python dependencies, so
# nothing shells out to pip mid-recording.
PKG_DIR = "curio.example-ui@1"
PKG_NAME = "Example: Custom UI Node"

DRAWER_DATA = '[data-curio-dataset-catalog-drawer="true"]'
DRAWER_NODES = '[data-curio-node-catalog-drawer="true"]'
DRAWER_AGENTS = '[data-curio-agent-catalog-drawer="true"]'
CARD = 'article:not([role="status"])'

# ---------------------------------------------------------------------------
# The AI provider the tour configures on camera
# ---------------------------------------------------------------------------
#
# Typed into AI Settings by ``scene_aisettings`` rather than pre-set with the
# launcher's --llm-* flags, because configuring a provider through the interface
# is one of the things the video exists to show. The account the tour signs up
# starts with nothing, which is also why the panel's "No default is configured
# on this deployment" copy is on screen to be read.
#
# The key renders as dots: the field is type="password" (AiSettingsModal.tsx).
#
# The endpoint and model are not secret and stay here so a checkout records
# against the same provider by default. The key is not: it is read from
# ``.curio/tour-provider.json`` (``.curio/`` is gitignored) or
# ``CURIO_TOUR_LLM_API_KEY``, so it never becomes a committed credential. With
# no key, the scenes that need a live provider say so on camera and skip their
# live half rather than recording an agent that visibly errors.
PROVIDER_FILE = os.path.join(REPO_ROOT, ".curio", "tour-provider.json")

_DEFAULT_BASE_URL = "https://sage200.evl.uic.edu/"
_DEFAULT_MODEL = "gemma4"

# Agents the tour adds to the dataflow. The order matters on screen:
#   node-explainer   attaches to a node and is the one that answers live;
#   connection-builder is the only built-in that accepts a connection target,
#                    which is the gesture this branch added;
#   dataflow-builder is the only built-in declaring requiresAgents, so its
#                    button reads "Add to project (+1 required)".
AGENT_EXPLAINER = "agent.node-explainer@1.0.0"
AGENT_CONNECTION = "agent.connection-builder@1.0.0"
AGENT_BUILDER = "agent.dataflow-builder@1.0.0"

AGENT_SEARCH_PLACEHOLDER = "Search agents, publishers, tags…"

# What the dataflow is for, in the words a user would use. Persisted into the
# spec as ``dataflow.task`` and composed into every agent's prompt.
DATAFLOW_GOAL = (
    "Compare income per capita across neighborhoods and flag the outliers."
)

TRANSFORM_TILE = "#step-transformation"
LOADER_TYPE = "curio.builtin/data-loading"
TRANSFORM_TYPE = "curio.builtin/data-transformation"

POS_LOADER = (150, 150)
POS_TRANSFORM = (760, 150)

TRANSFORM_CODE = (
    "df = arg\n"
    'df["income_per_capita"] = (df["median_income"] / df["population"]).round(2)\n'
    'print(df.sort_values("median_income", ascending=False).to_string(index=False))\n'
    "return df\n"
)

EXAMPLE_LINKED = os.path.join(
    REPO_ROOT, "docs", "examples", "03-vega-lite-linked-temporal-charts.json",
)
EXAMPLE_INTERACTION = os.path.join(
    REPO_ROOT, "docs", "examples", "dataflows", "Interaction_Vega_Simple.json",
)
EXAMPLE_AUTARK = os.path.join(
    REPO_ROOT, "docs", "examples", "11-autark-pbf-loading.json",
)


def _log(message: str) -> None:
    """Print without letting the console's codec fail the run.

    The menu labels carry ``⏷``, so a Playwright timeout message quoting one
    lands in a traceback that a cp1252 stdout cannot encode - and the resulting
    UnicodeEncodeError would replace the real failure.
    """
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    # flush: a tour run is long, and redirected stdout would otherwise hold the
    # scene log until the process exits.
    print(
        message.encode(encoding, "replace").decode(encoding, "replace"),
        flush=True,
    )


def _load_provider() -> tuple[str, str, str]:
    """``(baseUrl, model, apiKey)`` from the local file, env, then defaults."""
    data: dict = {}
    try:
        with open(PROVIDER_FILE, encoding="utf-8") as handle:
            data = json.load(handle) or {}
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as exc:
        _log(f"[tour] ignoring unreadable {PROVIDER_FILE}: {exc}")
    return (
        str(data.get("baseUrl") or os.environ.get("CURIO_TOUR_LLM_BASE_URL") or _DEFAULT_BASE_URL),
        str(data.get("model") or os.environ.get("CURIO_TOUR_LLM_MODEL") or _DEFAULT_MODEL),
        str(data.get("apiKey") or os.environ.get("CURIO_TOUR_LLM_API_KEY") or ""),
    )


LLM_BASE_URL, LLM_MODEL, LLM_API_KEY = _load_provider()


@dataclass
class Ctx:
    """Everything a scene needs, threaded through the scene registry."""

    page: object
    tour: Tour
    frontend: str
    backend: str
    state: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Shared beats
# ---------------------------------------------------------------------------


def _fit_view(page, padding: float = 0.22) -> None:
    """Frame the whole graph, the same way the screenshot helper does."""
    page.evaluate(
        """(padding) => {
            const fit = window.__curio_fitViewWithMenuOffset;
            if (typeof fit === 'function') {
                fit({ padding, duration: 600, includeHiddenNodes: true });
            }
        }""",
        padding,
    )
    page.wait_for_timeout(900)


def _reset_zoom(page) -> None:
    """Put the pane back to zoom 1 before dropping nodes.

    ``drag_to_canvas`` positions drops in screen pixels, so the canvas-space gap
    between two drops depends on the current zoom. The node geometry the offsets
    were chosen for (525x350, ~610px apart) only holds at zoom 1.
    """
    page.evaluate(
        """() => {
            const rf = window.__curio_reactFlow;
            if (!rf) return;
            const vp = rf.getViewport();
            if (Math.abs(vp.zoom - 1) < 0.01) return;
            rf.setViewport({ x: vp.x, y: vp.y, zoom: 1 }, { duration: 300 });
        }"""
    )
    page.wait_for_timeout(400)


def _menu(page, label: str):
    """Top-bar dropdown trigger (``File ⏷``, ``View ⏷``, ...)."""
    return page.get_by_role("button", name=f"{label} ⏷", exact=True)


def _load_example(ctx: Ctx, path: str, *, expected_nodes: int) -> None:
    """File > Load dataflow, on camera.

    Deliberately not ``utils.upload_workflow``: that helper hides the left tool
    rail so it cannot drift into a screenshot baseline, which is exactly the
    chrome a viewer needs to see here.
    """
    page, tour = ctx.page, ctx.tour
    tour.click(_menu(page, "File"), force=True)
    load = page.get_by_role("button", name="Load dataflow", exact=True)
    load.wait_for(state="visible", timeout=15000)
    tour.focus(load, hold=500)
    with page.expect_file_chooser() as chooser:
        # See utils.upload_workflow: get_by_text matches the menu row and the
        # button inside it, which is a strict-mode violation.
        load.click()
    chooser.value.set_files(path)
    page.wait_for_function(
        "(n) => document.querySelectorAll('.react-flow__node').length >= n",
        arg=expected_nodes,
        timeout=90000,
    )
    tour.beat(900)
    _fit_view(page)


def _new_dataflow_from_menu(ctx: Ctx) -> None:
    """File > New dataflow, accepting the unsaved-changes guard."""
    page, tour = ctx.page, ctx.tour
    tour.click(_menu(page, "File"), force=True)
    tour.click(page.get_by_role("button", name="New dataflow", exact=True))
    page.wait_for_url("**/dataflow/new", timeout=20000)
    page.wait_for_timeout(1200)


def _play_all(ctx: Ctx, *, timeout_ms: int = 240000) -> None:
    """Press the rail's Run-all button and wait for every node to settle.

    The button sits at the foot of the left rail, under three catalog dropdowns,
    and the rail does not scroll. If the frame is ever too short for all of it,
    a real click fails with "Element is outside of the viewport" and takes the
    whole scene with it. The recording frame is sized to fit (``VIDEO_SIZE``),
    but fall back to a dispatched click rather than lose the scene if the rail
    grows again - the same synthetic-event route ``utils.play_node`` already
    uses for the per-node play buttons.
    """
    page, tour = ctx.page, ctx.tour
    button = page.locator('#tools-menu button[title="Run all nodes"]')
    try:
        tour.click(button, force=True, hold=400)
    except PlaywrightError as exc:
        if "outside of the viewport" not in str(exc):
            raise
        _log(
            "[tour] Run-all is below the fold; dispatching the click instead. "
            "The left rail is taller than the frame."
        )
        tour.click(button, dispatch=True, hold=400)
    page.wait_for_function(
        """() => {
            const nodes = [...document.querySelectorAll('.react-flow__node')];
            if (!nodes.length) return false;
            return nodes.every((n) => {
                const el = n.querySelector('[data-curio-node-status]');
                if (!el) return false;
                const s = el.getAttribute('data-curio-node-status');
                return s === 'done' || s === 'error';
            });
        }""",
        timeout=timeout_ms,
    )
    page.wait_for_timeout(1500)


def _node_ids_by_type(page, node_type: str) -> list[str]:
    fragment = node_type.rsplit("/", 1)[-1]
    return [
        n["id"] for n in canvas_nodes(page)
        if fragment in (n["nodeType"] or "")
    ]


def _center_on(page, node_id: str, *, zoom: float = 0.9) -> None:
    """Pan the canvas so one node fills the frame."""
    page.evaluate(
        """({ nodeId, zoom }) => {
            const rf = window.__curio_reactFlow;
            if (!rf) return;
            const node = rf.getNodes().find((n) => n.id === nodeId);
            if (!node) return;
            const w = node.width || node.measured?.width || 525;
            const h = node.height || node.measured?.height || 350;
            rf.setCenter(node.position.x + w / 2, node.position.y + h / 2, {
                zoom, duration: 700,
            });
        }""",
        {"nodeId": node_id, "zoom": zoom},
    )
    page.wait_for_timeout(1000)


def _close_data_drawer(page) -> None:
    page.locator(DRAWER_DATA).locator("header").get_by_role(
        "button", name="Close Data Catalog drawer"
    ).click()
    expect(page.locator(DRAWER_DATA)).to_have_count(0, timeout=8000)


#: AI Settings inputs, by the id their label points at. The panel's fields grew
#: real ``htmlFor``/``id`` pairs when the model dropdown landed, so these are
#: stable accessible controls rather than "the input after this text".
_AI_FIELDS = {
    "Base URL": "#ai-settings-base-url",
    "API Key": "#ai-settings-api-key",
    "Model": "#ai-settings-model",
    "HuggingFace token": "#ai-settings-hf-token",
}


def _ai_field(page, label: str):
    return page.locator(_AI_FIELDS[label])


def _open_ai_settings(ctx: Ctx) -> None:
    """Open AI Settings from whichever entry point this page has.

    Two exist, and which one is available depends on where the tour is: the
    header button lives in ``GlobalPageHeader``, which renders on /projects and
    /catalog/* but *not* on the canvas, where the Agent Catalog drawer's cog is
    the only route (``docs/AGENT-CATALOG.md`` §5).

    Handling both is what lets ``aisettings`` be re-recorded alongside the canvas
    scenes: ``CURIO_TOUR_SCENES`` picks one landing page for the whole subset, so
    a scene that only knew the header could never share a run with them.
    """
    page, tour = ctx.page, ctx.tour
    header_button = page.get_by_role("button", name="AI Settings", exact=True)
    if header_button.count():
        tour.click(header_button.first)
    else:
        drawer = _open_agent_drawer(ctx)
        tour.say(
            "On the canvas, the Agent Catalog holds the way in",
            "The provider is an account setting, so it sits with the agents it answers.",
            hold=2600,
        )
        tour.click(drawer.get_by_role("button", name=re.compile("AI Settings")).first)
    expect(
        page.get_by_role("heading", name="AI Settings", level=2)
    ).to_be_visible(timeout=15000)


# ---------------------------------------------------------------------------
# Agent beats
# ---------------------------------------------------------------------------


def _open_agent_drawer(ctx: Ctx):
    """Data > Agent Catalog, returning the drawer dialog.

    ``exact=True`` on the menu row is load-bearing: the left rail's palette
    trigger is also named "Agent Catalog", so a substring match is ambiguous
    and Playwright's strict mode fails the scene.
    """
    page, tour = ctx.page, ctx.tour
    tour.click(_menu(page, "Data"), force=True)
    tour.click(page.get_by_role("button", name="Agent Catalog", exact=True))
    root = page.locator(DRAWER_AGENTS)
    root.wait_for(state="attached", timeout=15000)
    # Readiness is aria-hidden, not visibility: until the rAF flips it, every
    # role query inside the subtree returns zero matches.
    expect(root).to_have_attribute("aria-hidden", "false", timeout=10000)
    drawer = page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name="Agent Catalog", exact=True)
    )
    expect(drawer).to_be_visible(timeout=10000)
    return drawer


def _agent_card(drawer, coord: str):
    return drawer.locator(f'article[data-agent-coord="{coord}"]')


def _add_agent(ctx: Ctx, drawer, coord: str, *, hold: float = 1200):
    """Click a card's Add to project and wait for the install to land.

    The button label varies - an agent declaring ``requiresAgents`` reads
    "Add to project (+1 required)" - so it is matched by prefix and the
    confirmation is the flip to "Remove from project" rather than the label.
    """
    page, tour = ctx.page, ctx.tour
    card = _agent_card(drawer, coord)
    expect(card).to_have_count(1, timeout=20000)
    card.scroll_into_view_if_needed()
    tour.focus(card, hold=hold)
    add = card.get_by_role("button", name=re.compile(r"^Add to project"))
    tour.click(add)
    with page.expect_response(
        lambda r: "/api/agents/projects/" in r.url
        and r.url.endswith("/install")
        and r.request.method == "POST" and r.ok,
        timeout=60000,
    ):
        # Adding confirms first now (#196), listing any required agents.
        accept_confirm_dialog(
            page, title=re.compile(r"^Add "), button="Add to project"
        )
    expect(
        card.get_by_role("button", name="Remove from project", exact=True)
    ).to_be_visible(timeout=25000)
    return card


def _agent_row(page, coord: str):
    """A row in the left-rail Agent palette - the thing you drag to attach."""
    return page.locator(f'#agents-palette [data-agent-coord="{coord}"]')


def _drag_agent_to(ctx: Ctx, coord: str, point) -> None:
    """Drag an agent palette row onto a point and dispatch the drop.

    Reuses the e2e suite's HTML5 drag payload rather than Playwright's
    ``drag_to()``, which is unreliable against native drags. The drop is always
    dispatched on the canvas pane, because that is where ``handleDrop`` lives;
    what decides node vs connection vs canvas is the *coordinate*, hit-tested by
    ``pickNodeAtPoint`` (flow space) and then ``pickEdgeAtPoint``
    (``elementFromPoint``, screen space) in ``MainCanvas.handleDrop``.

    *point* may be an ``(x, y)`` pair or a zero-argument callable returning one.
    Pass a callable for anything whose position depends on the current layout:
    this helper spends over a second on cursor choreography and scrolls the
    palette row into view before it drops, and a coordinate measured before all
    that can be stale by the time it is used - which does not raise, it just
    resolves to a different target and attaches the agent somewhere else.

    Deliberately not ``drag_to_canvas``: that helper asserts a new node appeared,
    and an agent drop creates an attachment rather than a node.
    """
    page, tour = ctx.page, ctx.tour
    row = _agent_row(page, coord)
    row.wait_for(state="visible", timeout=20000)
    row.scroll_into_view_if_needed()
    # Show the viewer where the drag is going before it happens; the synthetic
    # cursor is the only pointer in the frame.
    tour.focus(row, hold=700)
    resolved = point() if callable(point) else point
    assert resolved, "no drop point resolved for the agent drag"
    client_x, client_y = resolved
    tour.point_at(client_x, client_y, hold=520)
    result = page.evaluate(
        _DRAG_TO_CANVAS_JS,
        {
            "source": row.element_handle(),
            "targetSelector": CANVAS_DROP_TARGET,
            "clientX": client_x,
            "clientY": client_y,
        },
    )
    assert result == "ok", f"agent drag failed: {result}"


def _expect_attach_toast(ctx: Ctx, where: str) -> None:
    """Wait for an attach toast and assert it names *where*.

    Which toast appears is exactly what distinguishes the three drop targets, so
    it is the assertion worth making. Matching any of them first - rather than
    only the expected one - turns "the drop silently resolved to the canvas"
    into a message that says so, instead of a timeout that looks identical to
    the feature being broken.

    The three attaches happen within a few seconds of each other and a toast
    outlives that, so the region is swept afterwards. Without it the second
    assertion reads the *first* attach's toast and reports the wrong target -
    which is indistinguishable from the drop having genuinely hit the wrong
    thing, and sent me looking at React Flow geometry that turned out to be
    correct all along.
    """
    page, tour = ctx.page, ctx.tour
    # Read the notifications region rather than matching the success wording.
    # The failure path is showToast(e?.message || "Attach failed.") in
    # MainCanvas.handleDrop, so a rejected attach carries the *server's*
    # message - which no pattern written from the happy path will match, and
    # the assertion then dies of a 45s timeout that says nothing.
    toast = page.locator('[aria-label="Notifications"] .toast').first
    toast.wait_for(state="visible", timeout=45000)
    actual = " ".join((toast.text_content() or "").split())
    assert f"attached to {where}." in actual, (
        f"expected an attach to {where}, but the app said: {actual!r}"
    )
    # Hold it long enough to read before clearing it.
    tour.beat(1100)
    dismiss_toasts(page)


def _node_client_point(page, node_id: str) -> tuple[float, float]:
    """The centre of a node in viewport coordinates."""
    box = node_locator(page, node_id).bounding_box()
    assert box, f"node {node_id} has no layout box"
    return (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)


def _empty_canvas_point(page) -> tuple[float, float] | None:
    """A visibly empty spot on the pane, in viewport coordinates.

    "Empty" has to mean empty to the viewer as well as to ``handleDrop``. A
    point under the open agent palette would still attach to the canvas - the
    palette is not a node and not an edge, so both hit-tests miss and the drop
    falls through to the canvas branch - but on camera it would read as dropping
    the agent onto the palette it came from. So this rejects any candidate whose
    topmost element is not the React Flow pane itself.
    """
    point = page.evaluate(
        """() => {
            const pane = document.querySelector('.curio-canvas-drop-target');
            if (!pane) return null;
            const box = pane.getBoundingClientRect();
            // Lower half, right of the rail, working inwards from the corner.
            const xs = [0.62, 0.72, 0.52, 0.82];
            const ys = [0.82, 0.74, 0.88, 0.66];
            for (const fy of ys) {
                for (const fx of xs) {
                    const x = box.left + box.width * fx;
                    const y = box.top + box.height * fy;
                    const hit = document.elementFromPoint(x, y);
                    if (!hit || !hit.closest) continue;
                    if (hit.closest('.react-flow__node')) continue;
                    if (hit.closest('.react-flow__edge')) continue;
                    // The pane, its background layer or the selection layer -
                    // anything still inside the flow and not on top of it.
                    if (!hit.closest('.react-flow')) continue;
                    return [x, y];
                }
            }
            return null;
        }"""
    )
    if not point:
        return None
    return (point[0], point[1])


def _edge_client_point(page) -> tuple[float, float] | None:
    """A point that ``pickEdgeAtPoint`` will actually resolve to an edge.

    React Flow draws a wide invisible ``.react-flow__edge-interaction`` path
    under every edge precisely so a pointer can land on a curve, and
    ``pickEdgeAtPoint`` hit-tests it with ``elementFromPoint``
    (``agentCatalogEvents.ts``). Two things make the obvious "take the midpoint"
    version wrong:

    * a bezier's bounding-box centre is usually empty space, so the point has to
      come from ``getPointAtLength`` on the path itself; and
    * the open agent palette is a ~545px strip floating *over* the left of the
      canvas, so a point that is geometrically on the edge can still be occluded
      - and ``elementFromPoint`` would return the palette, which resolves to no
      edge and silently attaches to the canvas instead.

    So this samples along the curve and returns the first point that
    ``elementFromPoint`` resolves to an edge, which is the same question the drop
    handler asks. ``None`` means no such point exists right now, and the caller
    skips the beat rather than recording a mislabelled one.
    """
    point = page.evaluate(
        """() => {
            const path = document.querySelector(
                '.react-flow__edge .react-flow__edge-interaction'
            ) || document.querySelector('.react-flow__edge path');
            if (!path || !path.getPointAtLength) return null;
            const total = path.getTotalLength();
            if (!total) return null;
            const svg = path.ownerSVGElement;
            const ctm = path.getScreenCTM();
            const rf = window.__curio_reactFlow;
            if (!svg || !ctm || !rf) return null;

            const toFlow = (x, y) => (
                rf.screenToFlowPosition
                    ? rf.screenToFlowPosition({ x, y })
                    : rf.project({ x, y })
            );
            // handleDrop's precedence, restated: pickNodeAtPoint runs first and
            // a hit there wins, so a point that is visually on the curve still
            // attaches to a NODE if it falls inside that node's box. React
            // Flow's boxes are generous - a node is 525x350 - and the bezier
            // dips back over them near its ends.
            const nodes = rf.getNodes();
            const insideANode = (flow) => nodes.some((n) => {
                const o = n.positionAbsolute ?? n.position;
                if (!o) return false;
                const w = n.width ?? 0;
                const h = n.height ?? 0;
                return flow.x >= o.x && flow.x <= o.x + w
                    && flow.y >= o.y && flow.y <= o.y + h;
            });

            // Walk outwards from the midpoint, which is the part of the curve
            // furthest from both node bodies.
            const fractions = [
                0.5, 0.48, 0.52, 0.45, 0.55, 0.42, 0.58, 0.4, 0.6, 0.35, 0.65,
            ];
            for (const f of fractions) {
                const at = path.getPointAtLength(total * f);
                const pt = svg.createSVGPoint();
                pt.x = at.x;
                pt.y = at.y;
                const screen = pt.matrixTransform(ctm);
                const hit = document.elementFromPoint(screen.x, screen.y);
                if (!hit || !hit.closest) continue;
                // Occluded (the palette strip floats over the pane), so
                // pickEdgeAtPoint would miss it.
                if (!hit.closest('.react-flow__edge')) continue;
                // Inside a node's box, so pickNodeAtPoint would claim it first.
                if (insideANode(toFlow(screen.x, screen.y))) continue;
                return { point: [screen.x, screen.y] };
            }
            // Nothing qualified. Hand back what was measured so the caller can
            // say why rather than just skipping the beat.
            const mid = path.getPointAtLength(total / 2);
            const mpt = svg.createSVGPoint();
            mpt.x = mid.x;
            mpt.y = mid.y;
            const mscreen = mpt.matrixTransform(ctm);
            const hit = document.elementFromPoint(mscreen.x, mscreen.y);
            return { why: {
                midScreen: [Math.round(mscreen.x), Math.round(mscreen.y)],
                midFlow: toFlow(mscreen.x, mscreen.y),
                topmost: hit ? (hit.className && hit.className.baseVal !== undefined
                    ? hit.className.baseVal : String(hit.className || hit.tagName)) : null,
                nodes: nodes.map((n) => {
                    const o = n.positionAbsolute ?? n.position;
                    return { id: n.id, x: o && o.x, y: o && o.y,
                             w: n.width, h: n.height };
                }),
            } };
        }"""
    )
    if not point:
        return None
    if point.get("point"):
        found = point["point"]
        return (found[0], found[1])
    _log(f"[tour] no usable point on the edge: {point.get('why')}")
    return None


# ---------------------------------------------------------------------------
# Scenes
# ---------------------------------------------------------------------------


def scene_intro(ctx: Ctx) -> None:
    page, tour = ctx.page, ctx.tour
    page.goto(f"{ctx.frontend}/auth/signin")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(1200)
    tour.chapter(
        "urban toolkit",
        "Curio",
        "A dataflow framework for collaborative urban visual analytics: "
        "code, grammars and GUI in one provenance-aware canvas.",
        hold=4200,
    )
    tour.say(
        "Everything in this tour runs locally",
        "Backend, sandbox and frontend, driven through a real browser.",
        hold=2600,
    )
    tour.hush()


def scene_signup(ctx: Ctx) -> None:
    page, tour = ctx.page, ctx.tour
    tour.chapter("01", "Accounts and projects", "Sign up, then organise your work.")
    page.goto(f"{ctx.frontend}/auth/signup")
    page.wait_for_load_state("domcontentloaded")
    page.get_by_text("Create an account").wait_for(timeout=30000)
    tour.say(
        "Curio is multi-user",
        "Every dataflow, dataset and installed package is scoped to an account.",
        hold=2400,
    )
    tour.type_into(page.get_by_label("Name", exact=True), USER_NAME)
    tour.type_into(page.get_by_label("Username"), USER_LOGIN)
    tour.type_into(page.get_by_label("Password", exact=True), USER_PASSWORD, delay=35)
    tour.type_into(page.get_by_label("Confirm Password"), USER_PASSWORD, delay=35)
    tour.hush()
    tour.click(page.get_by_role("button", name="Create account"))
    page.wait_for_url("**/projects", timeout=40000)
    wait_for_projects_page(page, timeout=15000)
    tour.beat(1200)


def scene_projects(ctx: Ctx) -> None:
    page, tour = ctx.page, ctx.tour
    tour.say(
        "The projects workspace",
        "Dataflows as cards, with search, filters and a grid or list view.",
        hold=2600,
    )
    tour.focus(page.get_by_placeholder("Search projects…"), hold=900)
    tour.focus(page.get_by_role("button", name="List", exact=True), hold=500)
    tour.click(page.get_by_role("button", name="List", exact=True))
    tour.click(page.get_by_role("button", name="Grid", exact=True))
    tour.say(
        "Bring a notebook with you",
        "Import a Jupyter notebook and Curio converts its cells into a dataflow.",
        hold=2400,
    )
    tour.focus(page.get_by_role("button", name="Import Jupyter notebook"), hold=1200)
    tour.hush()


def scene_ai_settings(ctx: Ctx) -> None:
    """Configure the AI provider, for real, before anything needs it.

    Placed before the canvas because the account the tour just signed up has no
    provider, and ``resolve_provider_config`` refuses every agent surface until
    one is set. Doing it here also means the panel's "No default is configured
    on this deployment" copy is true and on screen.
    """
    page, tour = ctx.page, ctx.tour
    tour.chapter(
        "02", "AI Settings",
        "One provider answers every AI surface in Curio.",
    )
    if not LLM_API_KEY:
        _log(
            "[tour] no provider key configured; recording the panel without "
            f"filling it in. Put one in {PROVIDER_FILE} or "
            "CURIO_TOUR_LLM_API_KEY to record the agent scenes for real."
        )
        _open_ai_settings(ctx)
        tour.say(
            "Point Curio at a provider",
            "OpenAI, Anthropic, Gemini, or any OpenAI-compatible endpoint.",
            hold=3000,
        )
        tour.hush()
        tour.click(page.get_by_role("button", name="Cancel", exact=True))
        return

    _open_ai_settings(ctx)
    tour.say(
        "Per-account, not per-dataflow",
        "The agents, the node-authoring assistants and chat all use this one.",
        hold=2600,
    )

    # Custom is the only tab that renders Base URL; it saves as the
    # openai_compatible provider kind.
    tour.click(page.get_by_role("button", name="Custom", exact=True))
    tour.say(
        "Any OpenAI-compatible endpoint",
        "Ollama, LM Studio, vLLM, Groq, Azure - or a lab's own inference server.",
        hold=2600,
    )

    tour.type_into(_ai_field(page, "Base URL"), LLM_BASE_URL, delay=42)

    # type="password", so the recording shows dots rather than the secret.
    tour.type_into(_ai_field(page, "API Key"), LLM_API_KEY, delay=42)
    tour.say("Keys are stored per account", "Never returned to the browser once saved.", hold=2000)

    # Ask the endpoint what it serves rather than typing a name from memory -
    # a model the endpoint does not have surfaces much later as a failed agent
    # run, not as a wrong value in this box.
    tour.say(
        "Ask the endpoint what it serves",
        "Curio queries the base URL above and offers what comes back.",
        hold=2800,
    )
    fetch = page.get_by_role("button", name=re.compile(r"^(Fetch|Refresh) models"))
    with page.expect_response(
        lambda r: r.url.endswith("/api/agents/provider-models")
        and r.request.method == "POST",
        timeout=60000,
    ) as listed:
        tour.click(fetch)
    assert listed.value.ok, (
        f"listing models failed: HTTP {listed.value.status} - "
        "check the base URL and key typed above"
    )

    model_select = _ai_field(page, "Model")
    expect(model_select).to_be_visible(timeout=20000)
    tour.focus(model_select, hold=1200)
    model_select.select_option(LLM_MODEL)
    tour.beat(900)
    tour.say(
        "The model is not optional here",
        "With no deployment default, a blank model means no provider at all.",
        hold=2800,
    )

    tour.hush()
    # Assert on the PATCH and on the panel closing, not on "Settings saved.".
    # That message is transient by design - handleSave shows it and calls
    # onClose 800ms later - and tour.click's own trailing beat eats most of the
    # window, so waiting for it is a race the recording loses. The request and
    # the close are the durable facts, and the request also surfaces a failed
    # save instead of letting it read as a slow one.
    with page.expect_response(
        lambda r: r.url.endswith("/api/auth/me")
        and r.request.method == "PATCH",
        timeout=45000,
    ) as saved:
        tour.click(page.get_by_role("button", name="Save", exact=True))
    assert saved.value.ok, (
        f"saving AI Settings failed: {saved.value.status} {saved.value.url}"
    )
    expect(
        page.get_by_role("heading", name="AI Settings", level=2)
    ).to_have_count(0, timeout=20000)
    tour.beat(900)

    # Reopen it: the only durable proof on screen that the key was stored, and
    # the clearest way to show the per-field inheritance the panel implements.
    _open_ai_settings(ctx)
    remove = page.get_by_role("button", name="Remove saved key", exact=True)
    expect(remove).to_be_visible(timeout=15000)
    tour.focus(remove, hold=1500)
    tour.say(
        "The key is saved, and never sent back",
        "The panel only knows that one exists - blank now means keep it.",
        hold=3000,
    )
    tour.hush()
    tour.click(page.get_by_role("button", name="Cancel", exact=True))
    expect(
        page.get_by_role("heading", name="AI Settings", level=2)
    ).to_have_count(0, timeout=15000)
    # If the drawer was the way in (canvas), put it back so the next scene
    # starts on a clean canvas rather than behind a panel it did not open.
    closer = page.get_by_role("button", name="Close Agent Catalog drawer")
    if closer.count():
        closer.first.click()
        expect(page.locator(DRAWER_AGENTS)).to_have_count(0, timeout=8000)
    tour.hush()


def scene_canvas(ctx: Ctx) -> None:
    page, tour = ctx.page, ctx.tour
    tour.chapter("03", "The dataflow canvas", "Where analysis is authored.")
    tour.click(page.get_by_role("button", name="+ New Dataflow"))
    page.wait_for_url("**/dataflow/**", timeout=20000)
    page.wait_for_timeout(2000)
    tour.say(
        "One canvas, several abstraction levels",
        "Python and JavaScript code, declarative grammars, and GUI widgets.",
        hold=2600,
    )
    tour.focus(page.locator("#tools-menu"), hold=1600)
    tour.say(
        "The built-in node rail",
        "Loading, transformation, computation, pooling, maps, charts, merging.",
        hold=2600,
    )
    for tile, label in (
        ("#step-loading", "Data Loading"),
        ("#step-analysis", "Python Computation"),
        ("#step-transformation", "Data Transformation"),
        ("#step-pool", "Data Pool"),
        ("#step-utk", "Autark: 2D and 3D maps, GPU compute"),
        ("#step-vega", "Vega-Lite charts"),
        ("#step-merge", "Merge Flow"),
    ):
        locator = page.locator(tile)
        if not locator.count():
            continue
        tour.say(label, hold=200)
        tour.focus(locator, hold=800)
    tour.hush()
    tour.say(
        "Menus for the rest",
        "File, View, Data catalogs, Provenance, and a built-in tutorial.",
        hold=2200,
    )
    for label in ("File", "View", "Data", "Provenance"):
        trigger = _menu(page, label)
        tour.click(trigger, force=True, hold=1100)
        page.keyboard.press("Escape")
        tour.click(trigger, force=True, hold=200)
    tour.hush()


def scene_data_catalog(ctx: Ctx) -> None:
    page, tour = ctx.page, ctx.tour
    tour.chapter(
        "04", "The Data Catalog",
        "Datasets are first-class: browse, add, import your own, publish.",
    )
    palette = open_tools_palette(page, "datasets")
    tour.say(
        "Every dataflow carries its datasets",
        "The rail lists what this dataflow can load; the catalog is the library.",
        hold=2600,
    )
    browse = palette.get_by_role("button", name="Browse Data Catalog +")
    tour.click(browse, force=True)

    root = page.locator(DRAWER_DATA)
    root.wait_for(state="attached", timeout=15000)
    expect(root).to_have_attribute("aria-hidden", "false", timeout=10000)
    drawer = page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name="Data Catalog", exact=True)
    )
    expect(drawer).to_be_visible(timeout=10000)
    tour.say(
        "CSV, GeoJSON, Parquet, GeoTIFF, Shapefile, OSM PBF",
        "Published datasets, your imports, and outputs computed by other nodes.",
        hold=3000,
    )

    card = drawer.locator(f'{CARD}[data-dataset-id="{DATASET_ID}"]')
    expect(card).to_have_count(1, timeout=20000)
    tour.focus(card, hold=1400)
    tour.hush()
    add = card.get_by_role("button", name="Add to project", exact=True)
    tour.click(add)
    with page.expect_response(
        lambda r: "/datasets/install" in r.url
        and r.request.method == "POST" and r.ok,
        timeout=60000,
    ):
        accept_confirm_dialog(
            page, title=re.compile(r"^Add "), button="Add to project"
        )
    expect(
        drawer.locator(f'{CARD}[data-dataset-id="{DATASET_ID}"]').get_by_role(
            "button", name="Remove from project", exact=True
        )
    ).to_be_visible(timeout=25000)
    tour.say(
        "Added to this dataflow",
        "Installed into the account's store and pinned to the dataflow spec.",
        hold=2400,
    )
    tour.hush()
    _close_data_drawer(page)
    row = page.locator(f'#datasets-palette [data-dataset-id="{DATASET_ID}"]')
    expect(row).to_have_count(1, timeout=20000)
    tour.focus(row, hold=1200)
    ctx.state["dataset_row"] = row


def scene_build(ctx: Ctx) -> None:
    page, tour = ctx.page, ctx.tour
    tour.chapter("05", "Authoring a dataflow", "Drag, wire, write, run.")

    row = ctx.state.get("dataset_row")
    if row is None:
        row = open_tools_palette(page, "datasets").locator(
            f'[data-dataset-id="{DATASET_ID}"]'
        )
    tour.say(
        "Drag a dataset onto the canvas",
        "Curio writes the loader for you, in the right format for the file.",
        hold=2600,
    )
    tour.focus(row, hold=700)
    _reset_zoom(page)
    pane = page.locator(".curio-canvas-drop-target").bounding_box()
    if pane:
        tour.point_at(pane["x"] + POS_LOADER[0] + 240, pane["y"] + POS_LOADER[1] + 40)
    loader_id = drag_to_canvas(page, row, at=POS_LOADER)
    tour.beat(1400)
    tour.hush()
    # The palette strip sits over the pane; from here on the graph is the point.
    # No fitView here, deliberately: fitting a single node zooms the pane right
    # in, and the next drop - whose offset is in screen pixels - then lands on
    # top of this node instead of 610px to its right, which makes connect_nodes
    # fail with the output handle covered by the other node's editor.
    close_tools_palette(page, "datasets")

    tour.say(
        "A Data Loading node, already coded",
        "pandas.read_csv against the installed copy, returning a DataFrame.",
        hold=3000,
    )
    tour.say(
        "Now a transformation to consume it",
        "Built-in node types drag off the same rail.",
        hold=2200,
    )
    _reset_zoom(page)
    transform_id = drag_to_canvas(page, page.locator(TRANSFORM_TILE), at=POS_TRANSFORM)
    tour.beat(900)
    _fit_view(page)

    tour.say(
        "Connect them",
        "The upstream result arrives in the next node as `arg`.",
        hold=2000,
    )
    connect_nodes(page, loader_id, transform_id)
    tour.beat(1200)
    tour.hush()

    tour.say(
        "Write the analysis",
        "Each code node is a Monaco editor running in a sandboxed process.",
        hold=2400,
    )
    _center_on(page, transform_id, zoom=0.95)
    set_node_code(page, transform_id, TRANSFORM_CODE)
    tour.beat(1600)

    tour.say("Run the loader", "", hold=1200)
    _center_on(page, loader_id, zoom=0.9)
    tour.hush()
    play = node_locator(page, loader_id).locator("svg.fa-circle-play")
    tour.focus(play, hold=400)
    run_node_and_wait(page, loader_id, node_type=LOADER_TYPE)
    tour.beat(1500)

    tour.say(
        "Play a node and its ancestors run first",
        "Results are cached as DuckDB artifacts and passed down the edges.",
        hold=2600,
    )
    _center_on(page, transform_id, zoom=0.9)
    tour.hush()
    output = run_node_and_wait(page, transform_id, node_type=TRANSFORM_TYPE)
    tour.beat(2400)
    _log(f"[tour] transformation output: {output[:200]}")
    _fit_view(page)
    ctx.state["loader_id"] = loader_id
    ctx.state["transform_id"] = transform_id

    tour.say(
        "Save it",
        "Auto-save, an unsaved-changes guard, and a save-status indicator.",
        hold=2200,
    )
    tour.click(_menu(page, "File"), force=True)
    save = page.get_by_role("button", name="Save dataflow", exact=True)
    save.wait_for(state="visible", timeout=10000)
    with page.expect_response(
        lambda r: "/api/projects" in r.url
        and r.request.method in ("POST", "PUT") and r.ok,
        timeout=40000,
    ):
        tour.click(save)
    save.wait_for(state="hidden", timeout=30000)
    tour.hush()


def scene_lineage(ctx: Ctx) -> None:
    page, tour = ctx.page, ctx.tour
    tour.chapter(
        "06", "Dataset lineage",
        "Outputs become inputs, and Curio remembers who made what.",
    )
    tour.click(_menu(page, "Data"), force=True)
    tour.click(page.get_by_role("button", name="Data Catalog", exact=True))
    root = page.locator(DRAWER_DATA)
    root.wait_for(state="attached", timeout=15000)
    expect(root).to_have_attribute("aria-hidden", "false", timeout=10000)
    drawer = page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name="Data Catalog", exact=True)
    )
    card = drawer.locator(f'{CARD}[data-dataset-id="{DATASET_ID}"]')
    expect(card).to_have_count(1, timeout=20000)
    tour.click(card.locator(f'button[aria-label^="View {DATASET_TITLE} ("]'))

    tabs = page.get_by_role("navigation", name="Dataset detail sections")
    expect(tabs).to_be_visible(timeout=20000)
    tour.say(
        "Every dataset has a detail panel",
        "Schema, preview, provenance and downstream usage.",
        hold=2600,
    )
    tour.click(tabs.get_by_role("button", name="Lineage", exact=True))
    center = page.locator('section[aria-label="Dataset content"]')
    expect(
        center.get_by_role("heading", name=re.compile(r"^Dataflows"))
    ).to_be_visible(timeout=15000)
    tour.say(
        "Consumed by the node we just wired",
        "The graph is read back from the saved dataflow, not hand-maintained.",
        hold=3200,
    )
    tour.hush()
    tour.beat(1200)
    page.locator('button[aria-label="Close"]:not([data-dismiss="toast"])').click()
    expect(tabs).to_have_count(0, timeout=10000)
    _close_data_drawer(page)


def scene_node_catalog(ctx: Ctx) -> None:
    page, tour = ctx.page, ctx.tour
    tour.chapter(
        "07", "The Node Catalog",
        "Every node lives in a versioned, shareable package.",
    )
    palette = open_tools_palette(page, "packages")
    tour.click(
        palette.get_by_role("button", name=re.compile(r"^Browse Node Catalog")),
        force=True,
    )
    drawer = page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name="Node Catalog", exact=True)
    )
    expect(drawer).to_be_visible(timeout=15000)
    tour.say(
        "Built-ins, community packages, and your own",
        "Mix them freely in one dataflow; a lockfile pins the exact set.",
        hold=3000,
    )
    search = drawer.get_by_placeholder("Search packages, publishers, tags…")
    tour.type_into(search, "example", delay=90)
    tour.beat(1200)

    card = drawer.locator(f'article[data-pkg-dir="{PKG_DIR}"]')
    expect(card).to_have_count(1, timeout=15000)
    tour.focus(card, hold=1500)
    tour.say("Add it to the dataflow", "", hold=1000)
    tour.hush()
    with page.expect_response(
        lambda r: r.url.endswith("/api/packages/resolve"), timeout=40000
    ):
        card.get_by_role("button", name="Add to project", exact=True).click()
    dialog = page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name=f'Add "{PKG_NAME}"', exact=True)
    )
    expect(dialog).to_be_visible(timeout=15000)
    tour.say(
        "Dependencies are resolved before anything is installed",
        "Python and JS requirements are read from the package manifest.",
        hold=2800,
    )
    confirm = dialog.get_by_role("button", name="Add to project", exact=True)
    tour.hush()
    with page.expect_response(
        lambda r: "/api/packages/projects/" in r.url
        and r.url.endswith("/install")
        and r.request.method == "POST" and r.ok,
        timeout=60000,
    ):
        tour.click(confirm)
    expect(dialog).to_have_count(0, timeout=40000)
    expect(
        card.get_by_role("button", name="Remove from project", exact=True)
    ).to_be_visible(timeout=25000)
    tour.say("Installed", "No reload: the palette re-renders in place.", hold=2000)
    tour.hush()
    drawer.locator("header").get_by_role(
        "button", name="Close Node Catalog drawer"
    ).click()
    expect(page.locator(DRAWER_NODES)).to_have_count(0, timeout=8000)
    new_row = page.locator(f'#packages-palette [data-pkg-palette-coords~="{PKG_DIR}"]')
    expect(new_row).to_have_count(1, timeout=25000)
    tour.focus(new_row, hold=2000)
    tour.say(
        "Its nodes are now draggable",
        "Authoring your own works the same way: Save as package node.",
        hold=2600,
    )
    tour.hush()
    close_tools_palette(page, "packages")


def scene_libraries(ctx: Ctx) -> None:
    page, tour = ctx.page, ctx.tour
    tour.say(
        "Python libraries, managed from the canvas",
        "Curio detects imports a dataflow needs and installs them per account.",
        hold=2600,
    )
    tour.click(_menu(page, "Data"), force=True)
    tour.click(page.get_by_role("button", name="Installed libraries", exact=True))
    expect(
        page.get_by_role("heading", name="Installed libraries")
    ).to_be_visible(timeout=20000)
    tour.beat(2600)
    tour.hush()
    page.get_by_role("button", name="Close", exact=True).first.click()
    expect(
        page.get_by_role("heading", name="Installed libraries")
    ).to_have_count(0, timeout=10000)


def scene_agent_catalog(ctx: Ctx) -> None:
    """The third catalog, alongside the Node and Data ones."""
    page, tour = ctx.page, ctx.tour
    tour.chapter(
        "08", "The Agent Catalog",
        "The third catalog: the assistants you attach to a dataflow.",
    )
    drawer = _open_agent_drawer(ctx)
    tour.say(
        "Nodes, data - and agents",
        "Twenty-one ship built in, each a versioned package like any other.",
        hold=2900,
    )
    tour.say(
        "Five categories",
        "node, canvas, data, evaluate and package - each with its own colour.",
        hold=2700,
    )

    search = drawer.get_by_placeholder(AGENT_SEARCH_PLACEHOLDER)
    tour.type_into(search, "explain", delay=85)
    tour.beat(1200)
    _add_agent(ctx, drawer, AGENT_EXPLAINER)
    tour.say("Added to this dataflow", "", hold=1300)

    search.fill("")
    tour.beat(700)
    tour.type_into(search, "connection", delay=85)
    tour.beat(900)
    _add_agent(ctx, drawer, AGENT_CONNECTION)

    search.fill("")
    tour.beat(700)
    tour.type_into(search, "builder", delay=85)
    tour.beat(900)
    tour.say(
        "Agents can require other agents",
        "This one reads 'Add to project (+1 required)': the closure comes with it.",
        hold=3000,
    )
    _add_agent(ctx, drawer, AGENT_BUILDER, hold=1800)
    tour.hush()

    settings = drawer.get_by_role("button", name=re.compile("AI Settings"))
    if settings.count():
        tour.focus(settings.first, hold=1500)
        tour.say(
            "The provider lives one click away",
            "On the canvas this cog is the only route to AI Settings.",
            hold=2600,
        )
        tour.hush()

    drawer.get_by_role("button", name="Close Agent Catalog drawer").click()
    expect(page.locator(DRAWER_AGENTS)).to_have_count(0, timeout=8000)

    # The palette re-reads the lockfile off a window event, with no reload.
    palette = open_tools_palette(page, "agents")
    row = _agent_row(page, AGENT_EXPLAINER)
    expect(row).to_have_count(1, timeout=25000)
    tour.focus(palette, hold=1200)
    tour.say(
        "Added is not attached",
        "The palette holds what this dataflow may use. Attaching binds one to a target.",
        hold=3000,
    )
    tour.hush()


def scene_agent_attach(ctx: Ctx) -> None:
    """Attach to a node, to a connection, and to the canvas."""
    page, tour = ctx.page, ctx.tour
    tour.chapter(
        "09", "Attaching an agent",
        "A node, a connection, or the whole canvas.",
    )
    _reset_zoom(page)
    _fit_view(page, padding=0.3)
    open_tools_palette(page, "agents")

    transform_id = ctx.state.get("transform_id")
    if transform_id is None:
        candidates = _node_ids_by_type(page, TRANSFORM_TYPE)
        transform_id = candidates[0] if candidates else None
    assert transform_id, "no transformation node on the canvas to attach to"

    # 1. onto a node
    tour.say(
        "Drop it on a node",
        "The agent binds to that node, with its own chat and its own settings.",
        hold=2800,
    )
    _drag_agent_to(
        ctx, AGENT_EXPLAINER, lambda: _node_client_point(page, transform_id)
    )
    _expect_attach_toast(ctx, "the node")
    tour.hush()

    # 2. onto the connection between the two nodes
    if _edge_client_point(page):
        tour.say(
            "Or on the connection itself",
            "An agent that reasons about what flows between two nodes.",
            hold=2800,
        )
        _drag_agent_to(ctx, AGENT_CONNECTION, lambda: _edge_client_point(page))
        _expect_attach_toast(ctx, "the connection")
        tour.hush()
    else:
        _log("[tour] no edge interaction path found; skipping the connection attach")

    # 3. onto empty canvas
    tour.say(
        "Or on the canvas",
        "A canvas agent sees the whole dataflow rather than one node.",
        hold=2800,
    )
    _drag_agent_to(ctx, AGENT_BUILDER, lambda: _empty_canvas_point(page))
    _expect_attach_toast(ctx, "the canvas")
    tour.hush()

    close_tools_palette(page, "agents")

    # The goal input appears in the dock as soon as anything is attached.
    goal = page.get_by_label("Dataflow goal")
    goal.wait_for(state="visible", timeout=20000)
    tour.say(
        "Tell them what the dataflow is for",
        "One sentence, shared with every agent and saved with the dataflow.",
        hold=2900,
    )
    tour.type_into(goal, DATAFLOW_GOAL, delay=32)
    goal.press("Enter")
    tour.beat(900)
    tour.hush()
    ctx.state["agent_node_id"] = transform_id


def scene_agent_run(ctx: Ctx) -> None:
    """Ask an attached agent a real question and wait for a real answer."""
    page, tour = ctx.page, ctx.tour
    tour.chapter(
        "10", "Running an agent",
        "A live model, answering about this dataflow.",
    )
    badge = page.get_by_role(
        "button", name=re.compile(r"^Open chat with Node Explainer")
    ).first
    badge.wait_for(state="visible", timeout=20000)
    tour.click(badge)

    panel = page.get_by_role("dialog", name=re.compile(r"^Chat with "))
    expect(panel).to_be_visible(timeout=20000)
    tour.say(
        "Every attachment is its own conversation",
        "Its own transcript, its own editable opening instruction.",
        hold=2800,
    )

    intent = panel.get_by_role("button", name="Edit initial intent")
    if intent.count():
        tour.focus(intent.first, hold=1400)
    tour.hush()

    composer = panel.get_by_label("Message this agent")
    tour.type_into(composer, "What does this node compute, and why?", delay=38)
    tour.hush()

    if not LLM_API_KEY:
        # Show the surface, but do not send: with no provider the reply would be
        # an error bubble, and filming that is worse than filming nothing.
        _log("[tour] no provider key configured; skipping the live agent run")
        tour.say(
            "Attach a provider in AI Settings to run it",
            "Curio ships no endpoint of its own, so nothing is called until you set one.",
            hold=3000,
        )
        tour.hush()
        close_chat = panel.get_by_label("Close chat")
        if close_chat.count():
            tour.click(close_chat.first)
        return

    # Watch every call the run makes, not just the first one to come back.
    # The panel opens an SSE stream (/run/stream) that answers 200 and then
    # carries the failure down the stream, and falls back to the plain /run,
    # which is where a provider failure actually shows up as a status. Asserting
    # on the first response alone let a run that 502'd record as a success -
    # the ledger said `"status": "error", "usage": null` while the scene passed.
    run_calls: list = []

    def _record(response) -> None:
        if "/attachments/" in response.url and "/run" in response.url:
            run_calls.append(response)

    page.on("response", _record)

    # A live provider: gate on the request completing, not on any wording.
    # 180s because a cold remote model can be slow and a truncated wait would
    # read on camera as the feature being broken.
    try:
        with page.expect_response(
            lambda r: "/attachments/" in r.url and "/run" in r.url,
            timeout=180000,
        ) as run:
            tour.click(panel.get_by_label("Send"))
        reply = run.value
    except PlaywrightTimeoutError:
        _log("[tour] agent run did not return in time; continuing the take")
        tour.say("The agent is still thinking", "", hold=1200)
        reply = None

    if reply is not None:
        tour.say(
            "Answered by the endpoint configured in AI Settings",
            "No key, no answer - Curio ships no provider of its own.",
            hold=3200,
        )
        # Let the reply stream in and be visible rather than cutting on arrival,
        # and give the non-streaming fallback time to land before judging.
        tour.beat(4200)

    page.remove_listener("response", _record)

    failed = [r for r in run_calls if not r.ok]
    if failed:
        first = failed[0]
        body = ""
        try:
            body = first.text()[:400]
        except Exception:  # noqa: BLE001 - a body is a nicety here
            pass
        raise AssertionError(
            "the agent run failed, so this scene would record a broken agent: "
            f"HTTP {first.status} from {first.url}\n{body}\n"
            "Check the provider in AI Settings - a rejected key, an unreachable "
            "base URL and a model the endpoint does not serve all land here."
        )
    assert run_calls, "the agent run made no request at all"
    # A configured-but-unusable provider is reported in the panel rather than as
    # a status, so check the surface the viewer is actually looking at too.
    blocked = panel.get_by_text(re.compile("No AI provider is configured", re.I))
    assert blocked.count() == 0, (
        "the agent surface reports no configured provider; AI Settings did "
        "not take effect for this account"
    )

    tour.hush()
    close_chat = panel.get_by_label("Close chat")
    if close_chat.count():
        tour.click(close_chat.first)
    tour.beat(700)


def scene_linked_views(ctx: Ctx) -> None:
    page, tour = ctx.page, ctx.tour
    tour.chapter(
        "11", "Visualization",
        "Vega-Lite views driven by real urban data, run end to end.",
    )
    _new_dataflow_from_menu(ctx)
    tour.say(
        "Load a published example",
        "Chicago speed-camera violations: load, aggregate, two linked views.",
        hold=2600,
    )
    _load_example(ctx, EXAMPLE_LINKED, expected_nodes=4)
    tour.say(
        "Play All runs the graph in topological order",
        "400k rows are trimmed at load, aggregated, then handed to both charts.",
        hold=3000,
    )
    tour.hush()
    _play_all(ctx)
    tour.say(
        "Two views from one computation",
        "A bar chart per camera and a total-by-year line, fed by the same node.",
        hold=3200,
    )
    tour.hush()
    _fit_view(page, padding=0.12)
    tour.beat(2000)
    ctx.state["vega_ids"] = _node_ids_by_type(page, "vis-vega")


def scene_dashboard(ctx: Ctx) -> None:
    page, tour = ctx.page, ctx.tour
    tour.say(
        "Pin the views you want to present",
        "Dashboard Mode keeps node state, edges and positions intact.",
        hold=2600,
    )
    for node_id in (ctx.state.get("vega_ids") or _node_ids_by_type(page, "vis-vega"))[:2]:
        # The header icons are FontAwesome svgs with role="button" and no
        # accessible name (the `title` prop does not survive into the DOM here),
        # so the icon class is the only stable handle: faCircle when unpinned,
        # faCircleDot once pinned. They activate on pointerdown/up so that
        # press-and-drag still moves the node, which is what
        # activate_header_icon sends.
        pin = node_locator(page, node_id).locator(
            'svg[role="button"].fa-circle, svg[role="button"].fa-circle-dot'
        ).first
        if not pin.count():
            _log(f"[tour] no dashboard pin control on {node_id}")
            continue
        tour.focus(pin, hold=450)
        activate_header_icon(pin)
        tour.beat(700)
    tour.hush()
    tour.click(_menu(page, "View"), force=True)
    tour.click(page.get_by_role("button", name="Dashboard Mode", exact=True))
    tour.beat(3200)
    tour.say(
        "The same dataflow, presented",
        "Toggle back and the canvas is exactly where you left it.",
        hold=2600,
    )
    tour.hush()
    exit_btn = page.locator('button[title="Exit Dashboard Mode"]')
    tour.click(exit_btn)
    tour.beat(1200)
    _fit_view(page)


def scene_provenance(ctx: Ctx) -> None:
    page, tour = ctx.page, ctx.tour
    tour.chapter(
        "12", "Provenance",
        "Curio tracks how a dataflow got to be the way it is.",
    )
    tour.click(_menu(page, "Provenance"), force=True)
    tour.click(page.get_by_role("button", name="Provenance", exact=True))
    tour.beat(1500)
    tour.say(
        "Versions of the dataflow, as a graph",
        "Tracked in the dataflow itself, so it travels with the file.",
        hold=3200,
    )
    tour.hush()
    page.keyboard.press("Escape")
    tour.beat(900)
    for label in ("Close", "close"):
        button = page.get_by_role("button", name=label, exact=True)
        if button.count():
            try:
                button.first.click(timeout=2500)
                break
            except Exception:
                pass


def scene_interaction(ctx: Ctx) -> None:
    page, tour = ctx.page, ctx.tour
    tour.chapter(
        "13", "Linked interactions",
        "A selection in one view is data the rest of the graph can read.",
    )
    _new_dataflow_from_menu(ctx)
    _load_example(ctx, EXAMPLE_INTERACTION, expected_nodes=3)
    tour.say(
        "Loader, Data Pool, Vega-Lite view",
        "The pool fans one result out and collects interaction state back.",
        hold=2800,
    )
    tour.hush()
    _play_all(ctx)

    vega_ids = _node_ids_by_type(page, "vis-vega")
    if not vega_ids:
        return
    _center_on(page, vega_ids[0], zoom=1.0)
    tour.say(
        "Hovering a bar writes back into the data",
        "The interaction becomes a column every downstream node can use.",
        hold=2800,
    )
    # Sweep the pointer across the plot rather than clicking marks: the Vega
    # view is one canvas, so every mark shares its bounding box and hovering
    # "each mark" would hover the same pixel five times. Walking x across the
    # plotting area is what actually fires pointerover on successive bars.
    plot = node_locator(page, vega_ids[0]).locator("canvas, svg").first
    box = plot.bounding_box()
    if box:
        y = box["y"] + box["height"] * 0.7
        left = box["x"] + box["width"] * 0.22
        right = box["x"] + box["width"] * 0.88
        for index in range(5):
            x = left + (right - left) * index / 4
            tour.point_at(x, y, hold=200)
            page.mouse.move(x, y)
            tour.beat(1100)
    tour.beat(1500)
    tour.hush()


def scene_autark(ctx: Ctx) -> None:
    page, tour = ctx.page, ctx.tour
    tour.chapter(
        "14", "Autark: maps and GPU compute",
        "One declarative UrbanSpec for data loading, WGSL compute and rendering.",
    )
    _new_dataflow_from_menu(ctx)
    _load_example(ctx, EXAMPLE_AUTARK, expected_nodes=2)
    tour.say(
        "An OSM extract, parsed in the browser",
        "DuckDB-WASM reads a local .pbf; no tile server, no Overpass call.",
        hold=3000,
    )
    tour.hush()
    _play_all(ctx)
    tour.say(
        "Rendered with WebGPU",
        "Lower Manhattan: buildings, roads and water as separate layers.",
        hold=3000,
    )
    tour.hush()
    ids = _node_ids_by_type(page, "autk-grammar")
    if ids:
        # Frame the rendering node: at fitView zoom the map is a thumbnail
        # inside a 525x350 node, which is not what this chapter is about.
        _center_on(page, ids[-1], zoom=1.25)
        tour.beat(5000)


def scene_catalog_pages(ctx: Ctx) -> None:
    page, tour = ctx.page, ctx.tour
    tour.chapter(
        "15", "Catalogs as pages",
        "The same catalogs, browsable outside any single dataflow.",
    )
    page.goto(f"{ctx.frontend}/catalog/nodes")
    page.wait_for_load_state("domcontentloaded")
    tour.beat(2600)
    tour.say(
        "Every package on this deployment",
        "Descriptions, licenses, READMEs, permissions and versions.",
        hold=2800,
    )
    tour.scroll(700, steps=7)
    tour.hush()
    page.goto(f"{ctx.frontend}/catalog/data")
    page.wait_for_load_state("domcontentloaded")
    tour.beat(2200)
    tour.say(
        "And every dataset",
        "Publish your own so the whole deployment can build on it.",
        hold=2800,
    )
    tour.scroll(700, steps=7)
    tour.hush()

    page.goto(f"{ctx.frontend}/catalog/agents")
    page.wait_for_load_state("domcontentloaded")
    expect(
        page.get_by_role("heading", name="Agent Catalog")
    ).to_be_visible(timeout=30000)
    tour.beat(1800)
    tour.say(
        "And every agent",
        "Filter by status or category, read the full detail, keep one for later.",
        hold=3000,
    )
    for name in ("In my account", "Published", "All agents"):
        button = page.get_by_role("button", name=name, exact=True)
        if button.count():
            tour.click(button.first, hold=900)
    tour.hush()

    card = page.locator("article").first
    if card.count():
        tour.click(card, hold=1200)
        add = page.get_by_role("button", name="Add to all projects", exact=True)
        if add.count():
            tour.focus(add.first, hold=1600)
    tour.say(
        "Account-level, on purpose",
        "This page cannot add to a dataflow: adding is relative to one, and it has none.",
        hold=3200,
    )
    tour.hush()


def scene_outro(ctx: Ctx) -> None:
    page, tour = ctx.page, ctx.tour
    page.goto(f"{ctx.frontend}/projects")
    page.wait_for_load_state("domcontentloaded")
    wait_for_projects_page(page, timeout=20000)
    tour.beat(1800)
    tour.say(
        "Reproducible and shareable",
        "Dataflows fork, export as .curio.zip or a notebook, and share by URL.",
        hold=3000,
    )
    tour.hush()
    tour.chapter(
        "urbantk.org/curio",
        "Curio",
        "Docs, examples and hosted instances at curio.urbantk.org.",
        hold=4200,
    )
    page.evaluate("() => window.__curioTour && window.__curioTour.clearAll()")
    tour.beat(800)


#: Ordered scene registry. Ids are what ``CURIO_TOUR_SCENES`` selects.
SCENES: list[tuple[str, Callable[[Ctx], None]]] = [
    ("intro", scene_intro),
    ("signup", scene_signup),
    ("projects", scene_projects),
    ("aisettings", scene_ai_settings),
    ("canvas", scene_canvas),
    ("datacatalog", scene_data_catalog),
    ("build", scene_build),
    ("lineage", scene_lineage),
    ("nodecatalog", scene_node_catalog),
    ("libraries", scene_libraries),
    ("agentcatalog", scene_agent_catalog),
    ("agentattach", scene_agent_attach),
    ("agentrun", scene_agent_run),
    ("linkedviews", scene_linked_views),
    ("dashboard", scene_dashboard),
    ("provenance", scene_provenance),
    ("interaction", scene_interaction),
    ("autark", scene_autark),
    ("catalogpages", scene_catalog_pages),
    ("outro", scene_outro),
]


#: Scenes that assume a dataflow canvas is already open. Used only to decide
#: where a partial re-record has to start from. ``aisettings`` is deliberately
#: absent: it runs on /projects, where the header that opens the panel lives.
CANVAS_SCENES = {
    "datacatalog", "build", "lineage", "nodecatalog", "libraries",
    "agentcatalog", "agentattach", "agentrun",
    "linkedviews", "dashboard", "provenance", "interaction", "autark",
}


def _selected_scenes() -> list[tuple[str, Callable[[Ctx], None]]]:
    wanted = os.environ.get("CURIO_TOUR_SCENES")
    if not wanted:
        return SCENES
    names = [n.strip() for n in wanted.split(",") if n.strip()]
    known = {name for name, _ in SCENES}
    unknown = [n for n in names if n not in known]
    if unknown:
        raise ValueError(
            f"unknown scene(s) {unknown}; valid ids: {[n for n, _ in SCENES]}"
        )
    return [(name, fn) for name, fn in SCENES if name in names]


def _warm_up(browser, frontend: str) -> None:
    """Pay webpack-dev-server's first-compile cost off camera.

    The very first request to the frontend can spend fifteen seconds serving a
    blank document while the bundle compiles. In a recording that is fifteen
    seconds of white, so it happens in a throwaway context before the one that
    is being recorded exists.
    """
    context = browser.new_context(viewport=VIDEO_SIZE)
    page = context.new_page()
    try:
        page.goto(f"{frontend}/auth/signin", timeout=120000)
        page.wait_for_load_state("domcontentloaded")
        try:
            page.get_by_text("Sign in", exact=False).first.wait_for(timeout=60000)
        except Exception:
            pass
    finally:
        context.close()


def test_record_feature_tour(frontend_server: str, current_server: str, browser):
    """Drive the whole feature set once, recording it as a single take."""
    scenes = _selected_scenes()
    raw_dir = os.path.join(out_dir(), "raw")
    os.makedirs(raw_dir, exist_ok=True)
    # Playwright names its recordings page@<hash>.webm and the finalizer deletes
    # the one it saved, but a killed run leaves its own behind. Clear only that
    # pattern, in a directory this test owns.
    for stale in os.listdir(raw_dir):
        if stale.startswith("page@") and stale.endswith(".webm"):
            try:
                os.remove(os.path.join(raw_dir, stale))
            except OSError:
                pass

    _warm_up(browser, frontend_server)

    context = browser.new_context(
        viewport=VIDEO_SIZE,
        record_video_dir=raw_dir,
        record_video_size=VIDEO_SIZE,
    )
    page = context.new_page()
    # The drawers slide with translate3d and the providers read
    # prefers-reduced-motion through useSyncExternalStore, so a panel is only
    # reachable once the transition is collapsed. The tour's own pacing supplies
    # the sense of movement instead.
    page.emulate_media(reduced_motion="reduce")
    # Unsaved-changes guards would otherwise block File > New dataflow with a
    # native confirm no one can answer.
    page.on("dialog", lambda d: d.accept())

    tour = Tour(page, pace=speed())
    ctx = Ctx(page=page, tour=tour, frontend=frontend_server, backend=current_server)

    # Recording a subset (CURIO_TOUR_SCENES) still has to start from a signed-in
    # browser, and re-running the signup form would collide with the account the
    # full tour creates. The DB stub gets there without spending screen time on
    # it, and is skipped when the signup scene is going to do it for real.
    selected = {name for name, _ in scenes}
    if not selected & {"intro", "signup"}:
        session = stub_db_login(
            page,
            frontend_url=frontend_server,
            backend_url=current_server,
            username=USER_LOGIN,
            name=USER_NAME,
            password=USER_PASSWORD,
            project_name="Feature Tour",
        )
        # Land where the first selected scene expects to be: the canvas scenes
        # assume a dataflow is already open, and dropping them on /projects
        # fails 30 seconds later on a menu that page does not have.
        if selected & CANVAS_SCENES and "canvas" not in selected:
            page.goto(f"{frontend_server}/dataflow/{session['project']['id']}")
            page.wait_for_load_state("domcontentloaded")
            page.locator("#tools-menu").wait_for(state="visible", timeout=45000)
        else:
            page.goto(f"{frontend_server}/projects")
            page.wait_for_load_state("domcontentloaded")
            wait_for_projects_page(page, timeout=30000)

    failures: list[tuple[str, str]] = []
    for name, scene in scenes:
        _log(f"[tour] scene: {name}")
        try:
            scene(ctx)
        except Exception:  # noqa: BLE001 - one bad scene must not lose the take
            failures.append((name, traceback.format_exc()))
            _log(f"[tour] scene {name} FAILED:\n{traceback.format_exc()}")
            # A still of the moment it broke localises the failure much faster
            # than the locator message on its own.
            try:
                page.screenshot(path=os.path.join(out_dir(), f"failed-{name}.png"))
            except Exception:
                pass
            try:
                tour.hush()
                page.keyboard.press("Escape")
            except Exception:
                pass

    page.close()
    context.close()
    written = finalize_video(page, stem="curio-feature-tour")
    for kind, path in written.items():
        _log(f"[tour] wrote {kind}: {path}")

    assert written, "no video was recorded"
    if failures:
        summary = "\n\n".join(f"--- {name} ---\n{tb}" for name, tb in failures)
        pytest.fail(
            f"{len(failures)} of {len(scenes)} scenes failed; the recording at "
            f"{written.get('mp4') or written.get('webm')} is missing them.\n\n"
            f"{summary}"
        )
