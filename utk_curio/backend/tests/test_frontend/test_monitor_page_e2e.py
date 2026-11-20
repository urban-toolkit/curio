"""Playwright E2E: the monitor page renders its two tabs, polls, pauses and logs a
browser error, its Usage tab counts a node's run, and its LLM performance section
counts an agent's turn on Curio's own model.

The first test exercises the whole chain end to end -- the React page, the real
backend, the sandbox proxy, real SQL and the public error ingest -- without
running a node or loading a dataflow, so it stays cheap. It opens /monitor on
its Status tab, then the Usage tab by a click (/monitor/usage), and Status again.

The browser-error step is the only coverage that path gets anywhere: the
window handler, the public POST, the ring buffer and the render are four
separate pieces and nothing else joins them up.

The second makes the scripted provider this Curio's own endpoint
(``/api/testing/llm-deployment``), which the monitor counts and a key a user
set for their own is not, under a model name of the test's own, so no other
test's requests count on it; runs one scripted agent turn on it
(``utils/scripted_llm.py``); and reads its requests and their times back from
the route and from the page, opened on the Usage tab by its URL.

The third runs two Python nodes through the backend as Play does
(``/processPythonCode``), one that fails, and reads them in the Usage tab's
``node.python`` measure, on the route and on the page.

The monitor's measures are histories every backend process writes into one
file each, kept across restarts, so a test has every process write what it
holds (``/api/testing/monitor-flush``) before each read, and reads what it
added.
"""

from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .utils import api_json, captured_agent_calls, script_agent_replies, stub_db_user

if TYPE_CHECKING:
    from .utils import FrontendPage

# An IPv4 in the rendered aggregate panels would mean a sign-in source leaked.
IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
# An address, not any "@": the hardware panel names the CPU, and an Intel
# model reads "Intel(R) Xeon(R) Platinum 8370C CPU @ 2.80GHz".
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def test_monitor_page_shows_stats_errors_and_polls(app_frontend: FrontendPage, page):
    base = app_frontend.base_url

    # 120s, matching test_feature_tour_video and test_walkthrough_videos. The
    # harness serves the frontend through webpack-dev-server, which opens its
    # port before it has finished the first compile, so the default 30s races
    # that build on a cold cache.
    page.goto(f"{base}/monitor", timeout=120000)
    page.wait_for_load_state("domcontentloaded")

    # 1. Every section of the Status tab renders, the tab /monitor opens on.
    for heading in ("Deployment", "Hardware", "Execution", "Accounts and content", "Storage", "Recent errors"):
        page.get_by_role("heading", name=heading).wait_for(timeout=30000)
    expect(page.get_by_role("tab", name="Status", exact=True)).to_have_attribute("aria-selected", "true")

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
    for panel in ("monitor-deployment", "monitor-hardware", "monitor-execution",
                  "monitor-accounts", "monitor-storage"):
        text = page.get_by_test_id(panel).inner_text()
        assert EMAIL.search(text) is None, f"{panel} rendered an email-shaped string"
        assert IPV4.search(text) is None, f"{panel} rendered an IP-shaped string"

    # 8. The Usage tab, by a click: its path, its sections, the LLM performance
    #    among them, its numbers, and its panels name nobody either.
    page.get_by_role("tab", name="Usage", exact=True).click()
    page.wait_for_url(re.compile(r"/monitor/usage$"), timeout=30000)
    expect(page.get_by_role("tab", name="Usage", exact=True)).to_have_attribute("aria-selected", "true")
    for heading in ("Activity", "Sessions seen", "Average time", "By measure", "LLM performance"):
        page.get_by_role("heading", name=heading, exact=True).wait_for(timeout=30000)
    page.locator('[data-testid="monitor-usage-measures"] tr[data-measure="node.python"]').wait_for(timeout=30000)
    for panel in ("monitor-usage", "monitor-usage-measures", "monitor-llm-performance"):
        text = page.get_by_test_id(panel).inner_text()
        assert EMAIL.search(text) is None, f"{panel} rendered an email-shaped string"
        assert IPV4.search(text) is None, f"{panel} rendered an IP-shaped string"

    # Back to Status, by a click, where the errors are.
    page.get_by_role("tab", name="Status", exact=True).click()
    page.wait_for_url(re.compile(r"/monitor$"), timeout=30000)
    page.get_by_role("heading", name="Recent errors").wait_for(timeout=30000)

    # 9. A browser error travels: window handler -> public POST -> ring buffer
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


