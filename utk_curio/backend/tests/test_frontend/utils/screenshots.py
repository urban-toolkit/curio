"""Screenshot baselines: compare a capture with its baseline, mint and re-mint,
frame nodes for a capture, and the browser log kept beside the baselines.
"""

import os
import json
import traceback
from contextlib import contextmanager
from io import BytesIO
from typing import NamedTuple

import allure
import pytest
from playwright.sync_api import Page

from .. import comparisons
from .environment import REPO_ROOT
from .capture_waits import (
    WEBFONT_FAMILY,
    _wait_for_changes_kept,
    _wait_for_no_node_running,
    _wait_for_reactflow_ready,
    _wait_for_webfont,
    dismiss_toasts,
)
from .images import (
    _capture_element,
    _capture_full_page,
    _compare_images,
    _image_to_png_bytes,
)


# PNGs from workflow E2E tests: ``screenshot_{workflow_stem}_{test_name}.png``
WORKFLOW_SCREENSHOT_EXPECTED_DIR = os.path.join(
    REPO_ROOT, "docs", "examples", "dataflows", "expected_outputs"
)


def dump_browser_log(
    workflow_filepath: str,
    test_name: str,
    log_entries: list,
    autk_errors: dict | None = None,
    webgpu_diagnostics: dict | None = None,
) -> str:
    """Write captured browser console + pageerror events (and any AUTK error
    tab text we extracted from the DOM) to a plain text file alongside the
    expected screenshot, and attach it to the Allure report.

    Returns the path written.
    """
    stem = os.path.splitext(os.path.basename(workflow_filepath))[0]
    os.makedirs(WORKFLOW_SCREENSHOT_EXPECTED_DIR, exist_ok=True)
    log_path = os.path.join(
        WORKFLOW_SCREENSHOT_EXPECTED_DIR,
        f"screenshot_{stem}_{test_name}_browser_log.txt",
    )
    lines: list[str] = []
    lines.append(f"# Browser log for {stem} :: {test_name}")
    lines.append(f"# Captured {len(log_entries)} console/pageerror events")
    lines.append("")
    if webgpu_diagnostics is not None:
        lines.append("## WebGPU diagnostics (probed once per session)")
        lines.append(json.dumps(webgpu_diagnostics, indent=2, default=str))
        lines.append("")
    if autk_errors:
        lines.append("## AUTK error tab text (extracted from DOM)")
        for node_id, text in autk_errors.items():
            lines.append(f"--- node {node_id} ---")
            lines.append(text or "(empty)")
            lines.append("")
    lines.append("## Console / pageerror events (chronological)")
    for entry in log_entries:
        if entry.get("kind") == "pageerror":
            lines.append(f"[pageerror] {entry.get('message', '')}")
        else:
            loc = entry.get("location") or {}
            url = loc.get("url", "")
            line_no = loc.get("lineNumber", "")
            lines.append(
                f"[{entry.get('type', 'log')}] {entry.get('text', '')}"
                f"  ({url}:{line_no})"
            )
    payload = "\n".join(lines) + "\n"
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(payload)
    try:
        allure.attach(
            payload,
            name=f"screenshot_{stem}_{test_name}_browser_log.txt",
            attachment_type=allure.attachment_type.TEXT,
        )
    except Exception:
        pass
    return log_path


#: Whether a missing baseline may be created by this run. Off unless
#: ``--mint-baselines`` was passed (see ``tests/conftest.py``), so no ordinary
#: run - local or CI, serial or parallel - can mint one as a side effect.
#:
#: A module global rather than an environment variable on purpose: an env var
#: survives in a shell and gets inherited by the next run, which is exactly how
#: someone mints without meaning to. A CLI flag has to be typed each time and is
#: recorded in the command.
MINT_BASELINES = False

#: Whether this run re-mints: every capture is compared with its committed
#: baseline, and one whose screen changed is written over it (a missing one is
#: minted). Off unless ``--remint-baselines`` was passed. The CI report page
#: shows each re-minted frame next to the baseline it replaced.
REMINT_BASELINES = False

#: How to ask for baselines, in every message that needs one.
REMINT_HOW = (
    "To make baselines, run `gh workflow run docker-compose.yml --ref <branch> "
    "-f remint=true`, review the frames on that run's curio-ci-report.html, "
    "then commit its reminted-baselines artifact."
)

#: Where a CI run that writes no baselines keeps its candidates: the captures
#: a re-mint would write, one per frame that moved past REMINT_MIN_RATIO
#: outside the volatile text and held still on a second capture, or that has
#: no baseline yet, each under the name of the baseline it was compared with.
#: CI's e2e jobs set it on every run but a re-mint, and the ci-report job
#: uploads them as the candidate-baselines artifact.
CANDIDATE_DIR_ENV = "CURIO_E2E_CANDIDATE_DIR"


def candidate_dir(environ=os.environ) -> str | None:
    """Where this run keeps its candidates, or None when it keeps none.

    None on a mint or re-mint run, which writes baselines instead, and on any
    run without CANDIDATE_DIR_ENV (a local run, the unit suites).
    """
    if MINT_BASELINES or REMINT_BASELINES:
        return None
    return environ.get(CANDIDATE_DIR_ENV) or None


