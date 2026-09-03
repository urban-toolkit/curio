"""Record a stress-test screencast of Curio: every surface, every node, every agent.

This is not a regression test. Like ``test_feature_tour_video.py`` it borrows the
e2e harness because that harness already knows how to boot the stack, launch a
WebGPU-capable Chrome and drive React Flow without fighting it. Unlike the tour,
it is adversarial and exhaustive: it instantiates *every* node type (built-in and
catalog), authors new ones from the canvas, installs *every* catalog dataset,
runs *every* built-in agent, and deliberately walks the paths that are supposed
to refuse.

The video is half the deliverable. The other half is ``.curio/stress/ISSUES.md``,
written by :mod:`stress`, where every anomaly the run heard - a console error, a
5xx, an error toast, a node that finished red, a step that raised - is listed
with the offset into the chapter's recording where it happened.

Six chapters, six recordings, one pytest session::

    # from utk_curio/backend, with PYTHONPATH=<repo root>
    CURIO_STRESS=1 pytest tests/test_frontend/test_stress_tour_video.py -s -v

    # one chapter, slower
    CURIO_STRESS=1 CURIO_STRESS_CHAPTERS=agents CURIO_STRESS_SPEED=1.0 \
      pytest tests/test_frontend/test_stress_tour_video.py -s

===============================  ==============================================
``CURIO_STRESS=1``               required; the module skips otherwise
``CURIO_STRESS_CHAPTERS``        comma-separated chapter ids (default: all)
``CURIO_STRESS_OUT``             output directory (default ``.curio/stress/``)
``CURIO_STRESS_SPEED``           pacing multiplier, >1 is faster (default 1.6)
===============================  ==============================================

The AI provider is read from ``.curio/tour-provider.json`` or
``CURIO_TOUR_LLM_*``, exactly as the feature tour reads it, so no credential
lives in the repository. Without one the ``agents`` chapter still records the
surfaces and says on camera that it cannot run a turn.

The chapters share one account, which is why ``TestCurioStressTour`` is listed in
``fixtures._SHARED_SESSION_CLASSES``: the autouse ``e2e_clean_db`` would
otherwise truncate the user out from under the browser between chapters.
"""
from __future__ import annotations

import json
import os
import re
import time

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect

from . import stress
from .stress import (
    DRAWER_AGENTS,
    DRAWER_DATA,
    DRAWER_NODES,
    REPO_ROOT,
    VIDEO_SIZE,
    StressRun,
    Tour,
    ai_field,
    builtin_tile,
    center_on,
    close_drawer,
    drag_agent_to,
    drawer_presentation_signals,
    edge_client_point,
    empty_canvas_point,
    expect_attach_toast,
    finalize_chapter_video,
    fit_view,
    frame_nodes,
    load_example,
    log,
    menu,
    node_client_point,
    node_ids_by_type,
    node_statuses,
    open_agent_drawer,
    open_data_drawer,
    open_node_drawer,
    out_dir,
    package_row,
    play_all,
    report_errored_nodes,
    reset_zoom,
    write_report,
)
from .utils import (
    _wait_for_reactflow_ready,
    accept_confirm_dialog,
    activate_header_icon,
    api_json,
    assert_vega_canvas_rendered,
    canvas_nodes,
    connect_nodes,
    dismiss_toasts,
    drag_to_canvas,
    node_locator,
    open_tools_palette,
    close_tools_palette,
    play_node,
    read_node_error_text,
    read_node_output_text,
    require_owner_view,
    run_node_and_wait,
    set_canvas_zoom,
    set_node_code,
    stub_db_login,
    wait_for_node_done,
    wait_for_node_settled,
    wait_for_projects_page,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("CURIO_STRESS") != "1",
    reason="stress-tour recording only runs with CURIO_STRESS=1",
)


# ---------------------------------------------------------------------------
# The account and the content the chapters use
# ---------------------------------------------------------------------------

USER_NAME = "Robin Stressfield"
USER_LOGIN = "robin_stress"
USER_EMAIL = "robin_stress@example.org"
USER_PASSWORD = "curio-stress-2026"

#: Carried between chapters. Each chapter can also run alone, in which case it
#: re-derives what it needs through the DB stub.
SHARED: dict = {}

PROVIDER_FILE = os.path.join(REPO_ROOT, ".curio", "tour-provider.json")
_DEFAULT_BASE_URL = "https://sage200.evl.uic.edu/"
_DEFAULT_MODEL = "gemma4"

EXAMPLES = os.path.join(REPO_ROOT, "docs", "examples")
DATAFLOWS = os.path.join(EXAMPLES, "dataflows")
EXAMPLE_DATA = os.path.join(EXAMPLES, "data")
NOTEBOOK = os.path.join(DATAFLOWS, "test_notebook.ipynb")

#: The dataset the authoring chapters build on: three rows, two numeric columns,
#: and a generated loader that only needs pandas.
DATASET_ID = "data.urbanlab.acs-neighborhood-profile"

DATAFLOW_GOAL = (
    "Stress every surface: compare income per capita across neighborhoods, "
    "map the heat exposure, and flag the outliers."
)

TRANSFORM_CODE = (
    "df = arg\n"
    'df["income_per_capita"] = (df["median_income"] / df["population"]).round(2)\n'
    'print(df.sort_values("median_income", ascending=False).to_string(index=False))\n'
    "return df\n"
)

RAISING_CODE = (
    "# deliberately wrong: the stress run wants to see the Error tab\n"
    'raise ValueError("stress: this node is supposed to fail")\n'
)

CSV_TRANSFORM_CODE = (
    "df = arg" + chr(10)
    + 'df["trips_per_minute"] = (df["trips"] / df["avg_duration_min"]).round(2)' + chr(10)
    + 'print(df.sort_values("trips", ascending=False).to_string(index=False))' + chr(10)
    + "return df" + chr(10)
)

VEGA_SPEC = json.dumps(
    {
        "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
        "mark": "bar",
        "encoding": {
            "x": {"field": "neighborhood", "type": "nominal",
                  "axis": {"labelAngle": 0}},
            "y": {"field": "income_per_capita", "type": "quantitative"},
        },
    },
    indent=2,
)


#: The Python distributions each catalog package declares. The stress run
#: installs packages through the *interface*, so the only way to know the
#: install really did the work - rather than finding the dependency already
#: sitting in the interpreter from an earlier `curio.py setup` - is to look for
#: the module before and after. Backend, sandbox and this pytest process all run
#: from the same interpreter, so find_spec here sees what a node would see.
PACKAGE_DEPS: dict[str, tuple[str, ...]] = {
    "curio.example-ui@1": (),
    "curio.weather@1": ("pythermalcomfort", "rasterio", "rasterstats"),
    "ai.urbanlab.uhvi@1": ("rasterio",),
    "curio.streetvision@1": (
        "torch", "transformers", "ultralytics", "huggingface_hub",
    ),
}


def _present_modules(names) -> set[str]:
    """Which of *names* are importable right now, ignoring any stale caches."""
    import importlib
    import importlib.util

    importlib.invalidate_caches()
    present = set()
    for name in names:
        try:
            if importlib.util.find_spec(name) is not None:
                present.add(name)
        except (ImportError, ValueError):
            pass
    return present


def _load_provider() -> tuple[str, str, str]:
    """``(baseUrl, model, apiKey)`` from the local file, then env, then defaults.

    Same contract as the feature tour's loader: the endpoint and model are not
    secret and have defaults, the key is read from outside the repository so a
    recording never requires a committed credential.
    """
    data: dict = {}
    try:
        with open(PROVIDER_FILE, encoding="utf-8") as handle:
            data = json.load(handle) or {}
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as exc:
        log(f"[stress] ignoring unreadable {PROVIDER_FILE}: {exc}")
    return (
        str(data.get("baseUrl") or os.environ.get("CURIO_TOUR_LLM_BASE_URL")
            or _DEFAULT_BASE_URL),
        str(data.get("model") or os.environ.get("CURIO_TOUR_LLM_MODEL")
            or _DEFAULT_MODEL),
        str(data.get("apiKey") or os.environ.get("CURIO_TOUR_LLM_API_KEY") or ""),
    )


LLM_BASE_URL, LLM_MODEL, LLM_API_KEY = _load_provider()


# ---------------------------------------------------------------------------
# Small shared beats
# ---------------------------------------------------------------------------


def _token(run: StressRun) -> str:
    return SHARED.get("token", "")


def _enter_project(run: StressRun, *, name: str, fresh: bool = True) -> dict:
    """Sign the stress user in through the DB stub and open a dataflow.

    Chapters after the first do not spend screen time re-doing the signup the
    first one already filmed, but they still need a real session cookie and a
    project of their own.
    """
    login = stub_db_login(
        run.page,
        frontend_url=run.frontend,
        backend_url=run.backend,
        username=USER_LOGIN,
        name=USER_NAME,
        password=USER_PASSWORD,
        email=USER_EMAIL,
        project_name=name if fresh else None,
    )
    SHARED["token"] = login["token"]
    SHARED["user"] = login["user"]
    project = login.get("project") or SHARED.get("project")
    assert project, "no project to open"
    SHARED["project"] = project
    run.page.goto(f"{run.frontend}/dataflow/{project['id']}")
    run.page.wait_for_load_state("domcontentloaded")
    _wait_for_canvas(run.page)
    require_owner_view(run.page)
    return login


def _pan(page, dx: float, dy: float = 0.0) -> None:
    """Shift the viewport so the next drop lands on fresh canvas."""
    page.evaluate(
        """({ dx, dy }) => {
            const rf = window.__curio_reactFlow;
            if (!rf) return;
            const vp = rf.getViewport();
            rf.setViewport({ x: vp.x + dx, y: vp.y + dy, zoom: vp.zoom },
                           { duration: 320 });
        }""",
        {"dx": dx, "dy": dy},
    )
    page.wait_for_timeout(380)


def _edge_count(page) -> int:
    return page.evaluate(
        "() => (window.__curio_reactFlow "
        "? window.__curio_reactFlow.getEdges().length : -1)"
    )


def _expect_connection_refused(run: StressRun, source: str, target: str, *,
                               what: str, source_handle: str = "out",
                               target_handle: str = "in") -> None:
    """Attempt a connection that should be rejected, and judge it by the graph.

    Not by whether ``connect_nodes`` raised: it also raises when a handle is
    covered or off screen, so treating any exception as "correctly refused"
    would let a harness problem masquerade as a passing guard. The edge count is
    the thing that actually answers the question.
    """
    page = run.page
    before = _edge_count(page)
    try:
        connect_nodes(page, source, target, source_handle=source_handle,
                      target_handle=target_handle)
    except Exception as exc:  # noqa: BLE001
        message = str(exc)
        if "not the topmost element" in message or "no layout box" in message:
            run.note(f"could not attempt {what}: {message[:200]}",
                     step=what, severity="note")
            return
    page.wait_for_timeout(900)
    after = _edge_count(page)
    if after > before:
        run.note(
            f"{what}: the connection was ACCEPTED (edges {before} -> {after})",
            step=what, severity="error",
        )
        run.snap(f"accepted-{_slug_label(what)}")
    dismiss_toasts(page)


def _slug_label(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]


def _close_modal(page, *, expect_escape_to_work: bool = False) -> bool:
    """Dismiss a ModalShell dialog and report whether Escape did it.

    The count has to be *snapshotted* before the key: a Playwright locator is
    lazy, so reading ``dialog.count()`` after the press re-queries the live DOM
    and compares the post-Escape state against itself - which is never smaller,
    so the helper reported "Escape did nothing" even once ModalShell handled it.

    The drawer underneath is also a ``role="dialog"``, which is what makes the
    count the right signal: a working Escape closes the modal and leaves the
    drawer, so the count drops by exactly one rather than to zero.
    """
    before = page.get_by_role("dialog").count()
    if not before:
        return True
    page.keyboard.press("Escape")
    page.wait_for_timeout(600)
    escape_worked = page.get_by_role("dialog").count() < before
    if not escape_worked:
        closer = page.get_by_role("button", name="Close", exact=True)
        if closer.count():
            closer.last.click(force=True)
            page.wait_for_timeout(700)
    return escape_worked


def _collapsed_accordion_count(page, root_selector: str) -> int:
    return page.locator(f"{root_selector} details:not([open])").count()


def _palette_template_ids(page) -> set[str]:
    rows = page.locator("#packages-palette [data-pkg-template-id]")
    return {
        rows.nth(i).get_attribute("data-pkg-template-id") or ""
        for i in range(rows.count())
    } - {""}


def _expand_accordions(page, root_selector: str) -> None:
    """Open every collapsed accordion under *root_selector*.

    PaletteAccordion is a native ``<details>``/``<summary>``. A collapsed one
    keeps its rows in the DOM but not visible, and both ``drag_to_canvas`` and
    Playwright's own actionability checks wait for *visible* - so an unopened
    package section makes its node types look absent rather than hidden.
    Clicking the summary rather than setting ``open`` keeps ``onSummaryClick``
    in the loop.
    """
    for _ in range(16):
        closed = page.locator(f"{root_selector} details:not([open]) > summary")
        if not closed.count():
            return
        try:
            closed.first.click(force=True)
        except Exception:  # noqa: BLE001
            return
        page.wait_for_timeout(250)


