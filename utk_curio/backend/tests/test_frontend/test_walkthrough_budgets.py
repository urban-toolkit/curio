"""What diff budget each walkthrough capture is actually compared at (#333).

A pure check over the registry — no browser, no stack — because the rule is a
property of the scene definitions, and the thing it guards against is a local
run going red for the platform it runs on rather than for a change:

The committed baselines are captured by CI, on Linux. Rendered anywhere else,
the same 1280x720 page differs by 4.5-7.7% of its pixels from text antialiasing
alone (measured over all 86 captures in ``walkthroughs.py``, macOS,
2026-09-15). Seven sat above 90% of their budget, one at 97%, so any restyle —
or any developer on a different machine — produced a failure indistinguishable
from a regression. That is the attribution cost #308 was filed about.

Tightening a FULL-PAGE budget below that floor buys nothing anyway: 3% of
1280x720 is 27,600 pixels and a button is ~3,000, so no setting a
cross-platform run could pass would catch a missing control. Clipped captures
are the opposite — the subject fills the frame — so those budgets stay exactly
as declared, and this file pins that distinction.
"""
from __future__ import annotations

from .walkthroughs import FULL_PAGE_DIFF_FLOOR, WALKTHROUGHS, Walkthrough


def _scene(**kw) -> Walkthrough:
    return Walkthrough(slug="s", title="t", premise="p", run=lambda ctx: None, **kw)


class TestTheFloor:
    def test_a_full_page_capture_is_never_compared_tighter_than_the_floor(self):
        scene = _scene(max_diff_ratio=0.03)
        assert scene.clip_selector is None
        assert scene.effective_max_diff_ratio == FULL_PAGE_DIFF_FLOOR

    def test_a_looser_full_page_budget_is_left_alone(self):
        # The floor raises; it never tightens. The 0.20 default stays 0.20.
        assert _scene(max_diff_ratio=0.20).effective_max_diff_ratio == 0.20

    def test_a_clipped_capture_keeps_its_declared_budget(self):
        # Here the subject fills the frame, so a tight budget bites: this is
        # where "a control disappeared" is actually caught.
        scene = _scene(max_diff_ratio=0.03, clip_selector='[data-curio-save-state]')
        assert scene.effective_max_diff_ratio == 0.03


class TestTheRegistry:
    def test_every_full_page_scene_clears_the_floor(self):
        tight = {
            w.slug: w.effective_max_diff_ratio
            for w in WALKTHROUGHS
            if w.clip_selector is None and w.effective_max_diff_ratio < FULL_PAGE_DIFF_FLOOR
        }
        assert tight == {}

    def test_clipped_scenes_still_carry_tight_budgets(self):
        # If this ever comes back empty, the floor has swallowed the scenes it
        # was supposed to leave alone.
        clipped = [
            w.slug for w in WALKTHROUGHS
            if w.clip_selector is not None and w.effective_max_diff_ratio < FULL_PAGE_DIFF_FLOOR
        ]
        assert clipped, "no clipped scene has a tight budget any more"

    def test_the_two_scenes_that_document_a_detail_stay_clipped(self):
        """#333: both of these captured far more than the claim they document.

        ``catalog-tag-chips-are-plain`` shot a whole 1280x720 page to say that
        the chips in one card share a background; at 5%, ~46k pixels, the budget
        was wider than the chip row, so a chip going coloured again would have
        passed. ``agent-catalog-action-labels-fit`` shot the whole drawer to say
        that one label fits one button.

        Named explicitly rather than covered by the general rule above, because
        the general rule is satisfied by any one clipped scene and these two are
        the ones that were wrong. Reverting either to a full page would restore
        exactly the gap the issue was filed about, and would do it silently:
        dropping ``clip_selector`` raises the effective budget to the floor,
        so the suite would go *greener*, not redder.
        """
        by_slug = {w.slug: w for w in WALKTHROUGHS}
        for slug in ("catalog-tag-chips-are-plain", "agent-catalog-action-labels-fit"):
            scene = by_slug.get(slug)
            assert scene is not None, f"{slug} is gone from the registry"
            assert scene.clip_selector is not None, (
                f"{slug} went back to a full-page capture; its claim is a detail "
                f"and a full-page budget cannot see a detail change"
            )
            assert scene.effective_max_diff_ratio <= 0.10, (
                f"{slug} is clipped but its budget is {scene.effective_max_diff_ratio}, "
                f"wide enough to hide the regression it exists to catch"
            )

    def test_the_floor_is_about_twice_the_measured_cross_platform_cost(self):
        # Measured worst case was 7.66% (project-drawer-offers-delete). A floor
        # at less than ~1.5x that is not headroom; far above it is not a budget.
        assert 0.12 <= FULL_PAGE_DIFF_FLOOR <= 0.20