#: The frame failures of the running test, told at its end: a list while
#: frame_failures_at_the_end holds them, None otherwise.
_held: list | None = None

#: What ends a test the same way whether or not one of its frames failed.
_PASS_THROUGH = (KeyboardInterrupt, SystemExit, pytest.exit.Exception)

_UTILS_DIR = os.path.dirname(os.path.abspath(__file__))


@contextmanager
def frame_failures_at_the_end():
    """Hold the block's frame failures, and fail at its end naming them all.

    test_frontend's conftest wraps each test's call in it. On a run that keeps
    candidates (candidate_dir), a frame over its budget or without a baseline
    is noted where it is taken and the test goes on, so every later frame is
    captured too. At the end the test fails with an AssertionError that starts
    with the first frame's own message and names every other one. When the
    test raised after such a frame, or skipped, that failure takes the place of
    what it raised, which it names, so a test that failed at a frame fails
    still. Without a held frame the test ends as it would have.

    Off, or inside another hold, it holds nothing and a frame failure raises
    where it is taken, as on every run that keeps no candidates.
    """
    global _held
    if _held is not None or not candidate_dir():
        yield
        return
    held = _held = []
    try:
        yield
    except _PASS_THROUGH:
        raise
    except BaseException as exc:  # noqa: BLE001 - a skip or an xfail too
        if held:
            raise AssertionError(_told(held, then=exc)) from exc
        raise
    finally:
        _held = None
    if held:
        raise AssertionError(_told(held))


def _frame_failed(message: str) -> None:
    """A frame failed: raise *message*, or hold it for the test's end."""
    if _held is None:
        raise AssertionError(message)
    _held.append((message, _where()))


def _where() -> str:
    """The file and line that asked for the frame: the innermost caller
    outside these helpers."""
    for frame in reversed(traceback.extract_stack()[:-1]):
        if os.path.dirname(os.path.abspath(frame.filename)) != _UTILS_DIR:
            return f"{os.path.basename(frame.filename)}:{frame.lineno}"
    return ""


def _told(held, then=None) -> str:
    """The failure of a test whose frames *held* failed, then *then*, if it raised."""
    (first, where), rest = held[0], held[1:]
    lines = [first]
    if where:
        lines.append(f"  frame taken at {where}")
    lines.append("The test went on to its end, so its later frames were captured too.")
    if rest:
        lines.append(f"{len(rest)} more frame{'s' if len(rest) > 1 else ''} of this test failed:")
        lines += [f"- {message}" + (f" (taken at {at})" if at else "") for message, at in rest]
    if then is not None:
        said = str(then).strip().splitlines()
        lines.append(f"Then the test raised {type(then).__name__}"
                     + (f": {said[0]}" if said else ""))
    return "\n".join(lines)


#: Baselines a re-mint rewrites whatever it finds, named by a part of their
#: file names (``--remint-force``): the frames a fix is known to change by
#: less than REMINT_MIN_RATIO, such as a few words of text.
REMINT_FORCE: tuple = ()


#: The GPU models CI's test-gpu job draws on: the arcade runners
#: (arcade-gpu-01..04) share an H100, utk-gpu has an RTX PRO 6000, and the
#: desktops utk-desktop-01 an RTX 3070 and utk-desktop-03 an RTX 4080 (kind
#: utk-desktop). A frame they draw differently (example 07's plot
#: close-up) keeps a baseline per GPU kind, ``<name>.<kind>.png``, beside its
#: default one.
GPU_KINDS = ("arcade-gpu", "utk-gpu", "utk-desktop")

#: Names the run's GPU kind, one of GPU_KINDS. CI's test-gpu job sets it from
#: its runner's name. A run without it (a local run, a CPU runner) compares
#: every frame with its default baseline.
GPU_KIND_ENV = "CURIO_E2E_GPU_KIND"

#: The ``gpu_pool`` dispatch input that sends test-gpu to each GPU kind.
_GPU_POOL = {"arcade-gpu": "arcade", "utk-gpu": "utk", "utk-desktop": "desktop"}

#: Frames a re-mint writes as baselines of the run's GPU kind, named by parts
#: of their baseline names (``--remint-gpu-kind <kind>:<part>,...``). Such a
#: run writes no other frame: it only compares them.
REMINT_GPU_KIND_FRAMES: tuple = ()


def run_gpu_kind(environ=os.environ) -> str:
    """This run's GPU kind, or "" for a run that has none."""
    kind = (environ.get(GPU_KIND_ENV) or "").strip()
    if kind and kind not in GPU_KINDS:
        raise ValueError(
            f"{GPU_KIND_ENV}={kind!r} is not a GPU kind; the kinds are {', '.join(GPU_KINDS)}")
    return kind


def kind_baseline(path: str, kind: str) -> str:
    """Where the baseline of GPU kind *kind* sits beside the default baseline *path*.

    ``screenshot_x_y.png`` has ``screenshot_x_y.utk-gpu.png``. Built from the
    default name and never parsed back out of a file name: baseline names hold
    dots of their own.
    """
    stem, ext = os.path.splitext(path)
    return f"{stem}.{kind}{ext}"


