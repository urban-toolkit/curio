"""Playwright E2E: a new connection hands its source's output to its new target alone.

A producer that ran feeds a Data Pool, which read the producer's artifact
through ``/get`` (its rows) and ``/get-preview`` (the table it shows), as a pool
does each time it is handed an input. Then the producer is connected to a
second node. The second node gets the producer's output, and the pool, which
already holds it, gets nothing again: it fetches nothing.

The dataflow is the dashboard page tests' (``test_dashboard_page_e2e.py``), a
producer, a Data Pool and a Vega chart, with a Python node that nothing feeds.
A Python node fetches nothing when its input arrives, so every fetch of the
producer's artifact after the connection is the pool's.

Run::

    CURIO_E2E_USE_EXISTING=1 pytest \\
        utk_curio/backend/tests/test_frontend/test_new_connection_fetched_once_e2e.py -v
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .test_dashboard_page_e2e import POOL, PRODUCER, _node, _run_the_chart, _spec
from .test_restored_outputs_fetched_once_e2e import QUIET_MS, _ArtifactRequests, _by_endpoint
from .utils import (
    connect_nodes,
    dismiss_toasts,
    frame_nodes,
    node_locator,
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

#: The node the producer is connected to once it ran: a Python node, below the pool.
SECOND = "conn-second"

#: The artifact a node's input names, or null.
_INPUT_PATH_JS = """(id) => (window.__curio_reactFlow.getNodes() || [])
    .find((n) => n.id === id)?.data?.input?.path ?? null"""

#: Whether a node's input names the artifact *path*.
_HOLDS_JS = """({ id, path }) => (window.__curio_reactFlow.getNodes() || [])
    .find((n) => n.id === id)?.data?.input?.path === path"""


def test_connecting_a_second_node_fetches_nothing_for_the_node_already_fed(
    app_frontend: "FrontendPage", current_server, page,
):
    require_project_page()
    require_user_auth()
    spec = _spec()
    spec["dataflow"]["nodes"].append(
        {**_node(SECOND, "curio.builtin/computation-analysis", 700), "y": 600}
    )
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Connection Owner",
        username=f"connect_once_{uuid.uuid4().hex[:8]}",
        project_name="New connection e2e",
        project_spec=spec,
    )
    require_owner_view(page)
    page.wait_for_selector(".react-flow__node", timeout=45000)
    dismiss_toasts(page)

    # The producer runs, and the pool reads its rows.
    _run_the_chart(page)
    pool_rows = node_locator(page, POOL).locator("table").first.locator("tbody tr")
    expect(pool_rows).to_have_count(3, timeout=45000)
    artifact = page.evaluate(_INPUT_PATH_JS, POOL)
    assert artifact, "the pool names no artifact of the producer after the run"
    requests = _ArtifactRequests(page, artifact)
    page.wait_for_timeout(QUIET_MS)
    requests.take()

    # The producer, connected to the second node.
    frame_nodes(page, [PRODUCER, SECOND])
    connect_nodes(page, PRODUCER, SECOND)
    page.wait_for_function(_HOLDS_JS, arg={"id": SECOND, "path": artifact}, timeout=15000)
    page.wait_for_timeout(QUIET_MS)
    seen = requests.take()

    fetched = _by_endpoint(seen)
    assert fetched == {"get": 0, "get-preview": 0}, (
        f"connecting {SECOND} to the producer made the pool, which already held the "
        f"producer's output ({artifact}), fetch it again, by endpoint: {fetched!r}; "
        f"the Accept header of each request: {seen!r}"
    )
