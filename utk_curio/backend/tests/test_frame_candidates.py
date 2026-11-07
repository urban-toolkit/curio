"""A CI run that writes no baselines keeps the frames a re-mint would write.

On CI's e2e jobs, every run but a re-mint sets ``CURIO_E2E_CANDIDATE_DIR``. A
frame whose comparison moved past ``REMINT_MIN_RATIO`` then gets the re-mint's
own judgment (``screenshots._judge``: the volatile text left out, the mint
checks, a second capture), and one a re-mint would write over its baseline is
kept there as a candidate, under its baseline's name, so a PR run's report
holds the frames to review with no re-mint dispatch. A frame over its budget
or without a baseline is held, and its test fails at its end
(``frame_failures_at_the_end``), so every later frame of the test is captured
too.

Driven with a stub page, like test_baseline_minting.py, so no browser and no
stack are needed. The last tests run a real pytest session, to pin what JUnit
records of a held frame: CI's reports and tools read it.
"""
from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from utk_curio.backend.tests.test_frontend import comparisons
from utk_curio.backend.tests.test_frontend.utils import screenshots as e2e_utils

REPO = Path(__file__).resolve().parents[3]
NODEID = "tests/test_frontend/test_scene.py::test_scene[a-chromium]@wf-scene"
#: Names the GPU kind of a run (CI's test-gpu job sets it from its runner).
GPU_KIND_ENV = "CURIO_E2E_GPU_KIND"
NAME = "screenshot_scene_step.png"


class _StubPage:
    """Enough of a Page for the code paths before the capture (see test_baseline_minting)."""

    def wait_for_function(self, *a, **k):
        raise RuntimeError("no browser")

    def evaluate(self, *a, **k):
        raise RuntimeError("no browser")


def _painted_at(*points, size=(40, 40)) -> Image.Image:
    img = Image.new("RGB", size, (255, 255, 255))
    for point in points:
        img.putpixel(point, (0, 0, 0))
    return img


def _baseline_drawing() -> Image.Image:
    return _painted_at((1, 1))


def _moved() -> Image.Image:
    """The baseline plus a whole row: 40 of 1,600 pixels, 2.5%, past the
    re-mint floor and within the 10% budget."""
    return _painted_at((1, 1), *[(x, 20) for x in range(40)])


def _over() -> Image.Image:
    """Most of the frame black: far over any budget, and not blank."""
    img = Image.new("RGB", (40, 40), (0, 0, 0))
    img.putpixel((5, 5), (255, 255, 255))
    return img


def _black() -> Image.Image:
    return Image.new("RGB", (40, 40), (0, 0, 0))


def _png(img) -> bytes:
    """The bytes a re-mint writes for *img*."""
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture()
def run(tmp_path, monkeypatch):
    """A CI run that keeps candidates: (baselines, records, candidates)."""
    expected, compare, candidates = tmp_path / "expected", tmp_path / "compare", tmp_path / "candidates"
    expected.mkdir()
    monkeypatch.setattr(e2e_utils, "WORKFLOW_SCREENSHOT_EXPECTED_DIR", str(expected))
    monkeypatch.setattr(e2e_utils, "MINT_BASELINES", False)
    monkeypatch.setattr(e2e_utils, "REMINT_BASELINES", False)
    monkeypatch.setattr(e2e_utils, "REMINT_FORCE", ())
    monkeypatch.setattr(e2e_utils, "REMINT_GPU_KIND_FRAMES", ())
    monkeypatch.setattr(e2e_utils, "_wait_for_webfont", lambda page: True)
    monkeypatch.setattr(e2e_utils, "_held", None)
    monkeypatch.delenv(GPU_KIND_ENV, raising=False)
    monkeypatch.setenv(comparisons.DIR_ENV, str(compare))
    monkeypatch.setenv(e2e_utils.CANDIDATE_DIR_ENV, str(candidates))
    monkeypatch.setattr(comparisons, "current_nodeid", NODEID)
    return expected, compare, candidates


def _captures(monkeypatch, *images):
    """The captures the page gives, in order; returns the ones left untaken."""
    taken = list(images)
    monkeypatch.setattr(e2e_utils, "_capture_full_page", lambda page: taken.pop(0))
    return taken