def baseline_in_use(path: str, kind: str) -> str:
    """The baseline a run of GPU kind *kind* compares a frame with.

    The kind's own baseline when the frame has one, otherwise the default
    baseline *path*, which is also what every run without a kind uses.
    """
    if kind:
        own = kind_baseline(path, kind)
        if os.path.isfile(own):
            return own
    return path


def _kind_frames(value: str) -> tuple:
    """``--remint-gpu-kind``'s ``<kind>:<name part>,...`` as (kind, parts)."""
    value = (value or "").strip()
    if not value:
        return "", ()
    kind, colon, parts = value.partition(":")
    kind = kind.strip()
    frames = tuple(part.strip() for part in parts.split(",") if part.strip())
    if not colon or kind not in GPU_KINDS or not frames:
        raise pytest.UsageError(
            f"--remint-gpu-kind takes <kind>:<baseline name part>,... with a kind of "
            f"{', '.join(GPU_KINDS)}, not {value!r}.")
    return kind, frames


def allow_baseline_writes(*, mint: bool, remint: bool, force=(), gpu_kind: str = "",
                          environ=os.environ) -> None:
    """Turn on ``--mint-baselines`` / ``--remint-baselines``, on CI only.

    A baseline is what CI renders. A capture from any other machine differs in
    text antialiasing, fonts and scrollbars, and would then fail on CI or hide
    a change there.

    *gpu_kind* is ``--remint-gpu-kind``'s ``<kind>:<name part>,...``: frames
    to write as baselines of that GPU kind, which only a job on a GPU of that
    kind draws.
    """
    global MINT_BASELINES, REMINT_BASELINES, REMINT_FORCE, REMINT_GPU_KIND_FRAMES
    force = tuple(part for part in force if part)
    if force and not remint:
        raise pytest.UsageError("--remint-force only means something with --remint-baselines.")
    kind, frames = _kind_frames(gpu_kind)
    if frames and not remint:
        raise pytest.UsageError("--remint-gpu-kind only means something with --remint-baselines.")
    if not (mint or remint):
        return
    if environ.get("GITHUB_ACTIONS") != "true":
        flag = "--remint-baselines" if remint else "--mint-baselines"
        raise pytest.UsageError(f"{flag} runs on CI only. {REMINT_HOW}")
    if frames:
        try:
            run_kind = run_gpu_kind(environ)
        except ValueError as exc:
            raise pytest.UsageError(str(exc)) from exc
        if run_kind != kind:
            raise pytest.UsageError(
                f"--remint-gpu-kind writes {kind} baselines, which only a job on {kind} "
                f"draws, and this job runs on {run_kind or 'no GPU kind'}. Dispatch the "
                f"re-mint with gpu_pool={_GPU_POOL[kind]}.")
    MINT_BASELINES = bool(mint)
    REMINT_BASELINES = bool(remint)
    REMINT_FORCE = force
    REMINT_GPU_KIND_FRAMES = frames


#: A re-mint leaves a baseline alone when at most this share of its pixels
#: changed, not counting the volatile text below. A fix usually changes far
#: more; one that changes a few words may not, and names its frames with
#: ``--remint-force`` instead. Layout that moves between runs (an id wrapping
#: at another character, a node settling a pixel away) can pass it, so a few
#: frames are re-minted by every run.
REMINT_MIN_RATIO = 0.0005

#: Text a run writes fresh every time, so it differs from any baseline even
#: when the screen is the same: artifact file names (epoch milliseconds and a
#: random suffix), uuids, bare uuid hex and the 8-character short ids, a
#: package id's random segment, dates and times of day, and the app version in
#: the corner, which moves with every commit to main. A re-mint does not count
#: differences inside it, or in the rest of its line, which a token of another
#: width moves; ordinary comparisons still count everything.
VOLATILE_TEXT = (
    r"\b\d{13}_[0-9a-f]{8}\b",
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    r"\b[0-9a-f]{32}\b",
    r"\b(?=[0-9a-f]{0,7}\d)(?=[0-9a-f]{0,7}[a-f])[0-9a-f]{8}\b",
    r"(?<=\.)(?=[a-z0-9]*\d)(?=[a-z0-9]*[a-z])[a-z0-9]{8,10}(?=@\d)",
    r"\b\d{1,2}/\d{1,2}/\d{4}\b",
    r"\b\d{1,2}:\d{2}(?::\d{2})?\s?[AP]M\b",
    r"^\s*\d+\.\d+\.\d+[\w.+-]*\s*$",
)

