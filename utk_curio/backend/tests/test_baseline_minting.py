"""A baseline is created deliberately, never as a side effect of a test run.

A screenshot baseline is the definition of correct for every run after it, so
the moment it is written matters more than the moment it is compared. This used
to mint implicitly whenever the PNG was absent, which meant a first run always
passed, and two ways that bites have both actually happened:

* a capture taken against a broken build enshrines the bug as expected output,
  and the suite then defends it;
* a capture taken on the wrong machine enshrines that machine. The macOS
  captures of the two #333 scenes looked perfect by eye and sat 6.11% and 10.05%
  from what CI renders, the second past its budget, because macOS rasterizes
  text with grayscale antialiasing while the runner uses LCD subpixel.

These tests drive ``save_workflow_test_screenshot``'s control flow directly with
a stub page, so they need no browser and no stack.
"""
from __future__ import annotations

import os
import re

import pytest
from PIL import Image

from utk_curio.backend.tests.test_frontend import utils as e2e_utils


def _painted() -> Image.Image:
    """A capture with something in it, i.e. not one the blank guard refuses."""
    img = Image.new("RGB", (8, 8), (255, 255, 255))
    img.putpixel((3, 3), (12, 34, 56))
    return img


class _StubPage:
    """Enough of a Page for the code paths reached before the baseline check.

    ``_wait_for_webfont`` is the only thing that touches the page there, and it
    swallows every exception by design, so raising is a faithful stand-in for
    "this is not a real browser".
    """

    def wait_for_function(self, *a, **k):
        raise RuntimeError("no browser")

    def evaluate(self, *a, **k):
        raise RuntimeError("no browser")


@pytest.fixture()
def expected_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(
        e2e_utils, "WORKFLOW_SCREENSHOT_EXPECTED_DIR", str(tmp_path)
    )
    return tmp_path


def _save(**kw):
    return e2e_utils.save_workflow_test_screenshot(
        _StubPage(),
        "some-scene.json",
        test_name="a-step",
        fit_reactflow=False,
        sweep_toasts=False,
        allow_running=True,
        **kw,
    )


def test_the_default_is_not_to_mint():
    # The module default is what every ordinary run gets: local or CI, serial or
    # parallel. Only --mint-baselines / --remint-baselines flip it
    # (tests/conftest.py), and only on CI.
    assert e2e_utils.MINT_BASELINES is False
    assert e2e_utils.REMINT_BASELINES is False


class TestOnlyOnCI:
    """A baseline is what CI renders, so no other machine may write one."""

    @pytest.fixture(autouse=True)
    def _restore(self, monkeypatch):
        monkeypatch.setattr(e2e_utils, "MINT_BASELINES", False)
        monkeypatch.setattr(e2e_utils, "REMINT_BASELINES", False)
        monkeypatch.setattr(e2e_utils, "REMINT_FORCE", ())

    def test_force_needs_a_remint(self):
        with pytest.raises(pytest.UsageError) as exc:
            e2e_utils.allow_baseline_writes(
                mint=False, remint=False, force=["19-storage"], environ={"GITHUB_ACTIONS": "true"})
        assert "--remint-force" in str(exc.value)

    def test_force_is_kept_on_ci(self):
        e2e_utils.allow_baseline_writes(
            mint=False, remint=True, force=["19-storage", ""], environ={"GITHUB_ACTIONS": "true"})
        assert e2e_utils.REMINT_FORCE == ("19-storage",)

    @pytest.mark.parametrize("flag", ["mint", "remint"])
    def test_either_flag_is_refused_off_ci(self, flag):
        with pytest.raises(pytest.UsageError) as exc:
            e2e_utils.allow_baseline_writes(
                mint=flag == "mint", remint=flag == "remint", environ={})
        assert f"--{flag}-baselines runs on CI only" in str(exc.value)
        assert "-f remint=true" in str(exc.value)
        assert (e2e_utils.MINT_BASELINES, e2e_utils.REMINT_BASELINES) == (False, False)

    def test_a_local_github_actions_value_that_is_not_true_is_refused(self):
        with pytest.raises(pytest.UsageError):
            e2e_utils.allow_baseline_writes(
                mint=True, remint=False, environ={"GITHUB_ACTIONS": "1"})

    def test_on_ci_the_flags_are_set(self):
        e2e_utils.allow_baseline_writes(
            mint=False, remint=True, environ={"GITHUB_ACTIONS": "true"})
        assert (e2e_utils.MINT_BASELINES, e2e_utils.REMINT_BASELINES) == (False, True)
        e2e_utils.allow_baseline_writes(
            mint=True, remint=False, environ={"GITHUB_ACTIONS": "true"})
        assert (e2e_utils.MINT_BASELINES, e2e_utils.REMINT_BASELINES) == (True, False)

    def test_without_a_flag_nothing_is_checked(self):
        e2e_utils.allow_baseline_writes(mint=False, remint=False, environ={})


