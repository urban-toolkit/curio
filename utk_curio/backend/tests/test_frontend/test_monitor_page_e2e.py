"""Playwright E2E: the monitor page renders, polls, pauses and logs a browser error,
and its LLM tokens section counts an agent's turn.

The first test exercises the whole chain end to end -- the React page, the real
backend, the sandbox proxy, real SQL and the public error ingest -- without
running a node or loading a dataflow, so it stays cheap.

The browser-error step is the only coverage that path gets anywhere: the
window handler, the public POST, the ring buffer and the render are four
separate pieces and nothing else joins them up.

The second runs one scripted agent turn (``utils/scripted_llm.py``) on a model
of its own, so its calls are told apart from every other test's, and reads its
tokens back from the route and from the page.
"""

from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING

from .utils import api_json, captured_agent_calls, script_agent_replies, stub_db_user, use_scripted_llm

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

    # 1. Every section renders.
    for heading in ("Deployment", "Hardware", "Execution", "LLM tokens",
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
    for panel in ("monitor-deployment", "monitor-hardware", "monitor-execution",
                  "monitor-llm-tokens", "monitor-accounts", "monitor-storage"):
        text = page.get_by_test_id(panel).inner_text()
        assert EMAIL.search(text) is None, f"{panel} rendered an email-shaped string"
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


#: The agent the turn runs: one that attaches to the canvas, so the dataflow
#: needs no node.
RESEARCHER = "agent.curio.researcher@1"


def test_an_agent_turn_shows_its_models_tokens_in_the_llm_section(app_frontend: FrontendPage, page,
                                                                   current_server: str):
    from utk_curio.backend.app.agents.infrastructure.testing_provider import DEFAULT_USAGE

    # 1. One turn, on a scripted model no other test uses, on the user's own key.
    model = f"monitor-e2e-{uuid.uuid4().hex[:8]}"
    session = stub_db_user(current_server, username=f"monitor_llm_{model[-8:]}", name="Monitor Tokens",
                           project_name="Monitor tokens")
    token = session["token"]
    use_scripted_llm(current_server, token, model=model, label="Monitor tokens")
    base = f"{current_server}/api/agents/projects/{session['project']['id']}"
    if RESEARCHER not in {row["dirName"] for row in api_json(base, token)["agents"]}:
        api_json(f"{base}/install", token, method="POST", payload={"coord": RESEARCHER})
    attachment = api_json(f"{base}/attachments", token, method="POST",
                          payload={"coord": RESEARCHER, "target": {"kind": "canvas"}})
    script_agent_replies(current_server, "The monitor counts this turn.")
    run = api_json(f"{base}/attachments/{attachment['attachmentId']}/run", token, method="POST",
                   payload={"message": "How many tokens did this take?"}, timeout=60.0)
    assert "The monitor counts this turn." in run["reply"], run["reply"]

    # 2. The route counts each of its calls once, the conversation's title
    #    among them, at the usage the scripted provider reports for each.
    calls = [call for call in captured_agent_calls(current_server) if call["model"] == model]
    assert calls, captured_agent_calls(current_server)
    counted = {"inputTokens": DEFAULT_USAGE["in"] * len(calls),
               "outputTokens": DEFAULT_USAGE["out"] * len(calls), "requests": len(calls)}
    body = api_json(f"{current_server}/api/monitor/llm", token)
    entry = next((entry for entry in body["models"] if entry["model"] == model), None)
    assert entry is not None, body["models"]
    assert (entry["curio"], entry["last24h"], entry["last7d"], entry["kept"]) == (
        False, counted, counted, counted), entry
    assert model in {row["model"] for row in body["hourly"]}, body["hourly"]

    # 3. The page shows them: the model's row, on its own key, and its line in both charts.
    page.goto(f"{app_frontend.base_url}/monitor", timeout=120000)
    page.get_by_role("heading", name="LLM tokens").wait_for(timeout=30000)
    row = page.locator(f'[data-testid="monitor-llm-models"] tr[data-model="{model}"]')
    row.wait_for(timeout=30000)
    text = row.inner_text()
    tokens = f"{counted['inputTokens']} in · {counted['outputTokens']} out"
    assert "Own key" in text and text.count(tokens) == 3, text
    section = page.get_by_test_id("monitor-llm-tokens")
    section.locator('[role="img"] svg').nth(1).wait_for(timeout=30000)
    legend = section.locator("svg text", has_text=f"{model} (own key)")
    legend.nth(1).wait_for(timeout=30000)