#: The agent the turn runs: one that attaches to the canvas, so the dataflow
#: needs no node.
RESEARCHER = "agent.curio.researcher@1"
#: The windows the route views the requests in.
WINDOWS = ("24h", "7d", "90d")
#: A duration as the page writes it (``formatMs``): "850 ms", "1.2 s".
SHOWN_DURATION = re.compile(r"\d+ ms|\d+\.\d s")


def _scripted_model(current_server: str, token: str, model: str):
    """The route's body and *model*'s stats in each window (None in a window
    with no request of it), once every backend process wrote what it holds of
    the history."""
    api_json(f"{current_server}/api/testing/monitor-flush", token, method="POST", payload={})
    body = api_json(f"{current_server}/api/monitor/llm", token)
    return body, {window: next((entry for entry in body["views"][window]["models"] if entry["model"] == model),
                               None)
                  for window in WINDOWS}


def _counts(stats: dict | None) -> tuple[int, int]:
    """A window's requests and failed requests, none in a window with no request."""
    return (stats["requests"], stats["failed"]) if stats else (0, 0)


def test_a_turn_on_curios_own_model_shows_in_llm_performance(app_frontend: FrontendPage, page,
                                                             current_server: str):
    # 1. The scripted provider is this Curio's own endpoint while the test
    #    runs, under a model name of this test's own, so a user with no LLM
    #    configuration of their own runs on it, and the monitor counts its
    #    requests and no other test's. Put back whatever happens, so no later
    #    test of the stack finds the stand-in.
    suffix = uuid.uuid4().hex[:8]
    model = f"scripted-{suffix}"
    session = stub_db_user(current_server, username=f"monitor_llm_{suffix}",
                           name="Monitor Performance", project_name="Monitor performance")
    token = session["token"]
    dataflow = session["project"]["id"]
    api_json(f"{current_server}/api/testing/llm-deployment", token, method="POST",
             payload={"scripted": True, "model": model})
    try:
        # The history is kept across restarts, so what it held before the
        # turn is read first.
        _, before = _scripted_model(current_server, token, model)
        base = f"{current_server}/api/agents/projects/{dataflow}"
        if RESEARCHER not in {row["dirName"] for row in api_json(base, token)["agents"]}:
            api_json(f"{base}/install", token, method="POST", payload={"coord": RESEARCHER})
        attachment = api_json(f"{base}/attachments", token, method="POST",
                              payload={"coord": RESEARCHER, "target": {"kind": "canvas"}})
        script_agent_replies(current_server, "The monitor times this turn.", dataflow=dataflow)
        run = api_json(f"{base}/attachments/{attachment['attachmentId']}/run", token, method="POST",
                       payload={"message": "How long did this take?"}, timeout=60.0)
        assert "The monitor times this turn." in run["reply"], run["reply"]

        # 2. The route counts each of the turn's calls once, on Curio's own
        #    model, the conversation's title among them, each with its time,
        #    and none failed.
        calls = [call for call in captured_agent_calls(current_server, dataflow=dataflow)
                 if call["model"] == model]
        assert calls, captured_agent_calls(current_server, dataflow=dataflow)
        body, after = _scripted_model(current_server, token, model)
        for window in WINDOWS:
            assert after[window] is not None, (window, body["views"][window]["models"])
            (requests, failed), (requests_before, failed_before) = _counts(after[window]), _counts(before[window])
            assert (requests - requests_before, failed - failed_before) == (len(calls), 0), (window, before, after)
            assert after[window]["averageMs"] is not None and after[window]["p95Ms"] is not None, after[window]
        assert model in {row["model"] for row in body["views"]["24h"]["rows"]}, body["views"]["24h"]["rows"]

        # 3. The page shows them on its Usage tab, opened by its URL: the
        #    model's row in the By model table, over the 7 days it shows
        #    first, and its line in the chart.
        week = after["7d"]
        page.goto(f"{app_frontend.base_url}/monitor/usage", timeout=120000)
        expect(page.get_by_role("tab", name="Usage", exact=True)).to_have_attribute("aria-selected", "true",
                                                                                    timeout=30000)
        page.get_by_role("heading", name="LLM performance").wait_for(timeout=30000)
        row = page.locator(f'[data-testid="monitor-llm-models"] tr[data-model="{model}"]')
        row.wait_for(timeout=30000)
        cells = row.locator("td")
        assert cells.nth(1).get_attribute("data-tooltip") == f"{week['requests']:,} requests", row.inner_text()
        average = cells.nth(3).inner_text().strip()
        assert SHOWN_DURATION.fullmatch(average), row.inner_text()
        assert cells.nth(3).get_attribute("data-tooltip") == f"{week['averageMs']:,} ms", row.inner_text()
        if week["averageMs"] < 1000:
            assert average == f"{week['averageMs']} ms", row.inner_text()
        section = page.get_by_test_id("monitor-llm-performance")
        section.locator('[role="img"] svg').first.wait_for(timeout=30000)
        section.locator("svg text", has_text=model).first.wait_for(timeout=30000)
    finally:
        api_json(f"{current_server}/api/testing/llm-deployment", token, method="DELETE")