def _boxes(monkeypatch, boxes=()):
    """The volatile text's boxes, and how many times they were asked for."""
    asked = []

    def volatile(page, clip):
        asked.append(clip)
        return list(boxes)

    monkeypatch.setattr(e2e_utils, "_volatile_boxes", volatile)
    return asked


def _save(test_name="step"):
    return e2e_utils.save_workflow_test_screenshot(
        _StubPage(), "scene.json", test_name=test_name, fit_reactflow=False,
        allow_running=True,
    )


def _records(compare_dir):
    return [json.loads((folder / "record.json").read_text(encoding="utf-8"))
            for folder in sorted(compare_dir.iterdir())]


def _kept(candidates):
    return sorted(p.name for p in candidates.iterdir()) if candidates.exists() else []


class TestAFrameThatMoved:
    def test_it_is_a_candidate_when_it_held_still(self, run, monkeypatch):
        expected, compare, candidates = run
        baseline = expected / NAME
        _baseline_drawing().save(baseline)
        before = baseline.read_bytes()
        new = _moved()
        left = _captures(monkeypatch, new, new.copy())
        _boxes(monkeypatch)
        assert _save() == str(baseline)  # within budget: the test goes on as before

        assert _kept(candidates) == [NAME]
        assert (candidates / NAME).read_bytes() == _png(new)  # what a re-mint writes
        assert baseline.read_bytes() == before  # never the baseline itself
        assert left == []  # captured twice: the frame, and the check that it held
        [record] = _records(compare)
        assert (record["status"], record["candidate"]) == ("passed", True)
        assert (record["ratio"], record["remint_ratio"], record["recapture_ratio"]) == (0.025, 0.025, 0.0)
        assert record["remint_min_ratio"] == e2e_utils.REMINT_MIN_RATIO

    def test_an_unmoved_frame_pays_nothing_and_is_no_candidate(self, run, monkeypatch):
        expected, compare, candidates = run
        _baseline_drawing().save(expected / NAME)
        left = _captures(monkeypatch, _baseline_drawing(), _baseline_drawing())
        asked = _boxes(monkeypatch)
        _save()
        assert asked == [] and len(left) == 1  # no volatile text read, one capture
        assert _kept(candidates) == []
        [record] = _records(compare)
        assert record["status"] == "passed"
        assert not {"candidate", "not_candidate", "remint_ratio", "recapture_ratio"} & set(record)

    def test_a_change_only_inside_volatile_text_is_no_candidate(self, run, monkeypatch):
        # Say a file name that embeds the time moved: the whole row differs,
        # but all of it inside the text's box, so a re-mint keeps the baseline.
        expected, compare, candidates = run
        _baseline_drawing().save(expected / NAME)
        left = _captures(monkeypatch, _moved(), _moved())
        _boxes(monkeypatch, [(0, 18, 40, 22)])
        _save()
        assert _kept(candidates) == []
        assert len(left) == 1  # unchanged by the re-mint's rule: no second capture
        [record] = _records(compare)
        assert (record["remint_ratio"], record["volatile_pixels"]) == (0.0, 40)
        assert "candidate" not in record and "not_candidate" not in record

    def test_a_change_under_the_floor_outside_volatile_text_is_no_candidate(self, run, monkeypatch):
        expected, _, candidates = run
        monkeypatch.setattr(e2e_utils, "REMINT_MIN_RATIO", 0.001)
        _baseline_drawing().save(expected / NAME)
        asked = _boxes(monkeypatch)
        _captures(monkeypatch, _painted_at((1, 1), (30, 30)))  # 1 pixel of 1,600
        _save()
        assert asked == [] and _kept(candidates) == []

    def test_a_screen_still_changing_is_no_candidate_and_still_passes(self, run, monkeypatch):
        # A re-mint fails this test, but this run judges only to keep a
        # candidate: the comparison it always made passed.
        expected, compare, candidates = run
        _baseline_drawing().save(expected / NAME)
        _captures(monkeypatch, _moved(), _black())
        _boxes(monkeypatch)
        _save()
        assert _kept(candidates) == []
        [record] = _records(compare)
        assert record["status"] == "passed" and "candidate" not in record
        assert record["not_candidate"].startswith("the screen was still changing")
        assert record["recapture_ratio"] > record["max_diff_ratio"]

    def test_a_blank_capture_is_no_candidate(self, run, monkeypatch):
        expected, compare, candidates = run
        _baseline_drawing().save(expected / NAME)  # 1 pixel off white: within budget
        _captures(monkeypatch, Image.new("RGB", (40, 40), (255, 255, 255)))
        _boxes(monkeypatch)
        _save()
        assert _kept(candidates) == []
        [record] = _records(compare)
        assert record["status"] == "passed"
        assert "blank" in record["not_candidate"]

    def test_a_gpu_kinds_candidate_is_named_after_the_kinds_baseline(self, run, monkeypatch):
        # As a re-mint on that kind rewrites the kind's baseline, never the default.
        expected, _, candidates = run
        _baseline_drawing().save(expected / NAME)
        _baseline_drawing().save(expected / "screenshot_scene_step.utk-gpu.png")
        monkeypatch.setenv(GPU_KIND_ENV, "utk-gpu")
        _captures(monkeypatch, _moved(), _moved())
        _boxes(monkeypatch)
        _save()
        assert _kept(candidates) == ["screenshot_scene_step.utk-gpu.png"]


