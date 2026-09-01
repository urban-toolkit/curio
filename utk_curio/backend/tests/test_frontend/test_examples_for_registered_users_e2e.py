"""Playwright E2E: a signed-up account's gallery lists the example dataflows (#200).

The examples were seeded to exactly one user - the shared guest - and project
listing is a plain owner filter, so under ``--auth`` every account signed in to
an empty gallery. ``--deploy`` carried the identical defect.

The reason nothing caught it is visible in ``fixtures.py``: the harness launched
with ``--auth`` but never ``--with-examples``, so the one configuration where
the gallery is empty was the one configuration never exercised. This module
turns the flag on (``CURIO_E2E_WITH_EXAMPLES``) and walks the reporter's path -
create an account, land on /projects, read what is there.

Cheaper coverage that already exists, and what this adds on top of it:

* ``tests/test_projects/test_example_seed_for_registered_users.py`` covers the
  seeding itself, both landmines (the global primary key, the destructive
  prune), idempotence and the marker that stops a deleted example coming back.
* ``tests/test_projects/test_routes.py`` covers ``GET /api/projects`` answering
  with the examples for a registered user's token.
* ``test_scripts/test_launcher_env.py`` pins ``--auth --with-examples`` to the
  two env vars.

None of those boot a browser against a real ``curio.py start``, which is where
the defect actually lived: seeding at startup, an account created afterwards,
and a listing filtered by owner are three separate pieces that were each
individually correct.
"""
from __future__ import annotations

import os
import uuid
from typing import TYPE_CHECKING

import pytest

from .utils import (
    require_project_page,
    require_user_auth,
    save_workflow_test_screenshot,
    signup_e2e_user,
    wait_for_projects_page,
)

if TYPE_CHECKING:
    from .utils import FrontendPage


pytestmark = pytest.mark.skipif(
    os.environ.get("CURIO_E2E_WITH_EXAMPLES", "0") not in ("1", "true", "yes", "on"),
    reason=(
        "needs a stack started with --with-examples; set CURIO_E2E_WITH_EXAMPLES=1 "
        "(seeding eleven dataflows costs real boot time, so it is opt-in)"
    ),
)

#: A handful of the curated examples, by the ``dataflow.name`` the seeder uses
#: as the project title. Named rather than counted so adding a twelfth example
#: does not break this, and so a gallery full of *something else* still fails.
EXPECTED_EXAMPLES = [
    "Vega-Lite chained transforms",
    "Vega-Lite spatial density",
]


def test_a_new_account_lands_on_a_gallery_of_examples(
    app_frontend: "FrontendPage", frontend_server: str, page
):
    require_user_auth()
    require_project_page()

    # A fresh username per run: the account is what the test is about, and
    # reusing one would pass on the second run for the wrong reason.
    username = f"examples_{uuid.uuid4().hex[:10]}"
    signup_e2e_user(page, frontend_server, name="Examples User", username=username)
    wait_for_projects_page(page, timeout=30000)

    # THE POINT: this list was empty for every registered account.
    for name in EXPECTED_EXAMPLES:
        page.get_by_text(name, exact=True).first.wait_for(
            state="visible", timeout=30000
        )

    cards = page.locator("[data-project-id]")
    assert cards.count() >= len(EXPECTED_EXAMPLES), (
        f"the gallery holds {cards.count()} project(s); the examples were not seeded "
        "for this account"
    )

    save_workflow_test_screenshot(
        page,
        "examples-gallery-registered-user",
        test_name="test_a_new_account_lands_on_a_gallery_of_examples",
        fit_reactflow=False,
    )


def test_each_account_gets_its_own_copy(
    app_frontend: "FrontendPage", frontend_server: str, page, context
):
    """Two accounts, two disjoint sets of project ids.

    ``Project.id`` is a global primary key and the example ids were derived
    from the filename alone, so the second account's seed collided on insert -
    an IntegrityError swallowed by a broad ``except`` into a silent zero-seed.
    Reading the ids from two browsers is what makes the collision visible.
    """
    require_user_auth()
    require_project_page()

    def ids_for_a_new_account(target_page) -> set[str]:
        username = f"examples_{uuid.uuid4().hex[:10]}"
        signup_e2e_user(
            target_page, frontend_server, name="Examples User", username=username
        )
        wait_for_projects_page(target_page, timeout=30000)
        target_page.get_by_text(EXPECTED_EXAMPLES[0], exact=True).first.wait_for(
            state="visible", timeout=30000
        )
        return set(
            target_page.locator("[data-project-id]").evaluate_all(
                "els => els.map(e => e.getAttribute('data-project-id'))"
            )
        )

    first = ids_for_a_new_account(page)

    second_page = context.new_page()
    try:
        second = ids_for_a_new_account(second_page)
    finally:
        second_page.close()

    assert first, "the first account's gallery was empty"
    assert second, "the second account's gallery was empty"
    assert first.isdisjoint(second), (
        "both accounts were served the same project ids, so they are sharing "
        f"one set of rows rather than owning a copy each: {sorted(first & second)}"
    )