# The client boxes of every VOLATILE_TEXT match through the end of its line
# (or of its text node, when that is wrapped rather than broken), relative to
# *root* (the captured element) or to the top-left of the page.
_VOLATILE_BOXES_BODY = """
    const origin = root ? root.getBoundingClientRect() : {left: 0, top: 0};
    const res = patterns.map((p) => new RegExp(p, 'g'));
    const boxes = [];
    const walker = document.createTreeWalker(root || document.body, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        const text = node.nodeValue || '';
        if (!text.trim()) continue;
        for (const re of res) {
            re.lastIndex = 0;
            for (let m = re.exec(text); m; m = re.exec(text)) {
                if (!m[0]) { re.lastIndex += 1; continue; }
                const range = document.createRange();
                const lineEnd = text.indexOf('\\n', m.index + m[0].length);
                range.setStart(node, m.index);
                range.setEnd(node, lineEnd === -1 ? text.length : lineEnd);
                for (const r of range.getClientRects()) {
                    if (r.width > 0 && r.height > 0) {
                        boxes.push([r.left - origin.left, r.top - origin.top,
                                    r.right - origin.left, r.bottom - origin.top]);
                    }
                }
            }
        }
    }
    return {boxes, scale: window.devicePixelRatio || 1};
"""
_VOLATILE_BOXES_PAGE_JS = (
    "(patterns) => { window.scrollTo(0, 0); const root = null;" + _VOLATILE_BOXES_BODY + "}"
)
_VOLATILE_BOXES_ELEMENT_JS = "(root, patterns) => {" + _VOLATILE_BOXES_BODY + "}"


def _volatile_boxes(page, clip: str | dict | None) -> list:
    """Pixel boxes of the volatile text in what is about to be captured: the
    page (*clip* None), an element (a selector) or a box of the page
    (``{x, y, width, height}``).

    Never raises: with no boxes a re-mint just counts every difference.
    """
    try:
        if clip is None or isinstance(clip, dict):
            found = page.evaluate(_VOLATILE_BOXES_PAGE_JS, list(VOLATILE_TEXT))
        else:
            # A missing element is the capture's failure to report, not this one's.
            found = page.locator(clip).first.evaluate(
                _VOLATILE_BOXES_ELEMENT_JS, list(VOLATILE_TEXT), timeout=5000)
        scale = float(found.get("scale") or 1)
        # In a box of the page, from the box's top-left corner.
        left, top = (clip["x"], clip["y"]) if isinstance(clip, dict) else (0, 0)
        return [
            ((x0 - left) * scale, (y0 - top) * scale, (x1 - left) * scale, (y1 - top) * scale)
            for x0, y0, x1, y1 in found.get("boxes") or []
        ]
    except Exception:  # noqa: BLE001 - best effort, like the webfont wait
        return []


def _box_mask(boxes, shape):
    """A boolean image of *shape* that is true inside *boxes*, one pixel padded."""
    import math

    import numpy as np

    mask = np.zeros(shape, dtype=bool)
    height, width = shape
    for x0, y0, x1, y1 in boxes:
        left, top = max(0, int(x0) - 1), max(0, int(y0) - 1)
        right, bottom = min(width, math.ceil(x1) + 1), min(height, math.ceil(y1) + 1)
        if right > left and bottom > top:
            mask[top:bottom, left:right] = True
    return mask


def _assert_mintable(image, expected_path: str, page) -> None:
    """Refuse to write a baseline that is obviously not what we came for.

    Two ways a mint goes wrong silently, both of which pass the comparison that
    immediately follows because it compares the capture against itself:

    * the webfont did not load, so the text is in a fallback typeface;
    * the capture is blank - a renderer starved of memory, or an element that
      was 'visible' but not yet painted, yields a single flat colour.

    A wrong baseline is worse than no baseline: it enshrines the defect as
    expected output, which is the whole complaint behind #308 and #333.
    """
    if not _wait_for_webfont(page):
        raise AssertionError(
            f"refusing to mint {os.path.basename(expected_path)}: the "
            f"{WEBFONT_FAMILY} webfont did not load, so this capture is in a "
            f"fallback typeface and would disagree with every later run. Check "
            f"network access to fonts.googleapis.com and re-run."
        )
    if len(image.convert("RGB").getcolors(maxcolors=2) or []) == 1:
        raise AssertionError(
            f"refusing to mint {os.path.basename(expected_path)}: the capture "
            f"is a single flat colour, i.e. blank. The element was reported "
            f"visible but nothing was painted."
        )


#: The most any screenshot comparison may let differ. Two CI captures of the
#: same screen differ by at most about 1.3%, so this leaves room for run-to-run
#: noise and none for a screen that changed. A comparison may ask for less,
#: never more.
MAX_DIFF_RATIO = 0.10


class _Judgment(NamedTuple):
    """What the re-mint rule makes of a capture.

    *verdict* is one of:

    * ``unchanged``: it moved by REMINT_MIN_RATIO or less outside the volatile
      text, and was not forced;
    * ``refused``: _assert_mintable refused it, with *error*;
    * ``recapture-failed``: the second capture raised *error*;
    * ``unsettled``: the second capture, *again*, differs from the first past
      the budget (*settle*), so the screen had not settled;
    * ``moved``: it would become the baseline (*settle* is the second capture
      against it).

    *evidence* is what a record of the comparison shows.
    """
    verdict: str
    evidence: dict
    error: BaseException | None = None
    again: object = None
    settle: object = None


