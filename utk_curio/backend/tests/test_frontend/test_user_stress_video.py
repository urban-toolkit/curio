"""Recorded user-test sessions: five personas trying to break Curio.

Not a regression suite. Each test is one *session* - a persona with a goal, doing
what a real user would do to reach it, including the mistakes on the way - and
each produces a video plus a list of findings. A session never aborts on the
first problem: it files it and keeps going, because a real user does, and because
the interesting findings are usually downstream of the first one.

The harness is borrowed wholesale. ``fixtures.curio_servers`` boots the stack,
``conftest.py`` launches the system Chrome that Autark's WebGPU needs, ``utils``
supplies the canvas vocabulary, and ``tour``/``usertest`` supply the on-screen
narration and the video plumbing. What is new here is the *stance*: see
``usertest.UserSession.step``.

Gated on ``CURIO_STRESS=1`` so an ordinary ``pytest tests/test_frontend/`` run
never spends half an hour recording.

Run (from ``utk_curio/backend``, with the repo root on PYTHONPATH)::

    BACKEND_PORT=5013 SANDBOX_PORT=2011 FRONTEND_PORT=8091 \
    CURIO_TESTING=1 CURIO_STRESS=1 CURIO_SANDBOX_TOKEN=usertest-local \
      python -m pytest tests/test_frontend/test_user_stress_video.py -s -v

Environment:

===============================  ==============================================
``CURIO_STRESS=1``               required; otherwise the module skips
``CURIO_STRESS_SESSIONS``        comma-separated session ids (default: all)
``CURIO_STRESS_OUT``             output dir (default ``.curio/usertest/``)
``CURIO_STRESS_SPEED``           pacing multiplier, >1 is faster (default 1.4)
===============================  ==============================================
"""
from __future__ import annotations

import json
import os
import re
import time

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect

from .tour import VIDEO_SIZE, finalize_video
from .usertest import (
    PALETTE_ICON_CLASS,
    UserSession,
    collect_sessions,
    out_dir,
    palette_tile,
    palette_tile_identity,
    write_report,
)
from .utils import (
    REPO_ROOT,
    accept_confirm_dialog,
    activate_header_icon,
    canvas_nodes,
    close_tools_palette,
    connect_nodes,
    dismiss_toasts,
    drag_to_canvas,
    node_locator,
    open_new_workflow,
    open_tools_palette,
    play_node,
    read_node_code,
    read_node_error_text,
    require_project_page,
    require_user_auth,
    set_canvas_zoom,
    set_node_code,
    signup_e2e_user,
    wait_for_node_settled,
    wait_for_projects_page,
)

# The tour module owns the shared canvas choreography (menus, Play All, fitView,
# the agent drag, the AI Settings panel). Importing it rather than restating it
# keeps this file about the *exploration* - and means a change to the app that
# breaks a gesture breaks it in one place.
from .test_feature_tour_video import (  # noqa: E402
    AGENT_BUILDER,
    AGENT_CONNECTION,
    AGENT_EXPLAINER,
    Ctx,
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MODEL,
    _add_agent,
    _center_on,
    _close_data_drawer,
    _drag_agent_to,
    _edge_client_point,
    _empty_canvas_point,
    _fit_view,
    _log,
    _menu,
    _new_dataflow_from_menu,
    _node_client_point,
    _node_ids_by_type,
    _open_agent_drawer,
    _play_all,
    _reset_zoom,
    scene_ai_settings,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("CURIO_STRESS") != "1",
    reason="recorded user-test sessions only run with CURIO_STRESS=1",
)


def _pace() -> float:
    try:
        value = float(os.environ.get("CURIO_STRESS_SPEED", "1.4"))
    except ValueError:
        return 1.4
    return value if value > 0 else 1.4


def _wanted(session_id: str) -> bool:
    selected = os.environ.get("CURIO_STRESS_SESSIONS")
    if not selected:
        return True
    return session_id in {s.strip() for s in selected.split(",") if s.strip()}


DRAWER_DATA = '[data-curio-dataset-catalog-drawer="true"]'
DRAWER_NODES = '[data-curio-node-catalog-drawer="true"]'
CARD = 'article:not([role="status"])'

GEO_DATASET = "data.urbanlab.chicago-boundary"

PKG_DIR = "curio.example-ui@1"
PKG_NAME = "Example: Custom UI Node"

# ---------------------------------------------------------------------------
# Content the sessions type
# ---------------------------------------------------------------------------

QUICKSTART_LOADER = (
    "import pandas as pd\n"
    "\n"
    "d = {'a': [\"A\", \"B\", \"C\", \"D\", \"E\", \"F\", \"G\", \"H\", \"I\"],\n"
    "     'b': [28, 55, 43, 91, 81, 53, 19, 87, 52]}\n"
    "df = pd.DataFrame(data=d)\n"
    "\n"
    "return df\n"
)

QUICKSTART_VEGA = json.dumps(
    {
        "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
        "mark": "bar",
        "encoding": {
            "x": {"field": "a", "type": "nominal", "axis": {"labelAngle": 0}},
            "y": {"field": "b", "type": "quantitative", "stack": None},
        },
    },
    indent=2,
)

# A typo a real person makes: a missing closing bracket, so the traceback is a
# SyntaxError the node has to surface rather than an exception it can catch.
BROKEN_LOADER = (
    "import pandas as pd\n"
    "\n"
    "d = {'a': [\"A\", \"B\", \"C\"], 'b': [1, 2, 3}\n"
    "df = pd.DataFrame(data=d)\n"
    "return df\n"
)

# A messy CSV, written to disk and imported through the interface. Every awkward
# thing here is something a real spreadsheet export contains: a UTF-8 BOM, a
# quoted comma inside a field, a column name with a space and one with a unit in
# parentheses, an empty cell, and a thousands separator.
MESSY_CSV = (
    "﻿"
    "Neighborhood Name,median income (USD),population,notes\n"
    '"Rogers Park, North",41250,54991,baseline\n'
    "Hyde Park,58300,25681,\n"
    '"West Town",72150,87781,"revised, 2024"\n'
    "Englewood,,24369,suppressed\n"
)


def _messy_csv_path() -> str:
    """Write the messy CSV under the output dir and return its path.

    Not ``tmp_path``: the file has to survive the test for a reader looking at a
    finding to be able to open the same bytes the session imported.
    """
    path = os.path.join(out_dir(), "user-upload-neighborhoods.csv")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(MESSY_CSV)
    return path


# ---------------------------------------------------------------------------
# Small helpers this file needs on top of utils
# ---------------------------------------------------------------------------

_GRAMMAR_EDITOR_JS = r"""(nodeId) => {
    const editors = (window.monaco && window.monaco.editor.getEditors()) || [];
    return editors.find((e) => {
        const uri = e.getModel() && e.getModel().uri && e.getModel().uri.path;
        return uri && uri.includes(`grammar-${nodeId}`);
    }) || null;
}"""


def set_node_grammar(page, node_id: str, spec: str, *, timeout: float = 20000) -> None:
    """Put *spec* into a node's Grammar editor.

    ``utils.set_node_code`` targets a node's first Monaco instance, which is the
    wrong one on any node that has both editors. The grammar model is registered
    under a ``grammar-<nodeId>.json`` path (``GrammarEditor`` passes ``path``),
    which is what distinguishes it - the same handle
    ``test_autark_grammar_edit_e2e.py`` uses.
    """
    node_el = node_locator(page, node_id)
    node_el.scroll_into_view_if_needed()
    tab = node_el.locator('.nav-link[data-rr-ui-event-key="grammar"]').first
    tab.wait_for(state="visible", timeout=timeout)
    if "active" not in (tab.get_attribute("class") or ""):
        tab.dispatch_event("click")
    page.wait_for_function(
        "(nodeId) => !!(" + _GRAMMAR_EDITOR_JS + ")(nodeId)",
        arg=node_id,
        timeout=timeout,
    )
    page.evaluate(
        "(args) => { const ed = (" + _GRAMMAR_EDITOR_JS + ")(args.nodeId);"
        " ed.setValue(args.spec); }",
        {"nodeId": node_id, "spec": spec},
    )
    page.wait_for_function(
        "(args) => { const ed = (" + _GRAMMAR_EDITOR_JS + ")(args.nodeId);"
        " return !!ed && ed.getValue() === args.spec; }",
        arg={"nodeId": node_id, "spec": spec},
        timeout=timeout,
    )


def read_node_grammar(page, node_id: str) -> str:
    return page.evaluate(
        "(nodeId) => { const ed = (" + _GRAMMAR_EDITOR_JS + ")(nodeId);"
        " return ed ? ed.getValue() : ''; }",
        node_id,
    )


def node_status(page, node_id: str) -> str:
    el = node_locator(page, node_id).locator("[data-curio-node-status]").first
    if not el.count():
        return "(no status element)"
    return el.get_attribute("data-curio-node-status") or "idle"



def load_example(session: UserSession, path: str, *, expected_nodes: int,
                 timeout: float = 120000) -> None:
    """File > Load dataflow, on camera, with a locator that is not ambiguous.

    Deliberately not ``tour._load_example`` (nor ``utils.upload_workflow``):
    both open the chooser with ``page.get_by_text("Load dataflow").click()``,
    and the menu row is a ``<div class=dropDownRow>`` wrapping a
    ``<button>`` that carries the same text (``UpMenu.tsx:394-397``). The text
    engine matches both, so that click dies of a strict-mode violation. The
    role-based locator resolves only the button.
    """
    page, tour = session.page, session.tour
    clear_canvas_overlays(page)
    tour.click(_menu(page, "File"), force=True)
    load = page.get_by_role("button", name="Load dataflow", exact=True)
    load.wait_for(state="visible", timeout=20000)
    tour.focus(load, hold=500)
    with page.expect_file_chooser() as chooser:
        load.click()
    chooser.value.set_files(path)
    page.wait_for_function(
        "(n) => document.querySelectorAll('.react-flow__node').length >= n",
        arg=expected_nodes,
        timeout=timeout,
    )
    tour.beat(900)
    _fit_view(page)


