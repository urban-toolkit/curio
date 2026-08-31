"""Visual regression over the scripted walkthroughs.

Each case drives ``walkthroughs.WALKTHROUGHS`` silently and diffs a committed PNG
under ``docs/examples/dataflows/expected_outputs/``. Unlike the screencasts this
is NOT opt-in: it runs in the normal e2e suite, so a restyle that quietly
changes a screen fails here rather than in someone's next round of user testing.

Generating a baseline
---------------------
``save_workflow_test_screenshot`` writes the baseline when the file is absent,
so a first run ALWAYS passes. Generate deliberately, against a build whose behaviour
you have already checked by hand, and look at the PNG before committing it -- a
baseline captured against a broken build enshrines the bug as expected output.

Run::

    ./scripts/test.sh --e2e-only
    # or, against a stack you already booted:
    CURIO_E2E_USE_EXISTING=1 pytest utk_curio/backend/tests/test_frontend/test_walkthrough_baselines.py -v
"""
from __future__ import annotations

import pytest

from .walkthroughs import WALKTHROUGHS, Ctx, SilentNarrator
from .utils import (
    dismiss_toasts,
    require_owner_view,
    require_project_page,
    require_user_auth,
    save_workflow_test_screenshot,
    stub_login_and_enter_workflow,
)
from .walkthroughs import PROVENANCE_EXAMPLE, load_example_spec


@pytest.mark.parametrize("walk", WALKTHROUGHS, ids=lambda w: w.slug)
def test_walkthrough_baseline(walk, app_frontend, current_server, page):
    require_project_page()
    require_user_auth()

    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Walkthrough",
        username=f"walk_{walk.slug.replace(chr(45), chr(95))[:24]}",
        project_name=walk.title[:40],
        project_spec=load_example_spec(PROVENANCE_EXAMPLE),
    )
    require_owner_view(page)
    page.wait_for_selector(".react-flow__node", timeout=45000)

    def snapshot(label: str) -> None:
        """One committed PNG per pinned step of the journey."""
        dismiss_toasts(page)
        save_workflow_test_screenshot(
            page,
            walk.stem,
            test_name=label,
            clip_selector=walk.clip_selector,
            fit_reactflow=walk.fit_reactflow,
            max_diff_ratio=walk.max_diff_ratio,
        )

    ctx = Ctx(
        page=page,
        frontend=app_frontend.base_url,
        backend=current_server,
        narrator=SilentNarrator(page),
        recording=False,
        snapshot=snapshot,
    )
    walk.run(ctx)

    # Toasts are timed, so one still fading would make the diff depend on how
    # fast the machine got here.
    dismiss_toasts(page)
    save_workflow_test_screenshot(
        page,
        walk.stem,
        test_name="walkthrough",
        clip_selector=walk.clip_selector,
        fit_reactflow=walk.fit_reactflow,
        max_diff_ratio=walk.max_diff_ratio,
    )
