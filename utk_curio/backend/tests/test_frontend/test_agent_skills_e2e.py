"""Playwright E2E: a skill added to an agent in its details reaches the agent's chat.

The Agent Catalog page lists skills beside its agents, from its rail's Skills
section. A skill added to the Dataset Finder in its details is saved for the
account, so the Dataset Finder's next chat run lists it in its catalog; ``/`` in
that chat offers it, ``/<name>`` hands it to the run with the message, and the
reply names the skills its run used, in a line under it. The run's system turn
is read back from the scripted provider, since the page cannot show it.

Frames for the owner: the Skills rail's grid and drawer, ``map-edits``' details,
the agent's Skills section after the add, the chat's ``/`` list, and the
reply's line of skills.

Run::

    pytest utk_curio/backend/tests/test_frontend/test_agent_skills_e2e.py -v
"""
from __future__ import annotations

import re

from playwright.sync_api import expect

from utk_curio.backend.app.agents.domain import builtin

from .test_agent_chat_e2e import (
    CHAT_PANEL_SELECTOR,
    VISIBLE_PROSE,
    _goto_when_served,
    _open_chat,
    _open_dataflow_with_agent,
)
from .utils import (
    api_json,
    captured_system_prompt,
    dismiss_toasts,
    install_session_cookie,
    require_project_page,
    require_user_auth,
    save_workflow_test_screenshot,
    stub_db_user,
    use_scripted_llm,
)

STEM = "agent-skills"
FINDER = "agent.curio.dataset-finder@1"
#: The skill the test adds to the Dataset Finder, which its manifest leaves out.
ADDED = "node-functions"
#: The skill whose details the test frames: it serves one base node kind.
DETAILED = "map-edits"
MODAL = '[data-curio-modal-shell="true"]'
BROWSE_DRAWER = '[data-curio-browse-drawer="true"]'


def _rail_row(page, section: str, value: str):
    return page.locator(f'[data-curio-rail-section="{section}"][data-curio-rail-value="{value}"]')


def _the_catalog_page_lists_the_skills(page, frontend: str) -> None:
    """The rail's Skills section lists every skill Curio ships in the grid,
    and the drawer opens on the first by name."""
    _goto_when_served(page, f"{frontend}/catalog/agents")
    expect(page.get_by_role("heading", name="Agent Catalog", level=1)).to_be_visible(timeout=30000)
    all_skills = _rail_row(page, "skills", "all-skills")
    expect(all_skills).to_be_visible(timeout=30000)
    expect(all_skills).to_contain_text("All skills")
    all_skills.click()
    cards = page.locator("article[data-skill-name]")
    expect(cards).to_have_count(16, timeout=20000)
    expect(page.locator("article[data-agent-coord]")).to_have_count(0)
    names = cards.evaluate_all("els => els.map(e => e.getAttribute('data-skill-name'))")
    assert names == sorted(names), f"the skills are not listed by name: {names}"
    drawer = page.locator(BROWSE_DRAWER)
    expect(drawer.get_by_role("heading", name=names[0], exact=True)).to_be_visible(timeout=15000)
    expect(drawer.get_by_text("Skill details", exact=True)).to_be_visible()
    page.mouse.move(0, 0)
    save_workflow_test_screenshot(page, STEM, test_name="skills-rail", fit_reactflow=False)


def _a_skills_details_open_in_a_modal(page) -> None:
    """``map-edits``' details: it serves the base package's one Map Editor,
    so no package or template added later moves this frame."""
    card = page.locator(f'article[data-skill-name="{DETAILED}"]')
    card.scroll_into_view_if_needed()
    card.get_by_role("button", name="View details").click()
    dialog = page.get_by_role("dialog", name="Skill details")
    expect(dialog).to_be_visible(timeout=15000)
    expect(dialog.get_by_role("heading", level=3)).to_have_text(
        ["Description", "Serves", "Used by", "Skill info", "Text", "Files"], timeout=15000,
    )
    # The text arrives after the window opens, collapsed.
    expect(dialog.locator("summary")).to_have_text("What an agent reads · SKILL.md", timeout=15000)
    assert dialog.locator("details").first.get_attribute("open") is None
    serves = dialog.locator("section").filter(has=page.get_by_role("heading", name="Serves", exact=True))
    expect(serves.get_by_role("listitem")).to_have_text(["Map Editor"])
    save_workflow_test_screenshot(page, STEM, test_name="skill-details", fit_reactflow=False, clip_selector=MODAL)
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0, timeout=10000)


