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
from .walkthroughs import PROVENANCE_EXAMPLE, TOAST_REGION, load_example_spec


def _walkthrough_params():
    """``WALKTHROUGHS`` as pytest params, carrying each scene's own marks.

    A scene that declares ``needs_examples`` gets the ``examples`` marker, so an
    ordinary run deselects it rather than driving it against an empty gallery and
    reporting the seed as broken.
    """
    return [
        pytest.param(w, marks=[pytest.mark.examples] if w.needs_examples else [])
        for w in WALKTHROUGHS
    ]

@pytest.mark.parametrize("walk", _walkthrough_params(), ids=lambda w: w.slug)
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
        project_spec=load_example_spec(walk.example) if walk.example else None,
    )
    require_owner_view(page)
    # An empty dataflow has no nodes; only wait for one when the scene asked for
    # a spec that puts them there. The seven catalog/agent scenes deliberately
    # start on a never-saved dataflow or a catalog page, and waiting on a node
    # they will never have killed every one of them in setup — 45 s before the
    # first assertion ran. ``test_walkthrough_videos.py`` already guards this;
    # this file was the half that was missed.
    if walk.example:
        page.wait_for_selector(".react-flow__node", timeout=45000)
    else:
        page.wait_for_selector("#tools-menu", timeout=45000)

    # A stray toast is timing noise in most baselines, so they are swept before
    # every capture — but NOT when the toast IS the subject.
    # `catalog-add-reports-success` clips to the toast region, so sweeping first
    # photographed an empty box and the capture timed out waiting for that box
    # to become visible. The scene was unsatisfiable as written, and nobody
    # could see it while the scene was still dying in setup.
    subject_is_a_toast = walk.clip_selector == TOAST_REGION

    def snapshot(label: str) -> None:
        """One committed PNG per pinned step of the journey."""
        if not subject_is_a_toast:
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
    # fast the machine got here — except where the toast is what we came for.
    if not subject_is_a_toast:
        dismiss_toasts(page)
    save_workflow_test_screenshot(
        page,
        walk.stem,
        test_name="walkthrough",
        clip_selector=walk.clip_selector,
        fit_reactflow=walk.fit_reactflow,
        max_diff_ratio=walk.max_diff_ratio,
    )
