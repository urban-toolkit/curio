"""Sign up through the UI, reach the projects page, open a new dataflow, and
check the page is the owner's.
"""

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .environment import require_user_auth


# ---------------------------------------------------------------------------
# Reusable auth + canvas-entry helpers
#
# Every workflow/project E2E test needs the same bootstrap: sign up a fresh
# user, land on /projects, then open a new empty workflow canvas. These
# helpers centralise that choreography so individual tests (and the class
# scoped ``loaded_workflow`` fixture) stay focused on their actual assertions.
# ---------------------------------------------------------------------------

DEFAULT_TEST_PASSWORD = "testpass123"


def signup_e2e_user(
    page,
    base_url: str,
    *,
    name: str,
    username: str,
    password: str = DEFAULT_TEST_PASSWORD,
) -> None:
    """Sign up a fresh user via the ``/auth/signup`` form.

    Waits until the sign-up flow has redirected to ``/projects`` so callers
    can immediately interact with the authenticated UI.
    """
    require_user_auth()
    page.goto(f"{base_url}/auth/signup")
    page.wait_for_load_state("domcontentloaded")
    page.get_by_text("Create an account").wait_for(timeout=30000)
    page.get_by_label("Name", exact=True).fill(name)
    page.get_by_label("Username").fill(username)
    page.get_by_label("Password", exact=True).fill(password)
    page.get_by_label("Confirm Password").fill(password)
    page.get_by_role("button", name="Create account").click()
    page.wait_for_url("**/projects", timeout=30000)


def wait_for_projects_page(page, *, timeout: float = 10000) -> None:
    """Wait until ``/projects`` has rendered.

    The page no longer has an ``<h1>Projects</h1>`` — the section tab strip
    (AppSectionTabs) names the page instead, so wait on that link. ``exact``
    keeps this off the Curio logo link, whose accessible name is "Curio".
    """
    page.get_by_role("link", name="Projects", exact=True).wait_for(timeout=timeout)


def project_card(page, name: str):
    """The ``/projects`` card whose title is *name*, scoped to the card grid.

    Not ``get_by_text(name)``: the browse rebuild auto-selects the first card so
    the detail drawer arrives populated, and that drawer renders the same name
    in an ``<h2>``. With one project on the page a bare text lookup therefore
    resolves to two elements and Playwright fails it as a strict mode violation.

    Keys off the two attributes ``ProjectsList.tsx`` exposes for exactly this -
    ``data-curio-projects-scroll`` on the scroller and ``data-project-id`` on
    each card - both of which the Jest suite already pins.
    """
    return page.locator(
        '[data-curio-projects-scroll="true"] [data-project-id]'
    ).filter(has_text=name)


def open_new_workflow(page) -> None:
    """From ``/projects``, click "+ New Dataflow" and wait for the canvas."""
    page.get_by_text("+ New Dataflow").click()
    page.wait_for_url("**/dataflow/**", timeout=15000)
    page.wait_for_load_state("domcontentloaded")


def signup_and_enter_new_workflow(
    page,
    base_url: str,
    *,
    name: str,
    username: str,
    password: str = DEFAULT_TEST_PASSWORD,
) -> None:
    """Sign up a user and navigate to a fresh empty dataflow canvas."""
    signup_e2e_user(
        page, base_url, name=name, username=username, password=password,
    )
    open_new_workflow(page)


def require_owner_view(page, *, timeout: float = 4000) -> None:
    """Fail when the dataflow opened read-only as the shared guest.

    This used to ``pytest.skip`` here, and that was the wrong call. A dataflow's
    packages, datasets and agents are visible only to the user who installed
    them, so a browser that lands as the shared guest sees empty catalogs -
    which means every test guarded by this is testing nothing. Skipping made
    that invisible: ``scripts/test.sh`` booted its shared stack without
    ``--deploy``, and 43 tests across 22 files - the whole agent-catalog suite
    among them - quietly skipped while the run reported green.

    The environment being wrong is a setup bug, and a setup bug should be loud.
    Detection is unchanged; only the consequence is. The fix when this fires is
    to boot with ``--deploy`` (which ``scripts/test.sh`` and the
    ``curio_servers`` fixture both now do), never to tolerate the state.
    """
    banner = page.get_by_test_id("shared-view-banner")
    try:
        banner.wait_for(state="visible", timeout=timeout)
    except PlaywrightTimeoutError:
        return  # no banner → authenticated owner, proceed
    raise AssertionError(
        "Dataflow opened read-only as the shared guest, so this test would "
        "assert against empty catalogs. The stack is running without user "
        "auth: boot it with `--deploy` (scripts/test.sh does, and so does the "
        "curio_servers fixture), or unset CURIO_NO_AUTH in the pytest "
        "environment so the fixture passes --deploy for you."
    )