def _judge(page, capture, new_img, *, baseline=None, cmp=None, boxes=(),
           pixel_threshold, max_diff_ratio, name, forced=False,
           before_recapture=None) -> _Judgment:
    """Judge *new_img* as a re-mint does, for both a re-mint and a candidate.

    *baseline* is the committed image *cmp* compared *new_img* with, and
    *boxes* the volatile text's (_volatile_boxes), which the move is measured
    without. With no *baseline* there is nothing to measure against, as for a
    frame that has none yet: only the mint checks and the second capture judge
    it. *name* is the baseline the capture would become, for _assert_mintable's
    message. *before_recapture* runs once the capture passed those checks,
    right before the second capture: a re-mint writes the baseline there.

    Captures again only a capture that moved, and never raises for the
    verdict: each caller decides what a verdict does to its test.
    """
    if baseline is None:
        evidence = dict(created=new_img)
    else:
        volatile = _box_mask(boxes, cmp.counted.shape) if new_img.size == baseline.size else None
        changed = cmp.counted & ~volatile if volatile is not None else cmp.counted
        remint_ratio = int(changed.sum()) / cmp.total if cmp.total else 0.0
        evidence = dict(
            expected=baseline, created=new_img, expected_cmp=cmp.expected_cmp,
            arr=cmp.arr, counted=cmp.counted, volatile=volatile,
            mismatched=cmp.mismatched, total=cmp.total, ratio=cmp.ratio,
            remint_ratio=remint_ratio, remint_min_ratio=REMINT_MIN_RATIO,
            forced=forced,
        )
        if remint_ratio <= REMINT_MIN_RATIO and not forced:
            return _Judgment("unchanged", evidence)
    try:
        _assert_mintable(new_img, name, page)
    except AssertionError as exc:
        return _Judgment("refused", evidence, error=exc)
    if before_recapture is not None:
        before_recapture()
    try:
        again = capture()
    except Exception as exc:  # noqa: BLE001 - the caller reports it
        return _Judgment("recapture-failed", evidence, error=exc)
    settle = _compare_images(again, new_img, pixel_threshold)
    if settle.ratio > max_diff_ratio:
        return _Judgment("unsettled", evidence, again=again, settle=settle)
    return _Judgment("moved", evidence, settle=settle)


def _remint(page, expected_path, capture, *, clip_selector, pixel_threshold,
            max_diff_ratio, record_args, forced=False, target=None, kind="",
            clip_rect=None) -> str:
    """Write a fresh capture over its baseline when the screen changed.

    Changed means more than REMINT_MIN_RATIO of the pixels differ outside the
    volatile text, or the frame is *forced* (REMINT_FORCE names it), as
    :func:`_judge` decides for re-mints and candidates alike. Otherwise the
    baseline stays as committed and the record says ``unchanged``. A re-minted frame is recorded next to the baseline it
    replaced, for the CI report page, and captured a second time: when that
    capture differs from the first by more than the budget the screen had not
    settled, so the old baseline is put back and the test fails.

    The capture goes to *target*: *expected_path*, the baseline it was compared
    with, unless ``--remint-gpu-kind`` names the frame and it has no baseline of
    the run's GPU kind *kind* yet. Then it becomes that kind's baseline, and
    the record shows it against the default baseline. Returns the baseline as
    this run leaves it.

    The old-versus-new difference never fails the test: showing what changed is
    what a re-mint is for.
    """
    from PIL import Image

    target = target or expected_path
    name = os.path.basename(target)
    with open(expected_path, "rb") as handle:
        old_bytes = handle.read()

    def put_back():
        if target == expected_path:
            with open(expected_path, "wb") as handle:
                handle.write(old_bytes)
        else:
            os.remove(target)  # a new baseline of a GPU kind: there was none

    old_img = Image.open(BytesIO(old_bytes)).convert("RGB")
    boxes = _volatile_boxes(page, clip_selector if clip_selector is not None else clip_rect)
    try:
        new_img = capture()
    except Exception as exc:
        comparisons.record(
            "capture-error", expected=old_img,
            error=f"{type(exc).__name__}: {exc}", **record_args,
        )
        raise

    cmp = _compare_images(new_img, old_img, pixel_threshold)
    judged = _judge(
        page, capture, new_img, baseline=old_img, cmp=cmp, boxes=boxes,
        pixel_threshold=pixel_threshold, max_diff_ratio=max_diff_ratio,
        name=target, forced=forced, before_recapture=lambda: new_img.save(target),
    )
    evidence = judged.evidence
    if judged.verdict == "unchanged":
        comparisons.record("unchanged", **evidence, **record_args)
        return expected_path

    if judged.verdict == "refused":
        comparisons.record("capture-error", error=str(judged.error), **evidence, **record_args)
        raise judged.error
    if judged.verdict == "recapture-failed":
        exc = judged.error
        put_back()
        comparisons.record(
            "capture-error", expected=old_img, created=new_img,
            error=f"second capture failed, baseline left as committed: "
                  f"{type(exc).__name__}: {exc}", **record_args,
        )
        raise exc
    settle, again = judged.settle, judged.again
    if judged.verdict == "unsettled":
        put_back()
        comparisons.record(
            "failed", expected=new_img, created=again,
            expected_cmp=settle.expected_cmp, arr=settle.arr,
            counted=settle.counted, mismatched=settle.mismatched,
            total=settle.total, ratio=settle.ratio,
            error="the screen was still changing: a second capture right "
                  "after the re-mint differs from it, so the baseline was left "
                  "as committed", **record_args,
        )
        raise AssertionError(
            f"not re-minting {name}: a second capture right after differs from "
            f"the first by {settle.ratio:.2%}, over the {max_diff_ratio:.2%} "
            "budget, so the screen had not settled. The baseline is left as "
            "committed."
        )
    written = dict(record_args)
    if target != expected_path:
        written.update(baseline=target, gpu_kind=kind,
                       compared_with=os.path.basename(expected_path))
    comparisons.record(
        "reminted", expected_bytes=old_bytes, recapture_ratio=settle.ratio,
        **evidence, **written,
    )
    return target