def _python_runs(current_server: str, token: str) -> dict:
    """The Usage tab's Python node runs in each window, once every backend
    process wrote what it holds of the history."""
    api_json(f"{current_server}/api/testing/monitor-flush", token, method="POST", payload={})
    body = api_json(f"{current_server}/api/monitor/usage", token)
    return {window: next(each for each in body["views"][window]["measures"] if each["key"] == "node.python")
            for window in WINDOWS}


def test_a_node_run_shows_in_the_usage_tab(app_frontend: FrontendPage, page, current_server: str):
    # 1. Two Python nodes run through the backend as Play runs them, one of
    #    which fails, on a dataflow of the test's own. The history is kept
    #    across restarts, so what it held before is read first.
    suffix = uuid.uuid4().hex[:8]
    session = stub_db_user(current_server, username=f"monitor_usage_{suffix}",
                           name="Monitor Usage", project_name="Monitor usage")
    token = session["token"]
    dataflow = session["project"]["id"]
    before = _python_runs(current_server, token)
    paths = []
    # Bodies indented, as the canvas sends a node's code.
    for code in ("    return 21 * 2\n", "    raise ValueError('the monitor counts this run as failed')\n"):
        reply = api_json(
            f"{current_server}/processPythonCode", token, method="POST",
            payload={
                "code": code, "nodeType": "curio.builtin/python-computation", "dataflowId": dataflow,
                "input": {"path": "", "dataType": ""}, "saveOutputDataset": False,
            },
            timeout=120, dataflow=dataflow,
        )
        paths.append((reply.get("output") or {}).get("path"))
    assert bool(paths[0]) and not paths[1], paths

    # 2. The route counts both, the second as failed, each with its time, in
    #    every window.
    after = _python_runs(current_server, token)
    for window in WINDOWS:
        added = (after[window]["count"] - before[window]["count"], after[window]["failed"] - before[window]["failed"])
        assert added == (2, 1), (window, before[window], after[window])
        assert after[window]["averageMs"] is not None and after[window]["p95Ms"] is not None, after[window]

    # 3. The page shows them on its Usage tab, opened by its URL: the Python
    #    row of the By measure table, over the 7 days it shows first.
    page.goto(f"{app_frontend.base_url}/monitor/usage", timeout=120000)
    expect(page.get_by_role("tab", name="Usage", exact=True)).to_have_attribute("aria-selected", "true",
                                                                                timeout=30000)
    row = page.locator('[data-testid="monitor-usage-measures"] tr[data-measure="node.python"]')
    row.wait_for(timeout=30000)
    cells = row.locator("td")
    week = after["7d"]
    expect(cells.nth(1)).to_have_attribute("data-tooltip", f"{week['count']:,} runs", timeout=30000)
    expect(cells.nth(2)).to_have_attribute(
        "data-tooltip", f"{week['failed']:,} of {week['count']:,} runs failed", timeout=30000)
    assert SHOWN_DURATION.fullmatch(cells.nth(3).inner_text().strip()), row.inner_text()
    assert cells.nth(3).get_attribute("data-tooltip") == f"{week['averageMs']:,} ms", row.inner_text()