class TestAFailedFrame:
    """Over its budget or without a baseline: held, and told at the test's end."""

    def test_it_is_held_and_the_test_fails_at_its_end_naming_it(self, run, monkeypatch):
        expected, compare, candidates = run
        _baseline_drawing().save(expected / "screenshot_scene_first.png")
        _baseline_drawing().save(expected / "screenshot_scene_later.png")
        over = _over()
        _captures(monkeypatch, over, over.copy(), _baseline_drawing())
        _boxes(monkeypatch)
        reached = []
        with pytest.raises(AssertionError) as exc:
            with e2e_utils.frame_failures_at_the_end():
                _save("first")  # held: no raise here
                reached.append("later")
                _save("later")
        assert reached == ["later"]
        message = str(exc.value)
        assert message.startswith("Screenshot regression for screenshot_scene_first.png: ")
        assert "test_frame_candidates.py:" in message  # where the frame was taken
        assert "candidate-baselines artifact" in message
        # The later frame was captured and compared, which used to never happen.
        assert [(r["baseline"], r["status"]) for r in _records(compare)] == [
            ("screenshot_scene_first.png", "failed"), ("screenshot_scene_later.png", "passed")]
        assert _kept(candidates) == ["screenshot_scene_first.png"]
        assert e2e_utils._held is None

    def test_every_held_frame_is_named_the_first_one_first(self, run, monkeypatch):
        expected, _, _ = run
        _baseline_drawing().save(expected / "screenshot_scene_first.png")
        _captures(monkeypatch, _over(), _over(), _moved(), _moved())
        _boxes(monkeypatch)
        with pytest.raises(AssertionError) as exc:
            with e2e_utils.frame_failures_at_the_end():
                _save("first")
                _save("new")  # no baseline
        message = str(exc.value)
        assert message.startswith("Screenshot regression for screenshot_scene_first.png")
        assert "1 more frame of this test failed:" in message
        assert f"- no baseline at {expected / 'screenshot_scene_new.png'}" in message
        assert "-f remint=true" in message  # still says how baselines are made

    def test_a_missing_baseline_is_a_candidate_after_the_mint_checks(self, run, monkeypatch):
        expected, compare, candidates = run
        new = _moved()
        _captures(monkeypatch, new, new.copy())
        with pytest.raises(AssertionError) as exc:
            with e2e_utils.frame_failures_at_the_end():
                _save()
        assert str(exc.value).startswith(f"no baseline at {expected / NAME}. ")
        assert _kept(candidates) == [NAME]
        assert (candidates / NAME).read_bytes() == _png(new)
        assert list(expected.iterdir()) == []  # still a refusal: no baseline is written
        [record] = _records(compare)
        assert (record["status"], record["candidate"], record["recapture_ratio"]) == ("missing", True, 0.0)
        assert record["images"] == {"created": "created.png"}

    @pytest.mark.parametrize("second, why", [
        (Image.new("RGB", (40, 40), (255, 255, 255)), "blank"),
        (_black(), "still changing"),
    ])
    def test_a_missing_frame_that_a_mint_would_refuse_is_no_candidate(self, run, monkeypatch, second, why):
        expected, compare, candidates = run
        first = second if why == "blank" else _moved()
        _captures(monkeypatch, first, second)
        with pytest.raises(AssertionError, match="no baseline at"):
            with e2e_utils.frame_failures_at_the_end():
                _save()
        assert _kept(candidates) == []
        [record] = _records(compare)
        assert record["status"] == "missing" and why in record["not_candidate"]

    def test_a_test_whose_frames_pass_ends_as_it_would_have(self, run, monkeypatch):
        expected, _, _ = run
        _baseline_drawing().save(expected / NAME)
        _captures(monkeypatch, _baseline_drawing())
        with e2e_utils.frame_failures_at_the_end():
            _save()
        with pytest.raises(KeyError):  # and its own failure is its own
            with e2e_utils.frame_failures_at_the_end():
                raise KeyError("the test's own")
        with pytest.raises(pytest.skip.Exception):
            with e2e_utils.frame_failures_at_the_end():
                pytest.skip("its own skip")

    def test_a_test_that_raised_after_a_held_frame_fails_with_the_frame_first(self, run, monkeypatch):
        expected, _, _ = run
        _baseline_drawing().save(expected / NAME)
        _captures(monkeypatch, _over(), _over())
        _boxes(monkeypatch)
        with pytest.raises(AssertionError) as exc:
            with e2e_utils.frame_failures_at_the_end():
                _save()
                raise TimeoutError("Locator.click: Timeout 30000ms exceeded")
        assert str(exc.value).startswith(f"Screenshot regression for {NAME}")
        assert "Then the test raised TimeoutError: Locator.click: Timeout 30000ms exceeded" in str(exc.value)
        assert isinstance(exc.value.__cause__, TimeoutError)

    def test_a_skip_after_a_held_frame_is_a_failure(self, run, monkeypatch):
        # Without the hold the test failed at the frame and never reached the skip.
        expected, _, _ = run
        _baseline_drawing().save(expected / NAME)
        _captures(monkeypatch, _over(), _over())
        _boxes(monkeypatch)
        with pytest.raises(AssertionError, match="Screenshot regression"):
            with e2e_utils.frame_failures_at_the_end():
                _save()
                pytest.skip("reached only because the frame was held")

    def test_outside_a_test_call_a_failed_frame_raises_where_it_is_taken(self, run, monkeypatch):
        # A frame a fixture takes is outside the call the hold wraps.
        expected, _, candidates = run
        _baseline_drawing().save(expected / NAME)
        _captures(monkeypatch, _over(), _over())
        _boxes(monkeypatch)
        with pytest.raises(AssertionError, match="Screenshot regression"):
            _save()
        assert _kept(candidates) == [NAME]


