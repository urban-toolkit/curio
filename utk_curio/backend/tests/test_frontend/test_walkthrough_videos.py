"""One narrated screencast per walkthrough.

Not a regression test -- ``test_walkthrough_baselines.py`` is, and it drives the
same journeys. This one exists to produce an artefact: a short video showing
Curio actually doing the thing.

One video per walkthrough rather than one long take, so each stands on its own
(and can be dropped into the issue it closes). Each gets a fresh browser context,
because Playwright records per context and only flushes the file once the page is
closed.

Opt-in through ``--videos`` (a marker, not an environment variable -- see the
``--longrun`` precedent in ``backend/tests/conftest.py``)::

    ./scripts/test.sh --e2e-only --videos --headed

    # one journey, against a stack you already booted
    CURIO_E2E_USE_EXISTING=1 pytest utk_curio/backend/tests/test_frontend/ \
        --videos -k "provenance-version-switching" -s

Output lands in ``.curio/walkthroughs/`` (gitignored, the same convention as
``tour.py``'s ``.curio/tour``): ``<slug>.webm``, ``<slug>.mp4`` when a system
ffmpeg is on PATH, and ``<slug>.md`` -- a short report naming whatever the
journey closes, to paste beside the video.
"""
from __future__ import annotations

import os
import traceback

import pytest

from . import tour
from .walkthroughs import (
    WALKTHROUGHS,
    Ctx,
    SilentNarrator,
    Walkthrough,
    load_example_spec,
)
from .utils import (
    REPO_ROOT,
    dismiss_toasts,
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_login_and_enter_workflow,
)

pytestmark = pytest.mark.video

OUT_DIR = os.path.join(REPO_ROOT, ".curio", "walkthroughs")
VIDEO_SIZE = {"width": 1280, "height": 800}


def _report(walk: Walkthrough) -> str:
    """The write-up that goes beside the video."""
    tests = "\n".join(f"- `{t}`" for t in walk.tests)
    closes = ", ".join(f"#{n}" for n in walk.refs)
    lines = [f"## {walk.title}", "", walk.premise, ""]
    if walk.note:
        lines += [f"**What changed.** {walk.note}", ""]
    if tests:
        lines += ["**Covered by**", tests, ""]
    lines += [f"Recorded from `{_branch()}` as `{walk.slug}.mp4`.", ""]
    if closes:
        lines += [f"Closes {closes}.", ""]
    return "\n".join(lines)


def _branch() -> str:
    """The current branch name, prefix and all.

    Split on ``refs/heads/`` rather than on the last slash: a branch called
    ``fix/provenance`` is not called ``provenance``.
    """
    head = os.path.join(REPO_ROOT, ".git", "HEAD")
    try:
        with open(head, encoding="utf-8") as fh:
            ref = fh.read().strip()
    except OSError:
        return "main"
    marker = "refs/heads/"
    return ref.split(marker, 1)[1] if marker in ref else ref


def _warm_up(browser, frontend: str) -> None:
    """Pay webpack-dev-server's first-compile cost off camera.

    The first request can spend fifteen seconds serving a blank document while
    the bundle compiles. In a recording that is fifteen seconds of white.
    """
    context = browser.new_context(viewport=VIDEO_SIZE)
    page = context.new_page()
    try:
        page.goto(f"{frontend}/auth/signin", timeout=120000)
        page.wait_for_load_state("domcontentloaded")
    except Exception:
        pass
    finally:
        context.close()


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
def test_record_walkthrough(walk: Walkthrough, app_frontend, current_server, browser):
    require_project_page()
    require_user_auth()
    os.makedirs(OUT_DIR, exist_ok=True)

    raw_dir = os.path.join(OUT_DIR, "raw")
    os.makedirs(raw_dir, exist_ok=True)
    _warm_up(browser, app_frontend.base_url)

    context = browser.new_context(
        viewport=VIDEO_SIZE,
        record_video_dir=raw_dir,
        record_video_size=VIDEO_SIZE,
    )
    page = context.new_page()
    # The drawers slide with translate3d and read prefers-reduced-motion through
    # useSyncExternalStore, so a panel is only reachable once the transition is
    # collapsed. The narration's own pacing supplies the sense of movement.
    page.emulate_media(reduced_motion="reduce")

    # No overlay. The recordings carried a title card, captions and a spotlight
    # cursor; they are the app's own UI competing with the app, and the report
    # written beside each video already says what the journey is. `Ctx` takes
    # any Narrator, and `SilentNarrator` implements the same calls with the
    # presentation removed - the interactions still happen, at the app's own
    # pace rather than a narrated one.
    narrator = SilentNarrator(page, beat_cap=None)
    failure: str | None = None
    try:
        stub_login_and_enter_workflow(
            page,
            frontend_url=app_frontend.base_url,
            backend_url=current_server,
            name="Walkthrough",
            username=f"walkvid_{walk.slug.replace(chr(45), chr(95))[:24]}",
            project_name=walk.title[:40],
            project_spec=load_example_spec(walk.example) if walk.example else None,
        )
        require_owner_view(page)
        # An empty dataflow has no nodes; only wait for one when the scene
        # asked for a spec that puts them there.
        if walk.example:
            page.wait_for_selector(".react-flow__node", timeout=45000)

        walk.run(Ctx(
            page=page,
            frontend=app_frontend.base_url,
            backend=current_server,
            narrator=narrator,
            recording=True,
        ))
        dismiss_toasts(page)
        page.wait_for_timeout(1200)
    except Exception:
        # Keep the take. A recording that ends early still shows where it broke,
        # and a still of the moment localises it faster than the locator message.
        failure = traceback.format_exc()
        try:
            narrator.hush()
            page.screenshot(path=os.path.join(OUT_DIR, f"failed-{walk.slug}.png"))
        except Exception:
            pass
    finally:
        page.close()
        # finalize_video writes to tour.out_dir(). Point that at our directory
        # for the call rather than inventing a second knob - CURIO_TOUR_OUT
        # already exists for exactly this.
        previous = os.environ.get("CURIO_TOUR_OUT")
        os.environ["CURIO_TOUR_OUT"] = OUT_DIR
        try:
            written = tour.finalize_video(page, stem=walk.stem)
        finally:
            if previous is None:
                os.environ.pop("CURIO_TOUR_OUT", None)
            else:
                os.environ["CURIO_TOUR_OUT"] = previous
        context.close()

    with open(os.path.join(OUT_DIR, f"{walk.stem}.md"), "w", encoding="utf-8") as fh:
        fh.write(_report(walk))

    print(f"[walkthrough] {walk.slug}: {written}")
    if failure:
        pytest.fail(f"walkthrough {walk.slug} broke:\n{failure}")