def _wait_for_canvas(page, *, timeout: float = 90000) -> None:
    """Wait until the dataflow canvas is interactive.

    Not ``_wait_for_reactflow_ready``: that helper's first act is to wait for a
    ``.react-flow__node``, which a brand-new dataflow does not have, so it burns
    its whole timeout on an empty canvas. It is still the right call once nodes
    exist, and this defers to it then.
    """
    page.locator("#tools-menu").wait_for(state="visible", timeout=timeout)
    page.locator(".react-flow__pane").wait_for(state="visible", timeout=timeout)
    page.wait_for_timeout(600)
    if page.locator(".react-flow__node").count():
        _wait_for_reactflow_ready(page)


def _clear_canvas(run: StressRun) -> int:
    """Delete every node through its own header control.

    React Flow binds no select-all, so Ctrl+A does nothing here; and the Delete
    key is guarded for a node that still has edges. Pressing each node's own
    delete icon is what a user would do, and it reports how many refused.
    """
    page = run.page
    for node in list(canvas_nodes(page)):
        icon = _header_icon(page, node["id"], "Delete node")
        if not icon.count():
            run.note(
                f"node {node['id']} ({node['nodeType']}) has no reachable Delete "
                "control in its header",
                step="clear the canvas", severity="error",
            )
            continue
        try:
            activate_header_icon(icon)
            page.wait_for_timeout(300)
        except Exception:  # noqa: BLE001 - a guarded node is a finding, not a stop
            pass
    dismiss_toasts(page)
    survivors = canvas_nodes(page)
    if survivors:
        run.note(
            "these nodes ignored their own header Delete control on an "
            "unconnected canvas: "
            + ", ".join(f"{n['id']} ({n['nodeType']})" for n in survivors),
            step="clear the canvas", severity="error",
        )
        run.snap("delete-refused")
    return len(survivors)


#: Node-header icons are FontAwesome SVGs. Their ``title`` prop is consumed by
#: FontAwesomeIcon (it is in DEFAULT_PROP_KEYS) rather than forwarded as a DOM
#: attribute, so ``[title="Delete node"]`` matches nothing. The icon class is
#: the handle the feature tour already relies on for the dashboard pin.
HEADER_ICONS = {
    "Minimize": ("fa-minus",),
    "Comments": ("fa-comments",),
    "Delete node": ("fa-xmark",),
    "Save template": ("fa-floppy-disk",),
    "Pin to dashboard": ("fa-circle",),
    "Unpin from dashboard": ("fa-circle-dot",),
}


def _header_icon(page, node_id: str, title: str):
    """One node-header icon, addressed the only way that is stable.

    Tries the accessible name first - FontAwesome renders ``title`` as a
    ``<title>`` child with ``aria-labelledby``, which *should* give the button a
    name - and falls back to the icon class, which is what actually works today.
    """
    node = node_locator(page, node_id)
    named = node.get_by_role("button", name=title, exact=True)
    if named.count():
        return named.first
    classes = HEADER_ICONS.get(title, ())
    selector = ", ".join(f'svg[role="button"].{cls}' for cls in classes)
    if not selector:
        return node.locator(f'[title="{title}"]').first
    # fa-circle also prefix-matches fa-circle-dot in a class selector? No: CSS
    # class selectors match whole tokens, so .fa-circle never matches
    # class="fa-circle-dot". The two pin states stay distinguishable.
    return node.locator(selector).first


#: NodeEditor renders its pills as react-bootstrap ``Nav.Link``s keyed by
#: eventKey, which is the handle ``set_node_code`` already uses. They carry no
#: accessible name, so a role+name lookup finds nothing.
EDITOR_TABS = {
    "Code": "code",
    "Widgets": "widgets",
    "Grammar": "grammar",
    "Provenance": "provenance",
    "Output": "output",
}


def _editor_tab(page, node_id: str, name: str):
    """One of the vertical editor pills on a node (Code, Grammar, Output, ...)."""
    key = EDITOR_TABS[name]
    return node_locator(page, node_id).locator(
        f'.nav-link[data-rr-ui-event-key="{key}"]'
    )


def _catalog(run: StressRun, path: str) -> dict:
    return api_json(f"{run.backend}{path}", _token(run))


def _drop_grid(run: StressRun, sources, *, per_row: int = 2):
    """Drop a sequence of palette sources, panning so none overlaps.

    Nodes are 525x350 at zoom 1 and the pane is ~1280 wide, so only two fit side
    by side. After each pair the viewport pans left by a node's width plus a
    gutter, which puts the next pair on empty canvas at the same screen
    coordinates.
    """
    placed: list[tuple[str, str]] = []
    for index, (label, source) in enumerate(sources):
        at = (150, 150) if index % per_row == 0 else (760, 150)
        node_id = drag_to_canvas(run.page, source, at=at)
        placed.append((label, node_id))
        if index % per_row == per_row - 1:
            _pan(run.page, -1350)
    return placed


# ---------------------------------------------------------------------------
# Chapter 01 - access: auth, the projects page, notebook import
# ---------------------------------------------------------------------------


def chapter_access(run: StressRun) -> None:
    page, tour = run.page, run.tour
    tour.chapter("Chapter 1", "Getting in",
                 "Sign up, sign in, and everything the projects page does.")

    with run.step("Open the sign-up form"):
        page.goto(f"{run.frontend}/auth/signup")
        page.wait_for_load_state("domcontentloaded")
        page.locator("#signup-username").wait_for(state="visible", timeout=60000)

    with run.step("Reject a password that is too short"):
        tour.type_into(page.locator("#signup-name"), USER_NAME)
        tour.type_into(page.locator("#signup-username"), USER_LOGIN)
        tour.type_into(page.locator("#signup-email"), USER_EMAIL)
        tour.type_into(page.locator("#signup-password"), "abc")
        tour.type_into(page.locator("#signup-confirm-password"), "abc")
        page.get_by_role("button", name=re.compile("Sign ?up|Create", re.I)).first.click()
        page.wait_for_timeout(1200)
        run.snap("signup-short-password")
        assert "/auth/signup" in page.url, (
            "a three-character password was accepted; the form navigated away"
        )

    with run.step("Reject a mismatched confirmation"):
        page.locator("#signup-password").fill(USER_PASSWORD)
        page.locator("#signup-confirm-password").fill(USER_PASSWORD + "-nope")
        page.get_by_role("button", name=re.compile("Sign ?up|Create", re.I)).first.click()
        page.wait_for_timeout(1200)
        run.snap("signup-mismatch")
        assert "/auth/signup" in page.url, (
            "a mismatched confirmation was accepted; the form navigated away"
        )

    with run.step("Sign up for real"):
        page.locator("#signup-confirm-password").fill(USER_PASSWORD)
        tour.click(
            page.get_by_role("button", name=re.compile("Sign ?up|Create", re.I)).first
        )
        page.wait_for_url("**/projects", timeout=60000)
        wait_for_projects_page(page, timeout=45000)

    with run.step("Dismiss the persona picker if it appears", may_fail=True):
        picker = page.get_by_text("Which professional are you?", exact=False)
        if picker.count():
            run.snap("persona-picker")
            choice = page.get_by_role("button").filter(
                has_text=re.compile("Researcher|Engineer|Analyst|Continue|Skip", re.I)
            )
            if choice.count():
                tour.click(choice.first)
            else:
                page.keyboard.press("Escape")
        else:
            log("[stress] no persona picker on this build")

    with run.step("Create a dataflow so the list has something in it"):
        tour.click(page.get_by_role("button", name="+ New Dataflow", exact=True))
        page.wait_for_url("**/dataflow/**", timeout=45000)
        _wait_for_canvas(page)

    with run.step("Name the dataflow from the canvas heading"):
        # UpMenu swaps the h1 out for an autofocused input rather than nesting
        # one inside it, so the heading is gone by the time the field exists.
        heading = page.locator("h1").first
        expect(heading).to_be_visible(timeout=15000)
        tour.click(heading)
        field = page.locator("input:focus")
        expect(field).to_be_visible(timeout=10000)
        field.fill("Stress Alpha")
        page.keyboard.press("Enter")
        page.wait_for_timeout(900)
        expect(page.locator("h1").first).to_have_text("Stress Alpha", timeout=10000)

    with run.step("Save it"):
        tour.click(menu(page, "File"), force=True)
        tour.click(page.get_by_role("button", name="Save dataflow", exact=True))
        page.wait_for_timeout(2500)
        dismiss_toasts(page)

    with run.step("Back to the projects page"):
        tour.click(menu(page, "File"), force=True)
        tour.click(page.get_by_role("button", name="Go to projects", exact=True))
        page.wait_for_url("**/projects", timeout=45000)
        wait_for_projects_page(page, timeout=45000)

    with run.step("Search the project list"):
        search = page.get_by_placeholder("Search projects…")
        tour.type_into(search, "Stress")
        page.wait_for_timeout(900)
        search.fill("no-such-project")
        page.wait_for_timeout(900)
        expect(
            page.get_by_text("No projects match the current filters.")
        ).to_be_visible(timeout=8000)
        search.fill("")
        page.wait_for_timeout(700)

    for tab in ("Recent", "All projects"):
        with run.step(f"Filter: {tab}"):
            tour.click(page.get_by_role("button", name=tab, exact=True).first)
            page.wait_for_timeout(900)

    with run.step("Re-sort the list"):
        select = page.get_by_label("Sort projects")
        for value in ("name", "created", "last_opened"):
            select.select_option(value)
            page.wait_for_timeout(700)

    with run.step("Switch to list view and back"):
        tour.click(page.get_by_role("button", name="List", exact=True))
        page.wait_for_timeout(900)
        run.snap("projects-list-view")
        tour.click(page.get_by_role("button", name="Grid", exact=True))
        page.wait_for_timeout(700)

    card = page.locator("[data-project-id]").first

    with run.step("Select a card, then open its drawer"):
        tour.click(card)
        page.wait_for_timeout(900)
        run.snap("projects-detail-drawer")

    with run.step("Keyboard: Enter and Space select a card"):
        card.focus()
        page.keyboard.press("Enter")
        page.wait_for_timeout(500)
        page.keyboard.press("Space")
        page.wait_for_timeout(500)

    with run.step("Duplicate from the right-click menu"):
        card.click(button="right")
        page.wait_for_timeout(600)
        run.snap("projects-context-menu")
        tour.click(page.get_by_text("Duplicate", exact=True).first)
        page.wait_for_timeout(2500)

    with run.step("Rename through the prompt"):
        # An in-app PromptDialog now (#197), so the name is typed into a real
        # field rather than answered through the dialog policy.
        page.locator("[data-project-id]").first.click(button="right")
        page.wait_for_timeout(500)
        tour.click(page.get_by_text("Rename", exact=True).first)
        rename = page.get_by_role("dialog", name="Rename dataflow")
        expect(rename).to_be_visible(timeout=10000)
        rename.get_by_label("Name").fill("Stress Alpha (renamed)")
        page.wait_for_timeout(600)
        tour.click(rename.get_by_role("button", name="Rename", exact=True))
        page.wait_for_timeout(2200)

    # Archive used to sit between these two steps - right-click Archive, find
    # it under the Archived tab, then delete it from there. Both the action
    # and the tab were removed in #261; deletion is the only removal now.
    with run.step("Delete one from the context menu"):
        projects = page.locator("[data-project-id]")
        if projects.count():
            projects.last.click(button="right")
            page.wait_for_timeout(500)
            tour.click(page.get_by_text("Delete", exact=True).first)
            # The confirmation is an in-app ConfirmDialog now (#197).
            confirm = page.get_by_role("dialog", name=re.compile(r"^Permanently delete "))
            expect(confirm).to_be_visible(timeout=10000)
            page.wait_for_timeout(800)
            run.snap("projects-delete-confirm")
            tour.click(confirm.get_by_role("button", name="Delete", exact=True))
            page.wait_for_timeout(2500)
        tour.click(page.get_by_role("button", name="All projects", exact=True).first)
        page.wait_for_timeout(1200)

    with run.step("Import a Jupyter notebook as a dataflow"):
        with page.expect_file_chooser() as chooser:
            page.get_by_role(
                "button", name="Import Jupyter notebook", exact=True
            ).click()
        chooser.value.set_files(NOTEBOOK)
        page.wait_for_timeout(6000)
        dismiss_toasts(page)
        run.snap("notebook-imported")

    with run.step("Sign out"):
        # The header renders Sign out directly, not behind an avatar menu
        # (GlobalPageHeader.tsx), and only when user auth is enabled.
        button = page.get_by_test_id("signout-button")
        assert button.count(), "the header has no Sign out button"
        tour.click(button.first)
        page.wait_for_url("**/auth/**", timeout=45000)

    with run.step("Refuse the wrong password",
                 allow=(r"HTTP 4\d\d .*auth",)):
        page.goto(f"{run.frontend}/auth/signin")
        page.locator("#signin-identifier").wait_for(state="visible", timeout=45000)
        tour.type_into(page.locator("#signin-identifier"), USER_LOGIN)
        tour.type_into(page.locator("#signin-password"), "definitely-not-it")
        page.get_by_role("button", name=re.compile("Sign ?in", re.I)).first.click()
        page.wait_for_timeout(2500)
        run.snap("signin-rejected")
        assert "/auth/signin" in page.url, (
            "a wrong password signed the user in"
        )

    with run.step("A rejected sign-in should keep what was typed"):
        # UserProvider renders `{loading ? <Loading /> : children}` and
        # `signin` sets loading true for the duration of the request, so the
        # whole form unmounts mid-submit and a fresh one mounts when it fails:
        # both fields come back empty and the error state died with the old
        # instance. Recorded rather than worked around silently.
        identifier = page.locator("#signin-identifier").input_value()
        if identifier != USER_LOGIN:
            run.note(
                "a rejected sign-in cleared the form: the username field came "
                f"back {identifier!r} instead of {USER_LOGIN!r}, and no error "
                "message is shown either",
                step="A rejected sign-in should keep what was typed",
                severity="error",
            )

    with run.step("Sign in properly"):
        page.locator("#signin-identifier").fill(USER_LOGIN)
        page.locator("#signin-password").fill(USER_PASSWORD)
        tour.click(page.get_by_role("button", name=re.compile("Sign ?in", re.I)).first)
        page.wait_for_url("**/projects", timeout=60000)
        wait_for_projects_page(page, timeout=45000)
        run.snap("projects-signed-in")

    with run.step("The version badge reports build and isolation"):
        # VersionBadge renders a bare div with inline styles - no class, no test
        # id - so the isolation span's own tooltip is the only stable handle.
        badge = page.locator("span[title]").filter(
            has_text=re.compile(r"isolated", re.I)
        )
        expect(badge.first).to_be_attached(timeout=15000)
        badge.first.hover()
        page.wait_for_timeout(1500)
        run.snap("version-badge")