class TestWithoutTheFlag:
    def test_a_missing_baseline_fails(self, expected_dir, monkeypatch):
        monkeypatch.setattr(e2e_utils, "MINT_BASELINES", False)
        with pytest.raises(AssertionError) as exc:
            _save()
        # The message says how baselines are made: a CI re-mint, not a local run.
        assert "-f remint=true" in str(exc.value)

    def test_it_writes_nothing(self, expected_dir, monkeypatch):
        # The refusal must be a refusal, not a refusal after the fact.
        monkeypatch.setattr(e2e_utils, "MINT_BASELINES", False)
        with pytest.raises(AssertionError):
            _save()
        assert list(expected_dir.iterdir()) == []


class TestWithTheFlag:
    def test_it_mints(self, expected_dir, monkeypatch):
        monkeypatch.setattr(e2e_utils, "MINT_BASELINES", True)
        monkeypatch.setattr(e2e_utils, "_wait_for_webfont", lambda page: True)
        monkeypatch.setattr(e2e_utils, "_capture_full_page", lambda page: _painted())
        path = _save()
        assert os.path.isfile(path)
        assert Image.open(path).size == (8, 8)

    def test_it_still_refuses_a_blank_capture(self, expected_dir, monkeypatch):
        # The flag says "I meant to create one", not "write whatever you saw".
        # A flat capture passes the comparison that immediately follows, because
        # it is compared against itself.
        monkeypatch.setattr(e2e_utils, "MINT_BASELINES", True)
        monkeypatch.setattr(e2e_utils, "_wait_for_webfont", lambda page: True)
        monkeypatch.setattr(
            e2e_utils,
            "_capture_full_page",
            lambda page: Image.new("RGB", (8, 8), (255, 255, 255)),
        )
        with pytest.raises(AssertionError) as exc:
            _save()
        assert "blank" in str(exc.value)
        assert list(expected_dir.iterdir()) == []

    def test_it_still_refuses_when_the_webfont_is_missing(
        self, expected_dir, monkeypatch
    ):
        monkeypatch.setattr(e2e_utils, "MINT_BASELINES", True)
        monkeypatch.setattr(e2e_utils, "_wait_for_webfont", lambda page: False)
        monkeypatch.setattr(e2e_utils, "_capture_full_page", lambda page: _painted())
        with pytest.raises(AssertionError) as exc:
            _save()
        assert e2e_utils.WEBFONT_FAMILY in str(exc.value)
        assert list(expected_dir.iterdir()) == []


def _painted_at(*points, size=(40, 40)) -> Image.Image:
    img = Image.new("RGB", size, (255, 255, 255))
    for point in points:
        img.putpixel(point, (0, 0, 0))
    return img


