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

import json
import os
import shutil
import subprocess
import sys
import time
from typing import Any

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
)

#: Where the finished recording lands. ``.curio/`` is gitignored, so a tour run
#: never leaves the repo dirty. Override with ``CURIO_TOUR_OUT``.
DEFAULT_OUT_DIR = os.path.join(REPO_ROOT, ".curio", "tour")

#: Recording geometry. 1280 wide matches the e2e suite's viewport, so the canvas
#: drop offsets the authoring scenes use (a node is 525x350 at zoom 1) still
#: hold. The height is 800 rather than 720 because the left tool rail does not
#: fit in 720: the built-in tile block plus the Node, Data and Agent Catalog
#: dropdowns push the "Run all nodes" button past the fold, where Playwright
#: cannot click it and a viewer cannot see it.
VIDEO_SIZE = {"width": 1280, "height": 800}


def out_dir() -> str:
    path = os.environ.get("CURIO_TOUR_OUT") or DEFAULT_OUT_DIR
    os.makedirs(path, exist_ok=True)
    return path


def _switch(name: str) -> bool:
    """An on-by-default environment switch: ``0``, ``false``, ``no`` or ``off`` turn it off."""
    return os.environ.get(name, "1").strip().lower() not in ("0", "false", "no", "off")


def caption_pos() -> str:
    """``CURIO_TOUR_CAPTION_POS=top`` moves the caption bar and the chapter chip
    under the top menu bar; anything else keeps them at the foot of the frame."""
    return "top" if os.environ.get("CURIO_TOUR_CAPTION_POS", "bottom").strip().lower() == "top" else "bottom"


def captions_on() -> bool:
    """Whether the overlay narrates: captions, chapter cards and the chapter chip.

    ``CURIO_TOUR_CAPTIONS=0`` records the same scenes with only the cursor, the
    click pulse and the spotlight ring, for clips that are shown next to their
    own text (the Curio guide at curio.urbantk.org, for one) and would otherwise
    say everything twice.
    """
    return _switch("CURIO_TOUR_CAPTIONS")


def ring_on() -> bool:
    """Whether the overlay rings what the cursor points at.

    ``CURIO_TOUR_RING=0`` keeps the cursor and the click pulse but drops the
    ring. In a clip shown on its own page, without the tour's captions, the ring
    reads as a box the app drew around whatever is clicked.
    """
    return _switch("CURIO_TOUR_RING")