# ---------------------------------------------------------------------------
# Chapter 02 - canvas: every built-in node, every editor, every guard
# ---------------------------------------------------------------------------


def chapter_canvas(run: StressRun) -> None:
    page, tour = run.page, run.tour
    tour.chapter("Chapter 2", "The canvas",
                 "All twelve built-in nodes, their editors, and the guards.")

    with run.step("Open a fresh dataflow"):
        _enter_project(run, name="Stress: canvas")

    with run.step("Drag all twelve built-in node types onto the canvas"):
        reset_zoom(page)
        sources = [
            (template, builtin_tile(page, template))
            for template, _ in stress.BUILTIN_TILES
        ]
        placed = _drop_grid(run, sources)
        run.state["placed"] = dict(placed)
        assert len(placed) == 12, f"only {len(placed)} of 12 tiles produced a node"
        fit_view(page)
        run.snap("all-builtin-nodes")

    with run.step("Node-header icon buttons expose an accessible name"):
        node_id = next(iter(run.state["placed"].values()))
        probe = page.evaluate(
            """(nodeId) => {
                const el = document.querySelector(
                    `.react-flow__node[data-id="${nodeId}"]`
                );
                if (!el) return null;
                return [...el.querySelectorAll('[role="button"]')].map((b) => ({
                    tag: b.tagName.toLowerCase(),
                    cls: (b.getAttribute('class') || '').split(' ')
                        .filter((c) => c.startsWith('fa-')).join(' '),
                    title: b.getAttribute('title'),
                    ariaLabel: b.getAttribute('aria-label'),
                    labelledBy: b.getAttribute('aria-labelledby'),
                    titleChild: b.querySelector('title')
                        ? b.querySelector('title').textContent : null,
                }));
            }""",
            node_id,
        )
        unnamed = [
            b for b in (probe or [])
            if not (b["ariaLabel"] or b["labelledBy"] or b["title"])
        ]
        if unnamed:
            run.note(
                f"{len(unnamed)} of {len(probe)} node-header controls carry "
                'role="button" with no accessible name at all (no aria-label, '
                "no aria-labelledby, no title attribute), so assistive tech "
                f"announces an unlabelled button: {unnamed}",
                step="Node-header icon buttons expose an accessible name",
                severity="error",
            )
        log(f"[stress] node header controls: {probe}")

    with run.step("Every dropped tile produced the node type it advertises"):
        types = {n["id"]: (n["nodeType"] or "") for n in canvas_nodes(page)}
        mismatched = [
            f"{template}: {types.get(node_id)!r}"
            for template, node_id in run.state["placed"].items()
            if template not in (types.get(node_id) or "")
        ]
        assert not mismatched, "palette tile produced the wrong node type: " + \
            ", ".join(mismatched)

    with run.step("Clear the canvas and build a real flow"):
        remaining = _clear_canvas(run)
        assert not remaining, (
            f"{remaining} node(s) could not be deleted from an unconnected canvas"
        )
        reset_zoom(page)

    with run.step("Data Loading -> Data Transformation, wired by hand"):
        loader = drag_to_canvas(page, builtin_tile(page, "data-loading"), at=(150, 150))
        transform = drag_to_canvas(
            page, builtin_tile(page, "data-transformation"), at=(760, 150)
        )
        run.state.update(loader=loader, transform=transform)
        set_node_code(page, loader, _loader_code())
        set_node_code(page, transform, TRANSFORM_CODE)
        connect_nodes(page, loader, transform)
        fit_view(page)

    with run.step("Run the loader, then the transform"):
        run_node_and_wait(page, loader, timeout_ms=180000)
        run_node_and_wait(page, transform, timeout_ms=180000)
        output = read_node_output_text(page, transform)
        assert "income_per_capita" in output, (
            f"the transform ran but printed nothing recognisable: {output[:200]!r}"
        )

    with run.step("Chart the result with a Vega-Lite node"):
        # A node is 525x350 at zoom 1 and the pane is ~740 tall, so a second
        # row at y=430 lands inside the first row's body and covers its
        # handles. Pan one node-width left instead: the transform slides into
        # the left slot and the right slot is empty canvas again.
        _pan(page, -610)
        vega = drag_to_canvas(page, builtin_tile(page, "vis-vega"), at=(760, 150))
        run.state["vega"] = vega
        set_node_code(page, vega, VEGA_SPEC)
        connect_nodes(page, transform, vega)
        # Not run_node_and_wait: its final read_node_output_text waits for the
        # inline [data-curio-node-output] box, which a chart node does not have.
        play_node(page, vega)
        wait_for_node_done(page, vega, timeout_ms=240000)
        assert_vega_canvas_rendered(page, vega)
        fit_view(page)
        run.snap("vega-chart")

    with run.step("Rename a node from its header"):
        node = node_locator(page, transform)
        pencil = node.get_by_role("button", name=re.compile("^Edit node title"))
        activate_header_icon(pencil.first)
        field = node.get_by_role("textbox", name="Node title")
        field.fill("Income per capita")
        page.keyboard.press("Enter")
        page.wait_for_timeout(900)
        expect(node).to_contain_text("Income per capita", timeout=8000)

    with run.step("Minimize and expand a node"):
        center_on(page, loader, zoom=0.9)
        activate_header_icon(_header_icon(page, loader, "Minimize"))
        page.wait_for_timeout(1200)
        run.snap("node-minimized")
        # A minimized node is a 70x40 chip; clicking it expands it again.
        center_on(page, loader, zoom=1.0)
        node_locator(page, loader).click(force=True)
        page.wait_for_timeout(1200)

    with run.step("Resize a node by its handle"):
        center_on(page, loader, zoom=0.9)
        handle = page.locator(f'[id="{loader}resizer"]')
        box = handle.bounding_box()
        assert box, "the resize handle has no layout box"
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.mouse.down()
        page.mouse.move(box["x"] + 220, box["y"] + 140, steps=18)
        page.mouse.up()
        page.wait_for_timeout(900)

    with run.step("Comment on a node, then resolve and delete the comment"):
        center_on(page, transform, zoom=0.9)
        activate_header_icon(_header_icon(page, transform, "Comments"))
        page.wait_for_timeout(900)
        box = page.get_by_placeholder("Write a comment...")
        box.first.fill("Stress run was here.")
        page.keyboard.press("Enter")
        page.wait_for_timeout(1200)
        run.snap("node-comments")
        activate_header_icon(_header_icon(page, transform, "Comments"))
        page.wait_for_timeout(500)

    with run.step("Pin a node to the dashboard, then unpin it"):
        center_on(page, transform, zoom=0.9)
        activate_header_icon(_header_icon(page, transform, "Pin to dashboard"))
        page.wait_for_timeout(800)
        activate_header_icon(_header_icon(page, transform, "Unpin from dashboard"))
        page.wait_for_timeout(800)

    with run.step("Walk the node editor tabs"):
        center_on(page, transform, zoom=0.9)
        for tab in ("Code", "Widgets", "Provenance", "Output"):
            pill = _editor_tab(page, transform, tab)
            if not pill.count():
                # NodeEditor gates the Output pane on
                # `outputId != undefined || contentComponent != undefined`, so a
                # plain code node legitimately has no Output tab - its result
                # goes to the inline [data-curio-node-output] box instead.
                if tab != "Output":
                    run.note(
                        f"the {tab} tab is absent on a Data Transformation node",
                        step="Walk the node editor tabs", severity="warning",
                    )
                continue
            pill.first.dispatch_event("click")
            page.wait_for_timeout(900)
        run.snap("node-editor-tabs")
        _editor_tab(page, transform, "Code").first.dispatch_event("click")

    with run.step("Open Node settings and read its whole form"):
        node = node_locator(page, transform)
        cog = node.get_by_role("button", name=re.compile("^Node settings for"))
        activate_header_icon(cog.first)
        expect(page.locator("#kind-config-label")).to_be_visible(timeout=15000)
        run.snap("node-settings-modal")

    with run.step("Define a new node: label, ports, editor mode"):
        page.locator("#kind-config-label").fill("Income Ratio")
        page.locator("#kind-config-description").fill(
            "Divides median income by population and flags the outliers."
        )
        page.locator("#kind-config-editor").select_option("code")
        page.locator("#kind-config-engine").select_option("python")
        section = page.get_by_text("Input ports", exact=True).locator("xpath=..")
        add = section.get_by_role("button", name="+ Add port")
        if add.count():
            add.first.click()
            page.wait_for_timeout(600)
            # Was ``rows.first.fill("table")`` against a free-text field. "table"
            # is not a SupportedType, so it was exactly the value the old editor
            # accepted and the registry then dropped -- the defect #219 fixed.
            # The control is a closed dropdown now, so pick a real type.
            type_select = page.locator('[aria-label="Input ports port 1 type 1"]')
            if type_select.count():
                type_select.select_option("DATAFRAME")
        run.snap("node-settings-ports")

    with run.step("Cancel out of Node settings"):
        page.get_by_role("button", name="Cancel", exact=True).first.click()
        page.wait_for_timeout(900)

    with run.step("Two more transformation nodes, for the connection guards"):
        _pan(page, -1350)
        reset_zoom(page)
        left = drag_to_canvas(
            page, builtin_tile(page, "data-transformation"), at=(150, 150)
        )
        right = drag_to_canvas(
            page, builtin_tile(page, "data-transformation"), at=(760, 150)
        )
        run.state.update(guard_left=left, guard_right=right)
        # Both handles have to be inside the frame for the drag to be attempted
        # at all; at zoom 1 the right node's output handle sits past x=1280.
        frame_nodes(page, [left, right])

    with run.step("Output to output is refused", allow=("toast",)):
        # Both ends are sources, which ConnectionValidator should reject.
        _expect_connection_refused(
            run, left, right, what="output to output",
            source_handle="out", target_handle="out",
        )

    with run.step("A valid edge between them is accepted"):
        connect_nodes(page, left, right)

    with run.step("A cycle is refused", allow=("toast",)):
        _expect_connection_refused(run, right, left, what="a cycle")

    with run.step("Deleting a connected node is guarded", allow=("toast",)):
        node_locator(page, left).click(force=True)
        page.wait_for_timeout(400)
        page.keyboard.press("Delete")
        page.wait_for_timeout(1200)
        still_there = any(n["id"] == left for n in canvas_nodes(page))
        if not still_there:
            run.note(
                "a node with edges was deleted by the Delete key without a guard",
                step="Deleting a connected node is guarded", severity="error",
            )
        dismiss_toasts(page)

    with run.step("Delete inside Monaco edits text, it does not delete the node"):
        before = len(canvas_nodes(page))
        editor = node_locator(page, left).locator(".monaco-editor").first
        editor.click()
        page.keyboard.press("Backspace")
        page.wait_for_timeout(800)
        after = len(canvas_nodes(page))
        assert after == before, (
            f"Backspace inside the code editor deleted a node ({before} -> {after})"
        )

    with run.step("Shift-drag box-selects"):
        page.mouse.move(300, 620)
        page.keyboard.down("Shift")
        page.mouse.down()
        page.mouse.move(1100, 300, steps=20)
        page.mouse.up()
        page.keyboard.up("Shift")
        page.wait_for_timeout(900)
        run.snap("box-selection")
        page.mouse.click(640, 660)

    with run.step("Zoom out, zoom in, fit"):
        set_canvas_zoom(page, 0.4)
        page.wait_for_timeout(700)
        set_canvas_zoom(page, 1.4)
        page.wait_for_timeout(700)
        fit_view(page)

    with run.step("Minimize every node, then expand them again"):
        tour.click(menu(page, "View"), force=True)
        item = page.get_by_role("button", name=re.compile("Minimize Nodes", re.I))
        if item.count():
            tour.click(item.first)
            page.wait_for_timeout(1400)
            run.snap("nodes-minimized")
            tour.click(menu(page, "View"), force=True)
            tour.click(page.get_by_role(
                "button", name=re.compile("Expand Nodes", re.I)).first)
            page.wait_for_timeout(1400)
        else:
            page.keyboard.press("Escape")
            run.note("View menu has no Minimize Nodes entry",
                     step="Minimize every node, then expand them again")

    with run.step("A node that raises reaches Error with a traceback",
                  allow=("stress: this node is supposed to fail", "HTTP 4\\d\\d",
                         "toast")):
        _pan(page, -1350)
        bad = drag_to_canvas(page, builtin_tile(page, "computation-analysis"),
                             at=(150, 150))
        set_node_code(page, bad, RAISING_CODE)
        play_node(page, bad)
        status = wait_for_node_settled(page, bad, timeout_ms=180000)
        assert status == "error", (
            f"a node whose body raises ValueError settled as {status!r}"
        )
        # A plain code node has no Output *tab*: NodeEditor gates that pane on
        # `outputId != undefined || contentComponent != undefined`, and the
        # sandbox's traceback is routed to the inline output box on the Code tab
        # instead (utils.read_node_error_text says the same).
        detail = read_node_error_text(node_locator(page, bad)) or ""
        assert "ValueError" in detail or "supposed to fail" in detail, (
            "the node reached Error but its inline output box shows no "
            f"traceback: {detail[:300]!r}"
        )
        page.wait_for_timeout(900)
        run.snap("node-error-inline")
        dismiss_toasts(page)

    with run.step("Run every node from the rail"):
        play_all(run, timeout_ms=300000)
        # This canvas is deliberately a mess of unwired nodes by now - a Merge
        # Flow with no inputs and two bare transformations - so a red node here
        # is the expected outcome, not a finding. The examples chapter is where
        # an errored node means something.
        errored = report_errored_nodes(
            run, "Run every node from the rail", severity="note",
        )
        log(f"[stress] play-all left {len(errored)} node(s) in error")

    with run.step("Save, then export the dataflow as JSON"):
        tour.click(menu(page, "File"), force=True)
        tour.click(page.get_by_role("button", name="Save dataflow", exact=True))
        page.wait_for_timeout(2500)
        dismiss_toasts(page)
        tour.click(menu(page, "File"), force=True)
        with page.expect_download(timeout=45000) as download:
            page.get_by_role("button", name="Save dataflow as", exact=True).click()
        path = download.value.suggested_filename
        assert path.endswith(".json"), f"Save-as produced {path!r}, not a .json"

    with run.step("Export the dataflow as a notebook"):
        tour.click(menu(page, "File"), force=True)
        with page.expect_download(timeout=60000) as download:
            page.get_by_role("button", name="Export as notebook", exact=True).click()
        name = download.value.suggested_filename
        assert name.endswith(".ipynb"), f"notebook export produced {name!r}"