def play_all_guarded(session: UserSession, *, timeout_ms: int = 240000) -> bool:
    """Run every node, unless there are none to run.

    ``tour._play_all`` waits on ``nodes.every(...)`` over a list that is empty
    when a load failed, and an empty list never satisfies it - so a session whose
    previous step did not manage to load anything would sit here for the whole
    budget before failing for the wrong reason. Returns False if there was
    nothing to run.
    """
    page = session.page
    if not canvas_nodes(page):
        session.note("Play All skipped: the canvas has no nodes to run")
        return False
    _play_all(
        Ctx(page=page, tour=session.tour, frontend=session.frontend,
            backend=session.backend),
        timeout_ms=timeout_ms,
    )
    return True


def report_failed_nodes(session: UserSession, *, label: str) -> list[str]:
    """File every node left in an error state, with what it said."""
    page = session.page
    failed = [
        n for n in canvas_nodes(page) if node_status(page, n["id"]) == "error"
    ]
    if not failed:
        return []
    details = [
        f"{n['id']} ({n['nodeType']}): "
        + (node_failure_detail(page, n["id"]) or "(no reason given anywhere)")
        for n in failed
    ]
    session.record(
        "node-error",
        f"{label} left {len(failed)} node(s) in error",
        severity="bug",
        detail_full="\n\n".join(details),
    )
    return [n["id"] for n in failed]


def _close_agent_panel(session: UserSession) -> None:
    """Close the agent chat panel without relying on Escape.

    Escape is not wired to anything (see the ModalShell finding), so a session
    that pressed it and moved on would leave the panel over the canvas and blame
    the next step for the consequences.
    """
    page = session.page
    panel = page.get_by_role("dialog", name=re.compile(r"^Chat with "))
    if not panel.count():
        return
    for name in ("Close chat", "Close"):
        button = panel.get_by_role("button", name=re.compile(name))
        if button.count():
            try:
                button.first.click(timeout=4000)
                panel.first.wait_for(state="hidden", timeout=8000)
                return
            except Exception:
                continue
    page.keyboard.press("Escape")


def clear_canvas_overlays(page) -> None:
    """Close any drawer or palette floating over the pane.

    ``connect_nodes`` hit-tests each handle with ``elementFromPoint`` and fails
    when anything is on top of it, and both catalog drawers and the left-rail
    palettes float *over* the canvas. A step that opened one and then failed
    before closing it would otherwise poison every later authoring step with an
    occlusion error that looks like a React Flow bug - which is exactly what the
    first run of this file recorded.
    """
    for closer in (
        "Close Data Catalog drawer",
        "Close Node Catalog drawer",
        "Close Agent Catalog drawer",
    ):
        button = page.get_by_role("button", name=closer)
        if button.count():
            try:
                button.first.click(timeout=4000)
                page.wait_for_timeout(300)
            except Exception:
                # Best effort. The button was there a moment ago; it may have
                # closed itself or slid under an overlay before the click landed,
                # and this helper only has to leave the canvas usable.
                pass
    for kind in ("datasets", "packages", "agents"):
        try:
            close_tools_palette(page, kind)
        except Exception:
            # Each palette is closed blind, without first asking whether it is
            # open, so "not open" arrives here as an exception rather than a
            # no-op. That is the common case, not a problem.
            pass
    dismiss_toasts(page)


# Canvas geometry. A node is 525x350 flow units, so at zoom z it paints
# 525*z by 350*z screen pixels. Hand-picked drop offsets are how the first S5
# run broke: three nodes at zoom 0.6 spaced 330px apart left a 15px gap between
# a node's right edge and the next node's left edge, and React Flow hit-tests a
# handle with elementFromPoint - so the neighbour's input handle sat on top of
# the output handle and connect_nodes failed. Deriving the spacing from the zoom
# makes that arithmetic impossible to get wrong.
GRID_ZOOM = 0.5
_NODE_W, _NODE_H = 525 * GRID_ZOOM, 350 * GRID_ZOOM
_GRID_X0 = 190.0  # clears the ~150px left tool rail, which floats over the pane
_GRID_Y0 = 110.0
_GRID_GAP_X, _GRID_GAP_Y = 70.0, 50.0


def grid_at(col: int, row: int) -> tuple[float, float]:
    """Drop coordinates for one cell of a 3x3 grid at ``GRID_ZOOM``.

    Fits a 1280x800 frame: columns end at x=1116, rows at y=735.
    """
    return (
        _GRID_X0 + col * (_NODE_W + _GRID_GAP_X),
        _GRID_Y0 + row * (_NODE_H + _GRID_GAP_Y),
    )


def grid_drop(session: UserSession, template_id: str, col: int, row: int) -> str:
    """Drop a built-in tile into one grid cell, so handles never overlap."""
    return drop_node(session, template_id, grid_at(col, row), zoom=GRID_ZOOM)


def drop_node(session: UserSession, template_id: str, at: tuple[float, float],
              *, zoom: float | None = None) -> str:
    """Drop a built-in tile on the canvas, narrating it, and return its id."""
    page, tour = session.page, session.tour
    clear_canvas_overlays(page)
    if zoom is not None:
        set_canvas_zoom(page, zoom)
    else:
        _reset_zoom(page)
    tile = palette_tile(page, template_id)
    tour.focus(tile, hold=420)
    node_id = drag_to_canvas(page, tile, at=at)
    tour.beat(500)
    return node_id


def node_output_or_empty(page, node_id: str, *, timeout: float = 8000) -> str:
    """The node's inline output box, or ``""`` if it has none.

    ``utils.read_node_output_text`` waits for ``[data-curio-node-output]``, which
    only ``CodeEditor`` renders - so on a Vega-Lite or Autark node (``hasCode:
    false`` in the builtin manifest) it times out rather than returning nothing.
    A session must not stall on a node type that legitimately has no output box.
    """
    box = node_locator(page, node_id).locator("[data-curio-node-output]").first
    if not box.count():
        return ""
    try:
        box.wait_for(state="visible", timeout=timeout)
    except Exception:
        return ""
    return box.text_content() or ""


def node_failure_detail(page, node_id: str) -> str:
    """Whatever the app says about a failed node, from wherever it says it.

    Three surfaces, because different node kinds use different ones:

    * ``[data-curio-node-output]`` for anything with a code editor;
    * the notifications region, which is where ``vegaBehavior``'s catch block
      puts ``error.message`` (``showToast(error.message, 'error')``) - a Vega node
      has no output box at all, so the toast is the *only* place its reason
      appears;
    * ``data.warnings``, rendered as a list next to the node header.

    Returns ``""`` when none of them said anything, which is itself worth
    reporting: a node in an error state with no message anywhere.
    """
    parts: list[str] = []
    inline = read_node_error_text(node_locator(page, node_id)) or ""
    if inline.strip():
        parts.append(f"[output box] {' '.join(inline.split())}")
    toasts = page.locator('[aria-label="Notifications"] .toast')
    for i in range(toasts.count()):
        text = " ".join((toasts.nth(i).text_content() or "").split())
        if text:
            parts.append(f"[toast] {text}")
    warnings = node_locator(page, node_id).locator("li p")
    for i in range(min(warnings.count(), 5)):
        text = " ".join((warnings.nth(i).text_content() or "").split())
        if text:
            parts.append(f"[warning] {text}")
    return "\n".join(parts)


def run_and_report(session: UserSession, node_id: str, *, label: str,
                   node_type: str = "", timeout_ms: int | None = None) -> str:
    """Play a node, wait for it to settle, and file the outcome.

    Returns the output text. Unlike ``utils.run_node_and_wait`` this does not
    raise on a node error - the caller is usually interested in what the error
    *said*, and a session that stopped at the first red badge would test nothing
    past it.
    """
    page = session.page
    play_node(page, node_id)
    status = wait_for_node_settled(
        page, node_id, node_type=node_type, timeout_ms=timeout_ms
    )
    output = node_output_or_empty(page, node_id)
    if status == "error":
        detail = node_failure_detail(page, node_id)
        session.record(
            "node-error",
            f"{label} failed to run",
            severity="bug",
            detail_full=(
                f"node {node_id} ({node_type or 'unknown'}):\n"
                + (detail or "the app gave no reason on any surface "
                             "(no output box, no toast, no warning)")
            ),
        )
    return output


# ---------------------------------------------------------------------------
# Session runner
# ---------------------------------------------------------------------------

#: Per-session summaries, drained into the report by the module fixture below.
_SUMMARIES: list[dict] = []
_VIDEOS: dict[str, dict] = {}


@pytest.fixture(scope="module", autouse=True)
def stress_report():
    """Write the combined report once every session in this module has run.

    Sourced from the files on disk rather than from ``_SUMMARIES``, so the report
    covers sessions recorded by earlier invocations too. A session that crashes
    the interpreter therefore costs its own video, not the whole report - which
    is not hypothetical: the first full run died inside S3 and took S1's and S2's
    findings with it.
    """
    yield
    sessions, videos = collect_sessions()
    if not sessions:
        return
    path = write_report(sessions, videos=videos)
    _log(f"[usertest] report: {path} ({len(sessions)} session(s))")
    for name, paths in videos.items():
        for kind, video in paths.items():
            _log(f"[usertest] video {name} ({kind}): {video}")


def run_session(browser, frontend: str, backend: str, *, session_id: str,
                title: str, body) -> None:
    """Record one session and file its summary.

    The context is created here rather than taken from a fixture because a
    recording context needs ``record_video_dir``, and because the video is only
    flushed once the page is closed - so the close, the save and the transcode
    all have to happen inside one place that owns them.
    """
    if not _wanted(session_id):
        pytest.skip(f"session {session_id} not selected by CURIO_STRESS_SESSIONS")

    require_user_auth()
    raw_dir = os.path.join(out_dir(), "raw")
    os.makedirs(raw_dir, exist_ok=True)

    context = browser.new_context(
        viewport=VIDEO_SIZE,
        record_video_dir=raw_dir,
        record_video_size=VIDEO_SIZE,
    )
    page = context.new_page()
    # The drawers slide with translate3d and the providers read
    # prefers-reduced-motion through useSyncExternalStore, so a panel is only
    # reachable once the transition is collapsed.
    page.emulate_media(reduced_motion="reduce")
    # Native confirms (the unsaved-changes guard) would otherwise block forever.
    # Bound to a name rather than a lambda so S5 can take it off again: Playwright
    # runs every registered dialog handler, and whichever acts first decides, so
    # an accept-all left in place silently overrides a later dismiss. That is
    # exactly how this file once "found" a data-loss bug in a guard whose code
    # (UpMenu.handleNewWorkflow) is correct.
    def _accept_dialog(dialog):
        dialog.accept()

    page.on("dialog", _accept_dialog)

    session = UserSession(
        page, name=title, frontend=frontend, backend=backend, pace=_pace()
    )
    session.state["_accept_dialog"] = _accept_dialog
    session.tour.chapter("USER TEST", title, "An exploratory session, recorded.")

    try:
        body(session)
    except BaseException as exc:  # noqa: BLE001 - the take and the report survive
        session.record(
            "exception",
            f"the session itself aborted: {type(exc).__name__}: {exc}"[:300],
            severity="bug",
            detail_full=str(exc),
            step="(session body)",
        )
    finally:
        summary = session.summary()
        _SUMMARIES.append(summary)
        with open(
            os.path.join(out_dir(), f"session-{session_id}.json"), "w",
            encoding="utf-8",
        ) as fh:
            json.dump(summary, fh, indent=2)
        try:
            page.close()
            context.close()
        except Exception:
            # Already closed, or closed by a crashed browser. finalize_video
            # below still has to run: losing the recording of a session that
            # died is exactly the outcome this module exists to prevent.
            pass
        written = finalize_video(page, stem=f"curio-usertest-{session_id}")
        if written:
            _VIDEOS[title] = written
        _log(
            f"[usertest] {title}: {len(summary['steps'])} steps, "
            f"{len(summary['findings'])} findings, video={written or 'NONE'}"
        )
        assert written, f"no video was recorded for session {session_id}"


