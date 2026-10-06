"""Playwright E2E: New node from a Python function (#662, step 21).

SCOUT's Compute Catalog, the Curio way. The Node Catalog drawer's **New node
from a Python function** lists the functions of the modules installed
packages ship. This picks ``season_factor`` in ``scout_shadow.deep_umbra``,
a module of the shipped, read-only ``scout.shadow@1`` package, gives its one
parameter a text widget, and creates the node in a new package. Then:

1. The node is in the palette with no reload, and its code imports the
   function and calls it with the widget's reference.
2. Run below a reader node, it returns the minutes a winter pixel stands for
   (360): the node imported the module of the package its own package depends
   on, since a read-only package takes no new template.
3. Set to spring, the widget makes the node stale, so running the reader again
   runs it again (540).

The dialog and the node are close-up baselines to review.

The package is in every account's store because the stack starts with
``--with-examples``.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_node_from_function_e2e.py -v
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .utils import (
    api_json,
    close_tools_palette,
    connect_nodes,
    drag_to_canvas,
    node_execution_timeout_ms,
    node_locator,
    open_tools_palette,
    play_node,
    read_node_code,
    read_node_output_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_node_and_wait,
    save_node_closeup,
    save_workflow_test_screenshot,
    set_node_code,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

TILE = "#tile-computation-analysis"
NODE_TYPE = "curio.builtin/computation-analysis"
READER_CODE = "print(f'<<{arg}>>')\nreturn arg\n"

SHADOW_DIR = "scout.shadow@1"
MODULE = "scout_shadow.deep_umbra"
FUNCTION = "season_factor"
LABEL = "Season factor"
WRITTEN_CODE = (
    "from scout_shadow.deep_umbra import season_factor\n"
    "\n"
    "return season_factor(season=[!! season !!])\n"
)

DRAWER = '[data-curio-node-catalog-drawer="true"]'
DIALOG = "[data-node-from-function]"

#: The close-ups' baselines are ``screenshot_node-from-function_<name>.png``.
CLOSEUP_STEM = "node-from-function"


def _open_drawer(page, project_id: str):
    """The bar's Node Catalog button, once the drawer knows the project."""
    with page.expect_response(
        lambda r: f"/api/packages/projects/{project_id}" in r.url and r.request.method == "GET",
        timeout=30000,
    ):
        page.get_by_role("button", name="Node Catalog", exact=True).click()
    page.locator(DRAWER).wait_for(state="attached", timeout=15000)
    drawer = page.get_by_role("dialog").filter(has=page.get_by_role("heading", name="Node Catalog", exact=True))
    expect(drawer).to_be_visible(timeout=10000)
    return drawer


def _open_tab(page, node_id: str, key: str) -> None:
    tab = node_locator(page, node_id).locator(f'.nav-link[data-rr-ui-event-key="{key}"]').first
    tab.wait_for(state="visible", timeout=15000)
    if "active" not in (tab.get_attribute("class") or ""):
        tab.dispatch_event("click")
    page.wait_for_function(
        """([nodeId, key]) => {
            const el = document.querySelector(
                `.react-flow__node[data-id="${nodeId}"] .nav-link[data-rr-ui-event-key="${key}"]`);
            return !!el && el.classList.contains("active");
        }""",
        arg=[node_id, key],
        timeout=10000,
    )


def _wait_for_code_containing(page, node_id: str, text: str, *, timeout: float = 20000) -> None:
    page.wait_for_function(
        """([nodeId, text]) => {
            const el = document.querySelector(`.react-flow__node[data-id="${nodeId}"] .monaco-editor`);
            const editors = (window.monaco && window.monaco.editor.getEditors()) || [];
            const ed = editors.find((e) => el && el.contains(e.getDomNode()));
            return !!ed && ed.getValue().includes(text);
        }""",
        arg=[node_id, text],
        timeout=timeout,
    )


def _wait_for_output(page, node_id: str, needle: str, what: str) -> None:
    try:
        page.wait_for_function(
            """([nodeId, needle]) => {
                const box = document.querySelector(
                    `.react-flow__node[data-id="${nodeId}"] [data-curio-node-output]`);
                return !!box && (box.textContent || "").includes(needle);
            }""",
            arg=[node_id, needle],
            timeout=node_execution_timeout_ms(NODE_TYPE),
        )
    except Exception:
        raise AssertionError(
            f"{what}: the reader never printed {needle!r}; its output reads "
            f"{read_node_output_text(page, node_id)!r}"
        ) from None


def _expand_package(anchor) -> None:
    """Open the palette accordion so its rows are draggable (the rows are in
    the DOM while it is shut; only a drag needs them visible)."""
    details = anchor.locator("details").first
    details.wait_for(state="attached", timeout=15000)
    if not details.evaluate("(el) => el.open"):
        anchor.locator("summary").first.locator("span[title]").first.click()
    expect(details).to_have_attribute("open", "", timeout=10000)