def _loader_code() -> str:
    return (
        "import pandas as pd\n"
        "\n"
        "df = pd.DataFrame({\n"
        '    "neighborhood": ["Loop", "Pilsen", "Hyde Park", "Uptown"],\n'
        '    "population": [42000, 35000, 28000, 57000],\n'
        '    "median_income": [96000, 48000, 61000, 54000],\n'
        "})\n"
        "return df\n"
    )


# ---------------------------------------------------------------------------
# Chapter 03 - nodes: every catalog package, and authoring new node types
# ---------------------------------------------------------------------------


def chapter_nodes(run: StressRun) -> None:
    page, tour = run.page, run.tour
    tour.chapter("Chapter 3", "Nodes and packages",
                 "Install every package, drop every node it ships, author a new one.")

    with run.step("Open a fresh dataflow"):
        _enter_project(run, name="Stress: nodes")

    catalog: list[dict] = []
    with run.step("Read the Node Catalog over the API"):
        payload = _catalog(run, "/api/packages/catalog")
        catalog = payload.get("packages") or payload.get("items") or []
        SHARED["packages"] = catalog
        assert catalog, "the node catalog came back empty"
        log(f"[stress] catalog packages: {[p.get('dirName') for p in catalog]}")

    with run.step("Note which package dependencies are already importable"):
        every = sorted({m for deps in PACKAGE_DEPS.values() for m in deps})
        already = _present_modules(every)
        run.state["deps_present_before"] = already
        log(f"[stress] dependencies already importable before any UI install: "
            f"{sorted(already)}")
        if already:
            run.note(
                "these package dependencies were already in the interpreter "
                "before the run started, so installing their package through "
                "the interface cannot demonstrate that the install path "
                f"actually resolves anything: {sorted(already)}",
                step="Note which package dependencies are already importable",
                severity="note",
            )

    with run.step("Open the Node Catalog drawer"):
        open_node_drawer(run)
        page.wait_for_timeout(1200)
        run.snap("node-catalog-drawer")

    with run.step("What an open drawer advertises to assistive tech"):
        # All three canvas drawers put aria-modal="true" on their role="dialog"
        # panel, and each provider unmounts the drawer once its exit transition
        # finishes (`const drawer = mounted ? <Drawer/> : null`), so none of them
        # lingers in the DOM while closed. What differs is the in-between: the
        # Data and Agent drawers carry aria-hidden={!presented} on the root, and
        # the Node Catalog drawer carries no aria-hidden at all - so during its
        # slide it is the only one whose modal dialog is exposed while not yet
        # presented. Recorded from the live DOM rather than asserted from source.
        signals = {
            "node": drawer_presentation_signals(page, DRAWER_NODES),
            "data": drawer_presentation_signals(page, DRAWER_DATA),
            "agents": drawer_presentation_signals(page, DRAWER_AGENTS),
        }
        log(f"[stress] open-drawer signals: {signals}")
        node_signal = signals.get("node") or {}
        if node_signal.get("rootAriaHidden") is None:
            run.note(
                "the Node Catalog drawer root sets no aria-hidden, where the "
                "Data and Agent drawers set aria-hidden={!presented}; its "
                'aria-modal="true" dialog is therefore exposed to assistive '
                "tech for the length of the open/close transition. Minor, "
                "because the provider unmounts the drawer afterwards. "
                f"signals: {signals}",
                step="What an open drawer advertises to assistive tech",
                severity="warning",
            )

    # Featured and Updates are gone from the Node drawer: neither was a scope
    # anything could fall into. What is left is everything, and this project.
    for tab in ("Browse all", "In project"):
        with run.step(f"Node Catalog tab: {tab}", may_fail=True):
            button = page.locator(DRAWER_NODES).get_by_role(
                "button", name=re.compile(f"^{re.escape(tab)}")
            )
            button.first.click()
            page.wait_for_timeout(1100)

    with run.step("Search the drawer"):
        search = page.locator(DRAWER_NODES).get_by_placeholder(
            re.compile("Search", re.I)
        )
        if search.count():
            tour.type_into(search.first, "weather")
            page.wait_for_timeout(1200)
            search.first.fill("")
            page.wait_for_timeout(800)

    # Install every catalog package for real. curio.weather, ai.urbanlab.uhvi and
    # curio.streetvision each shell out to pip (rasterio / geopandas / torch), so
    # the response wait is generous by design rather than optimistic.
    installable = [
        pkg for pkg in catalog
        if not pkg.get("installed") and "builtin" not in (pkg.get("dirName") or "")
    ]
    for pkg in installable:
        dir_name = pkg.get("dirName") or ""
        with run.step(f"Install {dir_name} (real pip)", may_fail=True):
            page.locator(DRAWER_NODES).get_by_role(
                "button", name=re.compile("^Browse all")
            ).first.click()
            page.wait_for_timeout(800)
            card = page.locator(f'article[data-pkg-dir="{dir_name}"]')
            card.first.scroll_into_view_if_needed()
            add = card.first.get_by_role(
                "button", name=re.compile("Add to project|Install")
            )
            add.first.click()
            # A package declaring permissions puts InstallPermissionsDialog
            # between the click and the POST, so the response cannot be awaited
            # around the click itself. Its confirm button carries the same
            # "Add to project" wording, which is why it is found by the
            # dialog's own heading rather than by the label.
            page.wait_for_timeout(1200)
            heading = page.get_by_role("heading", name=re.compile('^Add "'))
            if heading.count():
                run.snap(f"permissions-{dir_name}")
                # InstallPermissionsDialog's confirm defaults to the very same
                # "Add to project" wording as the card's button, so it is
                # scoped to the dialog the heading is a child of.
                heading.first.locator("xpath=..").get_by_role(
                    "button", name=re.compile("^Add to project")
                ).first.click()
            # pip runs synchronously inside the request for the heavy packages
            # (torch, rasterio, geopandas), capped at 30 minutes server-side.
            expect(
                card.first.get_by_role("button", name=re.compile("Remove from project"))
            ).to_be_visible(timeout=1_900_000)
            dismiss_toasts(page)
            expected = PACKAGE_DEPS.get(dir_name, ())
            if expected:
                before = run.state.get("deps_present_before", set())
                now = _present_modules(expected)
                fetched = sorted(set(expected) & now - before)
                still_missing = sorted(set(expected) - now)
                log(f"[stress] installed {dir_name}; deps fetched by the "
                    f"interface: {fetched}; still missing: {still_missing}")
                if still_missing:
                    run.note(
                        f"{dir_name} installed through the interface but these "
                        "declared Python dependencies are still not importable, "
                        "so a node from it will fail at run time: "
                        f"{still_missing}",
                        step=f"Install {dir_name}", severity="error",
                    )
                run.state["deps_present_before"] = before | now
            else:
                log(f"[stress] installed {dir_name} (declares no python deps)")

    with run.step("Close the drawer"):
        close_drawer(page, DRAWER_NODES, "Node Catalog drawer")

    templates: list[tuple[str, str]] = []
    with run.step("Every installed package shows its nodes in the palette"):
        open_tools_palette(page, "packages")
        page.wait_for_timeout(1500)
        _expand_accordions(page, "#packages-palette")
        run.snap("packages-palette")
        rows = page.locator("#packages-palette [data-pkg-template-id]")
        count = rows.count()
        for index in range(count):
            template_id = rows.nth(index).get_attribute("data-pkg-template-id") or ""
            if template_id:
                templates.append((template_id, template_id))
        run.state["templates"] = templates
        assert templates, "no package template rows in the palette after installing"
        log(f"[stress] palette templates: {[t for t, _ in templates]}")

    with run.step(f"Drop all {len(templates)} package node types onto the canvas"):
        reset_zoom(page)
        placed = []
        reclosed = 0
        for index, (template_id, _) in enumerate(templates):
            # Dropping a package node refreshes the registry, which re-mounts
            # the palette - and a native <details> that React re-mounts comes
            # back closed, so the next row is in the DOM but not visible. Count
            # how often that happens: needing to re-open the section after every
            # single drag is a real annoyance for anyone building a dataflow.
            if _collapsed_accordion_count(page, "#packages-palette"):
                if index:
                    reclosed += 1
                _expand_accordions(page, "#packages-palette")
            row = package_row(page, template_id).first
            row.scroll_into_view_if_needed()
            at = (150, 150) if index % 2 == 0 else (760, 150)
            placed.append((template_id, drag_to_canvas(page, row, at=at)))
            if index % 2 == 1:
                _pan(page, -1350)
        run.state["package_nodes"] = placed
        missing = [t for t, node_id in placed if not node_id]
        assert not missing, f"these package nodes did not instantiate: {missing}"
        if reclosed:
            run.note(
                f"the Node Catalog palette collapsed its package sections after "
                f"{reclosed} of {len(templates) - 1} drags, so a user dragging "
                "several nodes out of one package has to re-open it every time",
                step="Drop all package node types onto the canvas",
                severity="warning",
            )
        fit_view(page)
        run.snap("all-package-nodes")

    with run.step("Every package node reports a usable editor", may_fail=True):
        for _, node_id in run.state.get("package_nodes", []):
            node = node_locator(page, node_id)
            expect(node).to_be_visible(timeout=8000)

    with run.step("Clear the canvas for the authoring beat"):
        close_tools_palette(page, "packages")
        _clear_canvas(run)

    # -- authoring a brand new node type ---------------------------------

    with run.step("Note what the palette holds before authoring", may_fail=True):
        run.state["templates_before"] = set()
        open_tools_palette(page, "packages")
        page.wait_for_timeout(1200)
        _expand_accordions(page, "#packages-palette")
        run.state["templates_before"] = _palette_template_ids(page)
        close_tools_palette(page, "packages")

    with run.step("Build a node worth packaging"):
        reset_zoom(page)
        node_id = drag_to_canvas(
            page, builtin_tile(page, "data-transformation"), at=(300, 150)
        )
        run.state["authored"] = node_id
        set_node_code(
            page, node_id,
            "df = arg\n"
            'return df.describe(include="all")\n',
        )

    with run.step("Give the new node its identity in Node settings"):
        node = node_locator(page, node_id)
        activate_header_icon(
            node.get_by_role("button", name=re.compile("^Node settings for")).first
        )
        expect(page.locator("#kind-config-label")).to_be_visible(timeout=15000)
        page.locator("#kind-config-label").fill("Stress Describe")
        page.locator("#kind-config-description").fill(
            "Summary statistics for whatever reaches its input."
        )
        page.locator("#kind-config-editor").select_option("code")
        run.snap("authoring-node-settings")

    with run.step("Save as package node, into a brand new package"):
        page.get_by_role("button", name="Save as package node…", exact=True).click()
        expect(page.locator("#save-as-package-target")).to_be_visible(timeout=15000)
        # The first option is "New package…"; selecting it by its own value
        # avoids depending on the ellipsis character surviving the round trip.
        target = page.locator("#save-as-package-target")
        new_value = target.locator("option").first.get_attribute("value")
        target.select_option(new_value)
        page.wait_for_timeout(600)
        name_field = page.locator("#save-as-new-package-name")
        if name_field.count():
            name_field.fill("Stress Authored Pack")
        run.snap("save-as-package-modal")
        with page.expect_response(
            lambda r: "/api/packages/" in r.url and r.request.method == "POST",
            timeout=180000,
        ):
            page.get_by_role("button", name=re.compile("^(Save|Replace)$")).first.click()
        page.wait_for_timeout(3000)
        dismiss_toasts(page)

    new_template = ""
    with run.step("The authored node appears in the palette and can be dropped"):
        open_tools_palette(page, "packages")
        page.wait_for_timeout(1800)
        _expand_accordions(page, "#packages-palette")
        # The saved node keeps its SOURCE template id and lands in a generated
        # package coordinate (curio.canvas.draft.<slug>@1), so the new row is
        # found by diffing the palette rather than by guessing at a name derived
        # from the label that was typed.
        after = _palette_template_ids(page)
        fresh = sorted(after - run.state.get("templates_before", set()))
        assert fresh, (
            "the node just saved as a package does not appear in the palette; "
            f"before={sorted(run.state.get('templates_before', set()))} "
            f"after={sorted(after)}"
        )
        new_template = fresh[0]
        log(f"[stress] authored node reached the palette as {new_template}")
        row_text = " ".join(
            (package_row(page, new_template).first.inner_text() or "").split()
        )
        if "Stress Describe" not in row_text:
            run.note(
                "the label typed into Node settings does not reach the palette "
                f"row for the authored node: row reads {row_text!r}",
                step="The authored node appears in the palette and can be dropped",
                severity="warning",
            )
        reset_zoom(page)
        # The palette re-mounts whenever the registry refreshes, and a
        # re-mounted <details> comes back closed, so re-open before reaching for
        # the row.
        _expand_accordions(page, "#packages-palette")
        drag_to_canvas(page, package_row(page, new_template).first, at=(760, 150))
        run.snap("authored-node-on-canvas")

    with run.step("Edit the new package's metadata"):
        open_tools_palette(page, "packages")
        _expand_accordions(page, "#packages-palette")
        pencil = page.locator("#packages-palette").get_by_role(
            "button", name=re.compile("Edit package metadata|metadata", re.I)
        )
        if pencil.count():
            pencil.first.click()
            page.wait_for_timeout(1500)
            run.snap("package-metadata-modal")
            for field_id, value in (
                ("#pkg-meta-description", "Authored on camera by the stress run."),
                ("#pkg-meta-publisher", "curio.stress"),
                ("#pkg-meta-license", "MIT"),
            ):
                field = page.locator(field_id)
                if field.count():
                    field.fill(value)
            save = page.get_by_role("button", name=re.compile("^Save"))
            if save.count():
                save.first.click()
            page.wait_for_timeout(2000)
            dismiss_toasts(page)
        else:
            run.note("no Edit package metadata control in the packages palette",
                     step="Edit the new package's metadata")

    with run.step("Export the authored package as an archive"):
        open_tools_palette(page, "packages")
        _expand_accordions(page, "#packages-palette")
        export = page.locator("#packages-palette").get_by_role(
            "button", name=re.compile("Export", re.I)
        )
        assert export.count(), "the packages palette offers no Export control"
        export.first.scroll_into_view_if_needed()
        with page.expect_download(timeout=120000) as download:
            export.first.click()
        archive = os.path.join(out_dir(), download.value.suggested_filename)
        download.value.save_as(archive)
        run.state["archive"] = archive
        assert os.path.getsize(archive) > 0, "the exported archive is empty"

    with run.step("Re-importing the same coordinate is refused",
                  allow=(r"HTTP 400", "already", "exists")):
        open_node_drawer(run)
        page.wait_for_timeout(1200)
        chooser_button = page.locator(DRAWER_NODES).get_by_text(
            re.compile("Import|Sideload|\\.curio\\.zip", re.I)
        )
        if chooser_button.count():
            with page.expect_file_chooser() as chooser:
                chooser_button.first.click()
            chooser.value.set_files(run.state["archive"])
            page.wait_for_timeout(4000)
            run.snap("reimport-refused")
        dismiss_toasts(page)
        close_drawer(page, DRAWER_NODES, "Node Catalog drawer")

    with run.step("Installed libraries: add titlecase for real"):
        tour.click(menu(page, "Data"), force=True)
        tour.click(page.get_by_role("button", name="Installed libraries", exact=True))
        expect(
            page.get_by_role("heading", name="Installed libraries")
        ).to_be_visible(timeout=15000)
        run.snap("library-manager")
        page.get_by_placeholder(re.compile("numpy", re.I)).fill("titlecase")
        with page.expect_response(
            lambda r: "/api/packages/libraries" in r.url
            and r.request.method == "POST",
            timeout=600000,
        ):
            page.get_by_role("button", name="Add", exact=True).first.click()
        page.wait_for_timeout(3000)
        run.snap("library-installed")

    with run.step("A JavaScript library install is refused",
                  allow=(r"HTTP 501", "not implemented", "coming soon")):
        select = page.locator("select").filter(has_text="Python").first
        if select.count():
            select.select_option("js")
            page.wait_for_timeout(600)
            page.get_by_placeholder(re.compile("lodash", re.I)).fill("lodash")
            page.get_by_role("button", name="Add", exact=True).first.click()
            page.wait_for_timeout(2500)
            run.snap("js-library-refused")

    with run.step("Close the library manager"):
        page.get_by_role("button", name="Close").first.click()
        page.wait_for_timeout(800)

    with run.step("A node can import the library that was just installed"):
        reset_zoom(page)
        node_id = drag_to_canvas(
            page, builtin_tile(page, "data-loading"), at=(150, 430)
        )
        set_node_code(
            page, node_id,
            "import pandas as pd\n"
            "from titlecase import titlecase\n"
            'print(titlecase("a stress test of the node catalog"))\n'
            'return pd.DataFrame({"ok": [1]})\n',
        )
        run_node_and_wait(page, node_id, timeout_ms=240000)
        output = read_node_output_text(page, node_id)
        assert "Stress Test" in output, (
            f"titlecase was installed but the node could not use it: {output[:200]!r}"
        )

    with run.step("The Node Catalog page renders its rails and filters"):
        page.goto(f"{run.frontend}/catalog/nodes")
        page.wait_for_load_state("domcontentloaded")
        expect(
            page.get_by_role("heading", name="Node Catalog")
        ).to_be_visible(timeout=45000)
        page.wait_for_timeout(1500)
        run.snap("catalog-nodes-page")
        search = page.get_by_placeholder(re.compile("Search packages", re.I))
        if search.count():
            tour.type_into(search.first, "uhvi")
            page.wait_for_timeout(1200)
            search.first.fill("")
        card = page.locator("article").first
        if card.count():
            tour.click(card)
            page.wait_for_timeout(1500)
            run.snap("catalog-nodes-drawer")


