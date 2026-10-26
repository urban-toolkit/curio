"""Playwright E2E: a revert is read once the version's connections are drawn (#1168).

The walkthrough ``provenance-reverting-to-a-previous-version`` steps example 01
back through its history and checks, after each revert, that the canvas holds
the version's nodes and connections. Twice on CI (e2e-desktop (7), runs
40214372656 and 40266735120) its first revert read "6 nodes and 0 connections"
for version 11, which holds 6 and 4. The browser log showed the revert connect
all 4, and the screenshot taken at the failure showed them drawn.

A revert hands React Flow new node objects, without the sizes it measured. React
Flow then hides each node and draws no connection to it until it has measured
the node again, in its ResizeObserver callback, which the browser runs only
when it draws a frame. The canvas holds 6 nodes before that revert and after
it, so the scene's wait for 6 nodes passed at once, and its read, 150 ms after
the click, came before React Flow measured the nodes again.

This test plays a runner that draws no frame for a while after the click. An
init script, installed before the app loads, holds the page's ResizeObserver
and animation frame callbacks from the click on "Put this version on the
canvas" until ``HOLD_MS`` later, then runs them in the order they came. The
test runs the scene's own steps for its first revert (``walkthroughs/steps.py``)
and asserts what the scene asserts.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_provenance_revert_e2e.py -v
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .utils import (
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_login_and_enter_workflow,
)
from .walkthroughs import PROVENANCE_EXAMPLE, Ctx, SilentNarrator, load_example_spec
from .walkthroughs.steps import (
    await_canvas_nodes,
    canvas_graph,
    open_provenance,
    open_version,
    put_version_on_canvas,
    version_graph,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

#: How long the page runs no frame callback after the click: far past the
#: scene's 150 ms beat after it, and well inside its 15 s wait for the canvas.
HOLD_MS = 5000

#: The button that puts an opened version on the canvas.
RESTORE = "Put this version on the canvas"

# Before the app's own scripts, so React Flow's ResizeObserver and whatever
# takes requestAnimationFrame when the app loads go through it. A click on a
# version's restore button, seen before the app's own handler, starts the hold:
# for *ms* from then the page runs none of the callbacks the browser runs only
# when it draws a frame, as on a page that draws none. Then it runs them, in the
# order they came. The browser still delivers its observations; only their
# callbacks wait.
_HOLD_FROM_THE_RESTORE_JS = """(([label, ms]) => {
    const request = window.requestAnimationFrame.bind(window);
    const cancel = window.cancelAnimationFrame.bind(window);
    const Observer = window.ResizeObserver;
    let held = null;
    let nextId = -1;
    window.__curioTestHolds = 0;
    window.requestAnimationFrame = (callback) => {
        if (!held) return request(callback);
        const id = nextId--;
        held.set(id, () => request(callback));
        return id;
    };
    window.cancelAnimationFrame = (id) => {
        if (held && held.delete(id)) return;
        cancel(id);
    };
    window.ResizeObserver = class extends Observer {
        constructor(callback) {
            super((entries, observer) => {
                if (!held) {
                    callback(entries, observer);
                    return;
                }
                held.set(nextId--, () => callback(entries, observer));
            });
        }
    };
    const release = () => {
        const deferred = held ? [...held.values()] : [];
        held = null;
        deferred.forEach((run) => run());
    };
    document.addEventListener('click', (event) => {
        const button = event.target instanceof Element ? event.target.closest('button') : null;
        if (held || !button || button.textContent.trim() !== label) return;
        held = new Map();
        window.__curioTestHolds += 1;
        setTimeout(release, ms);
    }, true);
})"""

# How many nodes React Flow holds without a measured size, or null before the
# canvas is up.
_UNMEASURED_JS = """() => window.__curio_reactFlow
    ? window.__curio_reactFlow.getNodes()
        .filter((node) => !(node.width > 0 && node.height > 0)).length
    : null"""


def _hold_script() -> str:
    return f"{_HOLD_FROM_THE_RESTORE_JS}({json.dumps([RESTORE, HOLD_MS])});"


def test_a_revert_is_read_once_the_versions_connections_are_drawn(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()

    page.emulate_media(reduced_motion="reduce")
    page.context.add_init_script(_hold_script())
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Prov User",
        username="prov_revert_late",
        project_name="Provenance revert",
        project_spec=load_example_spec(PROVENANCE_EXAMPLE),
    )
    require_owner_view(page)
    page.wait_for_selector(".react-flow__node", timeout=45000)
    assert page.evaluate("() => window.__curioTestHolds") == 0, (
        "the init script that holds frame callbacks from the restore click is not in the page"
    )
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    ctx = Ctx(
        page=page,
        frontend=app_frontend.base_url,
        backend=current_server,
        narrator=SilentNarrator(page),
        recording=False,
    )

    # The scene's first revert: the version before the newest.
    panel = open_provenance(ctx)
    versions = panel.locator("[data-provenance-item]")
    count = versions.count()
    assert count > 1, f"the provenance history offers {count} versions to revert to"
    index = count - 2
    version = versions.nth(index)
    open_version(page, version, click=ctx.click)
    expected = version_graph(version)
    assert expected["edges"] > 0, (
        f"version {index + 1} holds no connection, so this test proves nothing: {expected}"
    )
    assert page.evaluate(_UNMEASURED_JS) == 0, (
        "React Flow had not measured every node before the revert, so this test proves nothing"
    )

    put_version_on_canvas(ctx, version)
    holds = page.evaluate("() => window.__curioTestHolds")
    assert holds == 1, f"the click on {RESTORE!r} started {holds} holds, not 1"
    unmeasured = page.evaluate(_UNMEASURED_JS)
    assert unmeasured == expected["nodes"], (
        f"{unmeasured} of the {expected['nodes']} nodes the revert put back were unmeasured "
        f"while the page ran no frame callback: React Flow measured the rest some other "
        f"way, so this test proves nothing"
    )

    # The scene's own steps from here (walkthroughs/provenance.py).
    await_canvas_nodes(page, expected["nodes"])
    actual = canvas_graph(page)

    assert not errors, (
        f"reverting to version {index + 1} threw, and with no error boundary "
        f"in the app React tears down the whole canvas: "
        f"{errors[0].splitlines()[0]}"
    )
    assert actual == expected, (
        f"reverting to version {index + 1} of {count} left {actual['nodes']} "
        f"nodes and {actual['edges']} connections on the canvas, but that "
        f"version holds {expected['nodes']} and {expected['edges']}"
    )
    assert version.get_attribute("data-provenance-current") == "true", (
        f"version {index + 1} is on the canvas, but the drawer still marks "
        f"another one as in use"
    )
