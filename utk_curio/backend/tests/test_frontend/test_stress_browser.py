"""Several users rendering Autark in real browsers at the same time.

The HTTP tiers in ``tests/stress`` cover the server side of a dataflow at 5,
10, 50 and 100 users, but an Autark node's map, plot and compute only ever run
in the browser, on WebGPU. This test covers that half the only way it can be
covered -- with real browser contexts -- which is also why it stops at a
handful of users: each one is a WebGPU context with its own GPU memory, and the
CI runner has one GPU.

Every user is a separate browser context (its own storage and session), so they
share nothing but the stack underneath them::

    CURIO_STRESS=1 pytest tests/test_frontend/test_stress_browser.py -s -v

    # more users, a different dataflow
    CURIO_STRESS=1 CURIO_STRESS_BROWSER_USERS=3 \
      CURIO_STRESS_BROWSER_WORKFLOW=docs/examples/dataflows/AutkMap.json \
      pytest tests/test_frontend/test_stress_browser.py -s

Playwright's sync API is single-threaded, so the users cannot literally click
at the same instant. The runs still overlap, which is what matters: every node
is started before any of them is waited on, so all the WebGPU work is in flight
together.
"""
from __future__ import annotations

import json
import os

import pytest

from .fixtures import VIEWPORT
from .utils import (
    node_execution_timeout_ms,
    play_node,
    read_node_error_text,
    node_locator,
    stub_login_and_enter_workflow,
    upload_workflow,
    wait_for_node_settled,
    FrontendPage,
)
from .workflow_spec import parse_workflow

pytestmark = pytest.mark.skipif(
    os.environ.get("CURIO_STRESS") != "1",
    reason="browser stress tier runs only with CURIO_STRESS=1",
)

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
)

# Interaction_Autark renders a map, a plot and a compute pass from one data
# load, so a single user exercises every browser-side Autark path.
DEFAULT_WORKFLOW = "docs/examples/dataflows/Interaction_Autark.json"
DEFAULT_USERS = 5


def _users() -> int:
    return int(os.environ.get("CURIO_STRESS_BROWSER_USERS", DEFAULT_USERS))


def _workflow_path() -> str:
    rel = os.environ.get("CURIO_STRESS_BROWSER_WORKFLOW", DEFAULT_WORKFLOW)
    return rel if os.path.isabs(rel) else os.path.join(REPO_ROOT, rel)


class TestBrowserStressTier:
    """One dataflow, N browsers, all rendering at once."""

    def test_concurrent_autark_users(
        self, browser, frontend_server, current_server, tmp_path,
    ):
        workflow_path = _workflow_path()
        spec = parse_workflow(workflow_path)
        playable = [n for n in spec.topo_sorted_nodes()
                    if n.category in ("code", "grammar")]
        assert playable, f"{workflow_path} has no playable nodes"

        contexts, pages = [], []
        try:
            for index in range(_users()):
                context = browser.new_context(viewport=VIEWPORT)
                page = context.new_page()
                page._curio_browser_log = []  # type: ignore[attr-defined]
                page.on("console", lambda msg, p=page: p._curio_browser_log.append(
                    {"kind": "console", "type": msg.type, "text": msg.text}))
                page.on("pageerror", lambda exc, p=page: p._curio_browser_log.append(
                    {"kind": "pageerror", "message": str(exc)}))

                username = f"stressbrowser{index}"
                stub_login_and_enter_workflow(
                    page,
                    frontend_url=frontend_server,
                    backend_url=current_server,
                    name=f"Browser Stress {index}",
                    username=username,
                    project_name=f"stub_{username}",
                )
                upload_workflow(
                    page, FrontendPage(frontend_server, page),
                    workflow_path, spec.nodes_count,
                )
                contexts.append(context)
                pages.append(page)

            # Start everything before waiting on anything: the point is to have
            # N users' GPU work in flight together, not one after another.
            for node in playable:
                for page in pages:
                    play_node(page, node.id)

            failures = []
            for index, page in enumerate(pages):
                for node in playable:
                    status = wait_for_node_settled(
                        page, node.id, node_type=node.type,
                        timeout_ms=node_execution_timeout_ms(node.type),
                    )
                    if status == "error":
                        failures.append({
                            "user": index,
                            "node_id": node.id,
                            "node_type": node.type,
                            "error": read_node_error_text(node_locator(page, node.id)),
                            "browser_log": page._curio_browser_log[-40:],
                        })

            if failures:
                # The browser log holds the only account of why an Autark node
                # went red: the behavior stores the reason in React state
                # without logging it, so the page listeners above are what
                # capture it.
                dump = tmp_path / "browser-stress-failures.json"
                dump.write_text(json.dumps(failures, indent=2, default=str))
                summary = "\n".join(
                    f"user {f['user']} node {f['node_id']} ({f['node_type']}): "
                    f"{(f['error'] or 'no message')[:400]}"
                    for f in failures
                )
                pytest.fail(
                    f"{len(failures)} node run(s) failed with "
                    f"{len(pages)} concurrent browser users "
                    f"(details: {dump})\n{summary}"
                )
        finally:
            for context in contexts:
                try:
                    context.close()
                except Exception:  # noqa: BLE001 - teardown must not mask a failure
                    pass