# ---------------------------------------------------------------------------
# Chapter 04 - data: every catalog dataset, every import format
# ---------------------------------------------------------------------------


def chapter_data(run: StressRun) -> None:
    page, tour = run.page, run.tour
    tour.chapter("Chapter 4", "Data",
                 "Add every catalog dataset, import every format Curio takes.")

    with run.step("Open a fresh dataflow"):
        _enter_project(run, name="Stress: data")

    datasets: list[dict] = []
    with run.step("Read the Data Catalog over the API"):
        payload = _catalog(run, "/api/datasets/catalog")
        datasets = payload.get("items") or payload.get("datasets") or []
        SHARED["datasets"] = datasets
        assert datasets, "the data catalog came back empty"
        log(f"[stress] catalog datasets: {[d.get('id') for d in datasets]}")

    with run.step("Open the Data Catalog drawer"):
        open_data_drawer(run)
        page.wait_for_timeout(1200)
        run.snap("data-catalog-drawer")

    # The Data drawer dropped Featured for the same reason. "Computed" stays:
    # it is a real scope, the datasets nodes produced.
    for tab in ("Browse all", "In project", "Computed"):
        with run.step(f"Data Catalog tab: {tab}", may_fail=True):
            page.locator(DRAWER_DATA).get_by_role(
                "button", name=re.compile(f"^{re.escape(tab)}")
            ).first.click()
            page.wait_for_timeout(1000)

    with run.step("Add every hub dataset to the dataflow"):
        page.locator(DRAWER_DATA).get_by_role(
            "button", name=re.compile("^Browse all")
        ).first.click()
        page.wait_for_timeout(1000)
        added = 0
        for dataset in datasets:
            dataset_id = dataset.get("id") or ""
            if not dataset_id:
                continue
            card = page.locator(f'article[data-dataset-id="{dataset_id}"]')
            if not card.count():
                run.note(f"dataset {dataset_id} is in the API but not in the drawer",
                         step="Add every hub dataset to the dataflow",
                         severity="warning")
                continue
            card.first.scroll_into_view_if_needed()
            add = card.first.get_by_role("button", name=re.compile("^Add to project"))
            if not add.count():
                continue
            add.first.click()
            # The Data catalog confirms an add now (#196).
            accept_confirm_dialog(
                page, title=re.compile(r"^Add "), button="Add to project"
            )
            expect(
                card.first.get_by_role(
                    "button", name=re.compile("Remove from project")
                )
            ).to_be_visible(timeout=300000)
            added += 1
            page.wait_for_timeout(300)
        dismiss_toasts(page)
        log(f"[stress] added {added} datasets to the dataflow")
        assert added, "no dataset could be added to the dataflow"

    with run.step("Open a dataset's detail panel and walk its tabs"):
        card = page.locator(f'article[data-dataset-id="{DATASET_ID}"]')
        if not card.count():
            card = page.locator("article[data-dataset-id]").first
        card.first.scroll_into_view_if_needed()
        avatar = card.first.get_by_role("button").first
        avatar.click()
        page.wait_for_timeout(1800)
        run.snap("dataset-detail")
        for tab in ("Overview", "Schema", "Table Preview", "Lineage"):
            pill = page.get_by_role("button", name=tab, exact=True)
            if pill.count():
                pill.first.click()
                page.wait_for_timeout(1100)
                run.snap(f"dataset-{tab.lower().replace(' ', '-')}")
            else:
                run.note(f"the dataset detail panel has no {tab} tab",
                         step="Open a dataset's detail panel and walk its tabs")
        if not _close_modal(page):
            run.note(
                "Escape did not dismiss this ModalShell dialog. It renders "
                'role="dialog" aria-modal="true", so the ARIA dialog pattern '
                "expects Escape to close it - and until it closes, its backdrop "
                "swallows clicks on everything underneath, which once took the "
                "next fifteen steps of this chapter down with it.",
                step="Open a dataset's detail panel and walk its tabs",
                severity="error",
            )

    # The headline case: a user brings their own CSV and expects a new entry in
    # the Data Catalog. Checked end to end - the file dialog, the new catalog
    # row, its schema and preview, and finally using it on the canvas.
    with run.step("Upload a CSV of my own through the Data Catalog"):
        csv_path = _upload_csv_path()
        run.state["csv_before"] = _catalog_dataset_ids(run)
        trigger = page.locator(DRAWER_DATA).get_by_text("Import dataset")
        assert trigger.count(), "the Data Catalog drawer offers no Import control"
        with page.expect_file_chooser() as chooser:
            tour.click(trigger.first)
        chooser.value.set_files(csv_path)
        page.wait_for_timeout(2500)
        try:
            page.wait_for_function(
                """() => !document.body.innerText.includes('Importing')""",
                timeout=300000,
            )
        except PlaywrightTimeoutError:
            run.note("the CSV import was still running after five minutes",
                     step="Upload a CSV of my own through the Data Catalog",
                     severity="warning")
        dismiss_toasts(page)
        run.snap("csv-uploaded")

    with run.step("The upload created exactly one new Data Catalog entry"):
        fresh = sorted(_catalog_dataset_ids(run) - run.state["csv_before"])
        assert fresh, (
            "uploading a CSV through the Data Catalog produced no new catalog "
            "entry"
        )
        if len(fresh) > 1:
            run.note(
                f"one uploaded CSV produced {len(fresh)} new catalog entries: "
                f"{fresh}",
                step="The upload created exactly one new Data Catalog entry",
                severity="warning",
            )
        dataset_id = next(
            (d for d in fresh if CSV_UPLOAD_NAME in d.replace("_", "-")), fresh[0]
        )
        run.state["csv_dataset_id"] = dataset_id
        log(f"[stress] the uploaded CSV became catalog entry {dataset_id}")

    with run.step("The new entry carries the schema and rows that were uploaded"):
        dataset_id = run.state["csv_dataset_id"]
        detail = _catalog(run, f"/api/datasets/{dataset_id}")
        blob = json.dumps(detail).lower()
        missing = [c for c in CSV_UPLOAD_COLUMNS if c.lower() not in blob]
        # Recorded rather than asserted: catalog_item.py defaults "schema" to
        # None, so the columns may legitimately live on /preview or be filled in
        # lazily. Blocking here would stop the two checks that answer that.
        if missing:
            run.note(
                "GET /api/datasets/<id> does not carry the uploaded CSV's "
                f"column names {missing}; schema={detail.get('schema')!r}",
                step="The new entry carries the schema and rows that were uploaded",
                severity="warning",
            )
        preview = _catalog(run, f"/api/datasets/{dataset_id}/preview")
        text = json.dumps(preview)
        for station, _neighborhood, _trips, _duration in CSV_UPLOAD_ROWS[:2]:
            assert station in text, (
                f"row {station!r} from the uploaded CSV is missing from its "
                f"preview: {text[:300]}"
            )
        preview_missing = [c for c in CSV_UPLOAD_COLUMNS if c not in text]
        if preview_missing and not missing:
            run.note(
                f"the preview omits these uploaded columns: {preview_missing}",
                step="The new entry carries the schema and rows that were uploaded",
                severity="warning",
            )
        log(f"[stress] uploaded CSV: detail carries columns={not missing}, "
            f"preview carries columns={not preview_missing}")
        log(f"[stress] {dataset_id} preview carries the uploaded rows")

    with run.step("The uploaded CSV shows its own schema and preview in the UI"):
        dataset_id = run.state["csv_dataset_id"]
        card = page.locator(f'article[data-dataset-id="{dataset_id}"]')
        if not card.count():
            page.locator(DRAWER_DATA).get_by_role(
                "button", name=re.compile("^Browse all")
            ).first.click()
            page.wait_for_timeout(1200)
            card = page.locator(f'article[data-dataset-id="{dataset_id}"]')
        assert card.count(), (
            f"the uploaded dataset {dataset_id} is in the API but has no card "
            "in the Data Catalog drawer"
        )
        card.first.scroll_into_view_if_needed()
        tour.click(card.first.get_by_role("button").first)
        page.wait_for_timeout(1600)
        run.snap("csv-detail-overview")
        for tab in ("Schema", "Table Preview"):
            pill = page.get_by_role("button", name=tab, exact=True)
            if not pill.count():
                run.note(f"the uploaded dataset's detail panel has no {tab} tab",
                         step="The uploaded CSV shows its own schema and preview",
                         severity="warning")
                continue
            pill.first.click()
            page.wait_for_timeout(1400)
            run.snap(f"csv-detail-{tab.lower().replace(' ', '-')}")
            shown = page.locator("[role=dialog], body").first.inner_text()
            absent = [c for c in CSV_UPLOAD_COLUMNS if c not in shown]
            if tab == "Schema" and absent:
                run.note(
                    "the Schema tab for the uploaded CSV does not list these "
                    f"columns: {absent}",
                    step="The uploaded CSV shows its own schema and preview",
                    severity="error",
                )
        _close_modal(page)

    # Every other format the Data Catalog claims to import, imported for real.
    imports = [
        ("Parquet", os.path.join(
            REPO_ROOT, "datasets", "data.cityofchicago.red-light-violations@1",
            "data", "red-light-violations.parquet")),
        ("GeoJSON", os.path.join(EXAMPLE_DATA, "nyc_zip.geojson")),
        ("GeoTIFF", os.path.join(EXAMPLE_DATA, "niteroi_lst_verao_2001_2024.tif")),
        ("OSM PBF", os.path.join(EXAMPLE_DATA, "chicago_loop.osm.pbf")),
        ("Shapefile", _shapefile_bundle()),
    ]
    for label, path in imports:
        with run.step(f"Import a {label} file", may_fail=(label == "Shapefile")):
            if not path or not os.path.exists(path):
                run.note(f"no {label} sample available at {path}",
                         step=f"Import a {label} file", severity="warning")
                continue
            trigger = page.locator(DRAWER_DATA).get_by_text("Import dataset")
            assert trigger.count(), "the Data Catalog drawer offers no Import control"
            with page.expect_file_chooser() as chooser:
                trigger.first.click()
            chooser.value.set_files(path)
            # A PBF is split into per-layer datasets and takes the longest.
            page.wait_for_timeout(3000)
            try:
                page.wait_for_function(
                    """() => !document.body.innerText.includes('Importing')""",
                    timeout=900000,
                )
            except PlaywrightTimeoutError:
                run.note(f"{label} import was still running after 15 minutes",
                         step=f"Import a {label} file", severity="warning")
            dismiss_toasts(page)
            run.snap(f"import-{label.lower().replace(' ', '-')}")

    with run.step("Add the uploaded CSV to this dataflow"):
        # Importing puts the file in the Data Catalog; using it still means
        # adding it to the open dataflow, which is what puts a row in the
        # left-rail palette.
        dataset_id = run.state.get("csv_dataset_id")
        assert dataset_id, "no uploaded dataset to add"
        page.locator(DRAWER_DATA).get_by_role(
            "button", name=re.compile("^Browse all")
        ).first.click()
        page.wait_for_timeout(1000)
        card = page.locator(f'article[data-dataset-id="{dataset_id}"]')
        assert card.count(), f"no card for the uploaded dataset {dataset_id}"
        card.first.scroll_into_view_if_needed()
        add = card.first.get_by_role("button", name=re.compile("^Add to project"))
        if add.count():
            tour.click(add.first)
            accept_confirm_dialog(
                page, title=re.compile(r"^Add "), button="Add to project"
            )
            expect(
                card.first.get_by_role(
                    "button", name=re.compile("Remove from project")
                )
            ).to_be_visible(timeout=120000)
        else:
            log("[stress] the uploaded CSV was already in the dataflow")
        dismiss_toasts(page)

    with run.step("Close the drawer"):
        close_drawer(page, DRAWER_DATA, "Data Catalog drawer")

    with run.step("The dataset palette lists what the dataflow now holds"):
        open_tools_palette(page, "datasets")
        page.wait_for_timeout(1800)
        _expand_accordions(page, "#datasets-palette")
        run.snap("dataset-palette")
        rows = page.locator("#datasets-palette [data-dataset-id]")
        assert rows.count(), "the dataset palette is empty after installing datasets"
        sort_toggle = page.locator("#datasets-palette").get_by_role(
            "button", name=re.compile("Import date|Added date", re.I)
        )
        if sort_toggle.count():
            sort_toggle.first.click()
            page.wait_for_timeout(900)

    with run.step("Drag the uploaded CSV onto the canvas; Curio writes the loader"):
        reset_zoom(page)
        # Prefer the dataset this run uploaded: proving a user's own CSV is
        # usable on the canvas is the point, and a hub dataset would prove only
        # that the bundled ones work.
        wanted = run.state.get("csv_dataset_id") or DATASET_ID
        row = page.locator(f'#datasets-palette [data-dataset-id="{wanted}"]')
        if not row.count():
            run.note(
                f"the uploaded dataset {wanted} has no row in the dataset "
                "palette, so it cannot be dragged onto the canvas",
                step="Drag the uploaded CSV onto the canvas", severity="error",
            )
            row = page.locator("#datasets-palette [data-dataset-id]").first
        node_id = drag_to_canvas(page, row.first, at=(150, 150))
        run.state["dataset_node"] = node_id
        run.state["dataset_source"] = (
            "upload" if wanted == run.state.get("csv_dataset_id") else "hub"
        )
        close_tools_palette(page, "datasets")
        output = run_node_and_wait(page, node_id, timeout_ms=300000)
        run.snap("dataset-loader-run")
        if wanted == run.state.get("csv_dataset_id"):
            # The generated loader prints the frame it loaded, so the uploaded
            # rows should be visible in the node's own output.
            if not any(station in output for station, *_ in CSV_UPLOAD_ROWS):
                run.note(
                    "the loader generated for the uploaded CSV ran, but its "
                    "output does not contain any of the uploaded rows: "
                    f"{output[:300]!r}",
                    step="Drag the uploaded CSV onto the canvas",
                    severity="warning",
                )

    with run.step("Save a node's output back into the Data Catalog"):
        transform = drag_to_canvas(
            page, builtin_tile(page, "data-transformation"), at=(760, 150)
        )
        # The upstream loader is the uploaded bike-trips CSV, so the transform
        # has to use ITS columns - TRANSFORM_CODE speaks the ACS dataset's.
        used_upload = run.state.get("dataset_source") == "upload"
        set_node_code(
            page, transform, CSV_TRANSFORM_CODE if used_upload else TRANSFORM_CODE,
        )
        connect_nodes(page, run.state["dataset_node"], transform)
        toggle = node_locator(page, transform).get_by_role(
            "checkbox", name=re.compile("Save output", re.I)
        )
        if not toggle.count():
            toggle = node_locator(page, transform).locator(
                "input[type=checkbox]"
            )
        if toggle.count():
            toggle.first.check(force=True)
        run_node_and_wait(page, transform, timeout_ms=300000)
        page.wait_for_timeout(4000)
        dismiss_toasts(page)

    with run.step("The computed dataset shows up with its lineage"):
        open_data_drawer(run)
        page.wait_for_timeout(1200)
        computed = page.locator(DRAWER_DATA).get_by_role(
            "button", name=re.compile("^Computed")
        )
        assert computed.count(), "the Data Catalog drawer has no Computed tab"
        computed.first.click()
        page.wait_for_timeout(1800)
        run.snap("computed-datasets")
        card = page.locator(f"{DRAWER_DATA} article[data-dataset-id]").first
        assert card.count(), "no computed dataset after running a node with save on"
        card.get_by_role("button").first.click()
        page.wait_for_timeout(1500)
        lineage = page.get_by_role("button", name="Lineage", exact=True)
        if lineage.count():
            lineage.first.click()
            page.wait_for_timeout(1500)
            run.snap("dataset-lineage")
        _close_modal(page)
        close_drawer(page, DRAWER_DATA, "Data Catalog drawer")

    with run.step("The Data Catalog page and a dataset's own page"):
        page.goto(f"{run.frontend}/catalog/data")
        page.wait_for_load_state("domcontentloaded")
        expect(
            page.get_by_role("heading", name="Data Catalog")
        ).to_be_visible(timeout=45000)
        page.wait_for_timeout(1500)
        run.snap("catalog-data-page")
        page.goto(f"{run.frontend}/catalog/data/{DATASET_ID}")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(2500)
        run.snap("catalog-data-detail")

    with run.step("A bad dataset id says so rather than breaking",
                  allow=(r"HTTP 404",)):
        page.goto(f"{run.frontend}/catalog/data/data.stress.does-not-exist")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(2500)
        run.snap("dataset-not-found")
        expect(page.get_by_text("Dataset not found.")).to_be_visible(timeout=20000)


