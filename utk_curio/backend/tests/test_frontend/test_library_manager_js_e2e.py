"""Playwright E2E: the Installed libraries dialog refuses a JavaScript add.

#239: the dialog labelled JavaScript "coming soon" and then enabled Add as soon
as a package name was typed. The backend answers 501, so the only outcome was a
red "Failed" row for an operation the dialog had just offered.

Deliberately separate from ``test_library_manager_e2e.py``. That test really
runs pip, needs PyPI, and is not repeat-safe within one server session, so
folding a pure-UI assertion into it would make this check as fragile as the
network. Nothing here leaves the browser except the modal's own GET.

Run::

    CURIO_TESTING=1 pytest \
        utk_curio/backend/tests/test_frontend/test_library_manager_js_e2e.py -v
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from .utils import (
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage


@pytest.fixture()
def libraries(app_frontend: "FrontendPage", current_server: str, page):
    """Open Data > Installed libraries on a fresh dataflow."""
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Libraries JS User",
        username="librariesjs",
        project_name="LibrariesJs",
    )
    require_owner_view(page)

    page.get_by_role("button", name=re.compile(r"^Data")).click(force=True)
    page.get_by_role("button", name="Installed libraries", exact=True).click()

    dialog = page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name="Installed libraries", exact=True)
    )
    expect(dialog).to_be_visible(timeout=15000)
    return dialog


def _controls(dialog):
    return (
        dialog.locator("select").first,
        dialog.locator('input[type="text"]').first,
        dialog.get_by_role("button", name="Add", exact=True),
    )


def test_javascript_cannot_be_submitted(libraries, page):
    kind, spec, add = _controls(libraries)

    # Python first: the negative control. Add has to be reachable at all, or
    # the assertions below would pass on a broken dialog.
    spec.fill("numpy")
    expect(add).to_be_enabled()

    kind.select_option("js")

    expect(spec).to_be_disabled()
    expect(add).to_be_disabled()
    # The placeholder that invited the attempt is gone.
    assert "coming soon" not in (spec.get_attribute("placeholder") or "").lower()


def test_it_says_where_a_javascript_dependency_belongs(libraries):
    kind, spec, _add = _controls(libraries)
    kind.select_option("js")

    note = libraries.get_by_text(re.compile("cannot install JavaScript libraries", re.I))
    expect(note).to_be_visible()
    expect(libraries.get_by_text("dependencies.js", exact=True)).to_be_visible()

    # The disabled box names the note, so a screen reader reaching a dead
    # control is told why it is dead.
    described = spec.get_attribute("aria-describedby")
    assert described, "the disabled spec box must point at the explanation"
    expect(libraries.locator(f"#{described}")).to_be_visible()


def test_no_install_request_is_ever_sent(libraries, page):
    """A typed spec carried across the kind switch still submits nothing.

    Typing under Python and then switching leaves the spec in state, which is
    the realistic way a user arrives at "JavaScript selected, box non-empty".
    The guard inside ``handleAdd`` covers the Enter key too, but a disabled
    input dispatches no key events in a real browser, so that half is pinned by
    the jest test rather than here.
    """
    kind, spec, add = _controls(libraries)
    spec.fill("lodash@^4.17")
    kind.select_option("js")

    posted: list[str] = []
    page.on(
        "request",
        lambda r: posted.append(r.url)
        if r.method == "POST" and r.url.endswith("/api/packages/libraries")
        else None,
    )

    expect(add).to_be_disabled()
    add.click(force=True)
    page.wait_for_timeout(1000)

    assert posted == [], f"an unsupported install was submitted: {posted}"
    # And no failure row appeared either, which is what the 501 used to draw.
    expect(libraries.get_by_text(re.compile(r"Couldn't install", re.I))).to_have_count(0)


def test_python_still_installs_from_the_same_dialog(libraries):
    """Switching back must not leave the dialog inert."""
    kind, spec, add = _controls(libraries)
    kind.select_option("js")
    expect(add).to_be_disabled()

    kind.select_option("python")
    expect(spec).to_be_enabled()
    spec.fill("numpy")
    expect(add).to_be_enabled()