class TestARunThatKeepsNoCandidates:
    def test_without_the_variable_a_failed_frame_raises_at_once_as_always(self, run, monkeypatch):
        # A local run, the unit suites, and the e2e jobs other than CI's two.
        expected, compare, candidates = run
        monkeypatch.delenv(e2e_utils.CANDIDATE_DIR_ENV)
        _baseline_drawing().save(expected / NAME)
        left = _captures(monkeypatch, _over(), _over())
        asked = _boxes(monkeypatch)
        with pytest.raises(AssertionError, match="Screenshot regression"):
            with e2e_utils.frame_failures_at_the_end():
                _save()
                pytest.fail("the frame did not raise")
        assert asked == [] and len(left) == 1 and _kept(candidates) == []
        [record] = _records(compare)
        assert not {"candidate", "remint_ratio"} & set(record)

    def test_a_remint_keeps_no_candidates_and_holds_nothing(self, run, monkeypatch):
        expected, _, candidates = run
        monkeypatch.setattr(e2e_utils, "REMINT_BASELINES", True)
        _baseline_drawing().save(expected / NAME)
        assert e2e_utils.candidate_dir() is None
        _captures(monkeypatch, _moved(), _black())
        _boxes(monkeypatch)
        with pytest.raises(AssertionError, match="had not settled"):
            with e2e_utils.frame_failures_at_the_end():
                _save()
                pytest.fail("a re-mint's failure did not raise at the frame")
        assert _kept(candidates) == []

    def test_a_mint_keeps_no_candidates(self, run, monkeypatch):
        monkeypatch.setattr(e2e_utils, "MINT_BASELINES", True)
        assert e2e_utils.candidate_dir() is None