#: A CSV the user "brings from their own machine". Deliberately not one of the
#: files already under datasets/ - re-importing a hub dataset's own file proves
#: nothing about creating a NEW catalog entry, because a row with that name is
#: already there. The columns are distinctive so the schema and the preview can
#: be checked against something only this file has.
CSV_UPLOAD_NAME = "stress-bike-trips"
CSV_UPLOAD_COLUMNS = ("station_id", "neighborhood", "trips", "avg_duration_min")
CSV_UPLOAD_ROWS = (
    ("S-101", "Loop", 4821, 12.4),
    ("S-102", "Pilsen", 2137, 17.9),
    ("S-103", "Hyde Park", 1580, 21.2),
    ("S-104", "Uptown", 3364, 14.6),
    ("S-105", "Logan Square", 2790, 16.1),
)


def _upload_csv_path() -> str:
    """Write the CSV a user would pick in the file dialog, and return its path."""
    target_dir = os.path.join(out_dir(), "fixtures")
    os.makedirs(target_dir, exist_ok=True)
    path = os.path.join(target_dir, f"{CSV_UPLOAD_NAME}.csv")
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(",".join(CSV_UPLOAD_COLUMNS) + chr(10))
        for row in CSV_UPLOAD_ROWS:
            handle.write(",".join(str(value) for value in row) + chr(10))
    return path


def _catalog_dataset_ids(run: StressRun) -> set[str]:
    payload = _catalog(run, "/api/datasets/catalog")
    items = payload.get("items") or payload.get("datasets") or []
    return {item.get("id") for item in items if item.get("id")}


def _shapefile_bundle() -> str:
    """Write a small shapefile to the scratch area; the repo ships none.

    Returns the path to the ``.shp`` itself. Not a zip: both
    IMPORTABLE_DATASET_EXTENSIONS (frontend) and SUPPORTED_SUFFIXES (backend)
    list ``.shp`` and neither accepts ``.zip``, so a zipped bundle is refused
    with "Unsupported dataset format: .zip" - correctly. Whether a lone .shp is
    usable without its .dbf/.shx sidecars is exactly what this exercises.
    """
    target_dir = os.path.join(out_dir(), "fixtures")
    os.makedirs(target_dir, exist_ok=True)
    work = os.path.join(target_dir, "stress_points")
    shp = os.path.join(work, "stress_points.shp")
    if os.path.exists(shp):
        return shp
    try:
        import geopandas as gpd
        from shapely.geometry import Point

        frame = gpd.GeoDataFrame(
            {"name": ["loop", "pilsen", "hyde park"], "score": [3, 7, 5]},
            geometry=[Point(-87.63, 41.88), Point(-87.66, 41.85),
                      Point(-87.59, 41.79)],
            crs="EPSG:4326",
        )
        os.makedirs(work, exist_ok=True)
        frame.to_file(shp)
        return shp
    except Exception as exc:  # noqa: BLE001 - a missing sample is not a defect
        log(f"[stress] could not synthesise a shapefile: {exc}")
        return ""


# ---------------------------------------------------------------------------
# Chapter 05 - agents: AI settings, every built-in agent, live turns
# ---------------------------------------------------------------------------


