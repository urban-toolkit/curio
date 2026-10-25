"""Playwright E2E: a dataflow holding a package's own node opens by its link and on reload.

The Column Filter of ``curio.example-ui@1`` draws its own interface with a
behavior hook that its package's bundle registers when it runs. A full load of
a dataflow, by its link or by a reload, builds the node descriptors before that
bundle has run: the node mounts with the generic package hook, and the bundle's
hook arrives in a rebuild after it. The node kept its body and called the new
hook where the old one's hooks were, React threw (its error 311), and the
route's error boundary replaced the whole canvas with "Something went wrong
here."

The owner adds ``curio.example-ui@1``, drops the Column Filter and saves. The
dataflow is then opened by its link, in a new full load, and reloaded. Each
time the package's bundle is held until the node is on the canvas, so the node
mounts before its hook is registered whichever of the page's registry
refreshes asks for the bundle first. The canvas stays, and the Column Filter
draws its own interface.

The same swap, without a browser: ``universalNodeHookSwap.test.tsx``.

Run::

    CURIO_E2E_USE_EXISTING=1 pytest \\
        utk_curio/backend/tests/test_frontend/test_package_node_reopens_e2e.py -v
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlparse

from playwright.sync_api import expect

from .test_package_refresh_e2e import _install_from_the_node_catalog
from .utils import (
    api_json,
    close_tools_palette,
    drag_to_canvas,
    node_locator,
    open_tools_palette,
    require_owner_view,
    require_project_page,
    require_user_auth,
    save_dataflow,
    stub_login_and_enter_workflow,
)
from .walkthroughs.column_filter import EXAMPLE_UI_PKG

if TYPE_CHECKING:
    from .utils import FrontendPage

#: What the Column Filter's own interface says before a frame reaches it. Only
#: the package's hook draws it: the generic package hook draws nothing in a
#: node with no editor.
OWN_INTERFACE = "Connect a DataFrame upstream"

#: What an error boundary draws in place of what threw (``ErrorBoundary.tsx``).
BOUNDARY_CARD = "Something went wrong here."

#: The line an error boundary logs when it catches a render error.
BOUNDARY_LOG = "[ErrorBoundary] contained a render error"

#: The global the example package's bundle sets once it has run, which is when
#: it registers the Column Filter's behavior (its UMD name, from
#: ``webpack.packages.config.js``).
BUNDLE_GLOBAL = "curio_example-ui_1"


def _is_the_bundle(url: str) -> bool:
    """The example package's behavior bundle,
    ``/api/packages/<dirName>/file/scripts/behaviors.js``. The dirName reaches
    the wire percent-encoded (``%40`` for ``@``), so the path is decoded first."""
    path = unquote(urlparse(url).path)
    return f"/api/packages/{EXAMPLE_UI_PKG}/file/" in path and path.endswith("/behaviors.js")


class _ParkedBundle:
    """Parks every request for the bundle until released, as ``_ParkedRegistry``
    in test_rail_fills_in_e2e does with ``GET /api/packages``. A request made
    after the release goes straight through."""

    def __init__(self, page):
        self.page = page
        self.held: list = []
        self.released = False
        self.handler = self._hold
        page.route(_is_the_bundle, self.handler)

    def _hold(self, route):
        if self.released:
            route.continue_()
        else:
            self.held.append(route)

    def release(self):
        self.released = True
        while self.held:
            route = self.held.pop()
            try:
                route.continue_()
            except Exception as exc:  # a request the page already abandoned
                print(f"[hook-swap] parked bundle request could not be continued: {exc}")
        self.page.unroute(_is_the_bundle, self.handler)


def _node_text(page, node_id: str) -> str:
    return " ".join(" ".join(node_locator(page, node_id).all_text_contents()).split())


def _draws_its_own_interface(page, node_id: str, *, when: str) -> None:
    try:
        expect(node_locator(page, node_id).get_by_text(OWN_INTERFACE)).to_be_visible(timeout=30000)
    except AssertionError as exc:
        raise AssertionError(
            f"{when}, the Column Filter does not draw its own interface. "
            f"It shows: {_node_text(page, node_id)[:300]!r}"
        ) from exc


def _open_with_the_bundle_held(page, navigate, node_id: str) -> None:
    """Navigate with the bundle parked until the Column Filter is on the canvas.

    A full load starts its registry refreshes before the dataflow loads, and
    the one that asks for the bundle first decides whether the node mounts
    before or after its hook is registered. Parking the bundle makes it before,
    every time, as it was in the CI runs that found the crash."""
    parked = _ParkedBundle(page)
    try:
        navigate()
        page.wait_for_load_state("domcontentloaded")
        node_locator(page, node_id).wait_for(state="attached", timeout=45000)
    finally:
        parked.release()


def _opens_whole(page, node_id: str, boundary_logs: list[str], *, when: str) -> None:
    """The canvas is there, with no error boundary's card, and the Column
    Filter draws its own interface once its package's hook is registered."""
    node = node_locator(page, node_id)
    own = node.get_by_text(OWN_INTERFACE)
    card = page.get_by_role("alert").filter(has_text=BOUNDARY_CARD)
    try:
        # Whichever comes first: the node's own interface, which only the
        # package's hook draws, or an error boundary's card.
        expect(own.or_(card).first).to_be_visible(timeout=60000)
    except AssertionError as exc:
        raise AssertionError(
            f"{when}, the Column Filter never drew its own interface. "
            f"It shows: {_node_text(page, node_id)[:300]!r}"
        ) from exc
    # The dataflow is the owner's, and waiting for a shared-view banner gives a
    # late render error a few seconds to show.
    require_owner_view(page)
    crashed = [text[:400] for text in boundary_logs]
    if card.count():
        crashed.append(" ".join((card.first.text_content() or "").split()))
    assert not crashed, (
        f"{when}, an error boundary replaced what threw: {' | '.join(crashed)}"
    )
    expect(page.locator("#tools-menu")).to_be_visible(timeout=15000)
    expect(node).to_be_visible(timeout=15000)
    expect(own).to_be_visible(timeout=15000)


