"""The scene on the example dataflows a new account is given."""
from __future__ import annotations

import uuid

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from ..utils import signup_e2e_user, wait_for_projects_page
from .framework import Ctx, walkthrough


# ---------------------------------------------------------------------------
# Examples for registered accounts (#200)
# ---------------------------------------------------------------------------

#: A couple of the curated examples, by the ``dataflow.name`` the seeder uses as
#: the project title. Named rather than counted, so adding a twelfth example
#: does not break the scene and a gallery full of something else still fails.
EXAMPLE_TITLES = [
    "Vega-Lite chained transforms",
    "Vega-Lite spatial density",
]


@walkthrough(
    slug="examples-are-seeded-for-a-new-account",
    needs_examples=True,
    refs=[200],
    title="A new account arrives to a gallery of examples",
    premise="Create an account and read what is waiting on the projects page.",
    note="The examples were seeded to exactly one user - the shared guest - "
         "and project listing is a plain owner filter, so under `--deploy` every "
         "account signed in to an empty gallery; `--deploy` carried the same "
         "defect. Each account now gets its own copies, seeded at sign-up and "
         "back-filled on first listing for anyone who registered earlier.",
    tests=["tests/test_projects/test_example_seed_for_registered_users.py",
           "tests/test_projects/test_routes.py",
           "test_frontend/test_examples_for_registered_users_e2e.py"],
    fit_reactflow=False,
)
def examples_are_seeded_for_a_new_account(ctx: Ctx) -> None:
    """Needs a stack started with ``--with-examples``.

    The runner has already stub-logged-in a walkthrough user on a canvas; this
    scene deliberately leaves that session and signs up a brand new account,
    because "what a new account sees" is the whole claim.
    """
    page = ctx.page

    ctx.say("Create an account", "The reporter's own path: sign up, then look.")
    # The runner has already stub-logged-in a walkthrough user, and the app
    # redirects an authenticated visitor away from /auth/signup - so the form
    # never appears and the scene would read the WRONG account's gallery. Drop
    # the session first; the token is the `session_token` cookie (utils/authApi).
    page.context.clear_cookies()
    page.evaluate("() => { try { localStorage.clear(); } catch (e) {} }")

    username = f"examples_{uuid.uuid4().hex[:10]}"
    signup_e2e_user(page, ctx.frontend, name="New User", username=username)
    wait_for_projects_page(page, timeout=30000)
    ctx.beat(900)

    # Wait for each title rather than counting once. Seeding eleven dataflows
    # and their datasets happens on the signup request, and the gallery fetches
    # them after the route renders, so a bare `count()` a beat later is a race
    # the scene loses on a cold store - it read zero while the seed was still
    # landing. The sibling e2e (`test_examples_for_registered_users_e2e`) has
    # always waited; this scene was the one asserting on a snapshot in time.
    missing = []
    for title in EXAMPLE_TITLES:
        try:
            page.get_by_text(title, exact=True).first.wait_for(
                state="visible", timeout=30000,
            )
        except PlaywrightTimeoutError:
            missing.append(title)
    if missing:
        # Distinguish the two ways this scene can fail: a stack booted without
        # the flag has nothing to show and is a harness problem, not the bug.
        raise AssertionError(
            f"the gallery is missing {missing}. If every example is absent, the "
            "stack was started without --with-examples (pass --with-examples to "
            "pytest); if only some are, the seed is at fault."
        )

    for title in EXAMPLE_TITLES:
        ctx.focus(page.get_by_text(title, exact=True).first, hold=900)

    ctx.say("The example dataflows, owned by this account",
            "Not the guest's copies - this account's own, ready to open.")
    ctx.capture("examples-gallery")