def _keep_candidate(directory: str, baseline: str, image) -> str:
    """Write *image* to *directory* under *baseline*'s file name, the PNG a
    re-mint would write over it. Returns the reason it could not, or ""."""
    try:
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, os.path.basename(baseline))
        tmp = path + ".tmp"
        image.save(tmp, format="PNG")
        os.replace(tmp, path)
        return ""
    except Exception as exc:  # noqa: BLE001 - best effort, like the records
        return f"it could not be written: {type(exc).__name__}: {exc}"


def _as_candidate(judged: _Judgment, directory: str, baseline: str, max_diff_ratio: float) -> dict:
    """What a record adds for *judged*, and the candidate kept when it moved.

    A capture that would not become a baseline is no candidate, and the record
    says why; on this run that never fails the test.
    """
    verdict, error, settle = judged.verdict, judged.error, judged.settle
    if verdict == "unchanged":
        return {}
    if verdict == "refused":
        return {"not_candidate": str(error)}
    if verdict == "recapture-failed":
        return {"not_candidate": f"a second capture failed: {type(error).__name__}: {error}"}
    fields = {"recapture_ratio": settle.ratio}
    if verdict == "unsettled":
        fields["not_candidate"] = (
            f"the screen was still changing: a second capture right after differs "
            f"from it by {settle.ratio:.2%}, over the {max_diff_ratio:.2%} budget")
        return fields
    unwritten = _keep_candidate(directory, baseline, judged.evidence["created"])
    if unwritten:
        fields["not_candidate"] = unwritten
    else:
        fields["candidate"] = True
    return fields


#: Added to a failed frame's message when its capture was kept as a candidate.
_CANDIDATE_KEPT = (
    " This run kept its capture as a candidate: review it on the run's "
    "curio-ci-report.html, then commit it from the candidate-baselines artifact."
)


