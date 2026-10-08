"""Playwright E2E: opening a saved dataflow fetches each saved output once.

A load restores the dataflow's saved outputs and hands each one to the nodes
below its producer. A Data Pool handed one reads its artifact through ``/get``
(its rows) and ``/get-preview`` (the table it shows), once per hand-over. So a
load that handed the producer's output to the pool twice fetched the artifact
twice, on every reopen of the canvas and every opening of its dashboard.

The dataflow, and the steps that run, pin and save it, are the dashboard page
tests' (``test_dashboard_page_e2e.py``): a producer, a Data Pool, a Vega chart.

Run::

    CURIO_E2E_USE_EXISTING=1 pytest \\
        utk_curio/backend/tests/test_frontend/test_restored_outputs_fetched_once_e2e.py -v
"""
from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect

from .test_dashboard_page_e2e import (
    POOL,
    PRODUCER,
    _chart_drew,
    _open_dashboard,
    _pinned_and_saved,
    _project,
)
from .utils import node_locator, require_project_page, require_user_auth

if TYPE_CHECKING:
    from .utils import FrontendPage

#: How long a page gets to fetch the artifact again once its chart has drawn. A
#: second hand-over lands a tick after the first, long before the chart draws.
QUIET_MS = 1500

#: The endpoints that read an artifact by name.
ARTIFACT_ENDPOINTS = ("get", "get-preview")


class _ArtifactRequests:
    """The requests the page sends for one artifact: endpoint and Accept header."""

    def __init__(self, page, artifact: str) -> None:
        self.artifact = artifact
        self.seen: list[tuple[str, str]] = []
        page.on("request", self._record)

    def _record(self, request) -> None:
        url = urlparse(request.url)
        endpoint = url.path.rsplit("/", 1)[-1]
        if endpoint not in ARTIFACT_ENDPOINTS:
            return
        if parse_qs(url.query).get("fileName") != [self.artifact]:
            return
        self.seen.append((endpoint, request.headers.get("accept", "")))

    def take(self) -> list[tuple[str, str]]:
        """The requests recorded since the last call."""
        seen, self.seen = self.seen, []
        return seen


def _by_endpoint(seen: list[tuple[str, str]]) -> dict[str, int]:
    return {endpoint: sum(1 for e, _ in seen if e == endpoint) for endpoint in ARTIFACT_ENDPOINTS}


def test_a_reopen_and_its_dashboard_fetch_each_saved_output_once(
    app_frontend: "FrontendPage", current_server, page,
):
    require_project_page()
    require_user_auth()
    session = _pinned_and_saved(page, app_frontend, current_server, prefix="fetch_once")
    base = app_frontend.base_url
    project_id = session["project"]["id"]

    project = _project(current_server, session["token"], project_id)
    saved = {o["node_id"]: o["filename"] for o in project["outputs"]}
    assert list(saved) == [PRODUCER], (
        f"the save recorded {saved!r}; the producer's output, which the pool "
        f"reads, should be the one saved output"
    )
    requests = _ArtifactRequests(page, saved[PRODUCER])

    # The canvas, opened again by a full load of its address.
    page.goto(f"{base}/projects")
    page.wait_for_load_state("domcontentloaded")
    requests.take()
    page.goto(f"{base}/dataflow/{project_id}")
    page.wait_for_selector(".react-flow__node", timeout=45000)
    _chart_drew(page)
    pool_rows = node_locator(page, POOL).locator("table").first.locator("tbody tr")
    expect(pool_rows).to_have_count(3, timeout=45000)
    page.wait_for_timeout(QUIET_MS)
    reopened = requests.take()

    # Its dashboard, opened the same way.
    _open_dashboard(page, base, project_id)
    _chart_drew(page)
    page.wait_for_timeout(QUIET_MS)
    on_dashboard = requests.take()

    fetched = {"reopen": _by_endpoint(reopened), "dashboard": _by_endpoint(on_dashboard)}
    assert all(f["get"] == 1 and f["get-preview"] <= 1 for f in fetched.values()), (
        f"each load should fetch the producer's saved output ({saved[PRODUCER]}) once, "
        f"by endpoint: {fetched!r}; the Accept header of each request: "
        f"reopen {reopened!r}, dashboard {on_dashboard!r}"
    )