def test_a_function_in_a_shipped_package_becomes_a_node_that_runs(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    require_project_page()
    require_user_auth()

    page.emulate_media(reduced_motion="reduce")
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Function Author",
        username="node_from_function_e2e",
        project_name="Node from a function",
    )
    require_owner_view(page)
    token = session["token"]
    project_id = session["project"]["id"]
    store = [p.get("dirName") for p in api_json(f"{current_server}/api/packages", token)["packages"]]
    assert SHADOW_DIR in store, f"{SHADOW_DIR} is not in the account's store {store}: start the stack --with-examples"

    reader = drag_to_canvas(page, page.locator(TILE), at=(760, 150))
    set_node_code(page, reader, READER_CODE)

    created = None
    try:
        # The dialog lists the shipped package's functions, read from the source.
        drawer = _open_drawer(page, project_id)
        drawer.get_by_role("button", name="New node from a Python function").click()
        dialog = page.locator(DIALOG)
        expect(dialog).to_be_visible(timeout=10000)
        choice = dialog.locator("#node-from-function-choice")
        value = f"{SHADOW_DIR}|{MODULE}|{FUNCTION}"
        expect(choice.locator(f'option[value="{value}"]')).to_have_count(1, timeout=30000)
        choice.select_option(value)

        # Nothing in the source says what season is, so it starts as an input;
        # it becomes a text widget that starts at winter.
        row = dialog.locator('[data-function-parameter="season"]')
        use = row.get_by_label("What season is given")
        expect(use).to_have_value("input")
        use.select_option("widget")
        row.get_by_role("button", name="Edit widget").click()
        form = row.locator("[data-widget-form]")
        expect(form.get_by_label("Widget type")).to_have_value("text")
        form.get_by_label("Widget default").fill("winter")
        form.get_by_role("button", name="Save widget").click()
        expect(row).to_contain_text("Text, starting at winter")

        # A read-only package takes no new template: a new package does.
        expect(dialog.locator("#node-from-function-package-target")).to_have_value("__save_as_new__")
        expect(dialog.locator("#node-from-function-label")).to_have_value(LABEL)
        dialog.locator("#node-from-function-new-package-name").fill("Shadow functions")
        # The fields scroll between the title and the buttons; the frame shows
        # them from the top, the function and its parameter first.
        dialog.locator("[data-node-from-function-body]").evaluate("(el) => el.scrollTo(0, 0)")
        save_workflow_test_screenshot(
            page, CLOSEUP_STEM, test_name="dialog", fit_reactflow=False, clip_selector=DIALOG,
        )

        with page.expect_response(
            lambda r: r.url.endswith("/api/packages/factory/install") and r.request.method == "POST",
            timeout=180000,
        ) as installed:
            dialog.get_by_role("button", name="Create node").click()
        response = installed.value
        assert response.ok, f"factory install failed ({response.status}): {response.text()[:500]}"
        package = response.json()["package"]
        created = package["dirName"]
        # The function's package is a dependency, not a library to pip-install.
        assert package["dependencies"]["packages"] == {SHADOW_DIR: "*"}, package["dependencies"]
        assert "scout_shadow" not in package["dependencies"]["python"], package["dependencies"]
        expect(dialog).to_have_count(0, timeout=30000)

        drawer.locator("header").get_by_role("button", name="Close Node Catalog drawer").click()
        expect(page.locator(DRAWER)).to_have_count(0, timeout=10000)

        # 1. In the palette with no reload; its code calls the function.
        open_tools_palette(page, "packages")
        anchor = page.locator(f'#packages-palette [data-pkg-palette-coords~="{created}"]')
        expect(anchor).to_have_count(1, timeout=20000)
        _expand_package(anchor)
        palette_row = anchor.locator("div:has(> [data-pkg-template-id])").filter(has_text=LABEL)
        expect(palette_row).to_have_count(1, timeout=20000)
        node = drag_to_canvas(page, palette_row, at=(150, 150))
        close_tools_palette(page, "packages")
        connect_nodes(page, node, reader)
        _wait_for_code_containing(page, node, "season_factor(")
        assert read_node_code(page, node) == WRITTEN_CODE, read_node_code(page, node)
        # The template's widget came with the node: its tag above the code, and
        # the reference drawn as a chip. Captured before the run, whose output
        # pane names a fresh artifact id every time.
        node_locator(page, node).locator('[data-widget-strip] [data-widget-tag="season"]').wait_for(
            state="visible", timeout=10000,
        )
        node_locator(page, node).locator(".monaco-editor .curio-widget-ref").first.wait_for(
            state="attached", timeout=10000,
        )
        assert node_locator(page, node).locator(".monaco-editor .curio-widget-ref-problem").count() == 0
        save_node_closeup(page, CLOSEUP_STEM, node, test_name="node", sweep_toasts=True)

        # 2. It runs, importing the function from the package it depends on.
        run_node_and_wait(page, reader, node_type=NODE_TYPE)
        _wait_for_output(page, reader, "<<360>>", "With the season at winter")

        # 3. A new value makes the node stale: running the reader runs it again.
        _open_tab(page, node, "widgets")
        node_locator(page, node).locator("[data-widgets-panel]").first.get_by_label("Season", exact=True).fill("spring")
        play_node(page, reader)
        _wait_for_output(page, reader, "<<540>>", "After setting the season to spring")
    finally:
        if created:
            try:
                api_json(f"{current_server}/api/packages/{created}", token, method="DELETE", timeout=60.0)
            except Exception as exc:  # noqa: BLE001 - teardown must not mask failures
                print(f"[teardown] DELETE package {created} failed: {exc}")
