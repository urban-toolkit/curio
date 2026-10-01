"""Every screenshot comparison, recorded for the CI report page.

``save_workflow_test_screenshot`` compares a capture against its committed
baseline and used to keep nothing when the comparison passed, so there was no
way to see what CI actually drew. With ``CURIO_E2E_COMPARE_DIR`` set it calls
:func:`record` for every comparison, passing or not, which writes one folder
per comparison:

- ``record.json``   the test id, the baseline, the outcome, and the numbers the
                    verdict came from: the per-channel tolerance, the budget,
                    and the share of pixels over the tolerance
- ``expected.png``  the baseline as committed
- ``created.png``   what this run captured
- ``diff.png``      where the two differ: red pixels count against the budget,
                    amber ones differ but within the tolerance, blue ones (a
                    re-mint only) differ inside text a run writes fresh every
                    time, and the rest is the expected image faded to gray

The status is ``passed``, ``failed``, ``minted``, ``missing`` or
``capture-error``, and under ``--remint-baselines`` also ``reminted`` (the
capture replaced the baseline; ``expected.png`` is the one it replaced) or
``unchanged`` (the baseline was kept).

``scripts/ci_report.py`` turns a directory of these into one HTML page. Like
diagnostics.py this is best effort: a record that cannot be written is
reported and skipped, never allowed to change the test's outcome.
"""

import hashlib
import json
import os
import re
import shutil

DIR_ENV = "CURIO_E2E_COMPARE_DIR"

# The test a comparison belongs to. conftest.py's pytest_runtest_call sets it
# around each test body; PYTEST_CURRENT_TEST is the fallback for callers
# outside that conftest, since pytest documents its format as unstable.
current_nodeid = None

COUNTED = (255, 0, 0)
WITHIN = (255, 190, 60)
VOLATILE = (70, 130, 255)
# How much of the expected image's contrast survives in the diff's backdrop:
# enough to find your way around the page, faint enough that the red wins.
FADE = 0.2


def enabled(environ=os.environ):
    return bool(environ.get(DIR_ENV))


def nodeid(environ=os.environ):
    if current_nodeid:
        return current_nodeid
    raw = environ.get("PYTEST_CURRENT_TEST") or ""
    return re.sub(r" \((setup|call|teardown)\)$", "", raw)


def diff_image(arr, counted, expected_cmp, volatile=None):
    """Where two same-size captures differ, drawn over the faded expected one.

    *arr* is the per-channel absolute difference the comparison measured,
    *counted* the pixels it counted against the budget, so the red here is
    exactly the share the verdict reports. *volatile*, from a re-mint, marks
    the counted pixels inside text a run writes fresh every time, which the
    re-mint did not count; they are drawn blue instead.
    """
    import numpy as np
    from PIL import Image

    gray = np.asarray(expected_cmp.convert("L"), dtype=np.float32)
    out = np.repeat((255.0 - (255.0 - gray) * FADE).astype(np.uint8)[:, :, None], 3, axis=2)
    out[arr.any(axis=2) & ~counted] = WITHIN
    out[counted] = COUNTED
    if volatile is not None:
        out[counted & volatile] = VOLATILE
    return Image.fromarray(out, "RGB")


def record(status, *, baseline, pixel_threshold, max_diff_ratio, capture,
           expected=None, created=None, expected_cmp=None, arr=None,
           counted=None, mismatched=None, total=None, ratio=None, error=None,
           volatile=None, remint_ratio=None, remint_min_ratio=None,
           recapture_ratio=None, expected_bytes=None, forced=False, closeup=False,
           interaction=None, environ=os.environ):
    """Write one comparison's folder. Returns its path, or None when off.

    *expected_bytes* is the baseline as it was before a re-mint replaced it;
    without it ``expected.png`` is copied from the file at *baseline*.
    *closeup* marks one node framed on its own (``utils.save_node_closeup``).
    *interaction* places a frame in its before/after pair
    (``utils.save_interaction_frame``).
    """
    if not enabled(environ):
        return None
    try:
        return _write(
            status, baseline=baseline, pixel_threshold=pixel_threshold,
            max_diff_ratio=max_diff_ratio, capture=capture, expected=expected,
            created=created, expected_cmp=expected_cmp, arr=arr, counted=counted,
            mismatched=mismatched, total=total, ratio=ratio, error=error,
            volatile=volatile, remint_ratio=remint_ratio,
            remint_min_ratio=remint_min_ratio, recapture_ratio=recapture_ratio,
            expected_bytes=expected_bytes, forced=forced, closeup=closeup,
            interaction=interaction, environ=environ,
        )
    except Exception as exc:
        print(f"[e2e-compare] could not record {os.path.basename(baseline)}: {exc}")
        return None