def chapter_agents(run: StressRun) -> None:
    page, tour = run.page, run.tour
    tour.chapter("Chapter 5", "Agents",
                 "Configure a provider, install all of them, and make them answer.")

    with run.step("Open a dataflow with something for an agent to look at"):
        _enter_project(run, name="Stress: agents")
        reset_zoom(page)
        loader = drag_to_canvas(page, builtin_tile(page, "data-loading"), at=(150, 150))
        transform = drag_to_canvas(
            page, builtin_tile(page, "data-transformation"), at=(760, 150)
        )
        set_node_code(page, loader, _loader_code())
        set_node_code(page, transform, TRANSFORM_CODE)
        connect_nodes(page, loader, transform)
        run.state.update(loader=loader, transform=transform)
        fit_view(page)

    with run.step("AI Settings from the Agent Catalog drawer"):
        drawer = open_agent_drawer(run)
        cog = drawer.get_by_role("button", name=re.compile("AI Settings"))
        assert cog.count(), "the Agent Catalog drawer has no AI Settings control"
        tour.click(cog.first)
        expect(
            page.get_by_role("heading", name="AI Settings", level=2)
        ).to_be_visible(timeout=20000)
        run.snap("ai-settings")

    for provider in ("OpenAI", "Anthropic", "Gemini", "Custom"):
        with run.step(f"AI Settings provider tab: {provider}", may_fail=True):
            tab = page.get_by_role("button", name=provider, exact=True)
            tab.first.click()
            page.wait_for_timeout(900)

    with run.step("Configure the live provider"):
        page.get_by_role("button", name="Custom", exact=True).first.click()
        page.wait_for_timeout(700)
        tour.type_into(ai_field(page, "Base URL"), LLM_BASE_URL)
        if LLM_API_KEY:
            ai_field(page, "API Key").fill(LLM_API_KEY)
        else:
            run.note("no provider key configured; the live turns will be skipped",
                     step="Configure the live provider", severity="warning")
        ai_field(page, "Model").fill(LLM_MODEL)
        run.snap("ai-settings-filled")

    with run.step("Ask the provider for its model list", may_fail=True):
        fetch = page.get_by_role("button", name=re.compile("(Fetch|Refresh) models", re.I))
        if fetch.count():
            fetch.first.click()
            page.wait_for_timeout(9000)
            run.snap("ai-settings-models")

    with run.step("Save the provider settings"):
        page.get_by_role("button", name="Save", exact=True).first.click()
        page.wait_for_timeout(3500)
        dismiss_toasts(page)

    agents: list[dict] = []
    with run.step("Read the Agent Catalog over the API"):
        payload = _catalog(run, "/api/agents/catalog")
        agents = payload.get("items") or payload.get("agents") or []
        SHARED["agents"] = agents
        assert agents, "the agent catalog came back empty"
        log(f"[stress] {len(agents)} agents in the catalog")

    with run.step("Search and sort the Agent Catalog drawer"):
        drawer = page.locator(DRAWER_AGENTS)
        if not drawer.count():
            open_agent_drawer(run)
            drawer = page.locator(DRAWER_AGENTS)
        search = drawer.get_by_placeholder(re.compile("Search agents", re.I))
        if search.count():
            tour.type_into(search.first, "builder")
            page.wait_for_timeout(1200)
            search.first.fill("")
            page.wait_for_timeout(800)
        run.snap("agent-catalog-drawer")

    installed: list[str] = []
    with run.step(f"Add all {len(agents)} agents to the dataflow"):
        for agent in agents:
            coord = agent.get("coord") or (
                f"{agent.get('id')}@{agent.get('version')}"
                if agent.get("id") and agent.get("version") else ""
            )
            if not coord:
                continue
            card = page.locator(f'article[data-agent-coord="{coord}"]')
            if not card.count():
                run.note(f"agent {coord} is in the API but not in the drawer",
                         step="Add all agents to the dataflow", severity="warning")
                continue
            card.first.scroll_into_view_if_needed()
            add = card.first.get_by_role("button", name=re.compile("^Add to project"))
            if not add.count():
                installed.append(coord)      # already in, e.g. a required closure
                continue
            try:
                with page.expect_response(
                    lambda r: "/api/agents/projects/" in r.url
                    and r.url.endswith("/install")
                    and r.request.method == "POST",
                    timeout=120000,
                ):
                    add.first.click()
                installed.append(coord)
            except PlaywrightTimeoutError:
                run.note(f"adding {coord} produced no install response",
                         step="Add all agents to the dataflow", severity="error")
            page.wait_for_timeout(250)
        SHARED["installed_agents"] = installed
        log(f"[stress] installed {len(installed)} agents")
        assert installed, "no agent could be added to the dataflow"

    with run.step("Close the drawer"):
        close_drawer(page, DRAWER_AGENTS, "Agent Catalog drawer")

    with run.step("The agents palette lists them all"):
        open_tools_palette(page, "agents")
        page.wait_for_timeout(1800)
        _expand_accordions(page, "#agents-palette")
        run.snap("agents-palette")

    with run.step("Attach an agent to a node by dragging"):
        dismiss_toasts(page)
        target = run.state["transform"]
        drag_agent_to(run, _first_coord(installed, "node-explainer"),
                      lambda: node_client_point(page, target))
        expect_attach_toast(run, "the node")

    with run.step("Say what the dataflow is for"):
        # The dock (and with it the goal input) only mounts once at least
        # one agent is attached, so this cannot run before the first drag.
        goal = page.get_by_label("Dataflow goal")
        assert goal.count(), "the agent dock has no Dataflow goal input"
        tour.type_into(goal.first, DATAFLOW_GOAL, delay=18)
        page.keyboard.press("Tab")
        page.wait_for_timeout(1200)

    with run.step("Attach an agent to a connection"):
        dismiss_toasts(page)
        point = edge_client_point(page)
        if point is None:
            close_tools_palette(page, "agents")
            fit_view(page)
            open_tools_palette(page, "agents")
            point = edge_client_point(page)
        if point is None:
            run.note("no reachable point on any edge for a connection attach",
                     step="Attach an agent to a connection", severity="warning")
        else:
            drag_agent_to(run, _first_coord(installed, "connection-builder"),
                          lambda: edge_client_point(page))
            expect_attach_toast(run, "the connection")

    with run.step("Attach an agent to the canvas itself"):
        dismiss_toasts(page)
        point = empty_canvas_point(page)
        assert point, "no empty canvas point for a canvas attach"
        drag_agent_to(run, _first_coord(installed, "dataflow-explainer"),
                      lambda: empty_canvas_point(page))
        expect_attach_toast(run, "the canvas")
        close_tools_palette(page, "agents")

    with run.step("Attach every remaining agent, so all of them can be asked"):
        # The three drags above are the gesture worth filming, but the chat
        # panel cycles ATTACHMENTS - so with three attachments only three of the
        # twenty-one agents would ever be asked anything. The rest are attached
        # through the same REST endpoint the drop handler calls, picking the
        # first target kind each agent's manifest accepts (the API refuses an
        # incompatible one with a 400 naming what it does accept).
        project_id = SHARED["project"]["id"]
        node_id = run.state["transform"]
        edges = page.evaluate(
            "() => (window.__curio_reactFlow "
            "? window.__curio_reactFlow.getEdges().map((e) => e.id) : [])"
        ) or []
        edge_id = edges[0] if edges else None
        already = {
            _first_coord(installed, "node-explainer"),
            _first_coord(installed, "connection-builder"),
            _first_coord(installed, "dataflow-explainer"),
        }
        attached, refused = list(already), []
        for coord in installed:
            if coord in already:
                continue
            for kind, target_id in (
                ("node", node_id), ("canvas", None), ("connection", edge_id),
            ):
                if kind == "connection" and not edge_id:
                    continue
                target = {"kind": kind}
                if target_id:
                    target["targetId"] = target_id
                try:
                    api_json(
                        f"{run.backend}/api/agents/projects/{project_id}"
                        "/attachments",
                        _token(run), method="POST",
                        payload={"coord": coord, "target": target},
                    )
                except Exception:
                    continue
                attached.append(coord)
                break
            else:
                refused.append(coord)
        run.state["attached_agents"] = attached
        log(f"[stress] {len(attached)} of {len(installed)} agents attached")
        if refused:
            run.note(
                "these installed agents could not be attached to a node, the "
                f"canvas or a connection: {refused}",
                step="Attach every remaining agent", severity="warning",
            )

    with run.step("Reload so the dock shows every attachment"):
        page.goto(f"{run.frontend}/dataflow/{SHARED['project']['id']}")
        page.wait_for_load_state("domcontentloaded")
        _wait_for_canvas(page)
        page.wait_for_timeout(2000)
        run.snap("agent-dock-full")

    with run.step("Open the chat panel"):
        badge = page.get_by_role("button", name=re.compile("^Open chat with"))
        assert badge.count(), "no attached-agent avatar to open a chat from"
        tour.click(badge.first)
        expect(page.get_by_label("Message this agent")).to_be_visible(timeout=20000)
        run.snap("agent-chat-panel")

    with run.step("Rename the conversation"):
        rename = page.get_by_role("button", name="Rename conversation title")
        if rename.count():
            rename.first.click()
            field = page.get_by_role("textbox", name="Conversation title")
            field.fill("Stress interrogation")
            page.keyboard.press("Enter")
            page.wait_for_timeout(1000)

    with run.step("Suggested prompts prefill the composer", may_fail=True):
        group = page.get_by_role("group", name="Suggested prompts")
        if group.count():
            group.get_by_role("button").first.click()
            page.wait_for_timeout(900)

    if not LLM_API_KEY:
        with run.step("No provider key: the live turns are skipped", may_fail=True):
            tour.say("No provider key configured",
                     "The chat surfaces are recorded; the model is not called.",
                     hold=3000)
        return

    # One real turn per attached agent, cycled through the panel's own
    # navigation. The point is coverage of the roster, so a slow or refusing
    # agent is recorded and the run moves on rather than stopping.
    turns = 0
    roster = run.state.get("attached_agents", installed)
    for index in range(len(roster)):
        header = page.locator("[role=dialog]").filter(
            has=page.get_by_label("Message this agent")
        )
        name = ""
        try:
            name = (header.first.get_attribute("aria-label") or "").replace(
                "Chat with ", ""
            )
        except Exception:  # noqa: BLE001
            pass
        with run.step(f"Live turn {index + 1}/{len(roster)}: {name or 'agent'}",
                      may_fail=True, allow=("HTTP 4\\d\\d", "HTTP 5\\d\\d", "toast")):
            composer = page.get_by_label("Message this agent")
            composer.fill(
                "In one sentence: what would you do with this dataflow?"
            )
            before = _chat_text_length(page)
            page.get_by_role("button", name="Send", exact=True).first.click()
            _wait_for_reply(page, timeout=180000, before=before)
            turns += 1
        with run.step(f"Next agent ({index + 1})", may_fail=True):
            nxt = page.get_by_role("button", name="Next agent")
            if not nxt.count():
                break
            nxt.first.click()
            page.wait_for_timeout(1500)
    log(f"[stress] completed {turns} live agent turns")
    run.snap("agent-chat-after-turns")

    with run.step("Apply a proposal if one was minted", may_fail=True):
        apply_button = page.get_by_role("button", name=re.compile("^Apply", re.I))
        if apply_button.count():
            before = len(canvas_nodes(page))
            apply_button.first.click()
            page.wait_for_timeout(6000)
            after = len(canvas_nodes(page))
            log(f"[stress] apply changed the canvas from {before} to {after} nodes")
            run.snap("agent-proposal-applied")
        else:
            log("[stress] no proposal was minted by the turns above")

    with run.step("Escape closes the chat"):
        page.keyboard.press("Escape")
        page.wait_for_timeout(1200)

    with run.step("The Agent Catalog page"):
        page.goto(f"{run.frontend}/catalog/agents")
        page.wait_for_load_state("domcontentloaded")
        expect(
            page.get_by_role("heading", name="Agent Catalog")
        ).to_be_visible(timeout=45000)
        page.wait_for_timeout(1800)
        run.snap("catalog-agents-page")

    with run.step("AI Settings from the global header"):
        button = page.get_by_role("button", name="AI Settings", exact=True)
        assert button.count(), "the catalog header has no AI Settings button"
        tour.click(button.first)
        expect(
            page.get_by_role("heading", name="AI Settings", level=2)
        ).to_be_visible(timeout=20000)
        hf = ai_field(page, "HuggingFace token")
        if hf.count():
            hf.fill("hf_stress_placeholder")
        run.snap("ai-settings-header")
        page.get_by_role("button", name="Cancel", exact=True).first.click()
        page.wait_for_timeout(900)


def _first_coord(installed: list[str], fragment: str) -> str:
    for coord in installed:
        if fragment in coord:
            return coord
    assert installed, "no agents installed"
    return installed[0]


def _chat_panel(page):
    return page.locator('[role=dialog][aria-label^="Chat with"]').first


def _chat_text_length(page) -> int:
    try:
        return len(_chat_panel(page).inner_text() or "")
    except Exception:  # noqa: BLE001
        return 0


