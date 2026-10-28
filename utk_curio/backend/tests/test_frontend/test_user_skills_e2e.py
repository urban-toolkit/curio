"""Playwright E2E: a skill of the account's own, imported through its review, exported and removed.

**Import skill**, on the Agent Catalog page's Skills view, takes a zip of a
skill's folder. The review shows the skill as the server read it, leniently:
its description, what does not follow the format, its files, and the agents
that will use it, each offered picked. Here the Researcher is unpicked, so
only the other agents are given the skill. Imported, the skill's drawer says
it is in the account's skills and offers **Remove from your skills**; its
details export it as a zip that agentskills.io's ``skills-ref`` validates;
and Remove takes it out of the grid and off its agents.

Frames for the owner: the import review, and the imported skill's drawer.

Run::

    pytest utk_curio/backend/tests/test_frontend/test_user_skills_e2e.py -v
"""
from __future__ import annotations

import io
import zipfile

from playwright.sync_api import expect

from .test_agent_chat_e2e import _goto_when_served
from .utils import (
    EXPORT_DOWNLOAD_TIMEOUT_MS,
    api_json,
    install_session_cookie,
    require_project_page,
    require_user_auth,
    save_workflow_test_screenshot,
    stub_db_user,
)

STEM = "user-skills"
NAME = "street-trees"
FINDER = "agent.curio.dataset-finder@1"
RESEARCHER = "agent.curio.researcher@1"
MODAL = '[data-curio-modal-shell="true"]'
BROWSE_DRAWER = '[data-curio-browse-drawer="true"]'

#: A skill written for another client: a colon in a plain value, which YAML
#: refuses, and a field the format does not define. The review reads both.
SKILL_MD = (
    "---\n"
    f"name: {NAME}\n"
    "description: Use this skill when: a dataflow counts or maps the city's street trees\n"
    "author: parks-team\n"
    "---\n"
    "## Street trees\n\n"
    "Count the trees of each block from the city's tree census, and map them by species.\n"
)
SPECIES = "Honey locust, London plane, pin oak.\n"