#: Each case: the committed baseline, the captures the page gives, and the
#: volatile text's boxes.
CASES = {
    "moved": (_baseline_drawing, (_moved, _moved), ()),
    "unmoved": (_baseline_drawing, (_baseline_drawing,), ()),
    "volatile only": (_baseline_drawing, (_moved,), [(0, 18, 40, 22)]),
    "over the budget": (_baseline_drawing, (_over, _over), ()),
    "still changing": (_baseline_drawing, (_moved, _black), ()),
    "blank": (_black, (lambda: Image.new("RGB", (40, 40), (255, 255, 255)),), ()),
    "a size change": (_baseline_drawing, (lambda: _painted_at((1, 1), size=(40, 44)),) * 2, ()),
}


class TestTheSameJudgmentAsAReMint:
    """A candidate is exactly the PNG a re-mint of the same captures writes."""

    @staticmethod
    def _through(tmp_path, monkeypatch, case, *, remint):
        make_baseline, makers, boxes = CASES[case]
        root = tmp_path / ("remint" if remint else "candidates-run")
        expected, candidates = root / "expected", root / "candidates"
        expected.mkdir(parents=True)
        make_baseline().save(expected / NAME)
        before = (expected / NAME).read_bytes()
        monkeypatch.setattr(e2e_utils, "WORKFLOW_SCREENSHOT_EXPECTED_DIR", str(expected))
        monkeypatch.setattr(e2e_utils, "REMINT_BASELINES", remint)
        monkeypatch.setenv(e2e_utils.CANDIDATE_DIR_ENV, str(candidates))
        _captures(monkeypatch, *[make() for make in makers])
        _boxes(monkeypatch, boxes)
        with contextlib.suppress(AssertionError):
            with e2e_utils.frame_failures_at_the_end():
                _save()
        if remint:
            after = (expected / NAME).read_bytes()
            return None if after == before else after
        assert (expected / NAME).read_bytes() == before
        kept = candidates / NAME
        return kept.read_bytes() if kept.exists() else None

    @pytest.mark.parametrize("case", sorted(CASES))
    def test_a_candidate_is_what_a_remint_writes(self, run, tmp_path, monkeypatch, case):
        reminted = self._through(tmp_path, monkeypatch, case, remint=True)
        candidate = self._through(tmp_path, monkeypatch, case, remint=False)
        assert candidate == reminted
        assert (reminted is not None) == (case in ("moved", "over the budget", "a size change"))


# A real pytest session: what JUnit records of a held frame. Its conftest
# wraps the call as test_frontend's conftest does.
CONFTEST = '''
import os

import pytest
from PIL import Image

from utk_curio.backend.tests.test_frontend.utils import screenshots

screenshots.WORKFLOW_SCREENSHOT_EXPECTED_DIR = os.path.join(os.getcwd(), "expected")
screenshots._wait_for_webfont = lambda page: True


def _painted(page, **kw):
    img = Image.new("RGB", (8, 8), (255, 255, 255))
    img.putpixel((3, 3), (12, 34, 56))
    return img


screenshots._capture_full_page = _painted


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    with screenshots.frame_failures_at_the_end():
        return (yield)
'''

TESTS = '''
import pytest

from utk_curio.backend.tests.test_frontend.utils import screenshots


class StubPage:
    def wait_for_function(self, *a, **k):
        raise RuntimeError("no browser")

    def evaluate(self, *a, **k):
        raise RuntimeError("no browser")


def frame(name):
    """A frame with no baseline: held on this run."""
    screenshots.save_workflow_test_screenshot(
        StubPage(), "scene.json", test_name=name, fit_reactflow=False, allow_running=True)


def reached(name):
    with open("reached.txt", "a", encoding="utf-8") as log:
        log.write(name + "\\n")


def test_passes():
    reached("passes")


def test_one_frame_fails():
    frame("one")
    reached("after one")


def test_two_frames_fail():
    frame("two-a")
    frame("two-b")


def test_raises_after_a_frame():
    frame("raises")
    raise KeyError("raised later")


def test_skips_after_a_frame():
    frame("skips")
    pytest.skip("skipped later")


def test_xfails_after_a_frame():
    frame("xfails")
    pytest.xfail("xfailed later")


@pytest.mark.xfail(raises=KeyError, strict=True)
def test_an_xfail_for_another_error_after_a_frame():
    frame("marked")
    raise KeyError("the error the mark expects")


@pytest.mark.xfail(strict=True)
def test_an_xfail_after_a_frame():
    frame("plain-xfail")


def test_skips_without_a_frame():
    pytest.skip("a plain skip")
'''


