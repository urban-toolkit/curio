"""What a walkthrough is: the narrator it talks through, the context it is
handed, its definition, and the registry the ``@walkthrough`` decorator fills.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

from ..utils import MAX_DIFF_RATIO


# ---------------------------------------------------------------------------
# Narration
# ---------------------------------------------------------------------------

class Narrator(Protocol):
    """The slice of :class:`tour.Tour` a walkthrough uses.

    ``SilentNarrator`` implements the same calls with no overlay and no pacing,
    so a walkthrough reads identically in both modes.
    """

    def chapter(self, kicker: str, title: str, sub: str = "", hold: float | None = None) -> None: ...
    def say(self, title: str, sub: str = "", hold: float | None = None) -> None: ...
    def beat(self, ms: float = 700) -> None: ...
    def focus(self, locator, *, hold: float = 900, ring: bool = True): ...
    def click(self, locator, *, force: bool = False, dispatch: bool = False,
              hold: float = 700, ring: bool = True) -> None: ...
    def type_into(self, locator, text: str, *, delay: float = 55) -> None: ...
    def scroll(self, dy: float, *, steps: int = 6, hold: float = 90) -> None: ...
    def hush(self) -> None: ...


class SilentNarrator:
    """Drives the page with no overlay, for the baseline pass.

    Every method mirrors ``Tour``'s signature and drops the presentation. The
    interactions still happen -- a baseline of a screen nobody navigated to
    would be a baseline of the wrong screen.
    """

    def __init__(self, page, *, beat_cap: float | None = 150) -> None:
        self.page = page
        #: Longest a single beat may last, in ms. The baseline pass caps them
        #: hard - it only needs the app to settle before a capture, and every
        #: extra millisecond is dead time in CI. A recording passes ``None`` to
        #: honour the full beat, so the video moves at a watchable pace without
        #: any narration to supply one.
        self.beat_cap = beat_cap

    def chapter(self, kicker: str, title: str, sub: str = "", hold: float | None = None) -> None:
        return None

    def say(self, title: str, sub: str = "", hold: float | None = None) -> None:
        return None

    def beat(self, ms: float = 700) -> None:
        # Beats are how a journey lets the app settle (a drawer transition, a
        # re-render), not only how it paces itself.
        self.page.wait_for_timeout(ms if self.beat_cap is None else min(ms, self.beat_cap))

    def focus(self, locator, *, hold: float = 900, ring: bool = True):
        try:
            locator.wait_for(state="visible", timeout=10000)
        except Exception:
            return None
        box = locator.bounding_box()
        # No ring and no cursor - but a recording still pauses on the subject,
        # which is the only pacing left once the captions are gone.
        self.beat(hold)
        return box

    def click(self, locator, *, force: bool = False, dispatch: bool = False,
              hold: float = 700, ring: bool = True) -> None:
        if dispatch:
            locator.dispatch_event("click")
        else:
            locator.click(force=force)
        self.beat(hold)

    def focus_hold(self, ms: float) -> None:
        self.beat(ms)

    def type_into(self, locator, text: str, *, delay: float = 55) -> None:
        locator.click()
        locator.fill(text)

    def scroll(self, dy: float, *, steps: int = 6, hold: float = 90) -> None:
        self.page.mouse.wheel(0, dy)
        self.beat(hold)

    def hush(self) -> None:
        return None


@dataclass
class Ctx:
    """What a walkthrough is handed."""
    page: object
    frontend: str
    backend: str
    narrator: Narrator
    recording: bool
    #: Pins an intermediate state as its own screenshot baseline. Supplied by
    #: the baseline suite; a no-op while recording, where the video already
    #: carries the whole journey.
    snapshot: Callable[..., None] = lambda label, **kw: None
    #: Pins one node, up close, as its own baseline. Also a no-op while recording.
    node_snapshot: Callable[[str, str], None] = lambda label, node_id: None

    def capture_node(self, label: str, node_id: str) -> None:
        """Pin one node, framed up close, as a baseline called *label*.

        For a node whose drawing is the claim: an Autark map, which in a
        full-page frame is a thumbnail (see ``utils.save_node_closeup``).
        """
        self.node_snapshot(label, node_id)

    def capture(self, label: str, *, allow_running: bool = False,
                fit_reactflow: bool | None = None) -> None:
        """Pin the current screen as a baseline called *label*.

        For a journey whose point is a sequence -- reverting through a version
        history, stepping through a wizard -- the final frame is not the claim.
        Each step is, so each step gets its own committed PNG.

        The capture waits for every node to stop running; *allow_running* is for
        the frame whose subject is a run in progress. *fit_reactflow* overrides
        the scene's setting for one frame, for a step that leaves the canvas
        empty.
        """
        self.snapshot(label, allow_running=allow_running, fit_reactflow=fit_reactflow)

    # Convenience passthroughs so a walkthrough reads as prose.
    def say(self, title: str, sub: str = "", hold: float | None = None) -> None:
        self.narrator.say(title, sub, hold)

    def click(self, locator, **kw) -> None:
        self.narrator.click(locator, **kw)

    def focus(self, locator, **kw):
        return self.narrator.focus(locator, **kw)

    def beat(self, ms: float = 700) -> None:
        self.narrator.beat(ms)


#: Smallest diff budget a FULL-PAGE capture is compared at (#333).
#:
#: Above the worst cross-platform cost measured over this file's captures
#: (7.66%), so a developer on a machine that is not the baseline's does not read
#: a platform difference as a regression. Clipped captures keep their own,
#: tighter budgets. See ``Walkthrough.effective_max_diff_ratio``.
FULL_PAGE_DIFF_FLOOR = 0.10


@dataclass
class Walkthrough:
    """One journey through the app, plus how to capture it."""
    #: Kebab-case name for the behaviour. Names the video, the baseline PNG and
    #: the test id, so all three stay legible without a ticket to hand.
    slug: str
    title: str
    #: What the journey demonstrates, shown on the video's chapter card.
    premise: str
    run: Callable[[Ctx], None]
    #: What changed, for the report. Empty for a journey that documents
    #: behaviour rather than a fix.
    note: str = ""
    #: Regression tests that cover the same ground.
    tests: list[str] = field(default_factory=list)
    #: Issues this journey closes. Metadata, not identity.
    refs: list[int] = field(default_factory=list)
    #: Capture the whole page, or just the element under test. Clipping keeps
    #: the diff budget on the subject instead of on surrounding chrome.
    clip_selector: str | None = None
    #: ``False`` for pages with no canvas -- the helper otherwise spends its
    #: whole timeout waiting for a ``.react-flow__node`` that never arrives.
    #:
    #: Also ``False`` for a scene that aims its own camera: the helper fitViews
    #: immediately before every capture, so a ``frame_node`` call is undone
    #: between the framing and the screenshot and the image comes out as the
    #: whole dataflow regardless.
    fit_reactflow: bool = True
    #: Fraction of pixels allowed to differ. The helper's 0.10 default is blind
    #: to a restored 1.5px border or a button that grew one line, so the small
    #: visual fixes tighten it hard.
    #:
    #: A tight value only means something on a CLIPPED capture, where the
    #: subject fills the frame. On a full page it is raised to
    #: ``FULL_PAGE_DIFF_FLOOR`` -- see ``effective_max_diff_ratio``.
    max_diff_ratio: float = MAX_DIFF_RATIO
    #: The example dataflow to open the journey on, by filename under
    #: ``docs/examples``. ``None`` means an EMPTY dataflow.
    #:
    #: It used to default to one particular example, so every recording opened
    #: on "Vega-Lite chained transforms" whether or not the journey had anything
    #: to do with it - which reads as if that dataflow were part of the subject.
    #: A catalog scene needs no dataflow at all; one about a chart or a wide
    #: table cannot demonstrate itself without the right one. So each scene says
    #: what it needs, and says nothing when it needs nothing.
    example: str | None = None
    #: Needs the stack seeded with the example dataflows. The scene then carries
    #: the ``examples`` marker, so an ordinary run skips it honestly instead of
    #: asserting against an empty gallery and blaming the seed.
    needs_examples: bool = False

    @property
    def stem(self) -> str:
        return self.slug

    @property
    def effective_max_diff_ratio(self) -> float:
        """The budget to compare with, floored for a full-page capture (#333).

        The committed baselines are captured by CI, on Linux. Everywhere else
        the same page renders text slightly differently, and on a full 1280x720
        viewport that alone costs **4.5-7.7% of pixels** (measured across all 86
        captures in this file on macOS, 2026-09-15: `catalog-tag-chips-are-plain`
        4.85% against its 5% budget, `project-drawer-offers-delete` 7.66%
        against 8%). Seven captures sat above 90% of budget, so any local run
        was one restyle away from a red that looks exactly like a regression --
        the attribution cost #308 was filed about.

        Tightening below that floor buys nothing on a full page anyway: 3% of
        1280x720 is 27,600 pixels, and a button is ~3,000. A full-page budget
        cannot see a missing control at ANY setting a cross-platform run could
        pass; what it catches is a page that changed wholesale, which 10% still
        catches. A claim that needs finer resolution needs ``clip_selector``
        (which keeps the subject filling the frame, where a tight budget bites)
        or an assertion in code, which every one of these scenes already has.

        Clipped captures are left exactly as declared.
        """
        if self.clip_selector is not None:
            return self.max_diff_ratio
        return max(self.max_diff_ratio, FULL_PAGE_DIFF_FLOOR)


WALKTHROUGHS: list[Walkthrough] = []


def walkthrough(**kw):
    """Register a walkthrough; the decorated function becomes its ``run``."""
    def wrap(fn):
        WALKTHROUGHS.append(Walkthrough(run=fn, **kw))
        return fn
    return wrap
