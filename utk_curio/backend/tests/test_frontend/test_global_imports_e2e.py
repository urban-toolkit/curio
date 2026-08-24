"""Playwright E2E for #158: imports must be global across a dataflow.

The issue as reported: "Only some libraries are imported globally. Some
libraries, such as numpy and shapely, must be manually imported to every node
that uses them... This is not the case for libraries such as pandas."

Two separate causes, and this test covers the user-visible surface of both:

  * ``pandas``/``geopandas`` were never inherited from anywhere - they are
    pre-seeded into every node's globals by ``_worker_init``. ``numpy`` and
    ``shapely`` were dropped from that seed when execution moved in-process
    (the old subprocess wrapper leaked them via ``from parsers import *``).
  * a node's own ``import`` was function-local by construction, because user
    code is sunk into ``def userCode(arg):``.

Both are unit-tested in ``test_sandbox_namespace.py``, which is where the
detail belongs. This test exists because that one talks to ``execute_code``
directly: it cannot see whether the frontend's indentation, the sandbox HTTP
hop, or session-token plumbing gets in the way of the same code path in a real
browser.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_global_imports_e2e.py -v
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .utils import (
    connect_nodes,
    dismiss_toasts,
    drag_to_canvas,
    require_project_page,
    require_user_auth,
    run_node_and_wait,
    save_workflow_test_screenshot,
    set_node_code,
    skip_if_shared_view,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

ANALYSIS_TILE = "#step-analysis"
ANALYSIS_TYPE = "curio.builtin/computation-analysis"

POS_UP = (150, 150)
POS_DOWN = (760, 150)

SEEDED_MARKER = "CURIO_E2E_SEEDED"
CROSS_MARKER = "CURIO_E2E_CROSS"


def test_a_library_imported_upstream_is_usable_downstream(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    """The issue's own reproduction: node A imports numpy, node B uses ``np``."""
    require_project_page()
    require_user_auth()

    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Import User",
        username="import_user",
        project_name="Global Imports",
    )
    skip_if_shared_view(page)

    upstream = drag_to_canvas(page, page.locator(ANALYSIS_TILE), at=POS_UP)
    downstream = drag_to_canvas(page, page.locator(ANALYSIS_TILE), at=POS_DOWN)
    connect_nodes(page, upstream, downstream)

    # Upstream imports under an alias the seed does not provide, so a pass can
    # only come from the import actually crossing the node boundary. Using plain
    # `np` here would prove nothing - it is pre-seeded.
    set_node_code(
        page, upstream,
        "import numpy as e2e_np\n"
        "return [1, 2, 3]\n",
    )
    set_node_code(
        page, downstream,
        # No import line. Pre-fix this raised NameError: name 'e2e_np' is not defined.
        f'print("{CROSS_MARKER}", e2e_np.mean(arg))\n'
        "return float(e2e_np.mean(arg))\n",
    )

    run_node_and_wait(page, upstream, node_type=ANALYSIS_TYPE)
    downstream_output = run_node_and_wait(page, downstream, node_type=ANALYSIS_TYPE)

    assert f"{CROSS_MARKER} 2.0" in downstream_output, (
        "the upstream node's `import numpy as e2e_np` did not reach the "
        f"downstream node (#158). Output was:\n{downstream_output}"
    )

    # Not just a sweep: the debounced dataset install fires a "couldn't be
    # generated" warning a second or two AFTER the node reports Done, so the
    # helper waits for a quiet window before returning.
    dismiss_toasts(page)
    save_workflow_test_screenshot(
        page, "global-imports",
        test_name="test_a_library_imported_upstream_is_usable_downstream",
    )


def test_numpy_and_shapely_work_with_no_import_line_at_all(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    """The other half of #158: names the in-process move silently dropped.

    ``pandas`` kept working because it is pre-seeded; ``numpy`` and ``shapely``
    were not, which is what made the behaviour look arbitrary to users.
    """
    require_project_page()
    require_user_auth()

    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Import User",
        username="import_user_seeded",
        project_name="Seeded Imports",
    )
    skip_if_shared_view(page)

    node_id = drag_to_canvas(page, page.locator(ANALYSIS_TILE), at=POS_UP)
    set_node_code(
        page, node_id,
        # Deliberately no imports. pd was always available; np and wkt are the
        # regression. Asserting them together is the point - the user's complaint
        # was the inconsistency between them.
        f'print("{SEEDED_MARKER}", pd.Series([1, 2, 3]).sum(), '
        'np.mean([1, 2, 3]), wkt.loads("POINT (4 5)").x)\n'
        "return 1\n",
    )

    output = run_node_and_wait(page, node_id, node_type=ANALYSIS_TYPE)
    assert f"{SEEDED_MARKER} 6 2.0 4.0" in output, (
        "pandas, numpy and shapely are not all usable without an import line "
        f"(#158). Output was:\n{output}"
    )