def _sign_up(session: UserSession, *, name: str, username: str) -> None:
    """Create this session's account through the real form."""
    signup_e2e_user(
        session.page, session.frontend, name=name, username=username,
        password="curio-usertest-2026",
    )


# ===========================================================================
# S1 - "First hour": the quick-start tutorial, then off-script
# ===========================================================================


class TestSessionFirstHour:
    """Someone who has read QUICK-START.md and nothing else."""

    def test_first_hour(self, browser, frontend_server, current_server):
        run_session(
            browser, frontend_server, current_server,
            session_id="s1", title="S1 First hour", body=self._body,
        )

    def _body(self, s: UserSession) -> None:
        page = s.page
        require_project_page()

        with s.step("Sign up for an account",
                    "The real /auth/signup form, not a test shortcut.",
                    chapter="Getting in"):
            _sign_up(s, name="Dana Reyes", username="dana_reyes")
            wait_for_projects_page(page, timeout=30000)

        with s.step("Open a new dataflow", "From the projects page."):
            open_new_workflow(page)
            page.locator("#tools-menu").wait_for(state="visible", timeout=45000)
            s.tour.beat(800)

        with s.step("Look over the node rail to see what is on offer",
                    "Twelve built-in tiles, grouped data / computation / views."):
            wrong_tile: list[str] = []
            nameless: list[str] = []
            for template_id in PALETTE_ICON_CLASS:
                info = palette_tile_identity(page, template_id)
                if not info.get("found"):
                    wrong_tile.append(f"{template_id}: no tile at that position")
                    continue
                if not info.get("iconOk"):
                    wrong_tile.append(
                        f"{template_id}: expected "
                        f"{PALETTE_ICON_CLASS[template_id]}, tile carries "
                        f"{info.get('icon')}"
                    )
                if not (info.get("ariaLabel") or info.get("title")
                        or info.get("accessibleText")):
                    nameless.append(
                        f"{template_id} (id={info.get('id')!r}, "
                        f"role={info.get('role')!r})"
                    )
            # A mismatch here means the positional lookup is wrong, which would
            # misattribute every later finding - so it fails the step rather than
            # being filed as an application defect.
            assert not wrong_tile, (
                "the palette tile lookup landed on the wrong tiles:\n  "
                + "\n  ".join(wrong_tile)
            )
            if nameless:
                s.record(
                    "a11y",
                    f"{len(nameless)} palette tiles have no accessible name",
                    severity="warning",
                    detail_full=(
                        "ToolsMenu.tsx:44 renders each tile as "
                        "<div id={tutorialID}> with no aria-label, no title "
                        "attribute and no text content; the only label is a "
                        "react-bootstrap tooltip that appears on hover. "
                        "packages/curio.builtin@1/manifest.json gives no "
                        "tutorialId to data-export, data-summary, js-computation "
                        "or spatial-join, so those four have no id either - "
                        "nothing in the DOM names them.\n\nTiles with no name:\n  "
                        + "\n  ".join(nameless)
                    ),
                )
            s.tour.focus(page.locator("#tools-menu"), hold=1400)

        loader_id = None
        with s.step("Drag a Data Loading node onto the canvas",
                    "The first tile on the rail.", chapter="The tutorial"):
            loader_id = drop_node(s, "data-loading", (150, 150))
            assert loader_id, "no node appeared"

        with s.step("Type the tutorial's pandas snippet",
                    "Nine rows, two columns, returned as a DataFrame."):
            set_node_code(page, loader_id, QUICKSTART_LOADER)

        with s.step("Run it", "The Python runs in the sandbox, not the browser."):
            output = run_and_report(
                s, loader_id, label="the tutorial loader",
                node_type="curio.builtin/data-loading",
            )
            if "Saved to file:" not in output:
                s.record(
                    "absent",
                    "the loader ran but reported no artifact",
                    severity="bug",
                    detail_full=f"output box said: {output!r}",
                )

        vega_id = None
        with s.step("Drag a Vega-Lite node in", "The chart half of the tutorial."):
            vega_id = drop_node(s, "vis-vega", (760, 150))

        # The first thing a real user does wrong: run the chart before there is
        # anything connected to it. Exploratory, because "an unconnected view
        # errors" and "an unconnected view sits idle" are both defensible.
        with s.step("Run the chart before connecting anything",
                    "What does an unwired view do?", expect="either",
                    quiet_console=True):
            play_node(page, vega_id)
            status = wait_for_node_settled(
                page, vega_id, node_type="curio.builtin/vis-vega",
                timeout_ms=30000,
            )
            detail = node_failure_detail(page, vega_id)
            if status == "error" and not detail:
                s.record(
                    "absent",
                    "an unconnected Vega node goes to an error state with no "
                    "message on any surface",
                    severity="warning",
                    detail_full=(
                        "vis-vega declares hasCode:false, so NodeEditor renders "
                        "no output box for it; vegaBehavior's catch block does "
                        "showToast(error.message), so a toast is the only place a "
                        "reason could appear - and none did. The user is left "
                        "with a red node and nothing to read."
                    ),
                )
            s.note(
                f"an unconnected Vega node settled as {status!r}; "
                f"it said: {detail[:300]!r}"
            )
            dismiss_toasts(page)

        with s.step("Connect the loader to the chart",
                    "Drag from the output handle to the input handle."):
            edge_id = connect_nodes(page, loader_id, vega_id)
            assert edge_id == f"reactflow__edge-{loader_id}out-{vega_id}in", edge_id
            _fit_view(page)

        with s.step("Wire the chart's output back into the loader",
                    "A loader has no input port, so this should be refused.",
                    expect="error"):
            connect_nodes(page, vega_id, loader_id, timeout=6000)

        with s.step("Paste the Vega-Lite spec into the Grammar tab",
                    "A bar chart over the two columns the loader returned."):
            set_node_grammar(page, vega_id, QUICKSTART_VEGA)

        with s.step("Run the chart", "Playing a node runs its ancestors first."):
            _center_on(page, vega_id, zoom=0.95)
            run_and_report(
                s, vega_id, label="the Vega-Lite chart",
                node_type="curio.builtin/vis-vega",
            )
            canvas = node_locator(page, vega_id).locator(f"#vega{vega_id} canvas")
            if not canvas.count():
                s.record(
                    "absent", "the Vega node drew no canvas", severity="bug",
                    detail_full="no <canvas> inside the node's vega container",
                )
            else:
                s.tour.beat(1600)

        # Now off-script: break it on purpose and see whether the app explains
        # itself. This is the single most common real-user experience.
        # NOT expect="error": this step's own body asserts that the node went
        # red and that the message named the SyntaxError, so the step completing
        # is the pass. expect="error" is for a step whose *gesture* the app must
        # refuse, where completing without incident is the defect.
        with s.step("Introduce a typo in the loader",
                    "A missing bracket - does the node say so clearly?",
                    quiet_console=True, chapter="Going wrong"):
            set_node_code(page, loader_id, BROKEN_LOADER)
            play_node(page, loader_id)
            status = wait_for_node_settled(
                page, loader_id, node_type="curio.builtin/data-loading",
                timeout_ms=60000,
            )
            detail = " ".join(
                (read_node_error_text(node_locator(page, loader_id)) or "").split()
            )
            assert status == "error", (
                f"a SyntaxError left the node in state {status!r}, not 'error'; "
                f"the box said {detail[:200]!r}"
            )
            if "SyntaxError" not in detail and "invalid syntax" not in detail:
                s.record(
                    "node-error",
                    "the syntax error was reported without naming itself",
                    severity="warning",
                    detail_full=f"the node's output box said: {detail[:800]}",
                )

        with s.step("Does the downstream chart know it is stale?",
                    "The loader is broken; running the chart must not succeed.",
                    quiet_console=True):
            # An assertion, not an observation. The loader produced a valid
            # artifact before the edit, so a naive "did it ever succeed" check
            # skips it and the chart reports Done off source that can no longer
            # produce it. playNodesUpTo now compares each ancestor's code against
            # the code that produced its output, so the broken loader is re-run
            # and takes the chart down with it.
            play_node(page, vega_id)
            status = wait_for_node_settled(
                page, vega_id, node_type="curio.builtin/vis-vega",
                timeout_ms=120000,
            )
            detail = node_failure_detail(page, vega_id)
            assert status == "error", (
                "the chart reported "
                f"{status!r} with a broken upstream, which means it reused the "
                "artifact the pre-edit loader produced.\n"
                f"the app said: {detail[:400]!r}"
            )
            s.note(f"the stale chain failed as it should: {detail[:200]!r}")
            dismiss_toasts(page)

        with s.step("Fix the typo and re-run", "Back to a working graph."):
            set_node_code(page, loader_id, QUICKSTART_LOADER)
            run_and_report(
                s, loader_id, label="the repaired loader",
                node_type="curio.builtin/data-loading",
            )
            run_and_report(
                s, vega_id, label="the chart after the repair",
                node_type="curio.builtin/vis-vega",
            )

        with s.step("Save the dataflow", "File > Save dataflow.",
                    chapter="Keeping it"):
            s.tour.click(_menu(page, "File"), force=True)
            save = page.get_by_role("button", name="Save dataflow", exact=True)
            save.wait_for(state="visible", timeout=15000)
            with page.expect_response(
                lambda r: "/api/projects" in r.url
                and r.request.method in ("POST", "PUT") and r.ok,
                timeout=40000,
            ):
                s.tour.click(save)
            save.wait_for(state="hidden", timeout=30000)

        with s.step("Reload the page and check the work came back",
                    "The graph, the code, and the spec should all survive."):
            url = page.url
            page.reload(wait_until="domcontentloaded")
            page.locator("#tools-menu").wait_for(state="visible", timeout=60000)
            page.wait_for_function(
                "() => document.querySelectorAll('.react-flow__node').length >= 2",
                timeout=60000,
            )
            _fit_view(page)
            nodes = {n["id"] for n in canvas_nodes(page)}
            assert {loader_id, vega_id} <= nodes, (
                f"after a reload of {url} the canvas holds {sorted(nodes)}"
            )
            restored = read_node_code(page, loader_id)
            assert "pd.DataFrame" in restored, (
                f"the loader's code did not survive the reload: {restored!r}"
            )
            grammar = read_node_grammar(page, vega_id)
            if '"mark"' not in grammar:
                s.record(
                    "absent",
                    "the Vega spec did not survive the reload",
                    severity="bug",
                    detail_full=f"the grammar editor holds: {grammar[:500]!r}",
                )
            s.tour.beat(1400)