def halo_on() -> bool:
    """Whether a click shows the pulse under the cursor (``CURIO_TOUR_HALO=0`` drops it)."""
    return _switch("CURIO_TOUR_HALO")


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
    // add_init_script runs at document-start, where document.body and even
    // document.documentElement can still be null. Appending then throws an
    // uncaught "Cannot read properties of null (reading 'appendChild')" on
    // every navigation. Nothing was lost - Tour._js() re-evaluates this on the
    // next call - but the recorder's own issue probe reported the noise as if
    // the app had raised it. Defer instead.
    if (!document.body && !document.documentElement) return 'deferred';

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
      /* A click: a yellow ring that grows from the cursor tip and fades, as screen
         recorders draw it. Two of them per click, the second a beat later. */
      @keyframes curio-tour-ripple {
        0%   { transform: translate(-50%, -50%) scale(.15); opacity: 1; }
        100% { transform: translate(-50%, -50%) scale(1);   opacity: 0; }
      }
      .curio-tour-ripple {
        position: absolute; width: 66px; height: 66px; border-radius: 50%;
        border: 4px solid #FFC72C; box-shadow: 0 0 0 1px rgba(17,19,24,.35), inset 0 0 0 1px rgba(17,19,24,.25);
        animation: curio-tour-ripple 760ms cubic-bezier(.2,.7,.3,1) forwards;
      }
      /* What is being dragged: a translucent copy of it, under the cursor. */
      .curio-tour-ghost {
        position: absolute; opacity: .85; margin: 0 !important;
        box-shadow: 0 12px 28px rgba(0,0,0,.28); border-radius: 8px;
        transform-origin: 0 0; transition: none;
      }
    `;

    // Caption bar: the running narration. Bottom-centre by default, clear of
    // the top menu bar and the left node rail; CURIO_TOUR_CAPTION_POS=top puts
    // it just under the menu bar instead, for scenes whose action is at the
    // foot of the frame (a chat composer, say).
    const captionTop = (window.__curioTourCaptionPos || 'bottom') === 'top';
    const caption = document.createElement('div');
    caption.className = 'curio-tour-fade';
    Object.assign(caption.style, {
        position: 'absolute', left: '50%', [captionTop ? 'top' : 'bottom']: captionTop ? '74px' : '26px',
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
        position: 'absolute', right: '18px', [captionTop ? 'top' : 'bottom']: captionTop ? '74px' : '26px', opacity: '0',
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
    // Where click ripples and the drag ghost are drawn, under the cursor.
    const clickHalo = document.createElement('div');
    Object.assign(clickHalo.style, { position: 'absolute', inset: '0' });
    let ghost = null, ghostOffset = [0, 0];

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
            cursor.style.transition = 'transform 460ms cubic-bezier(.22,.61,.36,1), opacity 300ms ease';
            cursor.style.transform = `translate(${x}px, ${y}px)`;
        },
        // A step of a drag: no easing of its own, the caller paces the steps.
        cursorStep(x, y) {
            cursor.style.opacity = '1';
            cursor.style.transition = 'opacity 300ms ease';
            cursor.style.transform = `translate(${x}px, ${y}px)`;
            if (ghost) ghost.style.transform = `translate(${x - ghostOffset[0]}px, ${y - ghostOffset[1]}px) scale(.96)`;
        },
        hideCursor() { cursor.style.opacity = '0'; },
        clickPulse(x, y) {
            for (const delay of [0, 220]) {
                const r = document.createElement('div');
                r.className = 'curio-tour-ripple';
                Object.assign(r.style, { left: x + 'px', top: y + 'px', animationDelay: delay + 'ms', opacity: delay ? '0' : '1' });
                clickHalo.appendChild(r);
                setTimeout(() => r.remove(), 1000 + delay);
            }
        },
        // Start dragging: copy the element under the press point; the copy then
        // follows the cursor (cursorStep) until dragEnd.
        dragStart(el, x, y) {
            api.dragEnd();
            if (!el) return;
            const rect = el.getBoundingClientRect();
            ghost = el.cloneNode(true);
            ghost.removeAttribute('id');
            ghost.classList.add('curio-tour-ghost');
            const cs = getComputedStyle(el);
            // The copy is shown outside its own panel, so it takes the colour it is
            // seen on: its own background, else the nearest ancestor's (a palette
            // tile is transparent, white on the dark rail).
            // A faint tint (an rgba with little alpha) counts as transparent too: the
            // agents palette row is white text on a 5 % white wash over the dark panel.
            const seeThrough = (c) => {
                if (!c || c === 'transparent') return true;
                const m = c.match(/rgba?\(([^)]+)\)/);
                const parts = m ? m[1].split(',').map(Number) : [];
                return parts.length === 4 && parts[3] < 0.5;
            };
            let bg = cs.backgroundColor, up = el;
            while (seeThrough(bg) && up.parentElement) {
                up = up.parentElement; bg = getComputedStyle(up).backgroundColor;
            }
            if (seeThrough(bg)) bg = '#ffffff';
            Object.assign(ghost.style, {
                left: '0px', top: '0px', width: rect.width + 'px', height: rect.height + 'px',
                background: bg, color: cs.color, font: cs.font,
                display: cs.display === 'inline' ? 'inline-block' : cs.display,
            });
            ghostOffset = [x - rect.x, y - rect.y];
            clickHalo.appendChild(ghost);
            api.cursorStep(x, y);
        },
        dragEnd() { if (ghost) { ghost.remove(); ghost = null; } },
        card(kicker, title, sub) {
            cardKicker.textContent = kicker || '';
            cardTitle.textContent = title || '';
            cardSub.textContent = sub || '';
            card.style.opacity = '1';
        },
        hideCard() { card.style.opacity = '0'; },
        clearAll() {
            api.hideCaption(); api.hideCard(); api.ring(null); api.hideCursor();
            api.chip(null); api.dragEnd();
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

    def __init__(
        self, page, *, pace: float | None = None, captions: bool | None = None,
        ring: bool | None = None, halo: bool | None = None,
    ) -> None:
        self.page = page
        self.pace = pace if pace is not None else speed()
        self.captions = captions if captions is not None else captions_on()
        self.ring = ring if ring is not None else ring_on()
        self.halo = halo if halo is not None else halo_on()
        self._chapter = ""
        # Seconds since the page was created, which is where Playwright starts
        # the recording, so a mark is also a position in the video.
        self._started = time.monotonic()
        self.marks: list[dict[str, Any]] = []
        page.add_init_script(f"window.__curioTourCaptionPos = {json.dumps(caption_pos())};")
        page.add_init_script(f"({_INSTALL_OVERLAY_JS})();")

    # -- plumbing ---------------------------------------------------------

    def _js(self, expression: str, arg: Any = None):
        """Run an overlay call, re-installing the overlay if it is gone."""
        self.page.evaluate(_INSTALL_OVERLAY_JS)
        return self.page.evaluate(expression, arg)

    def beat(self, ms: float = 700) -> None:
        self.page.wait_for_timeout(max(40, ms / self.pace))

    def mark(self, name: str, event: str) -> None:
        """Note where something starts or ends in the recording."""
        self.marks.append({
            "name": name, "event": event,
            "seconds": round(time.monotonic() - self._started, 2),
        })

    def write_marks(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(
                {"captions": self.captions, "ring": self.ring, "halo": self.halo, "marks": self.marks},
                handle, indent=2,
            )

    def still(self, name: str, *, cursor: bool = False) -> str:
        """Save this moment as ``<out>/stills/<name>.png`` and mark it.

        A screenshot rather than a frame of the video: the recording is VP8, and
        text in a frame pulled from it is visibly softer than on screen. The
        overlay is cleared first, so the still shows only the app, unless
        *cursor* keeps the pointer in it.
        """
        directory = os.path.join(out_dir(), "stills")
        os.makedirs(directory, exist_ok=True)
        if not cursor:
            self._js("() => window.__curioTour.clearAll()")
            # Let the overlay's own fades (300 to 420 ms) finish.
            self.page.wait_for_timeout(450)
        path = os.path.join(directory, f"{name}.png")
        self.page.screenshot(path=path)
        self.mark(name, "still")
        return path

    # -- narration --------------------------------------------------------

    def chapter(
        self, kicker: str, title: str, sub: str = "", hold: float | None = None,
    ) -> None:
        """Full-frame chapter break, then leave the chip showing."""
        self._chapter = title
        if not self.captions:
            self.beat(500)
            return
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
        if not self.captions:
            # Nothing to read, so only the pause that was asked for, if any.
            self.beat(hold or 600)
            return
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
        """Move the synthetic cursor onto *locator* and ring it (unless the ring is off)."""
        box = self._box(locator)
        if not box:
            return None
        cx = box["x"] + box["width"] / 2
        cy = box["y"] + box["height"] / 2
        self._js(
            "([x, y, r, box]) => { window.__curioTour.cursorTo(x, y);"
            " window.__curioTour.ring(r ? box : null); }",
            [cx, cy, ring and self.ring, box],
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
            self.pulse(point[0], point[1])
        if dispatch:
            locator.dispatch_event("click")
        else:
            locator.click(force=force)
        # Drop the ring immediately: a click usually removes what was clicked
        # (a menu row, a dialog button), and a highlight left behind on empty
        # canvas reads as a bug in the app rather than a flourish in the tour.
        self._js("() => window.__curioTour.ring(null)")
        self.beat(hold)

    # -- dragging ---------------------------------------------------------

    def pulse(self, x: float, y: float) -> None:
        """The click ripple at (x, y), when the halo is on."""
        if self.halo:
            self._js("([x, y]) => window.__curioTour.clickPulse(x, y)", [x, y])

    def pointer_move(self, x: float, y: float) -> None:
        """One step of a drag the mouse is really doing (``page.mouse``): the
        overlay's cursor (and ghost) follow it."""
        self._js("([x, y]) => window.__curioTour.cursorStep(x, y)", [x, y])

    def drag_motion(self, source, start, end, *, steps: int = 32, travel_ms: float = 1100) -> None:
        """Draw a drag from *start* to *end* the way a person makes one.

        The cursor goes to the press point on *source* (a locator), presses
        (ripple), a translucent copy of *source* lifts and follows the cursor
        along an eased path, and the release ripples at *end*. Drawing only: the
        caller delivers the drop itself (the e2e helpers' synthetic drop, which
        is what reliably reaches React's handlers). Nothing is drawn when the
        page has no tour overlay.
        """
        sx, sy = start
        ex, ey = end
        self.point_at(sx, sy, hold=480)
        self.pulse(sx, sy)
        self.beat(160)
        try:
            handle = source.element_handle()
        except Exception:  # noqa: BLE001 - a missing source just draws no ghost
            handle = None
        self.page.evaluate(_INSTALL_OVERLAY_JS)
        self.page.evaluate("([el, x, y]) => window.__curioTour.dragStart(el, x, y)", [handle, sx, sy])
        # A slight arc reads as a hand, a straight line as a robot.
        lift = min(60.0, abs(ex - sx) * 0.12 + 18)
        for i in range(1, steps + 1):
            t = i / steps
            e = t * t * (3 - 2 * t)  # smoothstep
            x = sx + (ex - sx) * e
            y = sy + (ey - sy) * e - lift * 4 * t * (1 - t)
            self.page.evaluate("([x, y]) => window.__curioTour.cursorStep(x, y)", [x, y])
            self.page.wait_for_timeout(max(8, travel_ms / steps / self.pace))
        self.beat(180)
        self.page.evaluate("() => window.__curioTour.dragEnd()")
        self.pulse(ex, ey)

    def type_code(self, node_id: str, code: str, *, chars_per_s: float = 45, max_s: float = 6.0) -> None:
        """Type *code* into a node's Monaco editor, a few characters at a time.

        Not keystrokes: the editor auto-closes brackets and formats on type, so
        typed Python never round-trips (see ``set_node_code``). The text is
        appended through ``executeEdits`` at the end of the model instead, with
        the caret moved after it, which draws exactly what typing would. When
        the editor already holds the start of *code*, only the rest is typed.
        The caller still sets the exact text afterwards.
        """
        js_editor = """(nodeId) => {
            const nodeEl = document.querySelector(`.react-flow__node[data-id="${nodeId}"]`);
            const editorEl = nodeEl && nodeEl.querySelector('.monaco-editor');
            const eds = (window.monaco && window.monaco.editor.getEditors && window.monaco.editor.getEditors()) || [];
            return eds.find((e) => editorEl && editorEl.contains(e.getDomNode())) || null;
        }"""
        current = self.page.evaluate(f"(id) => {{ const ed = ({js_editor})(id); return ed ? ed.getValue() : null; }}", node_id)
        if current is None:
            return
        editor_box = self.page.locator(f'.react-flow__node[data-id="{node_id}"] .monaco-editor').first.bounding_box()
        if editor_box:
            self.point_at(editor_box["x"] + 60, editor_box["y"] + 24, hold=380)
            self.pulse(editor_box["x"] + 60, editor_box["y"] + 24)
        keep = current if code.startswith(current) else ""
        rest = code[len(keep):]
        if not rest:
            return
        chunk = max(1, round(len(rest) / (chars_per_s * max_s))) if len(rest) > chars_per_s * max_s else 1
        step_ms = max(12, 1000 * chunk / chars_per_s / self.pace)
        self.page.evaluate(f"""([id, keep]) => {{ const ed = ({js_editor})(id); if (!ed) return;
            if (ed.getValue() !== keep) ed.setValue(keep); ed.focus(); }}""", [node_id, keep])
        append = f"""([id, text]) => {{ const ed = ({js_editor})(id); if (!ed) return;
            const m = ed.getModel(); const end = m.getFullModelRange().getEndPosition();
            const r = new window.monaco.Range(end.lineNumber, end.column, end.lineNumber, end.column);
            ed.executeEdits('curio-tour', [{{ range: r, text, forceMoveMarkers: true }}]);
            const after = m.getFullModelRange().getEndPosition();
            ed.setPosition(after); ed.revealPosition(after); }}"""
        for i in range(0, len(rest), chunk):
            self.page.evaluate(append, [node_id, rest[i:i + chunk]])
            self.page.wait_for_timeout(step_ms)
        self.beat(300)

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

    ``CURIO_TOUR_MP4=0`` turns the transcode off outright and keeps the webm
    Playwright already wrote. Stated as a switch rather than left to depend on
    whether ffmpeg happens to be installed, so "webm only" is a decision the
    caller makes and not an accident of the machine.
    """
    if os.environ.get("CURIO_TOUR_MP4", "1").strip().lower() in ("0", "false", "no", "off"):
        return None
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
            "[tour] writing webm only (CURIO_TOUR_MP4=0, or no system ffmpeg "
            "on PATH)",
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
