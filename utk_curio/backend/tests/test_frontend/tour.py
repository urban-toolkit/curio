"""Screencast toolkit for the Curio feature tour.

Not a test module (no ``test_`` prefix, so pytest does not collect it). It holds
the presentation layer used by ``test_feature_tour_video.py``: an on-page
caption/cursor/spotlight overlay, paced interaction helpers, and the video
plumbing that turns a Playwright recording into a deliverable file.

Why an overlay rather than post-production: Playwright records the page and
nothing else. A real mouse never appears in the frame, a click looks like a
thing that happened for no reason, and nothing labels what the viewer is
looking at. Everything the overlay draws is ``pointer-events: none`` and lives
above the app, so it narrates without changing what is being demonstrated.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Any

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
)

#: Where the finished recording lands. ``.curio/`` is gitignored, so a tour run
#: never leaves the repo dirty. Override with ``CURIO_TOUR_OUT``.
DEFAULT_OUT_DIR = os.path.join(REPO_ROOT, ".curio", "tour")

#: Recording geometry. Matches the e2e suite's viewport so the app lays out the
#: way its baselines expect, and is a clean 720p frame.
VIDEO_SIZE = {"width": 1280, "height": 720}


def out_dir() -> str:
    path = os.environ.get("CURIO_TOUR_OUT") or DEFAULT_OUT_DIR
    os.makedirs(path, exist_ok=True)
    return path


def speed() -> float:
    """Playback pacing multiplier: >1 is faster (shorter holds), <1 slower."""
    try:
        value = float(os.environ.get("CURIO_TOUR_SPEED", "1"))
    except ValueError:
        return 1.0
    return value if value > 0 else 1.0


# ---------------------------------------------------------------------------
# The overlay
# ---------------------------------------------------------------------------
#
# Installed by evaluating this function rather than only through
# add_init_script: the tour navigates between /auth, /projects and /dataflow,
# and each navigation throws the previous document (and the overlay with it)
# away. Making the installer idempotent lets every overlay call re-assert it
# cheaply instead of tracking which document is current.

_INSTALL_OVERLAY_JS = r"""() => {
    if (window.__curioTour && document.getElementById('curio-tour-root')) return 'ok';

    const root = document.createElement('div');
    root.id = 'curio-tour-root';
    Object.assign(root.style, {
        position: 'fixed', inset: '0', zIndex: '2147483647',
        pointerEvents: 'none', fontFamily:
            '"Inter","Segoe UI",system-ui,-apple-system,sans-serif',
    });

    const style = document.createElement('style');
    style.textContent = `
      #curio-tour-root * { box-sizing: border-box; pointer-events: none; }
      .curio-tour-fade { transition: opacity 420ms ease; }
      @keyframes curio-tour-pulse {
        0%   { box-shadow: 0 0 0 0 rgba(255,138,0,.55); }
        70%  { box-shadow: 0 0 0 14px rgba(255,138,0,0); }
        100% { box-shadow: 0 0 0 0 rgba(255,138,0,0); }
      }
    `;

    // Caption bar: the running narration, bottom-centre so it sits clear of
    // the top menu bar and the left node rail.
    const caption = document.createElement('div');
    caption.className = 'curio-tour-fade';
    Object.assign(caption.style, {
        position: 'absolute', left: '50%', bottom: '26px',
        transform: 'translateX(-50%)', maxWidth: '900px', opacity: '0',
        background: 'rgba(17,19,24,.92)', color: '#fff',
        border: '1px solid rgba(255,255,255,.12)', borderRadius: '12px',
        padding: '14px 20px', boxShadow: '0 12px 32px rgba(0,0,0,.35)',
        textAlign: 'center',
    });
    const captionTitle = document.createElement('div');
    Object.assign(captionTitle.style, {
        fontSize: '17px', fontWeight: '650', letterSpacing: '.2px',
        lineHeight: '1.35',
    });
    const captionSub = document.createElement('div');
    Object.assign(captionSub.style, {
        fontSize: '13.5px', color: 'rgba(255,255,255,.72)', marginTop: '5px',
        lineHeight: '1.45',
    });
    caption.append(captionTitle, captionSub);

    // Chapter chip: persistent "where am I in the tour" marker, top-right.
    const chip = document.createElement('div');
    chip.className = 'curio-tour-fade';
    Object.assign(chip.style, {
        position: 'absolute', right: '18px', bottom: '26px', opacity: '0',
        background: 'rgba(17,19,24,.82)', color: 'rgba(255,255,255,.85)',
        border: '1px solid rgba(255,255,255,.12)', borderRadius: '999px',
        padding: '6px 14px', fontSize: '12px', letterSpacing: '.4px',
        textTransform: 'uppercase', fontWeight: '600',
    });

    // Spotlight: a ring around whatever is being talked about.
    const ring = document.createElement('div');
    ring.className = 'curio-tour-fade';
    Object.assign(ring.style, {
        position: 'absolute', opacity: '0', borderRadius: '10px',
        border: '2px solid #ff8a00', background: 'rgba(255,138,0,.10)',
        transition: 'opacity 300ms ease, left 380ms ease, top 380ms ease, '
                  + 'width 380ms ease, height 380ms ease',
    });

    // Synthetic cursor. The real pointer is not in the recording, so clicks
    // would otherwise look unmotivated.
    const cursor = document.createElement('div');
    Object.assign(cursor.style, {
        position: 'absolute', left: '0', top: '0', width: '22px',
        height: '22px', marginLeft: '-3px', marginTop: '-3px', opacity: '0',
        transition: 'transform 460ms cubic-bezier(.22,.61,.36,1), opacity 300ms ease',
    });
    cursor.innerHTML = `
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
        <path d="M5 3l14 8.5-6.2 1.4L9.6 20 5 3z" fill="#111318"
              stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/>
      </svg>`;
    const clickHalo = document.createElement('div');
    Object.assign(clickHalo.style, {
        position: 'absolute', width: '34px', height: '34px', marginLeft: '-17px',
        marginTop: '-17px', borderRadius: '50%', opacity: '0',
        background: 'rgba(255,138,0,.35)', transition: 'transform 320ms ease, opacity 320ms ease',
    });

    // Title card: full-frame chapter break.
    const card = document.createElement('div');
    card.className = 'curio-tour-fade';
    Object.assign(card.style, {
        position: 'absolute', inset: '0', opacity: '0', display: 'flex',
        flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
        gap: '14px', background:
            'radial-gradient(120% 120% at 50% 40%, #1b1f2a 0%, #0c0e13 70%)',
        color: '#fff', textAlign: 'center', padding: '0 12%',
    });
    const cardKicker = document.createElement('div');
    Object.assign(cardKicker.style, {
        fontSize: '13px', letterSpacing: '3px', textTransform: 'uppercase',
        color: '#ff8a00', fontWeight: '700',
    });
    const cardTitle = document.createElement('div');
    Object.assign(cardTitle.style, {
        fontSize: '46px', fontWeight: '700', letterSpacing: '-.5px',
        lineHeight: '1.1',
    });
    const cardSub = document.createElement('div');
    Object.assign(cardSub.style, {
        fontSize: '18px', color: 'rgba(255,255,255,.7)', maxWidth: '760px',
        lineHeight: '1.5',
    });
    card.append(cardKicker, cardTitle, cardSub);

    root.append(style, ring, caption, chip, clickHalo, cursor, card);
    (document.body || document.documentElement).appendChild(root);

    const api = {
        caption(title, sub) {
            captionTitle.textContent = title || '';
            captionSub.textContent = sub || '';
            captionSub.style.display = sub ? 'block' : 'none';
            caption.style.opacity = '1';
        },
        hideCaption() { caption.style.opacity = '0'; },
        chip(text) {
            if (!text) { chip.style.opacity = '0'; return; }
            chip.textContent = text;
            chip.style.opacity = '1';
        },
        ring(rect) {
            if (!rect) { ring.style.opacity = '0'; return; }
            const pad = 6;
            ring.style.left = (rect.x - pad) + 'px';
            ring.style.top = (rect.y - pad) + 'px';
            ring.style.width = (rect.width + pad * 2) + 'px';
            ring.style.height = (rect.height + pad * 2) + 'px';
            ring.style.opacity = '1';
        },
        cursorTo(x, y) {
            cursor.style.opacity = '1';
            cursor.style.transform = `translate(${x}px, ${y}px)`;
            clickHalo.style.transform = `translate(${x}px, ${y}px) scale(.2)`;
        },
        hideCursor() { cursor.style.opacity = '0'; },
        clickPulse(x, y) {
            clickHalo.style.transition = 'none';
            clickHalo.style.transform = `translate(${x}px, ${y}px) scale(.2)`;
            clickHalo.style.opacity = '1';
            requestAnimationFrame(() => {
                clickHalo.style.transition = 'transform 340ms ease, opacity 340ms ease';
                clickHalo.style.transform = `translate(${x}px, ${y}px) scale(1)`;
                clickHalo.style.opacity = '0';
            });
        },
        card(kicker, title, sub) {
            cardKicker.textContent = kicker || '';
            cardTitle.textContent = title || '';
            cardSub.textContent = sub || '';
            card.style.opacity = '1';
        },
        hideCard() { card.style.opacity = '0'; },
        clearAll() {
            api.hideCaption(); api.hideCard(); api.ring(null); api.hideCursor();
            api.chip(null);
        },
    };
    window.__curioTour = api;
    return 'ok';
}"""


class Tour:
    """Paced, narrated driver for one recorded page.

    Every method that touches the app goes through here rather than through the
    raw locator, so the overlay stays in step with what the browser is doing:
    the cursor is where the click lands, the ring is around the thing being
    described, and there is a beat either side for the viewer to follow it.
    """

    def __init__(self, page, *, pace: float | None = None) -> None:
        self.page = page
        self.pace = pace if pace is not None else speed()
        self._chapter = ""
        page.add_init_script(f"({_INSTALL_OVERLAY_JS})();")

    # -- plumbing ---------------------------------------------------------

    def _js(self, expression: str, arg: Any = None):
        """Run an overlay call, re-installing the overlay if it is gone."""
        self.page.evaluate(_INSTALL_OVERLAY_JS)
        return self.page.evaluate(expression, arg)

    def beat(self, ms: float = 700) -> None:
        self.page.wait_for_timeout(max(40, ms / self.pace))

    # -- narration --------------------------------------------------------

    def chapter(
        self, kicker: str, title: str, sub: str = "", hold: float | None = None,
    ) -> None:
        """Full-frame chapter break, then leave the chip showing."""
        self._chapter = title
        words = len((f"{title} {sub}").split())
        self._js(
            "([k, t, s]) => { window.__curioTour.clearAll();"
            " window.__curioTour.card(k, t, s); }",
            [kicker, title, sub],
        )
        self.beat(max(2000 + words * 380, hold or 0))
        self._js("() => window.__curioTour.hideCard()")
        self.beat(700)
        self._js("(t) => window.__curioTour.chip(t)", title)

    def say(self, title: str, sub: str = "", hold: float | None = None) -> None:
        """Show a caption and hold it long enough to actually be read.

        The hold is derived from the text rather than passed in: a caption that
        is on screen for a fixed 2 s reads fine at four words and not at all at
        twenty. Callers can still pass *hold* to pin a beat (a one-word label
        under a spotlight, say), and it is treated as a floor, not a ceiling.
        """
        words = len((f"{title} {sub}").split())
        # ~2.6 words/second, which is a slow, comfortable read, plus a beat at
        # each end for the fade.
        reading = 1100 + words * 380
        self._js(
            "([t, s]) => window.__curioTour.caption(t, s)", [title, sub],
        )
        self.beat(max(reading, hold or 0))

    def hush(self) -> None:
        self._js("() => { window.__curioTour.hideCaption();"
                 " window.__curioTour.ring(null); }")

    # -- pointing ---------------------------------------------------------

    def _box(self, locator):
        try:
            locator.wait_for(state="visible", timeout=10000)
        except Exception:
            pass
        return locator.bounding_box()

    def focus(self, locator, *, hold: float = 900, ring: bool = True):
        """Move the synthetic cursor onto *locator* and ring it."""
        box = self._box(locator)
        if not box:
            return None
        cx = box["x"] + box["width"] / 2
        cy = box["y"] + box["height"] / 2
        self._js(
            "([x, y, r, box]) => { window.__curioTour.cursorTo(x, y);"
            " window.__curioTour.ring(r ? box : null); }",
            [cx, cy, ring, box],
        )
        self.beat(hold)
        return (cx, cy)

    def point_at(self, x: float, y: float, *, hold: float = 600) -> None:
        self._js("([x, y]) => window.__curioTour.cursorTo(x, y)", [x, y])
        self.beat(hold)

    def click(
        self,
        locator,
        *,
        force: bool = False,
        dispatch: bool = False,
        hold: float = 700,
        ring: bool = True,
    ) -> None:
        """Point at *locator*, pulse, then click it.

        ``dispatch`` sends a synthetic event instead of a real click, for the
        controls the e2e helpers already treat that way (SVG play buttons,
        header icons under the canvas chrome).
        """
        point = self.focus(locator, hold=380, ring=ring)
        if point:
            self._js(
                "([x, y]) => window.__curioTour.clickPulse(x, y)",
                [point[0], point[1]],
            )
        if dispatch:
            locator.dispatch_event("click")
        else:
            locator.click(force=force)
        # Drop the ring immediately: a click usually removes what was clicked
        # (a menu row, a dialog button), and a highlight left behind on empty
        # canvas reads as a bug in the app rather than a flourish in the tour.
        self._js("() => window.__curioTour.ring(null)")
        self.beat(hold)

    def type_into(self, locator, text: str, *, delay: float = 55) -> None:
        """Fill a field visibly, one key at a time."""
        self.focus(locator, hold=280)
        locator.click()
        locator.press_sequentially(text, delay=delay / self.pace)
        self.beat(320)

    def scroll(self, dy: float, *, steps: int = 6, hold: float = 90) -> None:
        """Wheel-scroll the page in visible increments."""
        for _ in range(steps):
            self.page.mouse.wheel(0, dy / steps)
            self.beat(hold)


# ---------------------------------------------------------------------------
# Video output
# ---------------------------------------------------------------------------


def _h264_ffmpeg() -> str | None:
    """An ffmpeg that can produce mp4, or ``None``.

    Only a system ffmpeg qualifies. Playwright ships its own build, but it is
    compiled down to what recording needs — vp8/webm, no libx264, no mp4 muxer —
    so pointing the transcode at it just fails with "Unrecognized option".
    """
    return shutil.which("ffmpeg")


def finalize_video(page, *, stem: str = "curio-feature-tour") -> dict[str, str]:
    """Save the page's recording under *stem* and transcode it to mp4.

    Must be called after ``page.close()`` — Playwright only flushes the webm
    when the page is gone. Returns the paths that were written; the mp4 entry is
    absent when no ffmpeg could be found, which is a downgrade rather than a
    failure since the webm plays on its own.
    """
    video = page.video
    if video is None:
        return {}
    destination = os.path.join(out_dir(), f"{stem}.webm")
    if os.path.exists(destination):
        os.remove(destination)
    video.save_as(destination)
    try:
        video.delete()
    except Exception:
        pass

    written = {"webm": destination}
    ffmpeg = _h264_ffmpeg()
    if not ffmpeg:
        print(
            "[tour] no system ffmpeg on PATH; leaving the recording as webm "
            "(install ffmpeg to also get an mp4)",
            file=sys.stderr,
        )
        return written

    mp4 = os.path.join(out_dir(), f"{stem}.mp4")
    # -vf pad: the webm can come out with an odd dimension, which yuv420p
    # (needed for QuickTime/PowerPoint playback) refuses.
    command = [
        ffmpeg, "-y", "-i", destination,
        "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
        "-c:v", "libx264", "-preset", "slow", "-crf", "22",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        mp4,
    ]
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=900,
    )
    if result.returncode != 0 or not os.path.exists(mp4):
        print(
            "[tour] ffmpeg transcode failed; the webm is still usable:\n"
            + (result.stderr or "")[-2000:],
            file=sys.stderr,
        )
        return written
    written["mp4"] = mp4
    return written