# ===========================================================================
# S2 - "Real data": the Data Catalog, a CSV of the user's own, a longer chain
# ===========================================================================


class TestSessionRealData:
    """An analyst with a spreadsheet and a shapefile-shaped problem."""

    def test_real_data(self, browser, frontend_server, current_server):
        run_session(
            browser, frontend_server, current_server,
            session_id="s2", title="S2 Real data", body=self._body,
        )

    # -- drawer plumbing ----------------------------------------------------

    def _open_data_drawer(self, s: UserSession):
        page = s.page
        palette = open_tools_palette(page, "datasets")
        s.tour.click(
            palette.get_by_role("button", name="Browse Data Catalog +"), force=True
        )
        root = page.locator(DRAWER_DATA)
        root.wait_for(state="attached", timeout=15000)
        expect(root).to_have_attribute("aria-hidden", "false", timeout=10000)
        drawer = page.get_by_role("dialog").filter(
            has=page.get_by_role("heading", name="Data Catalog", exact=True)
        )
        expect(drawer).to_be_visible(timeout=10000)
        return drawer

    def _add_to_dataflow(self, s: UserSession, drawer, dataset_id: str):
        page = s.page
        card = drawer.locator(f'{CARD}[data-dataset-id="{dataset_id}"]')
        expect(card).to_have_count(1, timeout=20000)
        card.scroll_into_view_if_needed()
        s.tour.click(card.get_by_role("button", name="Add to dataflow", exact=True))
        with page.expect_response(
            lambda r: "/datasets/install" in r.url
            and r.request.method == "POST" and r.ok,
            timeout=90000,
        ):
            # The Data catalog confirms an add now (#196).
            accept_confirm_dialog(
                page, title=re.compile(r"^Add "), button="Add to dataflow"
            )
        expect(
            drawer.locator(f'{CARD}[data-dataset-id="{dataset_id}"]').get_by_role(
                "button", name="Remove from dataflow", exact=True
            )
        ).to_be_visible(timeout=30000)

    def _body(self, s: UserSession) -> None:
        page = s.page
        require_project_page()

        with s.step("Sign up and open a dataflow", chapter="Bringing data in"):
            _sign_up(s, name="Priya Nandakumar", username="priya_nandakumar")
            wait_for_projects_page(page, timeout=30000)
            open_new_workflow(page)
            page.locator("#tools-menu").wait_for(state="visible", timeout=45000)

        # --- the user's own CSV, uploaded through the interface -------------
        csv_path = _messy_csv_path()
        imported_id = None
        with s.step("Import my own CSV through the Data Catalog",
                    "A real spreadsheet export: BOM, quoted commas, a blank cell."):
            drawer = self._open_data_drawer(s)
            import_button = drawer.get_by_role("button", name="Import dataset")
            expect(import_button).to_be_visible(timeout=15000)
            accept = drawer.locator('input[type="file"]').get_attribute("accept")
            assert accept and ".csv" in accept, (
                f"the import control does not accept .csv: {accept!r}"
            )
            with page.expect_response(
                lambda r: r.url.endswith("/api/datasets/import")
                and r.request.method == "POST",
                timeout=90000,
            ) as imported:
                with page.expect_file_chooser() as chooser:
                    s.tour.click(import_button)
                chooser.value.set_files(csv_path)
            response = imported.value
            assert response.ok, (
                f"the import was rejected: HTTP {response.status} "
                f"{response.text()[:300]}"
            )
            imported_id = response.json().get("id")
            assert imported_id, f"the import returned no id: {response.json()}"
            s.tour.beat(1200)

        with s.step("Confirm it became a catalog entry",
                    "An import registers the dataset; it does not attach it."):
            drawer = page.get_by_role("dialog").filter(
                has=page.get_by_role("heading", name="Data Catalog", exact=True)
            )
            card = drawer.locator(f'{CARD}[data-dataset-id="{imported_id}"]')
            expect(card).to_have_count(1, timeout=30000)
            s.tour.focus(card, hold=1200)
            add = card.get_by_role("button", name="Add to dataflow", exact=True)
            if not add.count():
                s.record(
                    "absent",
                    "the imported dataset was auto-attached to the dataflow",
                    severity="warning",
                    detail_full=(
                        "the card offered no 'Add to dataflow', which means the "
                        "import attached itself - import is documented as "
                        "register-only"
                    ),
                )

        with s.step("Inspect what Curio made of my messy columns",
                    "Schema and preview, before trusting it downstream."):
            view = card.locator('button[aria-label^="View "]')
            if not view.count():
                s.note("the dataset card offered no detail view button")
            else:
                s.tour.click(view.first)
                tabs = page.get_by_role(
                    "navigation", name="Dataset detail sections"
                )
                expect(tabs).to_be_visible(timeout=25000)
                s.tour.beat(1600)
                body_text = " ".join(
                    (page.locator(
                        'section[aria-label="Dataset content"]'
                    ).text_content() or "").split()
                )
                for column in ("Neighborhood Name", "median income", "population"):
                    if column.lower() not in body_text.lower():
                        s.record(
                            "absent",
                            f"the detail panel does not mention the column "
                            f"{column!r}",
                            severity="warning",
                            detail_full=(
                                f"the imported CSV's header is "
                                f"{MESSY_CSV.splitlines()[0]!r}\n"
                                f"the panel showed: {body_text[:900]}"
                            ),
                        )
                page.locator(
                    'button[aria-label="Close"]:not([data-dismiss="toast"])'
                ).first.click()
                expect(tabs).to_have_count(0, timeout=15000)

        with s.step("Add it to this dataflow, and a published dataset too",
                    "My own CSV plus the Chicago boundary geojson."):
            drawer = page.get_by_role("dialog").filter(
                has=page.get_by_role("heading", name="Data Catalog", exact=True)
            )
            self._add_to_dataflow(s, drawer, imported_id)
            geo_card = drawer.locator(f'{CARD}[data-dataset-id="{GEO_DATASET}"]')
            if geo_card.count():
                self._add_to_dataflow(s, drawer, GEO_DATASET)
            else:
                s.note(
                    f"{GEO_DATASET} was not in the catalog; the geo half of this "
                    "session runs without it"
                )
            _close_data_drawer(page)

        loader_id = None
        with s.step("Drag my CSV onto the canvas",
                    "Curio writes the loader; does it read my file correctly?",
                    chapter="Loading it"):
            row = page.locator(f'#datasets-palette [data-dataset-id="{imported_id}"]')
            expect(row).to_have_count(1, timeout=30000)
            _reset_zoom(page)
            loader_id = drag_to_canvas(page, row, at=(140, 130))
            close_tools_palette(page, "datasets")
            code = read_node_code(page, loader_id)
            assert "read_csv" in code, (
                f"the generated loader for a .csv does not read_csv:\n{code}"
            )
            s.tour.beat(900)

        with s.step("Run the generated loader",
                    "The BOM and the quoted comma are the interesting part.",
                    quiet_console=True):
            run_and_report(
                s, loader_id, label="the loader for my imported CSV",
                node_type="curio.builtin/data-loading",
            )

        summary_id = None
        with s.step("Check what actually arrived",
                    "A Data Summary node reads the frame's shape and columns."):
            summary_id = drop_node(s, "data-summary", (700, 130))
            connect_nodes(page, loader_id, summary_id)
            output = run_and_report(
                s, summary_id, label="the data summary",
                node_type="curio.builtin/data-summary",
            )
            s.note(f"Data Summary reported: {' '.join(output.split())[:300]}")

        transform_id = None
        with s.step("Compute something from it",
                    "Income per capita, and the column names my CSV really has.",
                    chapter="Working with it"):
            transform_id = grid_drop(s, "data-transformation", 0, 1)
            connect_nodes(page, loader_id, transform_id)
            set_node_code(
                page, transform_id,
                "df = arg.copy()\n"
                "print('columns:', list(df.columns))\n"
                "print('rows:', len(df))\n"
                "num = [c for c in df.columns if 'income' in c.lower()]\n"
                "print('income-ish columns:', num)\n"
                "if num:\n"
                "    col = num[0]\n"
                "    df['income_filled'] = df[col].fillna(0)\n"
                "print(df.to_string(index=False))\n"
                "return df\n",
            )
            output = run_and_report(
                s, transform_id, label="the transformation over my CSV",
                node_type="curio.builtin/data-transformation",
            )
            flat = " ".join(output.split())
            if "Rogers Park, North" not in flat and "Rogers Park" not in flat:
                s.record(
                    "node-error",
                    "the quoted comma in the CSV did not survive the loader",
                    severity="bug",
                    detail_full=(
                        'the first data row is \'"Rogers Park, North",41250,...\'; '
                        f"the transformation printed:\n{output[:1200]}"
                    ),
                )
            if re.search(r"﻿|Neighborhood Name'?\]?\s*$", flat):
                s.note("the BOM may still be attached to the first column name")

        with s.step("Save this node's output as a dataset",
                    "The database toggle next to the play button."):
            # The real control is a <label> wrapping #save-output-<nodeId>, and
            # its aria-label carries the state - so reading it back is how the
            # click doubles as an assertion (see test_computed_json_output_e2e).
            toggle = node_locator(page, transform_id).locator(
                f"label:has(input#save-output-{transform_id})"
            )
            toggle.wait_for(state="visible", timeout=20000)
            before = toggle.get_attribute("aria-label") or ""
            s.tour.focus(toggle, hold=700)
            if "enabled" not in before:
                toggle.click()
                expect(toggle).to_have_attribute(
                    "aria-label", "Save output to Data Catalog enabled",
                    timeout=15000,
                )
            else:
                s.note(
                    "the save-output toggle was already on "
                    "(--save-node-outputs is set deployment-wide)"
                )
            s.tour.beat(800)
            run_and_report(
                s, transform_id, label="the transformation, saving its output",
                node_type="curio.builtin/data-transformation",
            )

        with s.step("Look for the computed dataset in the catalog",
                    "A node output should be reusable as an input."):
            drawer = self._open_data_drawer(s)
            cards = drawer.locator(CARD)
            expect(cards.first).to_be_visible(timeout=20000)
            titles = " | ".join(
                " ".join((cards.nth(i).text_content() or "").split())[:120]
                for i in range(min(cards.count(), 12))
            )
            s.note(f"catalog now shows {cards.count()} card(s): {titles[:600]}")
            _close_data_drawer(page)
            close_tools_palette(page, "datasets")

        with s.step("Export the result", "A Data Export node ends the chain."):
            clear_canvas_overlays(page)
            export_id = grid_drop(s, "data-export", 2, 1)
            connect_nodes(page, transform_id, export_id)
            set_node_code(
                page, export_id,
                "df = arg\n"
                "print('exporting', len(df), 'rows')\n"
                "df.to_csv('curio_usertest_export.csv', index=False)\n"
                "print('wrote curio_usertest_export.csv')\n",
            )
            run_and_report(
                s, export_id, label="the data export",
                node_type="curio.builtin/data-export",
            )

        with s.step("Run the whole graph from scratch",
                    "Play All, in topological order.", chapter="All of it"):
            _fit_view(page)
            if play_all_guarded(s, timeout_ms=300000):
                report_failed_nodes(s, label="Play All over the whole graph")
            s.tour.beat(1800)