class TestRemint:
    """--remint-baselines rewrites a baseline whose screen changed, and only that."""

    @pytest.fixture(autouse=True)
    def _remint_on(self, expected_dir, monkeypatch):
        monkeypatch.setattr(e2e_utils, "MINT_BASELINES", False)
        monkeypatch.setattr(e2e_utils, "REMINT_BASELINES", True)
        monkeypatch.setattr(e2e_utils, "REMINT_FORCE", ())
        monkeypatch.setattr(e2e_utils, "_wait_for_webfont", lambda page: True)

    def _baseline(self, expected_dir, img):
        path = expected_dir / "screenshot_some-scene_a-step.png"
        img.save(path)
        return path

    def _captures(self, monkeypatch, *images):
        taken = list(images)
        monkeypatch.setattr(e2e_utils, "_capture_full_page", lambda page: taken.pop(0))
        return taken

    def test_a_changed_screen_replaces_its_baseline(self, expected_dir, monkeypatch):
        path = self._baseline(expected_dir, _painted_at((1, 1)))
        new = _painted_at(*[(x, 20) for x in range(40)])  # a whole new row
        left = self._captures(monkeypatch, new, new.copy())
        assert _save() == str(path)
        assert Image.open(path).convert("RGB").tobytes() == new.tobytes()
        assert left == []  # captured twice: the re-mint, and the check that it held

    def test_an_unchanged_screen_keeps_its_baseline_byte_for_byte(self, expected_dir, monkeypatch):
        path = self._baseline(expected_dir, _painted_at((1, 1)))
        before = path.read_bytes()
        self._captures(monkeypatch, _painted_at((1, 1)))
        _save()
        assert path.read_bytes() == before

    def test_a_change_below_the_floor_keeps_the_baseline(self, expected_dir, monkeypatch):
        # 1 pixel of 1,600 is 0.0625%; the floor is a share of the frame.
        monkeypatch.setattr(e2e_utils, "REMINT_MIN_RATIO", 0.001)
        path = self._baseline(expected_dir, _painted_at((1, 1)))
        before = path.read_bytes()
        self._captures(monkeypatch, _painted_at((1, 1), (30, 30)))
        _save()
        assert path.read_bytes() == before

    def test_a_baseline_named_by_force_is_reminted_however_small_the_change(self, expected_dir, monkeypatch):
        # A fix that changes a few words of text sits under the floor; the
        # batch names its frames so the committed baseline shows the fix.
        monkeypatch.setattr(e2e_utils, "REMINT_MIN_RATIO", 0.001)
        monkeypatch.setattr(e2e_utils, "REMINT_FORCE", ("some-scene",))
        path = self._baseline(expected_dir, _painted_at((1, 1)))
        new = _painted_at((1, 1), (30, 30))  # 1 pixel of 1,600, under the floor
        self._captures(monkeypatch, new, new.copy())
        _save()
        assert Image.open(path).convert("RGB").tobytes() == new.tobytes()

    def test_force_names_only_the_baselines_it_matches(self, expected_dir, monkeypatch):
        monkeypatch.setattr(e2e_utils, "REMINT_MIN_RATIO", 0.001)
        monkeypatch.setattr(e2e_utils, "REMINT_FORCE", ("another-scene",))
        path = self._baseline(expected_dir, _painted_at((1, 1)))
        before = path.read_bytes()
        self._captures(monkeypatch, _painted_at((1, 1), (30, 30)))
        _save()
        assert path.read_bytes() == before

    def test_a_change_inside_volatile_text_keeps_the_baseline(self, expected_dir, monkeypatch):
        # Say a file name that embeds the time moved: the whole row differs,
        # but all of it inside the text's box.
        path = self._baseline(expected_dir, _painted_at((1, 1)))
        before = path.read_bytes()
        monkeypatch.setattr(e2e_utils, "_volatile_boxes", lambda page, clip: [(0, 18, 40, 22)])
        self._captures(monkeypatch, _painted_at((1, 1), *[(x, 20) for x in range(40)]))
        _save()
        assert path.read_bytes() == before

    def test_volatile_text_does_not_hide_a_change_elsewhere(self, expected_dir, monkeypatch):
        path = self._baseline(expected_dir, _painted_at((1, 1)))
        monkeypatch.setattr(e2e_utils, "_volatile_boxes", lambda page, clip: [(0, 0, 40, 5)])
        new = _painted_at(*[(x, 20) for x in range(40)])
        self._captures(monkeypatch, new, new.copy())
        _save()
        assert Image.open(path).convert("RGB").tobytes() == new.tobytes()

    def test_a_change_over_the_budget_is_reminted_not_failed(self, expected_dir, monkeypatch):
        # Showing what changed is the point of a re-mint; the review decides.
        path = self._baseline(expected_dir, _painted_at((1, 1)))
        new = Image.new("RGB", (40, 40), (0, 0, 0))
        new.putpixel((5, 5), (255, 255, 255))
        self._captures(monkeypatch, new, new.copy())
        _save()
        assert Image.open(path).convert("RGB").tobytes() == new.tobytes()

    def test_a_screen_still_changing_puts_the_old_baseline_back(self, expected_dir, monkeypatch):
        path = self._baseline(expected_dir, _painted_at((1, 1)))
        before = path.read_bytes()
        first = _painted_at(*[(x, 20) for x in range(40)])
        second = Image.new("RGB", (40, 40), (0, 0, 0))  # far over the budget
        self._captures(monkeypatch, first, second)
        with pytest.raises(AssertionError) as exc:
            _save()
        assert "had not settled" in str(exc.value)
        assert path.read_bytes() == before

    def test_a_blank_capture_is_not_reminted(self, expected_dir, monkeypatch):
        path = self._baseline(expected_dir, Image.new("RGB", (40, 40), (0, 0, 0)))
        before = path.read_bytes()
        self._captures(monkeypatch, Image.new("RGB", (40, 40), (255, 255, 255)))
        with pytest.raises(AssertionError) as exc:
            _save()
        assert "blank" in str(exc.value)
        assert path.read_bytes() == before

    def test_a_missing_baseline_is_minted(self, expected_dir, monkeypatch):
        self._captures(monkeypatch, _painted(), _painted())
        path = _save()
        assert os.path.isfile(path)


