"""Playwright: a loader's candidates in the Dataflow Builder's chat, and the
pick that builds it.

1. **The plan.** The scripted Dataflow Builder plans one Data Loading node,
   which lands with its Node Builder and its own Dataset Finder.
2. **Build & validate plan.** The loader's builder declines in one line: no
   source names the data. So the loader's Dataset Finder is asked, and its
   candidates, one dataset of the dataflow's Data Catalog, come to the chat
   that asked: the Builder's, as the card the Finder's own chat holds. The
   build pauses on the loader. The rail's entry of the Finder and the Finder's
   badge on the loader show the dot of an agent that waits for you.
3. **Use this source** on the card in the Builder's chat records the pick on
   the Finder. The card reads Recorded, with the pick and where it comes
   from, in both chats; the turn under it says what comes of the pick, which
   nothing else in the chat says, and the dots go. The Builder goes on with
   Build & validate by itself, which builds the loader from that dataset.

Driven by the scripted provider, so no model is called. Nothing is drawn.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_handoff_in_the_builders_chat_e2e.py -v
"""
from __future__ import annotations

import json
import re
import time
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .utils import (
    api_json,
    dismiss_toasts,
    open_plan_more,
    require_owner_view,
    require_project_page,
    require_user_auth,
    save_workflow_test_screenshot,
    script_agent_replies,
    stub_db_login,
    use_scripted_llm,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

DFB_COORD = "agent.curio.dataflow-builder@1"
DFB_NAME = "Dataflow Builder"
LOADER_TITLE = "Load pedestrians"
SCREENSHOT_STEM = "handoff-in-the-builders-chat"
CHAT_PANEL_SELECTOR = '[role="dialog"][aria-label^="Chat with"]'

#: A dataset Curio ships, which the test adds to the dataflow's Data Catalog:
#: the Dataset Finder's candidate, and what the loader reads once it is picked.
DATASET = "data.curio.example-pedestrians-by-hour"

PLAN = {
    "goal": "count pedestrians by hour",
    "nodes": [{
        "ref": "load", "nodeType": "curio.builtin/data-loading", "title": LOADER_TITLE,
        "intent": "load the pedestrians counted per hour on four streets",
    }],
    "edges": [],
}
PLAN_REPLY = "One loader for the counts.\n```curio.v1\n" + json.dumps({"dataflowPlan": PLAN}) + "\n```"
TITLE = "Pedestrians by hour"
#: The loader's builder, asked before any source is picked: a one-line answer
#: that names what is missing, which ends its attempts and asks the Finder.
DECLINE = "No source names the pedestrian counts yet: a dataset of them must be picked first"
#: The Finder's candidates: the dataset the dataflow's Data Catalog holds.
CANDIDATES = json.dumps({"datasetCandidates": {"lanes": {
    "external": [],
    "catalog": [{
        "name": "Example table: pedestrians per hour", "sourceType": "catalog", "datasetId": DATASET,
        "fit": {"score": 95, "rationale": "the hourly counts the goal asks for"},
    }],
}}})
#: The loader, once its source is picked.
LOADER = f'import pandas as pd\nreturn pd.read_csv(curio_data_path("{DATASET}"))'
#: What the card says once the pick is recorded, in both chats: the pick and
#: where it comes from, and no more.
RECORDED = "Recorded: Example table: pedestrians per hour (Data Catalog)."
#: What comes of the pick, as the server says it: the Source recorded turn
#: under the card ends with it, in both chats, and nothing else says it.
NEXT = "The Dataflow Builder goes on with its plan and builds the loader from this source."

#: How long a Build & validate pass may take on a loaded runner.
BUILD_S = 240.0


def _spec() -> dict:
    """An empty dataflow."""
    return {"dataflow": {
        "name": "Pedestrians", "task": "", "timestamp": 1789193389280, "provenance_id": "Pedestrians",
        "nodes": [], "edges": [],
    }}


def _wait_until(predicate, *, what: str, timeout: float, step: float = 1.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(step)
    raise AssertionError(f"{what} did not happen within {timeout:.0f} s (last: {last!r})")


def _cards(backend: str, token: str, project_id: str) -> dict[str, dict]:
    """The dataflow's agents as the canvas lists them, by attachment id."""
    listing = api_json(f"{backend}/api/agents/projects/{project_id}/attachments", token)["attachments"]
    return {card["attachmentId"]: card for card in listing}


def _loader_id(backend: str, token: str, project_id: str) -> str:
    nodes = api_json(f"{backend}/api/projects/{project_id}", token)["spec"]["dataflow"]["nodes"]
    found = [node["id"] for node in nodes if node.get("title") == LOADER_TITLE]
    assert len(found) == 1, f"{len(found)} nodes are titled {LOADER_TITLE!r}"
    return found[0]


def _loader_code(backend: str, token: str, project_id: str, loader: str) -> str:
    nodes = api_json(f"{backend}/api/projects/{project_id}", token)["spec"]["dataflow"]["nodes"]
    return next((node.get("content") or "") for node in nodes if node["id"] == loader)


def test_the_builders_chat_holds_the_loaders_candidates_and_its_pick_builds_the_loader(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    login = stub_db_login(
        page, frontend_url=app_frontend.base_url, backend_url=current_server,
        username="handoff_in_the_builders_chat", name="Handoff Owner", project_name="Pedestrians", project_spec=_spec(),
    )
    token, project_id = login["token"], login["project"]["id"]
    use_scripted_llm(current_server, token)
    api_json(f"{current_server}/api/dataflows/{project_id}/datasets/install", token, method="POST",
             payload={"datasetId": DATASET})
    agents = f"{current_server}/api/agents/projects/{project_id}"
    api_json(f"{agents}/install", token, method="POST", payload={"coord": DFB_COORD})
    builder = api_json(f"{agents}/attachments", token, method="POST",
                       payload={"coord": DFB_COORD, "target": {"kind": "canvas"}})["attachmentId"]
    # Every call in order: the plan, the conversation's title, the loader's
    # builder, the Finder, and the loader's builder again once the source is
    # picked.
    script_agent_replies(current_server, PLAN_REPLY, TITLE, DECLINE, CANDIDATES, LOADER, dataflow=project_id)

    page.goto(f"{app_frontend.base_url}/dataflow/{project_id}", timeout=120000)
    page.wait_for_url(f"**/dataflow/{project_id}", timeout=20000)
    require_owner_view(page)
    opener = page.get_by_role("button", name=re.compile(rf"^Open chat with {re.escape(DFB_NAME)}")).first
    expect(opener).to_be_visible(timeout=45000)
    opener.click()
    panel = page.get_by_role("dialog", name=re.compile(rf"^Chat with {re.escape(DFB_NAME)}"))
    expect(panel).to_be_visible(timeout=20000)
    panel.get_by_role("textbox", name=re.compile(r"^Message ")).fill("Count the pedestrians by hour.")
    panel.get_by_role("button", name="Send", exact=True).click()
    expect(panel.get_by_role("group", name=re.compile(r"^Change: Plan")).first).to_be_visible(timeout=90000)
    # The title is the turn's last call: the build's calls come after it.
    expect(panel).to_have_attribute("aria-label", re.compile(re.escape(TITLE)), timeout=30000)
    loader = _loader_id(current_server, token, project_id)

    # Build & validate plan: the loader waits for its source, and the build
    # pauses on it.
    open_plan_more(panel)
    panel.get_by_role("button", name="Build & validate plan", exact=True).click()
    card = panel.get_by_role("group", name=f"Sources for {LOADER_TITLE}")
    expect(card).to_be_visible(timeout=BUILD_S * 1000)
    # The line over the card names the loader and counts its candidates.
    expect(panel.get_by_text(
        f"{LOADER_TITLE} needs a source. Its Dataset Finder found 1 candidate: pick one with Use this source.",
        exact=True,
    )).to_have_count(1)
    expect(panel.get_by_role("button", name="Resume", exact=True)).to_be_visible(timeout=60000)
    expect(card.get_by_role("button", name="Use this source", exact=True)).to_be_disabled()
    rail = panel.get_by_role("navigation", name="Agents on this dataflow")
    expect(rail.get_by_role("button", name=f"Dataset Finder on {LOADER_TITLE}, waits for you")).to_be_visible(
        timeout=30000)
    # The loader's Finder is the dataflow's one Dataset Finder: its badge is on
    # the loader.
    badge = page.get_by_role("button", name="Open chat with Dataset Finder, waits for you", exact=True)
    expect(badge).to_have_count(1, timeout=30000)
    cards = _cards(current_server, token, project_id)
    assert cards[builder]["waitsForYou"] == [loader], cards[builder]
    dismiss_toasts(page)
    # The chat sat at its newest turn, so it follows the candidates turn down,
    # read again as the build paused: the card's Use this source is in view,
    # with no pill to jump to the latest, as the frame shows it.
    expect(card.get_by_role("button", name="Use this source", exact=True)).to_be_in_viewport(timeout=10000)
    expect(panel.get_by_role("button", name=re.compile(r"^Jump to "))).to_have_count(0)
    save_workflow_test_screenshot(page, SCREENSHOT_STEM, test_name="card", clip_selector=CHAT_PANEL_SELECTOR)

    # The pick, on the card in the Builder's chat.
    card.get_by_role("checkbox").first.check()
    with page.expect_response(
        lambda r: r.request.method == "POST" and r.url.endswith("/dataset-selection"), timeout=60000,
    ) as picked:
        card.get_by_role("button", name="Use this source", exact=True).click()
    assert picked.value.status == 200, f"the pick was refused: HTTP {picked.value.status}"
    delegated = (picked.value.json() or {}).get("delegated") or {}
    assert (delegated.get("status"), delegated.get("continueWith")) == ("plan-waiting", "build"), delegated

    # The Builder goes on by itself, and builds the loader from the dataset.
    _wait_until(
        lambda: (lambda s: s if (s.get("nodeStates") or {}).get("load") == "approved" else None)(
            _cards(current_server, token, project_id)[builder].get("builderSession") or {}),
        what="the loader's build from the picked dataset", timeout=BUILD_S, step=2.0,
    )
    code = _loader_code(current_server, token, project_id, loader)
    assert f'curio_data_path("{DATASET}")' in code, code
    expect(card.get_by_role("status")).to_have_text(RECORDED, timeout=30000)
    expect(card.get_by_role("button", name="Use this source", exact=True)).to_have_count(0)
    expect(rail.get_by_role("button", name=f"Dataset Finder on {LOADER_TITLE}", exact=True)).to_be_visible(
        timeout=30000)
    expect(badge).to_have_count(0, timeout=30000)
    expect(panel.get_by_text(f"Source recorded for {LOADER_TITLE}", exact=False)).to_be_visible(timeout=30000)
    # The pick is said once: what comes of it is the turn's alone.
    expect(panel.get_by_text(NEXT, exact=False)).to_have_count(1, timeout=30000)
    # The server approves the loader before the tab's build ends: the frame
    # waits until the plan line has no Stop, so no build clock ticks in it.
    expect(panel.get_by_role("button", name=re.compile(r"^(Stop|Stopping…)$"))).to_have_count(0, timeout=60000)
    # The build's own turn reaches the chat when the tab reads it again as the
    # build ends, so the frame waits for it too. It names the loader by its
    # title, whole, as the canvas does.
    solved = re.compile(rf"Solved '{re.escape(LOADER_TITLE)}': PASS after \d+ rounds?")
    expect(panel.get_by_text(solved).last).to_be_visible(timeout=60000)
    # The plan went on and was built: the line says no more that it paused.
    expect(panel.get_by_text(re.compile(r"^Paused:"))).to_have_count(0)
    dismiss_toasts(page)
    save_workflow_test_screenshot(page, SCREENSHOT_STEM, test_name="recorded", clip_selector=CHAT_PANEL_SELECTOR)

    # The card itself, in its Recorded state in the Builder's chat.
    card.scroll_into_view_if_needed()
    expect(card).to_be_in_viewport()
    page.mouse.move(0, 0)
    save_workflow_test_screenshot(
        page, SCREENSHOT_STEM, test_name="card-recorded", clip_selector=CHAT_PANEL_SELECTOR, sweep_toasts=True,
    )

    # The Finder's own chat holds the same card, recorded the same way, and
    # has no Solve this node.
    rail.get_by_role("button", name=f"Dataset Finder on {LOADER_TITLE}", exact=True).click()
    finder_panel = page.get_by_role("dialog", name=re.compile(r"^Chat with Dataset Finder"))
    expect(finder_panel).to_be_visible(timeout=20000)
    own = finder_panel.get_by_role("group", name=f"Sources for {LOADER_TITLE}")
    expect(own.get_by_role("status")).to_have_text(RECORDED, timeout=30000)
    expect(finder_panel.get_by_role("group", name="Solve this node")).to_have_count(0)
    # Its own turns count the candidates and name the loader, and the pick is
    # said once here too.
    expect(finder_panel.get_by_text(
        f"I found 1 candidate for {LOADER_TITLE}. Pick one with Use this source.", exact=True,
    )).to_have_count(1)
    expect(finder_panel.get_by_text(f"Source recorded for {LOADER_TITLE}:", exact=False)).to_have_count(1)
    expect(finder_panel.get_by_text(NEXT, exact=False)).to_have_count(1, timeout=30000)
    own.scroll_into_view_if_needed()
    expect(own).to_be_in_viewport()
    page.mouse.move(0, 0)
    save_workflow_test_screenshot(
        page, SCREENSHOT_STEM, test_name="finder-chat", clip_selector=CHAT_PANEL_SELECTOR, sweep_toasts=True,
    )