def save_workflow_test_screenshot(
    page: Page,
    workflow_filepath: str,
    *,
    test_name: str,
    pixel_threshold: int = 30,
    max_diff_ratio: float = MAX_DIFF_RATIO,
    fit_reactflow: bool = True,
    clip_selector: str | None = None,
    clip_rect: dict | None = None,
    keep_tooltip: bool = False,
    sweep_toasts: bool = False,
    allow_running: bool = False,
    closeup: bool = False,
    interaction: dict | None = None,
) -> str:
    """Compare or create an expected screenshot for a workflow test.

    If the expected file already exists the current page is captured and
    compared pixel-by-pixel against it.  Both images are resized to the
    same dimensions before comparison so layout-only size changes don't
    cause false positives.  The assertion fails when more than
    *max_diff_ratio* (default 10%) of pixels differ by more than
    *pixel_threshold* (per-channel, 0-255).

    On failure the expected, actual, and diff images are attached to the
    Allure report so that reviewers can inspect the regression directly
    from the GitHub Actions artifact. With ``CURIO_E2E_COMPARE_DIR`` set,
    every comparison, passing or not, is also recorded there for the CI
    report page (see comparisons.py).

    If the file does **not** exist the run FAILS. Creating a baseline is a
    deliberate act, a CI run dispatched with ``remint=true`` (``--mint-baselines``
    and ``--remint-baselines`` refuse to run anywhere else), because whatever
    the app renders that day becomes the definition of correct for every run
    afterwards. Under ``--remint-baselines`` an existing baseline is compared
    and, when its screen changed, rewritten (see :func:`_remint`).

    A baseline captured against a broken build enshrines the bug as expected
    output, and the suite then *defends* it; one captured on another machine
    enshrines that machine. macOS rasterizes text with grayscale antialiasing
    and the runner uses LCD subpixel, so the macOS captures of the two #333
    scenes sat 6.11% and 10.05% from what CI renders, the second past its
    budget.

    Set *fit_reactflow* to ``False`` for pages with no canvas (the projects list,
    the catalog). The default path pins the ReactFlow viewport first, which waits
    on ``.react-flow__node`` and would otherwise spend its whole timeout waiting
    for a node that is never going to exist.

    Pass *clip_selector* when the subject of the baseline is one element rather
    than the page. The capture is then that element's box, so every pixel is
    about the thing under test and the diff budget is spent on it instead of on
    surrounding chrome. Pass *clip_rect* instead, a box of the page as
    ``{x, y, width, height}`` in CSS pixels, when no one element holds the
    subject: a tooltip and the control it names.

    An open Curio tooltip is hidden while the capture is taken: the pointer a
    test leaves resting on a control would otherwise put its tooltip in the
    frame. Pass *keep_tooltip* when the tooltip is the subject.

    Pass *sweep_toasts* instead of calling :func:`dismiss_toasts` yourself
    beforehand - and never as well as, each sweep costs its own quiet window.
    Sweeping outside this helper leaves a gap between the region going quiet and
    the shutter: the viewport wait below is seconds on a loaded runner, and an
    error toast now stays until it is dismissed, so anything arriving in that gap
    is in the baseline for good. `run-all-survives-a-failed-node` collected five
    of them that way on CI - 26.87% of a frame whose budget is 5% - while the two
    earlier captures of the same walkthrough, taken before the run that raised
    them, passed.

    The capture waits until no node on the canvas is running, so a view that
    draws on its own after its input arrives is photographed drawn, not
    mid-draw. Pass *allow_running* only when a run in progress is the subject.

    *closeup* only labels the record, for the CI report's Close-ups filter, and
    *interaction* (see :func:`save_interaction_frame`) for its Interaction pairs.

    On a run of a GPU kind (``CURIO_E2E_GPU_KIND``, see GPU_KINDS) a frame
    with a baseline of that kind, ``<name>.<kind>.png``, is compared with it,
    and a re-mint writes that file, never the default baseline.

    On a CI run that keeps candidates (:func:`candidate_dir`), a capture that
    moved past REMINT_MIN_RATIO gets the re-mint's judgment (:func:`_judge`),
    and one a re-mint would write is kept as a candidate, as is a settled
    capture of a frame without a baseline. A frame over its budget or without
    a baseline fails its test at the test's end there, inside
    :func:`frame_failures_at_the_end`, so the test's later frames are captured
    too. Only frames that moved pay for the judgment.

    Returns the path to the expected screenshot file.
    """
    if not 0.0 <= max_diff_ratio <= MAX_DIFF_RATIO:
        raise ValueError(
            f"max_diff_ratio={max_diff_ratio} is above the {MAX_DIFF_RATIO:.0%} "
            "ceiling (MAX_DIFF_RATIO): a comparison may be tighter, never looser"
        )
    if clip_selector is not None and clip_rect is not None:
        raise ValueError("pass clip_selector or clip_rect, not both: a capture has one subject")
    from PIL import Image, ImageEnhance

    stem = os.path.splitext(os.path.basename(workflow_filepath))[0]
    os.makedirs(WORKFLOW_SCREENSHOT_EXPECTED_DIR, exist_ok=True)
    filename = f"screenshot_{stem}_{test_name}.png"
    default_path = os.path.join(WORKFLOW_SCREENSHOT_EXPECTED_DIR, filename)
    kind = run_gpu_kind()
    expected_path = baseline_in_use(default_path, kind)
    # A remint_force or remint_gpu_kind part names a frame by either baseline.
    names = (filename, os.path.basename(expected_path))
    for_kind = bool(kind) and any(p in n for p in REMINT_GPU_KIND_FRAMES for n in names)
    # A run that writes baselines of its GPU kind writes nothing else.
    remint = REMINT_BASELINES and (for_kind or not REMINT_GPU_KIND_FRAMES)

    if not allow_running:
        _wait_for_no_node_running(page)

    # Pin the ReactFlow viewport to a deterministic fitView before any
    # capture, so baselines and subsequent comparisons share the same
    # zoom/pan regardless of when the in-app setTimeout(fitView) fires.
    if fit_reactflow:
        _wait_for_reactflow_ready(page)

    # After the viewport wait, not before it: this is the last moment the page
    # can be quieted, so it is the only sweep that holds until the capture.
    if sweep_toasts:
        dismiss_toasts(page)

    # The top bar reads Saved once the server holds the tab's last change, and
    # Saving... while an answer is slow: the same frame either way.
    _wait_for_changes_kept(page)
    _wait_for_webfont(page)

    # Options only when asked for: a plain capture is the call it always was.
    options = {"keep_tooltip": True} if keep_tooltip else {}

    def _capture():
        if clip_selector is not None:
            return _capture_element(page, clip_selector, **options)
        if clip_rect is not None:
            return _capture_full_page(page, clip=clip_rect, **options)
        return _capture_full_page(page, **options)

    if clip_selector is not None:
        capture = f"element {clip_selector}"
    elif clip_rect is not None:
        capture = "box {x:g},{y:g} {width:g}x{height:g}".format(**clip_rect)
    else:
        capture = "full page"
    record_args = dict(
        baseline=expected_path,
        pixel_threshold=pixel_threshold,
        max_diff_ratio=max_diff_ratio,
        capture=capture,
        closeup=closeup,
        interaction=interaction,
    )
    if expected_path != default_path:
        record_args["gpu_kind"] = kind

    minted_now = False
    if not os.path.isfile(expected_path):
        if not (MINT_BASELINES or remint):
            message = (
                f"no baseline at {expected_path}. {REMINT_HOW} A baseline is "
                "the definition of correct for every later run, so it is not "
                "something a test run should produce as a side effect."
            )
            candidates = candidate_dir()
            if candidates is None:
                comparisons.record_missing(_capture, **record_args)
            elif _missing_candidate(page, _capture, candidates, expected_path,
                                    pixel_threshold=pixel_threshold,
                                    max_diff_ratio=max_diff_ratio, record_args=record_args):
                message += _CANDIDATE_KEPT
            _frame_failed(message)
            return expected_path
        minted = _capture()
        _assert_mintable(minted, expected_path, page)
        minted.save(expected_path)
        minted_now = True
    elif remint:
        return _remint(
            page, expected_path, _capture, clip_selector=clip_selector, clip_rect=clip_rect,
            pixel_threshold=pixel_threshold, max_diff_ratio=max_diff_ratio,
            record_args=record_args,
            forced=any(p in n for p in REMINT_FORCE for n in names),
            target=kind_baseline(default_path, kind) if for_kind else expected_path,
            kind=kind,
        )

    expected_img = Image.open(expected_path).convert("RGB")
    try:
        actual_img = _capture()
    except Exception as exc:
        comparisons.record(
            "capture-error", expected=expected_img,
            error=f"{type(exc).__name__}: {exc}", **record_args,
        )
        raise

    cmp = _compare_images(actual_img, expected_img, pixel_threshold)
    actual_cmp, expected_cmp, diff = cmp.actual_cmp, cmp.expected_cmp, cmp.diff
    mismatched, total, ratio = cmp.mismatched, cmp.total, cmp.ratio
    failed = ratio > max_diff_ratio

    evidence = dict(
        expected=expected_img, created=actual_img, expected_cmp=expected_cmp,
        arr=cmp.arr, counted=cmp.counted, mismatched=mismatched, total=total,
        ratio=ratio,
    )
    # A run that keeps candidates judges a frame that moved as a re-mint would.
    # The volatile text is read after the capture, only for such a frame.
    candidates = candidate_dir()
    if candidates is not None and ratio > REMINT_MIN_RATIO:
        boxes = _volatile_boxes(page, clip_selector if clip_selector is not None else clip_rect)
        judged = _judge(
            page, _capture, actual_img, baseline=expected_img, cmp=cmp, boxes=boxes,
            pixel_threshold=pixel_threshold, max_diff_ratio=max_diff_ratio, name=expected_path,
        )
        evidence = {**judged.evidence,
                    **_as_candidate(judged, candidates, expected_path, max_diff_ratio)}
    comparisons.record(
        "failed" if failed else "minted" if minted_now else "passed",
        **evidence, **record_args,
    )

    if failed:
        actual_path = os.path.join(
            WORKFLOW_SCREENSHOT_EXPECTED_DIR,
            f"screenshot_{stem}_{test_name}_actual.png",
        )
        actual_img.save(actual_path)

        diff_highlighted = ImageEnhance.Brightness(diff).enhance(3.0)

        allure.attach(
            _image_to_png_bytes(expected_cmp),
            name=f"{filename} — expected",
            attachment_type=allure.attachment_type.PNG,
        )
        allure.attach(
            _image_to_png_bytes(actual_cmp),
            name=f"{filename} — actual",
            attachment_type=allure.attachment_type.PNG,
        )
        allure.attach(
            _image_to_png_bytes(diff_highlighted),
            name=f"{filename} — diff",
            attachment_type=allure.attachment_type.PNG,
        )

        _frame_failed(
            f"Screenshot regression for {os.path.basename(expected_path)}: "
            f"{mismatched}/{total} pixels differ ({ratio:.2%}), "
            f"allowed {max_diff_ratio:.2%}. "
            f"Expected {expected_img.size[0]}x{expected_img.size[1]}, "
            f"actual {actual_img.size[0]}x{actual_img.size[1]}. "
            f"Actual saved to {actual_path}. "
            f"See Allure report attachments for visual diff."
            + (_CANDIDATE_KEPT if evidence.get("candidate") else "")
        )
    return expected_path