def test_a_dataflow_holding_a_packages_own_node_opens_by_its_link_and_on_reload(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    base = app_frontend.base_url

    page.emulate_media(reduced_motion="reduce")
    session = stub_login_and_enter_workflow(
        page, frontend_url=base, backend_url=current_server,
        name="Hook Swap", username=f"hook_swap_{uuid.uuid4().hex[:8]}",
        project_name="Package node reopens",
    )
    require_owner_view(page)
    page.locator("#tools-menu").wait_for(state="visible", timeout=45000)
    project_id = session["project"]["id"]

    _install_from_the_node_catalog(page)
    # The bundle has run in this page, so the node dropped below is built with
    # the package's hook from the start.
    page.wait_for_function(f"() => window[{BUNDLE_GLOBAL!r}] !== undefined", timeout=30000)

    open_tools_palette(page, "packages")
    row = page.locator(f'#packages-palette [data-pkg-palette-coords~="{EXAMPLE_UI_PKG}"]')
    expect(row).to_have_count(1, timeout=30000)
    column_filter = drag_to_canvas(page, row, at=(640, 260))
    close_tools_palette(page, "packages")
    _draws_its_own_interface(page, column_filter, when="Right after the drop")

    save_dataflow(page)
    dataflow = api_json(
        f"{current_server}/api/projects/{project_id}", session["token"],
    )["spec"]["dataflow"]
    assert column_filter in {node["id"] for node in dataflow["nodes"]}, (
        f"the save did not record the Column Filter: {dataflow['nodes']}"
    )
    assert EXAMPLE_UI_PKG in (dataflow.get("packages") or []), (
        f"the save did not record the package in the dataflow: {dataflow.get('packages')}"
    )

    boundary_logs: list[str] = []
    page.on(
        "console",
        lambda msg: boundary_logs.append(msg.text) if BOUNDARY_LOG in msg.text else None,
    )

    # 1. Opened by its link, in a new full load.
    _open_with_the_bundle_held(
        page, lambda: page.goto(f"{base}/dataflow/{project_id}"), column_filter,
    )
    _opens_whole(page, column_filter, boundary_logs, when="Opened by its link")

    # 2. Reloaded.
    _open_with_the_bundle_held(page, page.reload, column_filter)
    _opens_whole(page, column_filter, boundary_logs, when="After a reload")
