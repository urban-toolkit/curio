"""Playwright E2E for #233: the Street Vision example explains itself.

The report: three nodes in the "Street-level computer vision" example sit on
"Loading node…" indefinitely, and "connections involving these nodes also fail
to render".

Both symptoms had one cause. Nothing installs ``curio.streetvision`` - by
design, it pulls ~3 GB of torch - and the example's lockfile did not declare it
either, so no layer could even name the package the nodes needed. The
placeholder could not tell "the registry has not caught up" from "nothing
provides this", so it showed the first message forever; and because it rendered
no ``<Handle>`` children, React Flow had no port bounds to attach edges to and
dropped every edge touching one (``error008``).

This test asserts the corrected behaviour WITHOUT installing anything: opening
the example must still not download torch. What changes is that the canvas says
so, and draws the graph.

Run::

    CURIO_E2E_USE_EXISTING=1 pytest \
        utk_curio/backend/tests/test_frontend/test_streetvision_example_e2e.py -v
"""
from __future__ import annotations

import json
import os
import uuid
from typing import TYPE_CHECKING

import pytest

from .utils import (
    REPO_ROOT,
    dismiss_toasts,
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

EXAMPLE = "10-street-vision-cv-analysis.json"
PACKAGE_NODE_TYPES = {
    "curio.streetvision/street-view-fetcher",
    "curio.streetvision/hf-cv-inference",
    "curio.streetvision/cv-gallery",
}


def _example_spec() -> dict:
    path = os.path.join(REPO_ROOT, "docs", "examples", EXAMPLE)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture()
def street_vision_canvas(app_frontend: "FrontendPage", current_server, page):
    require_project_page()
    require_user_auth()
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Street Vision Reader",
        username=f"sv_{uuid.uuid4().hex[:10]}",
        project_name="Street-level computer vision",
        project_spec=_example_spec(),
    )
    require_owner_view(page)
    page.wait_for_selector(".react-flow__node", timeout=45000)
    dismiss_toasts(page)
    page.curio_session = session
    return page


def test_the_example_declares_the_package_its_nodes_need(street_vision_canvas):
    """The data half, asserted against the shipped file.

    An empty lockfile is what started the whole failure, and it is invisible in
    the UI - so it is worth pinning here beside the behaviour it caused.
    """
    spec = _example_spec()
    assert "curio.streetvision@1" in spec["dataflow"]["packages"], (
        "example 10 must declare the package its nodes reference, or nothing "
        "downstream can resolve them (#233)"
    )


def test_unresolved_nodes_say_what_is_missing(street_vision_canvas):
    page = street_vision_canvas

    # The example's three package nodes, by the ids in the shipped spec.
    node_ids = [
        node["id"]
        for node in _example_spec()["dataflow"]["nodes"]
        if node["type"] in PACKAGE_NODE_TYPES
    ]
    assert len(node_ids) == 3, "the example should carry three streetvision nodes"

    for node_id in node_ids:
        node = page.locator(f'.react-flow__node[data-id="{node_id}"]')
        node.wait_for(state="visible", timeout=45000)
        # `Loading node…` is the right message only while the registry might
        # still deliver. It never will here, and the card has to say so.
        node.locator('[data-testid="unresolved-node"]').wait_for(
            state="visible", timeout=45000
        )
        assert node.get_by_text("Missing node package").count() > 0
        assert node.get_by_text("Streetvision", exact=False).count() > 0

    assert page.get_by_text("Loading node…").count() == 0, (
        "a node is still on the indefinite placeholder (#233)"
    )


def test_every_edge_renders(street_vision_canvas):
    """The missing-connections half.

    The edges were in React Flow's state the whole time; they had nowhere to
    attach, because the placeholder rendered no handles. Counting rendered
    edges against the spec is the check that would have caught it.
    """
    page = street_vision_canvas
    expected = len(_example_spec()["dataflow"]["edges"])

    page.wait_for_function(
        "(n) => document.querySelectorAll('.react-flow__edge').length >= n",
        arg=expected,
        timeout=45000,
    )
    rendered = page.locator(".react-flow__edge").count()
    assert rendered >= expected, (
        f"only {rendered} of {expected} edges rendered - the nodes without "
        f"descriptors are probably not emitting handles again (#233)"
    )


def test_opening_the_example_installs_nothing(street_vision_canvas, current_server):
    """Opening a dataflow must not start a multi-gigabyte download.

    The lockfile now declares the package, and `useEnsureWorkflowDeps` installs
    declared packages automatically - so this is exactly the regression the
    `deferred` flag exists to prevent.
    """
    from .utils import api_json

    token = street_vision_canvas.curio_session["token"]
    installed = api_json(f"{current_server}/api/packages", token) or {}
    names = {p.get("dirName") for p in installed.get("packages", [])}
    assert "curio.streetvision@1" not in names, (
        "opening the example installed Street Vision - that is a ~3 GB torch "
        "download the user never asked for (#233)"
    )