# ===========================================================================
# S3 - "Maps and interaction": Autark/WebGPU, linked views, dashboard
# ===========================================================================


class TestSessionMapsAndInteraction:
    """Someone who opens the shipped examples before building anything."""

    def test_maps_and_interaction(self, browser, frontend_server, current_server):
        run_session(
            browser, frontend_server, current_server,
            session_id="s3", title="S3 Maps and interaction", body=self._body,
        )

    def _body(self, s: UserSession) -> None:
        page = s.page
        require_project_page()
        ctx = Ctx(page=page, tour=s.tour, frontend=s.frontend, backend=s.backend)

        with s.step("Sign up and open a dataflow", chapter="Opening an example"):
            _sign_up(s, name="Tom Achebe", username="tom_achebe")
            wait_for_projects_page(page, timeout=30000)
            open_new_workflow(page)
            page.locator("#tools-menu").wait_for(state="visible", timeout=45000)

        linked = os.path.join(
            REPO_ROOT, "docs", "examples",
            "03-vega-lite-linked-temporal-charts.json",
        )
        with s.step("Load the linked-charts example",
                    "File > Load dataflow, from the shipped examples."):
            load_example(s, linked, expected_nodes=4)

        with s.step("Run the whole thing", "Play All over 400k rows.",
                    quiet_console=True):
            if play_all_guarded(s, timeout_ms=360000):
                report_failed_nodes(s, label="the shipped linked-charts example")
            _fit_view(page, padding=0.12)
            s.tour.beat(1500)

        vega_ids = _node_ids_by_type(page, "vis-vega")
        with s.step("Check both charts actually drew",
                    "A view that renders blank is worse than one that errors."):
            if not vega_ids:
                s.record(
                    "absent", "the example has no Vega nodes on the canvas",
                    severity="bug", detail_full=str(canvas_nodes(page)),
                )
            for node_id in vega_ids:
                probe = page.evaluate(
                    """(nodeId) => {
                        const el = document.getElementById('vega' + nodeId);
                        const c = el && el.querySelector('canvas');
                        if (!c) return null;
                        return { w: c.width, h: c.height };
                    }""",
                    node_id,
                )
                if not probe or not probe["w"] or not probe["h"]:
                    s.record(
                        "absent",
                        f"Vega node {node_id} drew no sized canvas",
                        severity="bug",
                        detail_full=f"canvas probe returned {probe!r}",
                    )

        with s.step("Brush across a chart to drive the rest of the graph",
                    "A selection propagates upstream and re-runs the filter.",
                    expect="either", chapter="Linked views"):
            if not vega_ids:
                raise AssertionError("no chart to interact with")
            _center_on(page, vega_ids[0], zoom=1.0)
            plot = node_locator(page, vega_ids[0]).locator("canvas, svg").first
            box = plot.bounding_box()
            assert box, "the chart has no layout box"
            y = box["y"] + box["height"] * 0.7
            left = box["x"] + box["width"] * 0.2
            right = box["x"] + box["width"] * 0.85
            page.mouse.move(left, y)
            page.mouse.down()
            for i in range(1, 7):
                page.mouse.move(left + (right - left) * i / 6, y)
                s.tour.point_at(left + (right - left) * i / 6, y, hold=120)
            page.mouse.up()
            s.tour.beat(2500)
            s.note(
                "after brushing, node statuses were: "
                + ", ".join(
                    f"{n['id'][:8]}={node_status(page, n['id'])}"
                    for n in canvas_nodes(page)
                )
            )

        with s.step("Pin the views and switch to Dashboard Mode",
                    "The presentation half of the canvas.", chapter="Dashboard"):
            pinned = 0
            for node_id in vega_ids[:2]:
                pin = node_locator(page, node_id).locator(
                    'svg[role="button"].fa-circle, svg[role="button"].fa-circle-dot'
                ).first
                if not pin.count():
                    continue
                s.tour.focus(pin, hold=400)
                activate_header_icon(pin)
                pinned += 1
                s.tour.beat(600)
            if not pinned:
                s.record(
                    "absent", "no dashboard pin control on any Vega node",
                    severity="warning",
                    detail_full=(
                        "looked for svg[role=button].fa-circle / .fa-circle-dot "
                        "in each node header"
                    ),
                )
            s.tour.click(_menu(page, "View"), force=True)
            s.tour.click(
                page.get_by_role("button", name="Dashboard Mode", exact=True)
            )
            s.tour.beat(2600)
            exit_btn = page.locator('button[title="Exit Dashboard Mode"]')
            exit_btn.wait_for(state="visible", timeout=20000)
            s.tour.click(exit_btn)
            s.tour.beat(1200)
            _fit_view(page)

        with s.step("Open the provenance window",
                    "How this dataflow got to be the way it is."):
            s.tour.click(_menu(page, "Provenance"), force=True)
            s.tour.click(page.get_by_role("button", name="Provenance", exact=True))
            s.tour.beat(2200)
            page.keyboard.press("Escape")
            s.tour.beat(700)
            for label in ("Close", "close"):
                button = page.get_by_role("button", name=label, exact=True)
                if button.count():
                    try:
                        button.first.click(timeout=2500)
                        break
                    except Exception:
                        # Try the next spelling of "Close" instead. Failing to
                        # shut this panel is not what the step is testing.
                        pass

        # A map, on WebGPU, in a fresh dataflow.
        with s.step("Start over and load the Autark map example",
                    "An OSM extract parsed in the browser, rendered on WebGPU.",
                    chapter="Maps"):
            _new_dataflow_from_menu(ctx)
            load_example(
                s,
                os.path.join(
                    REPO_ROOT, "docs", "examples", "11-autark-pbf-loading.json"
                ),
                expected_nodes=2,
            )

        with s.step("Run the map", "DuckDB-WASM reads the .pbf, WebGPU draws it.",
                    quiet_console=True):
            if play_all_guarded(s, timeout_ms=420000):
                report_failed_nodes(s, label="the Autark map example")
            autark_ids = _node_ids_by_type(page, "autk-grammar")
            if autark_ids:
                _center_on(page, autark_ids[-1], zoom=1.2)
                s.tour.beat(3000)

        with s.step("Edit the map's grammar and re-run",
                    "The spec is the interface; an edit must stick.",
                    expect="either"):
            autark_ids = _node_ids_by_type(page, "autk-grammar")
            if not autark_ids:
                raise AssertionError("no Autark node to edit")
            node_id = autark_ids[-1]
            before = read_node_grammar(page, node_id)
            assert before.strip(), "the Autark grammar editor opened empty"
            marker = '"curio_usertest_marker": 1,'
            lines = before.split("\n")
            target = max(1, len(lines) // 2)
            page.evaluate(
                "(args) => {"
                "  const ed = (" + _GRAMMAR_EDITOR_JS + ")(args.nodeId);"
                "  ed.focus();"
                "  ed.setPosition({ lineNumber: args.line, column: 1 });"
                "  ed.executeEdits('usertest', [{ range: {"
                "    startLineNumber: args.line, startColumn: 1,"
                "    endLineNumber: args.line, endColumn: 1 },"
                "    text: args.text, forceMoveMarkers: true }]);"
                "}",
                {"nodeId": node_id, "line": target, "text": marker + "\n"},
            )
            page.wait_for_timeout(1800)
            after = read_node_grammar(page, node_id)
            assert marker.strip(",") in after, (
                "the grammar edit was reverted by the controlled value "
                "(this is issue #157's failure mode)"
            )
            s.note("the mid-document grammar edit stuck")
            # Now put it back and confirm the node still runs.
            set_node_grammar(page, node_id, before)
            run_and_report(
                s, node_id, label="the Autark node after a grammar round-trip",
                node_type="curio.builtin/autk-grammar", timeout_ms=300000,
            )

        with s.step("Squeeze the window and pan around hard",
                    "Does the chrome survive a small viewport?",
                    chapter="Rough handling"):
            page.set_viewport_size({"width": 900, "height": 620})
            s.tour.beat(1200)
            rail_fits = page.evaluate(
                """() => {
                    const rail = document.querySelector('#tools-menu');
                    if (!rail) return { found: false };
                    const r = rail.getBoundingClientRect();
                    return {
                        found: true,
                        bottom: Math.round(r.bottom),
                        viewport: window.innerHeight,
                        overflows: r.bottom > window.innerHeight + 1,
                    };
                }"""
            )
            if rail_fits.get("overflows"):
                s.record(
                    "absent",
                    "the left tool rail runs past the bottom of a 900x620 window",
                    severity="warning",
                    detail_full=json.dumps(rail_fits),
                )
            overflow = page.evaluate(
                "() => document.documentElement.scrollWidth "
                "- document.documentElement.clientWidth"
            )
            if overflow and overflow > 2:
                s.record(
                    "absent",
                    f"the page scrolls horizontally by {overflow}px at 900x620",
                    severity="warning",
                    detail_full=f"scrollWidth - clientWidth = {overflow}",
                )
            for zoom in (0.2, 2.5, 1.0):
                set_canvas_zoom(page, zoom)
                s.tour.beat(700)
            page.set_viewport_size(VIDEO_SIZE)
            s.tour.beat(900)
            _fit_view(page)


# ===========================================================================
# S4 - "Extending Curio": packages, libraries, agents, notebooks
# ===========================================================================


class TestSessionExtending:
    """A user who wants Curio to do something it does not ship with."""

    def test_extending(self, browser, frontend_server, current_server):
        run_session(
            browser, frontend_server, current_server,
            session_id="s4", title="S4 Extending Curio", body=self._body,
        )

    def _body(self, s: UserSession) -> None:
        page = s.page
        require_project_page()
        ctx = Ctx(page=page, tour=s.tour, frontend=s.frontend, backend=s.backend)

        with s.step("Sign up", chapter="Setting up"):
            _sign_up(s, name="Marcus Oyelaran", username="marcus_oyelaran")
            wait_for_projects_page(page, timeout=30000)

        with s.step("Configure the AI provider in AI Settings",
                    "Curio ships no endpoint; nothing AI works until this is set."):
            if not LLM_API_KEY:
                s.record(
                    "absent",
                    "no LLM key was configured, so the agent surfaces cannot be "
                    "exercised for real",
                    severity="warning",
                    detail_full=(
                        "put a key in .curio/tour-provider.json or "
                        "CURIO_TOUR_LLM_API_KEY"
                    ),
                )
            scene_ai_settings(ctx)
            s.note(f"provider configured: {LLM_BASE_URL} model={LLM_MODEL}")

        with s.step("Open a dataflow and build something worth packaging",
                    "A small transformation of my own."):
            open_new_workflow(page)
            page.locator("#tools-menu").wait_for(state="visible", timeout=45000)
            loader_id = drop_node(s, "data-loading", (150, 150))
            set_node_code(page, loader_id, QUICKSTART_LOADER)
            transform_id = drop_node(s, "data-transformation", (760, 150))
            connect_nodes(page, loader_id, transform_id)
            set_node_code(
                page, transform_id,
                "df = arg.copy()\n"
                "df['rank'] = df['b'].rank(ascending=False).astype(int)\n"
                "print(df.sort_values('rank').to_string(index=False))\n"
                "return df\n",
            )
            run_and_report(
                s, loader_id, label="the loader",
                node_type="curio.builtin/data-loading",
            )
            run_and_report(
                s, transform_id, label="my ranking transformation",
                node_type="curio.builtin/data-transformation",
            )
            _fit_view(page)
            s.state.update(loader=loader_id, transform=transform_id)

        # --- node packages -------------------------------------------------
        with s.step("Install a package from the Node Catalog",
                    "The example UI package: no python deps to resolve.",
                    chapter="Packages"):
            palette = open_tools_palette(page, "packages")
            s.tour.click(
                palette.get_by_role(
                    "button", name=re.compile(r"^Browse Node Catalog")
                ),
                force=True,
            )
            drawer = page.get_by_role("dialog").filter(
                has=page.get_by_role("heading", name="Node Catalog", exact=True)
            )
            expect(drawer).to_be_visible(timeout=20000)
            search = drawer.get_by_placeholder("Search packages, publishers, tags…")
            s.tour.type_into(search, "example", delay=70)
            card = drawer.locator(f'article[data-pkg-dir="{PKG_DIR}"]')
            expect(card).to_have_count(1, timeout=20000)
            with page.expect_response(
                lambda r: r.url.endswith("/api/packages/resolve"), timeout=60000
            ):
                card.get_by_role("button", name="Add to dataflow", exact=True).click()
            confirm_dialog = page.get_by_role("dialog").filter(
                has=page.get_by_role("heading", name=f'Add "{PKG_NAME}"', exact=True)
            )
            expect(confirm_dialog).to_be_visible(timeout=20000)
            with page.expect_response(
                lambda r: "/api/packages/projects/" in r.url
                and r.url.endswith("/install")
                and r.request.method == "POST" and r.ok,
                timeout=120000,
            ):
                s.tour.click(
                    confirm_dialog.get_by_role(
                        "button", name="Add to dataflow", exact=True
                    )
                )
            expect(confirm_dialog).to_have_count(0, timeout=60000)
            drawer.locator("header").get_by_role(
                "button", name="Close Node Catalog drawer"
            ).click()
            expect(page.locator(DRAWER_NODES)).to_have_count(0, timeout=10000)

        with s.step("Drag the package's node onto the canvas and wire it up",
                    "An installed package must be usable, not just listed."):
            row = page.locator(
                f'#packages-palette [data-pkg-palette-coords~="{PKG_DIR}"]'
            )
            expect(row).to_have_count(1, timeout=30000)
            _reset_zoom(page)
            pkg_node = drag_to_canvas(page, row, at=(200, 470))
            close_tools_palette(page, "packages")
            connect_nodes(page, s.state["transform"], pkg_node)
            s.state["pkg_node"] = pkg_node
            s.tour.beat(1200)

        with s.step("Work out how a custom-UI node is supposed to run",
                    "It has controls in its body rather than a code editor.",
                    expect="either"):
            # Deliberately not run_and_report: curio.example-ui declares
            # editor:"none" / hasWidgets:false, and styles.tsx only renders the
            # play control inside the `sendCodeToWidgets != undefined` block, so
            # this node has no Play button at all. Asserting one exists was this
            # session's own mistake on an earlier pass; what is worth recording
            # is whether the node explains itself and whether it receives data.
            node_el = node_locator(page, s.state["pkg_node"])
            has_play = node_el.locator("svg.fa-circle-play").count() > 0
            body = " ".join((node_el.text_content() or "").split())
            s.note(
                f"the package node renders a play control: {has_play}; "
                f"its body reads: {body[:220]!r}"
            )
            if not has_play and "run that node" not in body.lower():
                s.record(
                    "absent",
                    "a package node with no Play control gives the user no hint "
                    "how to run it",
                    severity="warning",
                    detail_full=(
                        "curio.example-ui/column-filter has no play button "
                        "(styles.tsx gates it on sendCodeToWidgets) and its body "
                        f"text does not say how to trigger it. Body: {body[:600]}"
                    ),
                )
            s.tour.beat(1000)

        with s.step("Open the library manager",
                    "Which python libraries this account has."):
            s.tour.click(_menu(page, "Data"), force=True)
            s.tour.click(
                page.get_by_role("button", name="Installed libraries", exact=True)
            )
            expect(
                page.get_by_role("heading", name="Installed libraries")
            ).to_be_visible(timeout=30000)
            s.tour.beat(1800)
            page.get_by_role("button", name="Close", exact=True).first.click()
            expect(
                page.get_by_role("heading", name="Installed libraries")
            ).to_have_count(0, timeout=15000)

        with s.step("Save my own node as a package",
                    "The cog on a node header > Save as package node.",
                    expect="either"):
            gear = node_locator(page, s.state["transform"]).get_by_role(
                "button", name=re.compile(r"^Node settings for ")
            )
            gear.wait_for(state="visible", timeout=30000)
            s.tour.click(gear)
            # U+2026, not three dots.
            save_as = page.get_by_role("button", name="Save as package node…")
            save_as.wait_for(state="visible", timeout=20000)
            s.tour.click(save_as)
            modal = page.get_by_role(
                "heading", name="Save as package node", level=2
            )
            modal.wait_for(state="visible", timeout=20000)
            s.tour.beat(1600)
            s.note(
                "the Save-as-package modal opened over the node built in this "
                "session"
            )

        with s.step("Press Escape to back out of the modal",
                    "The reflex every user has. It must close."):
            # ModalShell used to claim role="dialog" aria-modal="true" with no
            # keydown handler, so Escape did nothing - and since its backdrop
            # covers the viewport and takes pointer events, the next click went
            # to the backdrop and the app read as frozen. This session could not
            # open the Agent Catalog at all until the modal was closed properly.
            page.keyboard.press("Escape")
            s.tour.beat(1200)
            still_open = modal.count() and modal.first.is_visible()
            if still_open:
                # Leave the app usable so the rest of the session still runs.
                page.get_by_role("button", name="Close").first.click()
                modal.first.wait_for(state="hidden", timeout=10000)
            assert not still_open, (
                "Escape did not dismiss the modal; its backdrop now blocks "
                "every click behind it"
            )
            s.note("Escape closed the modal")
            s.tour.beat(700)
            clear_canvas_overlays(page)

        # --- agents --------------------------------------------------------
        with s.step("Add three agents to the dataflow",
                    "A node agent, a connection agent, and a canvas agent.",
                    chapter="Agents"):
            drawer = _open_agent_drawer(ctx)
            for coord in (AGENT_EXPLAINER, AGENT_CONNECTION, AGENT_BUILDER):
                _add_agent(ctx, drawer, coord, hold=700)
            drawer.get_by_role("button", name="Close Agent Catalog drawer").click()
            s.tour.beat(900)

        with s.step("Attach the node agent to a node", expect="either"):
            open_tools_palette(page, "agents")
            _drag_agent_to(
                ctx, AGENT_EXPLAINER,
                lambda: _node_client_point(page, s.state["transform"]),
            )
            toast = page.locator('[aria-label="Notifications"] .toast').first
            toast.wait_for(state="visible", timeout=45000)
            said = " ".join((toast.text_content() or "").split())
            if "attached to the node" not in said:
                s.record(
                    "absent",
                    "dropping a node agent on a node did not attach it to the node",
                    severity="bug",
                    detail_full=f"the app said: {said!r}",
                )
            dismiss_toasts(page)

        with s.step("Drop the node agent somewhere it does not belong",
                    "The canvas. A refusal must say so, not silently rebind.",
                    expect="either"):
            point = _empty_canvas_point(page)
            if not point:
                raise AssertionError("no empty canvas point found")
            _drag_agent_to(ctx, AGENT_EXPLAINER, point)
            toast = page.locator('[aria-label="Notifications"] .toast').first
            toast.wait_for(state="visible", timeout=45000)
            said = " ".join((toast.text_content() or "").split())
            if "attached to the canvas" in said:
                s.record(
                    "absent",
                    "a node-only agent was accepted onto the canvas",
                    severity="bug",
                    detail_full=(
                        "agent.node-explainer declares node targets only, so the "
                        f"canvas drop should have been refused. The app said: {said!r}"
                    ),
                )
            else:
                s.note(f"the canvas drop was answered with: {said!r}")
            dismiss_toasts(page)

        with s.step("Attach the connection agent to the edge", expect="either"):
            # The agents palette is a ~545px strip floating over the left of the
            # pane, and _edge_client_point rejects any candidate it occludes - so
            # an edge has to be framed clear of it before the drag. Fit first,
            # then nudge the viewport right if the only edges are still hidden.
            _fit_view(page, padding=0.25)
            point = _edge_client_point(page)
            if not point:
                page.evaluate(
                    """() => {
                        const rf = window.__curio_reactFlow;
                        if (!rf) return;
                        const vp = rf.getViewport();
                        rf.setViewport({ x: vp.x + 420, y: vp.y, zoom: vp.zoom });
                    }"""
                )
                page.wait_for_timeout(700)
                point = _edge_client_point(page)
            if not point:
                raise AssertionError(
                    "no point on any edge resolved; pickEdgeAtPoint would miss"
                )
            _drag_agent_to(ctx, AGENT_CONNECTION, lambda: _edge_client_point(page))
            toast = page.locator('[aria-label="Notifications"] .toast').first
            toast.wait_for(state="visible", timeout=45000)
            said = " ".join((toast.text_content() or "").split())
            if "attached to the connection" not in said:
                s.record(
                    "absent",
                    "dropping a connection agent on an edge did not attach it to "
                    "the connection",
                    severity="bug",
                    detail_full=f"the app said: {said!r}",
                )
            dismiss_toasts(page)
            close_tools_palette(page, "agents")

        with s.step("Ask the node agent a real question",
                    "A live model, over this dataflow.", expect="either",
                    quiet_console=True):
            badge = page.get_by_role(
                "button", name=re.compile(r"^Open chat with Node Explainer")
            ).first
            badge.wait_for(state="visible", timeout=25000)
            s.tour.click(badge)
            panel = page.get_by_role("dialog", name=re.compile(r"^Chat with "))
            expect(panel).to_be_visible(timeout=25000)
            composer = panel.get_by_label("Message this agent")
            s.tour.type_into(
                composer, "What does this node compute, in one sentence?", delay=25
            )
            if not LLM_API_KEY:
                s.note("no provider key; not sending the question")
                _close_agent_panel(s)
                return
            # Measured off the network, not off the transcript's shape. A turn
            # is one POST to
            # /api/agents/projects/<p>/attachments/<a>/run (or its SSE sibling),
            # so the request's status and duration are the fact; guessing from
            # bubble counts produced a "the agent never answered" claim on an
            # earlier pass that the DOM could not actually support.
            before = " ".join((panel.text_content() or "").split())
            started = time.monotonic()
            status = None
            try:
                # method + /run/stream, not just "/run": the browser sends a
                # CORS preflight first, and matching that reported a 30 ms
                # "answer" from an OPTIONS that never touched the model. The turn
                # is streamed (SSE), so this resolves on the response headers -
                # the rendered reply is checked separately below.
                with page.expect_response(
                    lambda r: r.request.method == "POST" and "/run" in r.url,
                    timeout=200000,
                ) as run_response:
                    composer.press("Enter")
                status = run_response.value.status
            except PlaywrightTimeoutError:
                s.record(
                    "absent",
                    "pressing Enter in the agent composer issued no run request "
                    "within 200s",
                    severity="bug",
                    detail_full=(
                        "expected a POST to "
                        "/api/agents/projects/<id>/attachments/<id>/run; none was "
                        "observed, so the composer did not dispatch the turn"
                    ),
                )
            elapsed = int((time.monotonic() - started) * 1000)

            if status is not None and status >= 400:
                s.record(
                    "node-error",
                    f"the agent run returned HTTP {status}",
                    severity="bug",
                    detail_full=(
                        f"POST .../run -> {status} after {elapsed} ms against "
                        f"{LLM_BASE_URL} model={LLM_MODEL}"
                    ),
                )
            elif status is not None:
                # The reply renders after the response resolves; wait for the
                # transcript to actually grow rather than assuming it did.
                grew = False
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    now = " ".join((panel.text_content() or "").split())
                    if len(now) > len(before) + 40:
                        grew = True
                        break
                    page.wait_for_timeout(1500)
                after = " ".join((panel.text_content() or "").split())
                if grew:
                    s.note(
                        f"the agent answered in {elapsed} ms (HTTP {status}); "
                        f"transcript grew {len(after) - len(before)} chars"
                    )
                    s.tour.beat(2500)
                else:
                    s.record(
                        "absent",
                        f"the agent run returned HTTP {status} but nothing was "
                        "rendered into the transcript",
                        severity="bug",
                        detail_full=(
                            f"run completed in {elapsed} ms with HTTP {status}, "
                            f"then 60s passed with the panel text unchanged at "
                            f"{len(before)} chars.\nPanel: {after[:1200]}"
                        ),
                    )
            _close_agent_panel(s)

        with s.step("Export this dataflow as a Jupyter notebook",
                    "Then check the file is a notebook.", expect="either",
                    chapter="Taking it elsewhere"):
            s.tour.click(_menu(page, "File"), force=True)
            candidates = page.get_by_role(
                "button", name=re.compile(r"notebook", re.I)
            )
            if not candidates.count():
                raise AssertionError(
                    "the File menu offers no notebook action; menu read: "
                    + " ".join(
                        (page.locator("[role='menu'], .dropdown-menu")
                         .first.text_content() or "").split()
                    )[:300]
                )
            with page.expect_download(timeout=60000) as download:
                s.tour.click(candidates.first)
            path = download.value.path()
            saved = os.path.join(out_dir(), "exported-dataflow.ipynb")
            download.value.save_as(saved)
            with open(saved, encoding="utf-8") as fh:
                notebook = json.load(fh)
            assert "cells" in notebook, (
                f"the export at {path} is not a notebook: keys={list(notebook)}"
            )
            # Coverage, not merely shape. The first version of this step asserted
            # only that a "cells" key existed, so a three-node dataflow that
            # exported one cell passed it.
            on_canvas = canvas_nodes(page)
            body = json.dumps(notebook)
            missing = [n["id"] for n in on_canvas if n["id"] not in body]
            assert not missing, (
                f"{len(missing)} of {len(on_canvas)} nodes never reached the "
                f"notebook: {missing}"
            )
            # And every code cell must be runnable: a node body ends in `return`,
            # which is a SyntaxError at a notebook's top level.
            for index, cell in enumerate(notebook["cells"]):
                if cell.get("cell_type") != "code":
                    continue
                source = cell["source"]
                if isinstance(source, list):
                    source = "".join(source)
                stray = [
                    line for line in source.splitlines()
                    if line.startswith("return ") or line.strip() == "return"
                ]
                assert not stray, (
                    f"cell {index} has a top-level return and cannot run: {stray}"
                )
            s.note(
                f"exported a notebook with {len(notebook['cells'])} cell(s) "
                f"covering all {len(on_canvas)} node(s) "
                f"to {os.path.basename(saved)}"
            )

        with s.step("Browse the catalogs as pages",
                    "/catalog/nodes, /catalog/data, /catalog/agents."):
            for path, heading in (
                ("/catalog/nodes", "Node"),
                ("/catalog/data", "Data"),
                ("/catalog/agents", "Agent Catalog"),
            ):
                page.goto(f"{s.frontend}{path}")
                page.wait_for_load_state("domcontentloaded")
                s.tour.beat(1600)
                body = " ".join((page.locator("body").text_content() or "").split())
                if heading.lower() not in body.lower():
                    s.record(
                        "absent",
                        f"{path} did not render anything mentioning {heading!r}",
                        severity="bug",
                        detail_full=body[:600],
                    )
                s.tour.scroll(600, steps=5)


# ===========================================================================
# S5 - "Abuse": deliberate misuse, no persona politeness
# ===========================================================================


class TestSessionAbuse:
    """Everything a careful user would not do."""

    def test_abuse(self, browser, frontend_server, current_server):
        run_session(
            browser, frontend_server, current_server,
            session_id="s5", title="S5 Abuse", body=self._body,
        )

    def _body(self, s: UserSession) -> None:
        page = s.page
        require_project_page()

        with s.step("Sign up and open a dataflow", chapter="Breaking things"):
            _sign_up(s, name="Rae Kowalczyk", username="rae_kowalczyk")
            wait_for_projects_page(page, timeout=30000)
            open_new_workflow(page)
            page.locator("#tools-menu").wait_for(state="visible", timeout=45000)

        with s.step("Build a three-node chain to abuse"):
            set_canvas_zoom(page, 0.6)
            loader = grid_drop(s, "data-loading", 0, 0)
            middle = grid_drop(s, "data-transformation", 1, 0)
            tail = grid_drop(s, "data-transformation", 2, 0)
            connect_nodes(page, loader, middle)
            connect_nodes(page, middle, tail)
            set_node_code(page, loader, QUICKSTART_LOADER)
            set_node_code(page, middle, "df = arg.copy()\ndf['c'] = df['b'] * 2\nreturn df\n")
            set_node_code(page, tail, "df = arg\nprint('tail sees', list(df.columns))\nreturn df\n")
            run_and_report(s, tail, label="the chain's tail",
                           node_type="curio.builtin/data-transformation")
            _fit_view(page)
            s.state.update(loader=loader, middle=middle, tail=tail)

        with s.step("Add a Data Summary and a second transformation",
                    "Setting up an illegal edge, not attempting it yet."):
            summary = grid_drop(s, "data-summary", 0, 1)
            # NOT spatial-join as the target: it declares two input ports, so its
            # handles are not called "in" and connect_nodes fails on the missing
            # handle rather than on type validation - which reads as a refusal
            # without ConnectionValidator ever being consulted.
            # data-transformation takes DATAFRAME/GEODATAFRAME/RASTER on a single
            # "in" handle and data-summary emits JSON, so this is a real mismatch
            # exercised through the normal handles.
            sink = grid_drop(s, "data-transformation", 2, 1)
            connect_nodes(page, s.state["loader"], summary)
            s.state["summary"], s.state["sink"] = summary, sink

        # Only the illegal gesture lives in this step: a failure in the setup
        # above would otherwise be recorded as "refused as it should be".
        with s.step("Connect two incompatible ports",
                    "Data Summary emits JSON; a transformation wants a frame.",
                    expect="error"):
            connect_nodes(
                page, s.state["summary"], s.state["sink"], timeout=6000
            )

        with s.step("Wire a cycle: tail back into the middle node",
                    "Type-compatible, so the validator allows it. Then what?",
                    expect="either", quiet_console=True):
            edge = connect_nodes(
                page, s.state["tail"], s.state["middle"], timeout=8000
            )
            s.note(f"the app accepted a cycle-forming edge: {edge}")
            play_node(page, s.state["tail"])
            status = wait_for_node_settled(
                page, s.state["tail"],
                node_type="curio.builtin/data-transformation",
                timeout_ms=90000,
            )
            s.note(f"running inside a cycle settled as {status!r}")

        with s.step("Delete the middle node with the Delete key",
                    "Then run what used to depend on it.", expect="either",
                    quiet_console=True):
            node_el = node_locator(page, s.state["middle"])
            box = node_el.bounding_box()
            assert box, "the node to delete has no layout box"
            # The header strip, not the corner: x=12 lands on the minimize icon
            # and selects nothing, which on an earlier pass produced a false
            # "Delete does not work" finding. test_canvas_delete_key_e2e clicks
            # x=300 at zoom 1; as a fraction it survives any zoom.
            node_el.click(position={"x": box["width"] * 0.55, "y": 6})
            page.wait_for_function(
                "(id) => { const el = document.querySelector("
                "  `.react-flow__node[data-id=\"${id}\"]`);"
                "  return !!el && el.classList.contains('selected'); }",
                arg=s.state["middle"],
                timeout=8000,
            )
            s.tour.beat(500)
            page.keyboard.press("Delete")
            s.tour.beat(900)
            remaining = {n["id"] for n in canvas_nodes(page)}
            if s.state["middle"] in remaining:
                # Not a defect: MainCanvas.handleNodesChange refuses a "remove"
                # change for any node that still has an edge, and says so in a
                # toast. Bisected against the shipped test (which never wires its
                # nodes): unconnected nodes delete on Delete *and* Backspace, a
                # connected one is refused on both. What is worth recording is
                # whether the user is actually told why.
                said = " ".join(
                    (page.locator('[aria-label="Notifications"] .toast')
                     .first.text_content() or "").split()
                ) if page.locator(
                    '[aria-label="Notifications"] .toast'
                ).count() else ""
                if "cannot be removed" in said.lower():
                    s.note(
                        "Delete on a wired node is refused by design, and the "
                        f"app explains it: {said[:200]!r}"
                    )
                else:
                    s.record(
                        "absent",
                        "Delete on a wired node did nothing and said nothing",
                        severity="bug",
                        detail_full=(
                            "MainCanvas.handleNodesChange refuses the remove and "
                            "is supposed to showToast('Connected boxes cannot be "
                            "removed...'), but no such toast was on screen. "
                            f"Toast region held: {said[:300]!r}"
                        ),
                    )
                dismiss_toasts(page)
            else:
                play_node(page, s.state["tail"])
                status = wait_for_node_settled(
                    page, s.state["tail"],
                    node_type="curio.builtin/data-transformation",
                    timeout_ms=90000,
                )
                s.note(
                    f"after its upstream was deleted, the tail settled as {status!r}"
                )

        with s.step("Import a library nobody installed",
                    "Runtime install is off under --auth, so this must explain "
                    "itself.", quiet_console=True):
            probe = grid_drop(s, "computation-analysis", 0, 2)
            set_node_code(
                page, probe,
                "import curio_definitely_not_a_real_package as nope\n"
                "return nope.anything()\n",
            )
            play_node(page, probe)
            status = wait_for_node_settled(
                page, probe, node_type="curio.builtin/computation-analysis",
                timeout_ms=120000,
            )
            detail = " ".join(
                (read_node_error_text(node_locator(page, probe)) or "").split()
            )
            assert status == "error", (
                f"a missing import left the node {status!r}, and said: {detail[:200]}"
            )
            if not re.search(r"(ModuleNotFound|No module named|install)", detail, re.I):
                s.record(
                    "node-error",
                    "a missing module was reported without naming the module or "
                    "how to install it",
                    severity="warning",
                    detail_full=detail[:900],
                )

        with s.step("Generate a large frame",
                    "250k rows through one edge.", quiet_console=True):
            big = grid_drop(s, "data-loading", 2, 2)
            set_node_code(
                page, big,
                "import pandas as pd, numpy as np\n"
                "n = 250_000\n"
                "df = pd.DataFrame({\n"
                "    'i': np.arange(n),\n"
                "    'x': np.random.default_rng(7).normal(size=n),\n"
                "    'g': np.random.default_rng(8).integers(0, 40, size=n),\n"
                "})\n"
                "print('built', len(df), 'rows')\n"
                "return df\n",
            )
            started = time.monotonic()
            run_and_report(
                s, big, label="a 250k-row loader",
                node_type="curio.builtin/data-loading", timeout_ms=240000,
            )
            elapsed = int((time.monotonic() - started) * 1000)
            output = node_output_or_empty(page, big)
            if "built 250000 rows" not in " ".join(output.split()):
                s.record(
                    "absent",
                    "the 250k-row node settled without printing what it built",
                    severity="warning",
                    detail_full=(
                        f"settled in {elapsed} ms; output box held: {output[:600]!r}. "
                        "A settle this fast with no stdout suggests the status "
                        "was read before the run began."
                    ),
                )
            s.note(f"a 250k-row frame took {elapsed} ms end to end")
            if elapsed > 120000:
                s.record(
                    "slow",
                    f"a 250k-row DataFrame took {elapsed // 1000}s to run and store",
                    severity="warning",
                    detail_full=f"elapsed {elapsed} ms",
                )

        with s.step("Double-click Play on the same node",
                    "Two runs of one node at once.", expect="either",
                    quiet_console=True):
            play = node_locator(page, s.state["loader"]).locator(
                "svg.fa-circle-play"
            ).first
            if not play.count():
                raise AssertionError("no play control on the loader")
            play.dispatch_event("click")
            play.dispatch_event("click")
            status = wait_for_node_settled(
                page, s.state["loader"], node_type="curio.builtin/data-loading",
                timeout_ms=120000,
            )
            s.note(f"a double-clicked play settled as {status!r}")

        with s.step("Navigate away in the middle of a run",
                    "Then come back and see what state the node is in.",
                    expect="either", quiet_console=True):
            slow = grid_drop(s, "computation-analysis", 1, 2)
            set_node_code(
                page, slow,
                "import time\n"
                "time.sleep(12)\n"
                "print('finished after a nap')\n"
                "return 1\n",
            )
            dataflow_url = page.url
            play_node(page, slow)
            page.wait_for_timeout(1500)
            page.goto(f"{s.frontend}/projects")
            page.wait_for_load_state("domcontentloaded")
            wait_for_projects_page(page, timeout=30000)
            s.tour.beat(1500)
            page.goto(dataflow_url)
            page.wait_for_load_state("domcontentloaded")
            page.locator("#tools-menu").wait_for(state="visible", timeout=60000)
            page.wait_for_timeout(3000)
            still_there = {n["id"] for n in canvas_nodes(page)}
            s.note(
                f"after leaving mid-run and returning, the canvas holds "
                f"{len(still_there)} node(s); the slow node is "
                f"{'present' if slow in still_there else 'GONE'}"
            )
            if slow in still_there:
                s.note(f"its status on return was {node_status(page, slow)!r}")

        with s.step("Open the same dataflow in a second tab",
                    "Two tabs, one project, both editing.", expect="either"):
            second = page.context.new_page()
            try:
                second.goto(page.url, wait_until="domcontentloaded")
                second.locator("#tools-menu").wait_for(state="visible", timeout=60000)
                second.wait_for_timeout(2500)
                here = len(canvas_nodes(page))
                there = len(canvas_nodes(second))
                s.note(
                    f"tab one shows {here} node(s), tab two shows {there}"
                )
                if there and there != here:
                    s.record(
                        "absent",
                        "two tabs on one dataflow disagree about the node count",
                        severity="warning",
                        detail_full=f"tab1={here} tab2={there}",
                    )
            finally:
                second.close()
                s.tour.beat(600)

        with s.step("Leave with unsaved changes and refuse the guard",
                    "Dismissing the confirm must keep me on the canvas.",
                    expect="either"):
            set_node_code(
                page, s.state["loader"],
                QUICKSTART_LOADER + "# an unsaved edit\n",
            )
            s.tour.beat(700)
            # Answer this one confirm with Cancel, then restore the accept-all
            # handler the rest of the session relies on.
            handled: list[str] = []

            def _dismiss(dialog):
                handled.append(dialog.message)
                dialog.dismiss()

            accept_all = s.state.get("_accept_dialog")
            if accept_all is not None:
                page.remove_listener("dialog", accept_all)
            page.on("dialog", _dismiss)
            try:
                s.tour.click(_menu(page, "File"), force=True)
                new_btn = page.get_by_role("button", name="New dataflow", exact=True)
                if not new_btn.count():
                    raise AssertionError("File menu has no 'New dataflow'")
                new_btn.click()
                page.wait_for_timeout(2500)
                if handled:
                    s.note(f"the guard asked: {handled[0][:200]!r}")
                    if "/dataflow/new" in page.url:
                        s.record(
                            "absent",
                            "cancelling the unsaved-changes guard still navigated "
                            "away",
                            severity="bug",
                            detail_full=f"landed on {page.url}",
                        )
                else:
                    s.note(
                        "no unsaved-changes confirm appeared when leaving with an "
                        f"unsaved edit; now at {page.url}"
                    )
            finally:
                page.remove_listener("dialog", _dismiss)
                if accept_all is not None:
                    page.on("dialog", accept_all)
                s.tour.beat(800)