def _missing_candidate(page, capture, directory, expected_path, *, pixel_threshold,
                       max_diff_ratio, record_args) -> bool:
    """Record a frame without a baseline, keeping its capture as a candidate
    when the mint checks pass and a second capture agrees with it, as a mint's
    does. Returns whether it kept one."""
    try:
        first = capture()
    except Exception as exc:  # noqa: BLE001 - recorded, as record_missing does
        comparisons.record("missing", error=f"capture failed: {type(exc).__name__}: {exc}",
                           **record_args)
        return False
    judged = _judge(page, capture, first, pixel_threshold=pixel_threshold,
                    max_diff_ratio=max_diff_ratio, name=expected_path)
    fields = _as_candidate(judged, directory, expected_path, max_diff_ratio)
    comparisons.record("missing", **judged.evidence, **fields, **record_args)
    return bool(fields.get("candidate"))


def park_pointer(page: Page) -> None:
    """Move the pointer to the pane's empty bottom-right corner.

    The pointer is wherever the last click left it, and once a node is framed
    that spot can be over its map or its chart.
    """
    viewport = page.viewport_size or {"width": 1280, "height": 720}
    page.mouse.move(viewport["width"] - 10, viewport["height"] - 60)


def frame_nodes(page: Page, node_ids) -> None:
    """Fit the canvas to *node_ids* at up to 100% zoom, the pointer parked first."""
    park_pointer(page)
    # The full-page fit's padding: less lets a tall node's header reach the
    # dataflow title in the canvas's top-left corner.
    _wait_for_reactflow_ready(page, node_ids=list(node_ids), max_zoom=1.0)