def _zip() -> bytes:
    sink = io.BytesIO()
    with zipfile.ZipFile(sink, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{NAME}/SKILL.md", SKILL_MD)
        archive.writestr(f"{NAME}/references/species.md", SPECIES)
    return sink.getvalue()


def _rail_row(page, section: str, value: str):
    return page.locator(f'[data-curio-rail-section="{section}"][data-curio-rail-value="{value}"]')


def _skill_names(backend: str, token: str) -> list[str]:
    return [card["name"] for card in api_json(f"{backend}/api/agents/skills", token)["skills"]]


def _agent_skill_names(backend: str, token: str, coord: str) -> list[str]:
    return [row["name"] for row in api_json(f"{backend}/api/agents/definitions/{coord}/skills", token)["skills"]]


def test_a_skill_of_your_own_is_imported_through_its_review_exported_and_removed(
    page, frontend_server, current_server, tmp_path,
):
    import skills_ref

    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    login = stub_db_user(current_server, username="userskills", name="User Skills User")
    token = login["token"]
    install_session_cookie(page, frontend_server, token)

    _goto_when_served(page, f"{frontend_server}/catalog/agents")
    expect(page.get_by_role("heading", name="Agent Catalog", level=1)).to_be_visible(timeout=30000)
    all_skills = _rail_row(page, "skills", "all-skills")
    expect(all_skills).to_be_visible(timeout=30000)
    all_skills.click()
    cards = page.locator("article[data-skill-name]")
    shipped = len(_skill_names(current_server, token))
    expect(cards).to_have_count(shipped, timeout=20000)

    # The review: the skill as the server read it, every agent offered picked.
    page.get_by_role("button", name="Import skill").click()
    dialog = page.locator(MODAL)
    expect(dialog.get_by_role("heading", name="Import skill")).to_be_visible(timeout=15000)
    with page.expect_response(lambda r: r.url.endswith("/api/agents/skills/imports/check"), timeout=20000) as checked:
        dialog.get_by_label("Skill files").set_input_files(
            files=[{"name": f"{NAME}.zip", "mimeType": "application/zip", "buffer": _zip()}],
        )
    assert checked.value.ok, checked.value.text()[:300]
    review = dialog.locator('[data-curio-skill-review="true"]')
    expect(review).to_be_visible(timeout=15000)
    expect(review).to_contain_text("Use this skill when: a dataflow counts or maps the city's street trees")
    expect(review).to_contain_text("colon")
    expect(review).to_contain_text("author, which the format does not define")
    expect(review).to_contain_text("references/species.md")
    boxes = review.get_by_role("checkbox")
    assert boxes.count() >= 4, boxes.count()
    for index in range(boxes.count()):
        expect(boxes.nth(index)).to_be_checked()
    review.get_by_label("Researcher").uncheck()
    expect(review.get_by_label("Researcher")).not_to_be_checked()
    page.mouse.move(0, 0)
    save_workflow_test_screenshot(page, STEM, test_name="skill-import-review", fit_reactflow=False,
                                  clip_selector=MODAL)

    with page.expect_response(
        lambda r: r.url.endswith("/api/agents/skills/imports") and r.request.method == "POST", timeout=20000,
    ) as imported:
        dialog.get_by_role("button", name="Import", exact=True).click()
    assert imported.value.status == 201, imported.value.text()[:300]
    expect(page.locator(MODAL)).to_have_count(0, timeout=15000)

    # Imported: in the grid, in the drawer, and with the agents the review left picked.
    expect(cards).to_have_count(shipped + 1, timeout=20000)
    drawer = page.locator(BROWSE_DRAWER)
    expect(drawer.get_by_role("heading", name=NAME, exact=True)).to_be_visible(timeout=15000)
    expect(drawer.get_by_text("✓ In your skills", exact=True)).to_be_visible()
    expect(drawer.get_by_text("You imported it", exact=True)).to_be_visible()
    expect(drawer.get_by_role("button", name="Remove from your skills")).to_be_visible()
    assert NAME in _agent_skill_names(current_server, token, FINDER)
    assert NAME not in _agent_skill_names(current_server, token, RESEARCHER)
    card = page.locator(f'article[data-skill-name="{NAME}"]')
    card.scroll_into_view_if_needed()
    page.mouse.move(0, 0)
    save_workflow_test_screenshot(page, STEM, test_name="own-skill-drawer", fit_reactflow=False)

    # Exported from its details: a zip of its folder that skills-ref validates.
    card.get_by_role("button", name="View details").click()
    details = page.get_by_role("dialog", name="Skill details")
    expect(details).to_be_visible(timeout=15000)
    with page.expect_download(timeout=EXPORT_DOWNLOAD_TIMEOUT_MS) as info:
        details.get_by_role("button", name="Export").click()
    download = info.value
    assert download.suggested_filename == f"{NAME}.zip"
    with zipfile.ZipFile(download.path()) as archive:
        assert sorted(archive.namelist()) == [f"{NAME}/SKILL.md", f"{NAME}/references/species.md"]
        archive.extractall(tmp_path)
    assert skills_ref.validate(tmp_path / NAME) == []
    assert (tmp_path / NAME / "references" / "species.md").read_text(encoding="utf-8") == SPECIES
    expect(details.locator("[data-curio-export-error]")).to_have_count(0)
    page.keyboard.press("Escape")
    expect(details).to_have_count(0, timeout=10000)

    # Removed: out of the grid and off its agents.
    with page.expect_response(
        lambda r: r.url.endswith(f"/api/agents/skills/{NAME}") and r.request.method == "DELETE", timeout=20000,
    ) as removed:
        drawer.get_by_role("button", name="Remove from your skills").click()
    assert removed.value.ok, removed.value.text()[:300]
    expect(cards).to_have_count(shipped, timeout=20000)
    assert NAME not in _skill_names(current_server, token)
    assert NAME not in _agent_skill_names(current_server, token, FINDER)
