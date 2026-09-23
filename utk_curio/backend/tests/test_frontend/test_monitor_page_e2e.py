"""Playwright E2E: the monitor page renders, polls, pauses and logs a browser error.

One test, deliberately. It exercises the whole chain end to end -- the React
page, the real backend, the sandbox proxy, real SQL and the public error
ingest -- without running a node or loading a dataflow, so it stays cheap.

The browser-error step is the only coverage that path gets anywhere: the
window handler, the public POST, the ring buffer and the render are four
separate pieces and nothing else joins them up.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .utils import FrontendPage

# An IPv4 in the rendered aggregate panels would mean a sign-in source leaked.
IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")


def test_monitor_page_shows_stats_errors_and_polls(app_frontend: FrontendPage, page):
    base = app_frontend.base_url

    # 120s, matching test_feature_tour_video and test_walkthrough_videos. The
    # harness serves the frontend through webpack-dev-server, which opens its
    # port before it has finished the first compile, so the default 30s races
    # that build on a cold cache.
    page.goto(f"{base}/monitor", timeout=120000)
    page.wait_for_load_state("domcontentloaded")

    # 1. Every section renders.
    for heading in ("Deployment", "Hardware", "Execution",
                    "Accounts and content", "Storage", "Recent errors"):
        page.get_by_role("heading", name=heading).wait_for(timeout=30000)

    # 2. Real numbers arrived. The harness always has at least the shared guest
    #    account, so this is >= 1 without being a flaky exact figure.
    accounts = page.get_by_test_id("monitor-accounts")
    accounts.wait_for(timeout=15000)
    assert re.search(r"\d", accounts.inner_text())

    # 3. The hardware section is populated from the host, not left as dashes.
    hardware = page.get_by_test_id("monitor-hardware").inner_text()
    assert re.search(r"\d", hardware), hardware

    # 4. A real poll happens: the stamp moves on its own.
    updated = page.get_by_text(re.compile(r"^Last updated")).inner_text()
    page.wait_for_timeout(6500)
    assert page.get_by_text(re.compile(r"^Last updated")).inner_text() != updated

    # 5. Pausing stops it, and resuming starts it again.
    page.get_by_role("button", name="Pause").click()
    paused_at = page.get_by_text(re.compile(r"^Last updated")).inner_text()
    page.wait_for_timeout(6500)
    assert page.get_by_text(re.compile(r"^Last updated")).inner_text() == paused_at
    page.get_by_role("button", name="Resume").click()

    # 6. The diagnostics bundle is what a user actually hands over.
    page.get_by_role("button", name="Copy diagnostics").click()
    page.get_by_role("button", name="Copied").wait_for(timeout=10000)

    # 7. The aggregate panels name nobody. Scoped to those panels rather than
    #    the whole body: the error log is raw by design, so a body-wide
    #    assertion would now be wrong rather than strict.
    for panel in ("monitor-deployment", "monitor-hardware",
                  "monitor-execution", "monitor-accounts", "monitor-storage"):
        text = page.get_by_test_id(panel).inner_text()
        assert "@" not in text, f"{panel} rendered an email-shaped string"
        assert IPV4.search(text) is None, f"{panel} rendered an IP-shaped string"

    # 8. A browser error travels: window handler -> public POST -> ring buffer
    #    -> render. The marker makes it unambiguous which entry is ours.
    #
    # LAST on purpose, and nothing may click after it. This harness serves the
    # frontend through webpack-dev-server, whose client shows a full-page
    # overlay iframe on any window error and swallows every pointer event
    # behind it. The overlay is a dev-server feature that does not exist in a
    # built bundle, so working around it here beats weakening the test: the
    # assertion below reads the DOM rather than clicking, so the overlay
    # cannot affect it.
    marker = "curio-e2e-marker-9f3a1c"
    page.evaluate(
        """(marker) => {
            window.dispatchEvent(new ErrorEvent('error', {
                message: marker,
                error: new Error(marker),
            }));
        }""",
        marker,
    )
    page.get_by_text(marker).wait_for(timeout=30000)