def _wait_for_reply(page, *, timeout: float, before: int) -> None:
    """Wait for the transcript to grow and then settle.

    The panel's class names are hashed CSS modules, so there is nothing stable
    to select the streaming indicator by. The transcript's own text length is
    both stable and exactly what "a reply arrived" means: it grows past where it
    was, then stops changing once the stream ends.
    """
    deadline = time.monotonic() + timeout / 1000
    grown = False
    stable = 0
    last = before
    while time.monotonic() < deadline:
        page.wait_for_timeout(1500)
        current = _chat_text_length(page)
        if current > before + 20:
            grown = True
        if grown:
            stable = stable + 1 if current == last else 0
            if stable >= 3:
                return
        last = current
    raise PlaywrightTimeoutError(
        f"no reply within {timeout} ms (transcript {before} -> {last} chars)"
    )


# ---------------------------------------------------------------------------
# Chapter 06 - views: the bundled examples, dashboard, provenance, Autark
# ---------------------------------------------------------------------------


#: (file, node count, whether it needs WebGPU). Node counts gate the load, so a
#: dataflow that half-loads fails at the load rather than three steps later.
EXAMPLE_RUNS: tuple[tuple[str, int, bool], ...] = (
    ("01-vega-lite-chained-transforms.json", 6, False),
    ("02-vega-lite-spatial-density.json", 8, False),
    ("03-vega-lite-linked-temporal-charts.json", 4, False),
    ("04-vega-lite-multi-flow-dashboard.json", 24, False),
    ("05-vega-lite-multi-view-drilldown.json", 27, False),
    ("09-heterogeneous-data-linked-views.json", 13, False),
    ("06-autark-what-if-shadow-study.json", 6, True),
    ("07-autark-gpu-shader.json", 5, True),
    ("08-autark-spatial-join-regression.json", 8, True),
    ("11-autark-pbf-loading.json", 2, True),
    # Needs curio.streetvision, which the `nodes` chapter installs, and a
    # HuggingFace token for its gated model.
    ("10-street-vision-cv-analysis.json", 8, False),
)


def chapter_views(run: StressRun) -> None:
    page, tour = run.page, run.tour
    tour.chapter("Chapter 6", "Views and provenance",
                 "Every bundled example, dashboard mode, provenance, WebGPU maps.")

    with run.step("Open a dataflow"):
        _enter_project(run, name="Stress: views")

    for filename, expected, needs_gpu in EXAMPLE_RUNS:
        path = os.path.join(EXAMPLES, filename)
        with run.step(f"Load {filename}", may_fail=True):
            if not os.path.exists(path):
                run.note(f"example {filename} is missing from docs/examples",
                         step=f"Load {filename}", severity="warning")
                continue
            load_example(run, path, expected_nodes=expected)
            run.snap(f"example-{filename.split('-')[0]}-loaded")
        with run.step(f"Run {filename}", may_fail=True,
                      allow=("HTTP 4\\d\\d",)):
            play_all(run, timeout_ms=420000)
            errored = report_errored_nodes(run, f"Run {filename}")
            dismiss_toasts(page)
            run.snap(f"example-{filename.split('-')[0]}-ran")
            if errored and needs_gpu:
                run.note(
                    f"{filename}: {len(errored)} node(s) errored - for an Autark "
                    "dataflow this usually means WebGPU is unavailable in the "
                    "browser this run launched",
                    step=f"Run {filename}", severity="error",
                )

    with run.step("Linked views: brush one chart, watch the other follow",
                  may_fail=True):
        load_example(run, os.path.join(DATAFLOWS, "Interaction_Vega_Simple.json"),
                     expected_nodes=3)
        play_all(run, timeout_ms=300000)
        canvas = page.locator("canvas").first
        if canvas.count():
            box = canvas.bounding_box()
            if box:
                page.mouse.move(box["x"] + box["width"] * 0.3,
                                box["y"] + box["height"] * 0.5)
                page.mouse.down()
                page.mouse.move(box["x"] + box["width"] * 0.7,
                                box["y"] + box["height"] * 0.5, steps=25)
                page.mouse.up()
                page.wait_for_timeout(2500)
                run.snap("linked-brush")

    with run.step("The Data Pool node scrolls its own rows", may_fail=True):
        load_example(run, os.path.join(DATAFLOWS, "DataPool_Dataframe.json"),
                     expected_nodes=2)
        play_all(run, timeout_ms=300000)
        pool = node_ids_by_type(page, "data-pool")
        if pool:
            center_on(page, pool[0], zoom=1.0)
            box = node_locator(page, pool[0]).bounding_box()
            if box:
                page.mouse.move(box["x"] + box["width"] / 2,
                                box["y"] + box["height"] / 2)
                for _ in range(6):
                    page.mouse.wheel(0, 160)
                    page.wait_for_timeout(220)
                run.snap("data-pool-scrolled")

    with run.step("A Merge Flow dataflow", may_fail=True):
        load_example(run, os.path.join(DATAFLOWS, "Merge.json"), expected_nodes=5)
        play_all(run, timeout_ms=300000)
        report_errored_nodes(run, "A Merge Flow dataflow")

    with run.step("A JavaScript computation node", may_fail=True):
        load_example(run, os.path.join(DATAFLOWS, "JSComputation.json"),
                     expected_nodes=2)
        play_all(run, timeout_ms=300000)
        report_errored_nodes(run, "A JavaScript computation node")
        run.snap("js-computation")

    with run.step("Widgets drive a node", may_fail=True):
        load_example(run, os.path.join(DATAFLOWS, "Widget.json"), expected_nodes=6)
        play_all(run, timeout_ms=300000)
        run.snap("widgets")

    with run.step("Dashboard mode: pin, enter, lock, exit"):
        load_example(run, os.path.join(EXAMPLES,
                                       "04-vega-lite-multi-flow-dashboard.json"),
                     expected_nodes=24)
        play_all(run, timeout_ms=420000)
        before = len(canvas_nodes(page))
        for node in canvas_nodes(page)[:2]:
            pin = _header_icon(page, node["id"], "Pin to dashboard")
            if pin.count():
                activate_header_icon(pin)
                page.wait_for_timeout(500)
        tour.click(menu(page, "View"), force=True)
        tour.click(page.get_by_role(
            "button", name=re.compile("Dashboard Mode", re.I)).first)
        page.wait_for_timeout(2500)
        run.snap("dashboard-mode")
        lock = page.locator("[title*='ock']").first
        if lock.count():
            lock.click(force=True)
            page.wait_for_timeout(1000)
            lock.click(force=True)
            page.wait_for_timeout(800)
        exit_button = page.get_by_role(
            "button", name=re.compile("Exit Dashboard", re.I))
        if exit_button.count():
            tour.click(exit_button.first)
        else:
            page.locator("[title*='Exit']").first.click(force=True)
        page.wait_for_timeout(2500)
        after = len(canvas_nodes(page))
        assert after == before, (
            f"dashboard mode lost nodes: {before} before, {after} after"
        )

    with run.step("The provenance window", may_fail=True):
        tour.click(menu(page, "Provenance"), force=True)
        tour.click(page.get_by_role("button", name="Provenance", exact=True).first)
        page.wait_for_timeout(2500)
        run.snap("provenance-window")
        _close_modal(page)

    with run.step("A node's own provenance tab", may_fail=True):
        nodes = canvas_nodes(page)
        if nodes:
            node_id = nodes[0]["id"]
            center_on(page, node_id, zoom=1.0)
            tab = _editor_tab(page, node_id, "Provenance")
            if tab.count():
                tab.first.dispatch_event("click")
                page.wait_for_timeout(1800)
                run.snap("node-provenance")

    with run.step("Share the dataflow read-only", may_fail=True):
        share = page.get_by_role("button", name=re.compile("Share", re.I))
        if share.count():
            share.first.click()
            page.wait_for_timeout(2000)
            run.snap("share-dialog")
            _close_modal(page)
        else:
            run.note("no Share control found on the canvas",
                     step="Share the dataflow read-only")

    with run.step("The in-app tutorial walks the palette"):
        tour.click(menu(page, "Help"), force=True)
        tour.click(page.get_by_role("button", name="Tutorial", exact=True).first)
        page.wait_for_timeout(2000)
        run.snap("intro-tutorial")
        for index in range(9):
            nxt = page.locator(".introjs-nextbutton")
            if not nxt.count() or not nxt.first.is_visible():
                break
            nxt.first.click()
            page.wait_for_timeout(900)
        done = page.locator(".introjs-donebutton, .introjs-skipbutton")
        if done.count():
            done.first.click()
        page.wait_for_timeout(1200)

    tour.chapter("That is the tour", "Curio",
                 "Every surface, every node, every agent.")


# ---------------------------------------------------------------------------
# The chapter registry and the recorder
# ---------------------------------------------------------------------------


CHAPTERS: list[tuple[str, object]] = [
    ("access", chapter_access),
    ("canvas", chapter_canvas),
    ("nodes", chapter_nodes),
    ("data", chapter_data),
    ("agents", chapter_agents),
    ("views", chapter_views),
]

CHAPTER_IDS = [name for name, _ in CHAPTERS]


def _selected() -> set[str]:
    wanted = os.environ.get("CURIO_STRESS_CHAPTERS")
    if not wanted:
        return set(CHAPTER_IDS)
    names = {n.strip() for n in wanted.split(",") if n.strip()}
    unknown = names - set(CHAPTER_IDS)
    if unknown:
        raise ValueError(f"unknown chapter(s) {sorted(unknown)}; valid: {CHAPTER_IDS}")
    return names


def _warm_up(browser, frontend: str) -> None:
    """Pay webpack-dev-server's first-compile cost off camera.

    The very first request can spend fifteen seconds serving a blank document
    while the bundle compiles, which in a recording is fifteen seconds of white.
    """
    context = browser.new_context(viewport=VIDEO_SIZE)
    page = context.new_page()
    try:
        page.goto(f"{frontend}/auth/signin", timeout=180000)
        page.wait_for_load_state("domcontentloaded")
        try:
            page.get_by_text("Sign in", exact=False).first.wait_for(timeout=90000)
        except Exception:  # noqa: BLE001
            pass
    finally:
        context.close()


@pytest.fixture(scope="class")
def warmed(browser, frontend_server):
    _warm_up(browser, frontend_server)
    return True


@pytest.fixture(scope="class", autouse=True)
def stress_report():
    """Merge the per-chapter reports once the whole class has run."""
    yield
    path = write_report()
    log(f"[stress] wrote {path}")


class TestCurioStressTour:
    """Six recorded chapters. Listed in fixtures._SHARED_SESSION_CLASSES."""

    def _record(self, chapter, scene, browser, frontend, backend):
        if chapter not in _selected():
            pytest.skip(f"chapter {chapter} not selected")

        raw_dir = os.path.join(out_dir(), "raw")
        os.makedirs(raw_dir, exist_ok=True)
        for stale in os.listdir(raw_dir):
            if stale.startswith("page@") and stale.endswith(".webm"):
                try:
                    os.remove(os.path.join(raw_dir, stale))
                except OSError:
                    pass

        context = browser.new_context(
            viewport=VIDEO_SIZE,
            record_video_dir=raw_dir,
            record_video_size=VIDEO_SIZE,
        )
        page = context.new_page()
        # The drawers slide with translate3d and their providers read
        # prefers-reduced-motion through useSyncExternalStore, so a panel is only
        # reachable once the transition is collapsed. Must precede any login.
        page.emulate_media(reduced_motion="reduce")

        run = StressRun(
            chapter, page, Tour(page, pace=stress.speed()),
            frontend=frontend, backend=backend,
        )
        # One dialog policy for the whole chapter, so a step that needs a
        # specific prompt answer can set it rather than racing a second handler.
        run.state["dialog"] = {"accept": True, "prompt": None}

        def on_dialog(dialog):
            try:
                policy = run.state.get("dialog", {})
                if not policy.get("accept", True):
                    dialog.dismiss()
                elif policy.get("prompt") is not None:
                    dialog.accept(policy["prompt"])
                else:
                    dialog.accept()
            except Exception:  # noqa: BLE001
                pass

        page.on("dialog", on_dialog)
        run.mark_recording_start()
        written: dict = {}

        try:
            scene(run)
        except Exception as exc:  # noqa: BLE001 - the recording is the deliverable
            run.add("blocker", "step", f"chapter aborted: {exc}",
                    step="(chapter)", detail=str(exc))
            log(f"[stress] chapter {chapter} aborted: {exc}")
        finally:
            page.close()
            context.close()
            written = finalize_chapter_video(page, chapter=chapter)
            for kind, path in written.items():
                log(f"[stress] wrote {kind}: {path}")
            run.write()
            log(f"[stress] {run.summary()}")

        assert written, f"chapter {chapter} recorded no video"

    def test_chapter_access(self, warmed, browser, frontend_server, current_server):
        self._record("access", chapter_access, browser, frontend_server,
                     current_server)

    def test_chapter_canvas(self, warmed, browser, frontend_server, current_server):
        self._record("canvas", chapter_canvas, browser, frontend_server,
                     current_server)

    def test_chapter_nodes(self, warmed, browser, frontend_server, current_server):
        self._record("nodes", chapter_nodes, browser, frontend_server,
                     current_server)

    def test_chapter_data(self, warmed, browser, frontend_server, current_server):
        self._record("data", chapter_data, browser, frontend_server, current_server)

    def test_chapter_agents(self, warmed, browser, frontend_server, current_server):
        self._record("agents", chapter_agents, browser, frontend_server,
                     current_server)

    def test_chapter_views(self, warmed, browser, frontend_server, current_server):
        self._record("views", chapter_views, browser, frontend_server,
                     current_server)