def record_missing(take, *, baseline, pixel_threshold, max_diff_ratio, capture,
                   closeup=False, interaction=None, environ=os.environ):
    """Record a comparison that had no baseline, with what would have been minted."""
    if not enabled(environ):
        return None
    created, error = None, None
    try:
        created = take()
    except Exception as exc:
        error = f"capture failed: {type(exc).__name__}: {exc}"
    return record(
        "missing", baseline=baseline, pixel_threshold=pixel_threshold,
        max_diff_ratio=max_diff_ratio, capture=capture, created=created,
        error=error, closeup=closeup, interaction=interaction, environ=environ,
    )


def _write(status, *, baseline, pixel_threshold, max_diff_ratio, capture,
           expected, created, expected_cmp, arr, counted, mismatched, total,
           ratio, error, volatile, remint_ratio, remint_min_ratio,
           recapture_ratio, expected_bytes, forced, closeup, interaction, environ):
    test_id = nodeid(environ)
    name = os.path.basename(baseline)
    out_dir = _claim(environ[DIR_ENV], name, test_id)
    images = {}

    if expected_bytes is not None:
        with open(os.path.join(out_dir, "expected.png"), "wb") as handle:
            handle.write(expected_bytes)
        images["expected"] = "expected.png"
    elif os.path.isfile(baseline):
        shutil.copyfile(baseline, os.path.join(out_dir, "expected.png"))
        images["expected"] = "expected.png"
    if created is not None:
        created.save(os.path.join(out_dir, "created.png"))
        images["created"] = "created.png"
    if arr is not None and counted is not None and expected_cmp is not None:
        diff_image(arr, counted, expected_cmp, volatile).save(os.path.join(out_dir, "diff.png"))
        images["diff"] = "diff.png"
    volatile_pixels = (
        int((counted & volatile).sum())
        if volatile is not None and counted is not None else None
    )

    data = {
        "nodeid": test_id,
        "baseline": name,
        "status": status,
        "pixel_threshold": pixel_threshold,
        "max_diff_ratio": max_diff_ratio,
        "mismatched": mismatched,
        "total": total,
        "ratio": ratio,
        "max_delta": int(arr.max()) if arr is not None and arr.size else None,
        "expected_size": list(expected.size) if expected is not None else None,
        "created_size": list(created.size) if created is not None else None,
        "compared_size": [int(arr.shape[1]), int(arr.shape[0])] if arr is not None else None,
        "capture": capture,
        "error": error,
        "images": images,
    }
    # Only a re-mint writes these, so every other record reads as before.
    for key, value in (("remint_ratio", remint_ratio), ("remint_min_ratio", remint_min_ratio),
                       ("recapture_ratio", recapture_ratio), ("volatile_pixels", volatile_pixels)):
        if value is not None:
            data[key] = value
    if forced:
        data["forced"] = True  # named by --remint-force
    if closeup:
        data["closeup"] = True
    if interaction:
        data["interaction"] = dict(interaction)
    # Last, and atomically: the report skips a folder without record.json, so
    # a run killed mid-write leaves nothing half-read.
    tmp = os.path.join(out_dir, "record.json.tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=1, sort_keys=True)
    os.replace(tmp, os.path.join(out_dir, "record.json"))
    return out_dir


def _claim(root, baseline_name, test_id):
    """A fresh folder for this comparison, safe against the other xdist workers.

    Named by the baseline first, so the folder list reads like the baseline
    directory. The test id is hashed rather than spelled out because a real
    one is 130 to 160 characters on its own.
    """
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", os.path.splitext(baseline_name)[0]).strip("_")[:120]
    digest = hashlib.sha1(test_id.encode("utf-8")).hexdigest()[:10]
    os.makedirs(root, exist_ok=True)
    for n in range(1, 1000):
        path = os.path.join(root, f"{stem}--{digest}" + (f"-{n}" if n > 1 else ""))
        try:
            os.mkdir(path)  # atomic: exactly one worker gets each name
            return path
        except FileExistsError:
            continue
    raise RuntimeError(f"no free record folder for {baseline_name} under {root}")
