"""Export from "View details" works for rows the account never installed (#275).

The Node and Agent Catalog pages list the whole shipped catalog and the whole
built-in roster, and every row's details view has an Export button. Both export
paths read only this account's store, so a package the user had not added
answered ``package X is not installed`` and a built-in agent never imported
produced a bare ``Export failed.`` in the Prompts section. Nothing downloaded.

Two rows are exported here, on a fresh account that has installed nothing: the
package and the agent named in the report.
"""
from __future__ import annotations

import io
import json
import zipfile

from playwright.sync_api import expect

from .utils import (
    require_project_page,
    require_user_auth,
    stub_db_login,
)

#: Shipped in packages/, referenced by no example, so no seeder installs it.
PACKAGE_NAME = "Urban Heat Vulnerability Index"
PACKAGE_DIR = "ai.urbanlab.uhvi@1"

#: A built-in from the roster; readable without ever being imported.
AGENT_NAME = "Node Researcher"
AGENT_DIR = "agent.node-researcher@1.0.0"


def _login(page, app_frontend, current_server):
    require_project_page()
    require_user_auth()
    return stub_db_login(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        username="catalog_export_user",
        name="Catalog Export User",
    )


def _open_details(page, base: str, path: str, heading: str, name: str) -> None:
    page.goto(f"{base}{path}")
    expect(page.get_by_role("heading", name=heading, level=1)).to_be_visible(timeout=20000)
    # A card is an <article> titled by an <h2>; its "View details" is a plain
    # link-styled button, so scope by the card rather than by an aria-label.
    card = page.locator("article").filter(
        has=page.get_by_role("heading", name=name, level=2, exact=True),
    )
    card.first.wait_for(state="visible", timeout=20000)
    card.first.get_by_role("button", name="View details").click(timeout=20000)
    expect(page.get_by_role("dialog")).to_be_visible(timeout=10000)


def test_a_catalog_only_package_exports_from_view_details(app_frontend, current_server, page):
    _login(page, app_frontend, current_server)
    _open_details(page, app_frontend.base_url, "/catalog/nodes", "Node Catalog", PACKAGE_NAME)

    dialog = page.get_by_role("dialog")
    with page.expect_download(timeout=30000) as info:
        dialog.get_by_role("button", name="Export").click()
    download = info.value

    assert download.suggested_filename == f"{PACKAGE_DIR}.curio.zip"
    with zipfile.ZipFile(download.path()) as zf:
        names = zf.namelist()
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["id"] == "ai.urbanlab.uhvi", manifest
    assert "integrity.json" not in names
    # No error line appeared under the header.
    assert dialog.locator("text=/is not installed|Export failed/i").count() == 0


def test_a_builtin_agent_exports_from_view_details(app_frontend, current_server, page):
    _login(page, app_frontend, current_server)
    _open_details(page, app_frontend.base_url, "/catalog/agents", "Agent Catalog", AGENT_NAME)

    dialog = page.get_by_role("dialog")
    with page.expect_download(timeout=30000) as info:
        dialog.get_by_role("button", name="Export").click()
    download = info.value

    assert download.suggested_filename == f"{AGENT_DIR}.curio-agent.json"
    with open(download.path(), "rb") as fh:
        bundle = json.load(io.TextIOWrapper(fh, encoding="utf-8"))
    assert bundle["manifest"]["id"] == "agent.node-researcher", bundle["manifest"]
    declared = {asset["path"] for asset in bundle["manifest"]["prompts"].values()}
    assert declared and declared <= set(bundle["prompts"]), (declared, list(bundle["prompts"]))
    assert dialog.locator("[data-curio-export-error]").count() == 0