def _session(tmp_path, *, candidates=True):
    (tmp_path / "conftest.py").write_text(CONFTEST, encoding="utf-8")
    (tmp_path / "test_held.py").write_text(TESTS, encoding="utf-8")
    junit = tmp_path / "junit.xml"
    env = {**os.environ, "PYTHONPATH": str(REPO), comparisons.DIR_ENV: str(tmp_path / "compare")}
    env.pop("PYTEST_ADDOPTS", None)  # CI's points at the unit suite's own JUnit file
    env.pop(GPU_KIND_ENV, None)
    env.pop(e2e_utils.CANDIDATE_DIR_ENV, None)
    if candidates:
        env[e2e_utils.CANDIDATE_DIR_ENV] = str(tmp_path / "candidates")
    subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q",
         f"--junitxml={junit}", str(tmp_path)],
        cwd=tmp_path, capture_output=True, text=True, env=env, timeout=600,
    )
    cases = {}
    for case in ET.parse(junit).iter("testcase"):
        outcome = next((child for child in case if child.tag in ("failure", "error", "skipped")), None)
        cases[case.get("name")] = (outcome.tag if outcome is not None else "passed",
                                   (outcome.get("message") or "") if outcome is not None else "")
    reached_log = tmp_path / "reached.txt"
    reached = reached_log.read_text(encoding="utf-8").split("\n") if reached_log.exists() else []
    return cases, [line for line in reached if line]


def test_junit_records_a_held_frame_as_the_tests_failure(tmp_path):
    cases, reached = _session(tmp_path)
    expected = tmp_path / "expected"

    assert cases["test_passes"] == ("passed", "")
    assert cases["test_skips_without_a_frame"][0] == "skipped"
    # A failure of the call, never a teardown error, starting with the
    # frame's own message as it read when the frame raised.
    outcome, message = cases["test_one_frame_fails"]
    assert outcome == "failure"
    assert f"no baseline at {expected / 'screenshot_scene_one.png'}. " in message
    assert "frame taken at test_held.py:" in message
    assert "after one" in reached  # the test went on past its frame
    outcome, message = cases["test_two_frames_fail"]
    assert outcome == "failure"
    assert "screenshot_scene_two-a.png" in message and "screenshot_scene_two-b.png" in message
    outcome, message = cases["test_raises_after_a_frame"]
    assert outcome == "failure" and "screenshot_scene_raises.png" in message
    assert "Then the test raised KeyError: 'raised later'" in message
    # What the test did after its frame cannot make it weaker than a failure.
    for name in ("test_skips_after_a_frame", "test_xfails_after_a_frame",
                 "test_an_xfail_for_another_error_after_a_frame"):
        assert cases[name][0] == "failure", name
    # An xfail mark that expected the test to fail still sees it fail.
    assert cases["test_an_xfail_after_a_frame"][0] == "skipped"

    # Every frame was recorded, and kept as a candidate.
    kept = sorted(p.name for p in (tmp_path / "candidates").iterdir())
    assert kept == sorted(f"screenshot_scene_{name}.png" for name in (
        "one", "two-a", "two-b", "raises", "skips", "xfails", "marked", "plain-xfail"))
    assert len(list((tmp_path / "compare").iterdir())) == len(kept)


def test_without_candidates_junit_reads_as_it_always_did(tmp_path):
    cases, reached = _session(tmp_path, candidates=False)
    outcome, message = cases["test_one_frame_fails"]
    assert outcome == "failure" and "no baseline at" in message
    assert "frame taken at" not in message
    assert "after one" not in reached  # stopped at its frame, as before
    assert cases["test_two_frames_fail"][0] == "failure"
    assert "screenshot_scene_two-b.png" not in cases["test_two_frames_fail"][1]
    assert cases["test_skips_after_a_frame"][0] == "failure"
    assert cases["test_an_xfail_for_another_error_after_a_frame"][0] == "failure"
    assert not (tmp_path / "candidates").exists()