def _the_finder_is_given_the_skill(page, backend: str, token: str) -> None:
    """Add skill in the Dataset Finder's details, saved for this account."""
    page.get_by_role("complementary", name="Filter agents").get_by_role(
        "button", name=re.compile(r"^All agents"),
    ).click()
    expect(page.locator("article[data-agent-coord]").first).to_be_visible(timeout=15000)
    expect(page.locator("article[data-skill-name]")).to_have_count(0)
    card = page.locator(f'article[data-agent-coord="{FINDER}"]')
    card.get_by_role("button", name="View details").click()
    dialog = page.get_by_role("dialog", name="Agent details")
    expect(dialog).to_be_visible(timeout=15000)
    skills = dialog.locator('[data-curio-agent-skills="true"]')
    expect(skills.locator('[data-curio-skill-row="catalogs"]')).to_contain_text("Always for Find datasets",
                                                                               timeout=15000)
    # The core skills and the mode's own show no Remove.
    expect(skills.get_by_role("button", name=re.compile(r"^Remove "))).to_have_count(0)
    skills.get_by_role("button", name="Add skill").click()
    picker = skills.get_by_role("list", name="Skills to add to Dataset Finder")
    with page.expect_response(
        lambda r: r.url.endswith("/skills") and "/definitions/" in r.url and r.request.method == "POST",
        timeout=20000,
    ) as answered:
        picker.get_by_role("button", name=re.compile(rf"^{re.escape(ADDED)}")).click()
    assert answered.value.ok, answered.value.text()[:300]
    added = skills.locator(f'[data-curio-skill-row="{ADDED}"]')
    expect(added).to_contain_text("Added by you", timeout=15000)
    expect(added.get_by_role("button", name=f"Remove {ADDED} from Dataset Finder")).to_be_visible()
    expect(skills.get_by_role("button", name="Restore")).to_be_visible()
    rows = api_json(f"{backend}/api/agents/definitions/{FINDER}/skills", token)
    assert [row["name"] for row in rows["skills"] if row["added"]] == [ADDED], rows
    skills.scroll_into_view_if_needed()
    page.mouse.move(0, 0)
    save_workflow_test_screenshot(page, STEM, test_name="agent-skills-added", fit_reactflow=False,
                                  clip_selector=MODAL)
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0, timeout=10000)


def test_a_skill_added_to_an_agent_reaches_its_chat(page, frontend_server, current_server):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    login = stub_db_user(current_server, username="agentskills", name="Agent Skills User")
    install_session_cookie(page, frontend_server, login["token"])
    use_scripted_llm(current_server, login["token"])
    session = {
        "page": page, "frontend": frontend_server, "backend": current_server,
        "token": login["token"], "username": "agentskills",
    }

    _the_catalog_page_lists_the_skills(page, frontend_server)
    _a_skills_details_open_in_a_modal(page)
    _the_finder_is_given_the_skill(page, current_server, login["token"])

    # The Dataset Finder's chat, on a dataflow of its own.
    spec = builtin.get_builtin_manifest(FINDER)
    _open_dataflow_with_agent(session, spec, project_name="Skills reach the chat", replies=(VISIBLE_PROSE,))
    panel = _open_chat(page, spec)
    box = panel.get_by_role("textbox", name="Message this agent")

    # `/` lists the skills its next run lists: its own, and the one added.
    box.fill("/")
    menu = panel.get_by_role("listbox", name="Skills")
    expect(menu.get_by_role("option")).to_have_count(2, timeout=15000)
    expect(menu.get_by_role("option").first).to_contain_text("/catalogs")
    expect(menu.get_by_role("option").nth(1)).to_contain_text(f"/{ADDED}")
    save_workflow_test_screenshot(page, STEM, test_name="slash-list", fit_reactflow=False,
                                  clip_selector=CHAT_PANEL_SELECTOR)

    box.fill("/node")
    expect(menu.get_by_role("option")).to_have_count(1, timeout=10000)
    box.press("Enter")
    expect(menu).to_have_count(0, timeout=10000)
    expect(box).to_have_value(f"/{ADDED} ")
    message = f"/{ADDED} write the loader for the city's bike lanes"
    box.fill(message)
    panel.get_by_role("button", name="Send", exact=True).click()

    expect(panel.get_by_text(VISIBLE_PROSE, exact=False)).to_be_visible(timeout=30000)
    line = panel.locator('[data-curio-reply-skills="true"]')
    expect(line).to_have_text(f"Skills: {ADDED}", timeout=15000)
    expect(line.locator("[data-tooltip]")).to_have_attribute("data-tooltip", "Named with / in the message")

    # The run listed the added skill in its catalog, and was handed it.
    system = captured_system_prompt(current_server)
    catalog = system[system.index("<available_skills>"):system.index("</available_skills>")]
    assert re.findall(r"<name>([^<]+)</name>", catalog) == ["catalogs", ADDED], catalog[:600]
    assert f'<skill_content name="{ADDED}">' in system

    dismiss_toasts(page)
    page.mouse.move(0, 0)
    save_workflow_test_screenshot(page, STEM, test_name="reply-skills", fit_reactflow=False,
                                  clip_selector=CHAT_PANEL_SELECTOR)