class TestVolatileText:
    """What a re-mint does not count: text a run writes fresh every time.

    The patterns run as JavaScript regexes in the page; these use Python's
    re, which reads them the same way.
    """

    @staticmethod
    def _found(text):
        return [m.group(0) for p in e2e_utils.VOLATILE_TEXT for m in re.finditer(p, text)]

    @pytest.mark.parametrize("text, fresh", [
        ("[1]: Saved to file: 1790694581680_354ba6af", "1790694581680_354ba6af"),
        ("computed.n2dd5dee2-cc0d-4935-8907-f59f7f5a6349@1", "2dd5dee2-cc0d-4935-8907-f59f7f5a6349"),
        ("node c4217856-b247-449d-b7ff-451e772b02a2", "c4217856-b247-449d-b7ff-451e772b02a2"),
        ("id 3f2a9c1e0b7d4e6f8a9b0c1d2e3f4a5b", "3f2a9c1e0b7d4e6f8a9b0c1d2e3f4a5b"),
        ("proposal 0e4210b6", "0e4210b6"),
        ("ad6e9e15 pending", "ad6e9e15"),
        ("user.configured.d3dp5whi8@1", "d3dp5whi8"),
        ("v 131 · 9/29/2026", "9/29/2026"),
        ("9/29/2026, 2:59:55 PM", "2:59:55 PM"),
        ("0.16.158", "0.16.158"),
    ])
    def test_fresh_text_is_found(self, text, fresh):
        assert fresh in self._found(text)

    @pytest.mark.parametrize("text", [
        "v0.1.0", "0.16.158 (not isolated)", "Saved to file:", "12:00", "1234",
        "curio.builtin@1", "data.utk.chicago-boundary@1", "Configured Metadata Package",
        "12345678", "deadbeef", "population 20240501",
    ])
    def test_other_text_is_counted(self, text):
        assert self._found(text) == []

    def test_the_mask_pads_each_box_and_stays_inside_the_image(self):
        mask = e2e_utils._box_mask([(2.5, 3.2, 4.1, 5.0), (-5, -5, 1, 1)], (10, 10))
        assert mask[2:6, 1:6].all() and mask[0:2, 0:2].all()
        assert int(mask.sum()) == 4 * 5 + 2 * 2
        assert not mask[6, 3] and not mask[3, 6]


class _RunningNodePage:
    """A page where one node never stops running."""

    def evaluate(self, script, *a, **k):
        return ["node-still-drawing"] if "data-id" in script else None

    def wait_for_function(self, *a, **k):
        raise e2e_utils.PlaywrightTimeoutError("still running")


class TestARunningNode:
    def test_it_is_not_captured(self, expected_dir, monkeypatch):
        # A view below a node that just ran draws on its own after that node's
        # Done; a capture in that gap would record it mid-draw.
        monkeypatch.setattr(e2e_utils, "MINT_BASELINES", True)
        monkeypatch.setattr(e2e_utils, "_capture_full_page", lambda page: _painted())
        with pytest.raises(AssertionError) as exc:
            e2e_utils.save_workflow_test_screenshot(
                _RunningNodePage(), "some-scene.json", test_name="a-step",
                fit_reactflow=False,
            )
        assert "node-still-drawing" in str(exc.value)
        assert list(expected_dir.iterdir()) == []
