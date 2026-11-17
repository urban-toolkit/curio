"""Playwright E2E: a hosted guest's Run All of example 25 joins in all nine
Spatial Joins, in the browser.

A hosted guest's runs stay in its browser (``FlowProvider``'s
``runsOnServer``): its page sends each node to ``/processPythonCode``, and a
node's editor first checks that every input the run reads holds a value. A
Spatial Join keeps each of its two ports' inputs by handle
(``data.portInputs``), which that check did not read: on dev 0.17.332 a guest
of example 25 saw all nine joins refused with "input_0 (from Data Loading) has
no value yet. Run the node that feeds it.", and a guest of example 32 saw its
join refused the same way. An account's runs go to the server, which
``test_spatial_join_operations_e2e.py`` and
``test_server_run_spatial_joins_e2e.py`` cover.

The example is a dataflow of the shared guest account, as every shipped
example is (``test_guests_and_an_editor_on_one_example_e2e.py``). A browser
with no sign-in opens it: on a stack with sign-in that is a hosted guest, on
its own copy. Its Run All must end with every join done and printing what it
paired, the lines ``test_spatial_join_operations_e2e.py`` pins, its page having
sent each join to ``/processPythonCode`` and followed no run on the server.

On a stack without sign-in (CI's test-isolated job) the browser is the shared
guest, the one local user, which owns the example, and its Run All is a run on
the server: every join must pair there too.
"""

from __future__ import annotations

import json
from urllib.parse import urlparse

from .test_spatial_join_operations_e2e import CASES, EXAMPLE
from .utils import (
    allow_guest_login_env,
    api_json,
    auth_enabled_env,
    node_locator,
    read_node_output_text,
    run_all_and_wait,
    wait_for_node_done,
)

NAME = "Spatial Join operations"


def _example(backend: str, hosted: bool) -> str:
    """Example 25 as a dataflow of the shared guest account, which every
    shipped example is."""
    route = "signin/guest" if hosted else "signin/auto-guest"
    signed_in = api_json(f"{backend}/api/auth/{route}", "", method="POST", payload={})
    with open(EXAMPLE, encoding="utf-8") as fh:
        spec = json.load(fh)
    return api_json(
        f"{backend}/api/testing/stub-project", "", method="POST",
        payload={"username": signed_in["user"]["username"], "name": NAME, "spec": spec},
    )["id"]


class _Sent:
    """What a browser's page sent: the node of each ``/processPythonCode``, a
    run in the browser, and each run on the server it followed at
    ``/api/runs/<run>``."""

    def __init__(self, context):
        self.played: list[str] = []
        self.followed: list[str] = []
        context.on("request", self._sent)

    def _sent(self, request) -> None:
        path = urlparse(request.url).path
        if request.method == "POST" and path.endswith("/processPythonCode"):
            try:
                body = request.post_data_json or {}
            except Exception:  # noqa: BLE001 - a body that is no JSON names no node
                body = {}
            self.played.append(str(body.get("nodeId") or ""))
        elif "/api/runs/" in path:
            self.followed.append(f"{request.method} {path}")


def _opened(page, base: str, example: str) -> None:
    """Open *example*'s canvas and wait until it shows every join and its room
    names this tab the owner, with the canvas bound to the doc it joined: a
    hosted guest owns its copy, and the local guest the example."""
    page.goto(f"{base}/dataflow/{example}", timeout=120000)
    for join, _view, _printed in CASES.values():
        node_locator(page, join).wait_for(timeout=60000)
    try:
        page.locator('[data-curio-room-role="owner"]').wait_for(state="attached", timeout=30000)
        page.wait_for_function("() => !!window.__curio_awareness", timeout=30000)
    except Exception as exc:  # noqa: BLE001 - said in the test's words
        raise AssertionError("the room never named this tab its owner, with its doc bound") from exc


def test_a_hosted_guests_run_all_of_example_25_joins_in_every_spatial_join_in_the_browser(
    app_frontend, current_server, browser,
):
    """Example 25's nine joins, each pairing its inputs, after a guest's Run
    All: in the browser for a hosted guest, on the server for the local
    guest of a stack without sign-in."""
    hosted = auth_enabled_env()
    if hosted:
        assert allow_guest_login_env(), "this stack turns guest login off, so it has no hosted guest"
    base, backend = app_frontend.base_url, current_server
    example = _example(backend, hosted)
    context = browser.new_context(viewport={"width": 1280, "height": 768})
    try:
        sent = _Sent(context)
        page = context.new_page()
        _opened(page, base, example)

        run_all_and_wait(page, timeout_ms=600000)

        for case, (join, _view, printed) in CASES.items():
            wait_for_node_done(page, join, node_type="SPATIAL_JOIN", timeout_ms=240000)
            shown = read_node_output_text(page, join)
            # The join's account of what it paired, as its code printed it.
            assert printed in shown, f"{case}: {shown!r}"
            assert "No pairs:" not in shown, f"{case}: {shown!r}"

        joins = {join for join, _view, _printed in CASES.values()}
        if hosted:
            assert joins <= set(sent.played), (
                f"the guest's page sent no /processPythonCode for the joins {sorted(joins - set(sent.played))}"
            )
            assert not sent.followed, f"the guest's Run All followed a run on the server: {sent.followed[:5]}"
        else:
            # The local guest owns the example, so its Run All is a run on the server.
            assert sent.followed, "the local guest's Run All followed no run at /api/runs/<run>"
    finally:
        context.close()
