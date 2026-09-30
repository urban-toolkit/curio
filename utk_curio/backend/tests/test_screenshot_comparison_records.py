"""Every screenshot comparison is recorded, passing or not, when asked to be.

``save_workflow_test_screenshot`` used to keep nothing when a comparison
passed, so CI could never show what it drew. With ``CURIO_E2E_COMPARE_DIR`` set
it writes one folder per comparison for ``scripts/ci_report.py``, and the
recording must never change what the comparison decides.

Driven with a stub page, like test_baseline_minting.py, so no browser and no
stack are needed.
"""
from __future__ import annotations

import json

import numpy as np
import pytest
from PIL import Image

from utk_curio.backend.tests.test_frontend import comparisons
from utk_curio.backend.tests.test_frontend import utils as e2e_utils

NODEID = "tests/test_frontend/test_scene.py::test_scene[a-chromium]@wf-scene"


class _StubPage:
    """Enough of a Page for the code paths before the capture (see test_baseline_minting)."""

    def wait_for_function(self, *a, **k):
        raise RuntimeError("no browser")

    def evaluate(self, *a, **k):
        raise RuntimeError("no browser")


def _white(paint=0, value=(0, 0, 0)):
    """A 10x10 white capture with its first *paint* pixels set to *value*."""
    img = Image.new("RGB", (10, 10), (255, 255, 255))
    for i in range(paint):
        img.putpixel((i % 10, i // 10), value)
    return img


@pytest.fixture()
def dirs(tmp_path, monkeypatch):
    expected, compare = tmp_path / "expected", tmp_path / "compare"
    expected.mkdir()
    monkeypatch.setattr(e2e_utils, "WORKFLOW_SCREENSHOT_EXPECTED_DIR", str(expected))
    monkeypatch.setattr(e2e_utils, "MINT_BASELINES", False)
    monkeypatch.setattr(e2e_utils, "REMINT_BASELINES", False)
    monkeypatch.setattr(e2e_utils, "REMINT_FORCE", ())
    monkeypatch.setenv(comparisons.DIR_ENV, str(compare))
    monkeypatch.setattr(comparisons, "current_nodeid", NODEID)
    return expected, compare


def _baseline(expected_dir, img=None):
    path = expected_dir / "screenshot_scene_step.png"
    (img or _white()).save(path)
    return path


def _save(monkeypatch, capture, **kw):
    monkeypatch.setattr(e2e_utils, "_capture_full_page", capture)
    return e2e_utils.save_workflow_test_screenshot(
        _StubPage(), "scene.json", test_name="step", fit_reactflow=False,
        allow_running=True, **kw
    )


def _records(compare_dir):
    return [
        (folder, json.loads((folder / "record.json").read_text(encoding="utf-8")))
        for folder in sorted(compare_dir.iterdir())
    ]


def test_a_passing_comparison_is_recorded(dirs, monkeypatch):
    expected, compare = dirs
    baseline = _baseline(expected)
    _save(monkeypatch, lambda page: _white(paint=1))

    [(folder, record)] = _records(compare)
    assert record["status"] == "passed"
    assert record["nodeid"] == NODEID
    assert record["baseline"] == "screenshot_scene_step.png"
    assert (record["mismatched"], record["total"], record["ratio"]) == (1, 100, 0.01)
    assert (record["pixel_threshold"], record["max_diff_ratio"]) == (30, 0.10)
    assert record["max_delta"] == 255
    assert record["expected_size"] == record["created_size"] == record["compared_size"] == [10, 10]
    assert record["capture"] == "full page"
    assert record["images"] == {"expected": "expected.png", "created": "created.png", "diff": "diff.png"}
    # The baseline as committed, byte for byte, not a re-encoded copy.
    assert (folder / "expected.png").read_bytes() == baseline.read_bytes()


def test_a_failing_comparison_is_recorded_and_still_fails(dirs, monkeypatch):
    expected, compare = dirs
    _baseline(expected)
    with pytest.raises(AssertionError, match=r"Screenshot regression for screenshot_scene_step\.png: 30/100"):
        _save(monkeypatch, lambda page: _white(paint=30))

    [(_, record)] = _records(compare)
    assert record["status"] == "failed"
    assert (record["mismatched"], record["ratio"]) == (30, 0.30)
    # The failure path's own evidence is unchanged.
    assert (expected / "screenshot_scene_step_actual.png").is_file()


def test_the_difference_image_shows_what_was_counted(dirs, monkeypatch):
    expected, compare = dirs
    _baseline(expected)
    capture = _white()
    capture.putpixel((0, 0), (0, 0, 0))        # 255 off: counted
    capture.putpixel((1, 0), (240, 240, 240))  # 15 off: within the tolerance of 30
    _save(monkeypatch, lambda page: capture)

    [(folder, _)] = _records(compare)
    diff = Image.open(folder / "diff.png").convert("RGB")
    assert diff.getpixel((0, 0)) == comparisons.COUNTED
    assert diff.getpixel((1, 0)) == comparisons.WITHIN
    assert diff.getpixel((5, 5)) == (255, 255, 255)  # the faded expected, white here


def test_the_backdrop_is_the_expected_image_faded():
    arr = np.zeros((1, 1, 3), dtype=np.uint8)
    img = comparisons.diff_image(arr, np.zeros((1, 1), dtype=bool), Image.new("RGB", (1, 1), (0, 0, 0)))
    # Black keeps FADE of its contrast against white.
    assert img.getpixel((0, 0)) == (204, 204, 204)


def test_a_missing_baseline_records_what_would_have_been_minted(dirs, monkeypatch):
    expected, compare = dirs
    with pytest.raises(AssertionError, match="remint=true"):
        _save(monkeypatch, lambda page: _white(paint=3))

    [(folder, record)] = _records(compare)
    assert record["status"] == "missing"
    assert record["images"] == {"created": "created.png"}
    assert record["created_size"] == [10, 10]
    # Still a refusal: nothing lands in the baseline directory.
    assert list(expected.iterdir()) == []


def test_a_capture_that_raises_is_recorded_and_reraised(dirs, monkeypatch):
    expected, compare = dirs
    _baseline(expected)

    def boom(page):
        raise RuntimeError("the clip box never showed up")

    with pytest.raises(RuntimeError, match="the clip box never showed up"):
        _save(monkeypatch, boom)

    [(_, record)] = _records(compare)
    assert record["status"] == "capture-error"
    assert record["error"] == "RuntimeError: the clip box never showed up"
    assert record["images"] == {"expected": "expected.png"}


def test_a_minted_baseline_is_recorded_as_minted(dirs, monkeypatch):
    expected, compare = dirs
    monkeypatch.setattr(e2e_utils, "MINT_BASELINES", True)
    monkeypatch.setattr(e2e_utils, "_wait_for_webfont", lambda page: True)
    _save(monkeypatch, lambda page: _white(paint=1))

    [(_, record)] = _records(compare)
    assert record["status"] == "minted"


def _remint_on(monkeypatch, *captures):
    monkeypatch.setattr(e2e_utils, "REMINT_BASELINES", True)
    monkeypatch.setattr(e2e_utils, "_wait_for_webfont", lambda page: True)
    taken = list(captures)
    return lambda page: taken.pop(0)


def test_a_reminted_baseline_is_recorded_with_the_one_it_replaced(dirs, monkeypatch):
    expected, compare = dirs
    baseline = _baseline(expected, _white(paint=1))
    old_bytes = baseline.read_bytes()
    new = _white(paint=30)
    _save(monkeypatch, _remint_on(monkeypatch, new, new.copy()))

    [(folder, record)] = _records(compare)
    assert record["status"] == "reminted"
    # Old against new, which is what the review looks at: 29 pixels changed.
    assert (record["mismatched"], record["ratio"]) == (29, 0.29)
    assert (record["remint_ratio"], record["recapture_ratio"]) == (0.29, 0.0)
    assert record["remint_min_ratio"] == e2e_utils.REMINT_MIN_RATIO
    assert record["volatile_pixels"] == 0
    # The baseline as it was, byte for byte, although the file now holds the new one.
    assert (folder / "expected.png").read_bytes() == old_bytes
    assert baseline.read_bytes() != old_bytes
    assert Image.open(folder / "created.png").convert("RGB").tobytes() == new.tobytes()


def test_a_baseline_named_by_force_is_recorded_as_requested(dirs, monkeypatch):
    expected, compare = dirs
    _baseline(expected, _white(paint=1))
    monkeypatch.setattr(e2e_utils, "REMINT_FORCE", ("scene_step",))
    same = _white(paint=1)
    _save(monkeypatch, _remint_on(monkeypatch, same, same.copy()))

    [(_, record)] = _records(compare)
    assert (record["status"], record["forced"], record["ratio"]) == ("reminted", True, 0.0)


def test_a_kept_baseline_is_recorded_as_unchanged(dirs, monkeypatch):
    expected, compare = dirs
    baseline = _baseline(expected, _white(paint=1))
    before = baseline.read_bytes()
    _save(monkeypatch, _remint_on(monkeypatch, _white(paint=1)))

    [(_, record)] = _records(compare)
    assert record["status"] == "unchanged"
    assert (record["ratio"], record["remint_ratio"]) == (0.0, 0.0)
    assert "recapture_ratio" not in record
    assert baseline.read_bytes() == before


def test_volatile_text_is_drawn_blue_and_not_counted_by_a_remint(dirs, monkeypatch):
    expected, compare = dirs
    _baseline(expected, _white())
    # The first row changed, all of it inside a volatile text box.
    monkeypatch.setattr(e2e_utils, "_volatile_boxes", lambda page, clip: [(0, 0, 10, 0.5)])
    _save(monkeypatch, _remint_on(monkeypatch, _white(paint=10)))

    [(folder, record)] = _records(compare)
    assert record["status"] == "unchanged"
    assert (record["mismatched"], record["volatile_pixels"], record["remint_ratio"]) == (10, 10, 0.0)
    diff = Image.open(folder / "diff.png").convert("RGB")
    assert diff.getpixel((0, 0)) == comparisons.VOLATILE
    assert diff.getpixel((5, 5)) == (255, 255, 255)


def test_an_ordinary_comparison_records_no_remint_fields(dirs, monkeypatch):
    expected, compare = dirs
    _baseline(expected)
    _save(monkeypatch, lambda page: _white(paint=1))
    [(_, record)] = _records(compare)
    assert not {"remint_ratio", "remint_min_ratio", "recapture_ratio", "volatile_pixels",
                "closeup"} & set(record)


def test_a_close_up_says_so_in_its_record(dirs, monkeypatch):
    expected, compare = dirs
    _baseline(expected)
    _save(monkeypatch, lambda page: _white(paint=1), closeup=True)
    [(_, record)] = _records(compare)
    assert (record["status"], record["closeup"]) == ("passed", True)


def test_a_missing_close_up_says_so_in_its_record(dirs, monkeypatch):
    _, compare = dirs
    with pytest.raises(AssertionError, match="remint=true"):
        _save(monkeypatch, lambda page: _white(paint=1), closeup=True)
    [(_, record)] = _records(compare)
    assert (record["status"], record["closeup"]) == ("missing", True)


def test_nothing_is_recorded_when_it_is_off(dirs, monkeypatch):
    expected, compare = dirs
    monkeypatch.delenv(comparisons.DIR_ENV)
    _baseline(expected)
    _save(monkeypatch, lambda page: _white(paint=1))
    assert not compare.exists()


def test_a_record_that_cannot_be_written_changes_nothing(dirs, monkeypatch, tmp_path, capsys):
    expected, _ = dirs
    blocker = tmp_path / "a-file"
    blocker.write_text("not a directory")
    monkeypatch.setenv(comparisons.DIR_ENV, str(blocker / "compare"))
    _baseline(expected)

    assert _save(monkeypatch, lambda page: _white(paint=1)).endswith("screenshot_scene_step.png")
    with pytest.raises(AssertionError, match="Screenshot regression"):
        _save(monkeypatch, lambda page: _white(paint=30))
    assert "[e2e-compare] could not record screenshot_scene_step.png" in capsys.readouterr().out


def test_two_records_of_one_comparison_get_their_own_folders(dirs, monkeypatch):
    expected, compare = dirs
    _baseline(expected)
    _save(monkeypatch, lambda page: _white(paint=1))
    _save(monkeypatch, lambda page: _white(paint=2))

    records = _records(compare)
    assert [r["mismatched"] for _, r in records] == [1, 2]
    assert records[1][0].name == records[0][0].name + "-2"


def test_the_test_id_falls_back_to_pytest_current_test(monkeypatch):
    monkeypatch.setattr(comparisons, "current_nodeid", None)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/a.py::test_b[x] (call)")
    assert comparisons.nodeid() == "tests/a.py::test_b[x]"
