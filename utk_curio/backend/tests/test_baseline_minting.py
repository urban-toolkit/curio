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

from utk_curio.backend.tests.test_frontend.utils import capture_waits
from utk_curio.backend.tests.test_frontend.utils import screenshots as e2e_utils


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


#: Names the GPU kind of a run (CI's test-gpu job sets it from its runner).
GPU_KIND_ENV = "CURIO_E2E_GPU_KIND"


@pytest.fixture()
def expected_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(
        e2e_utils, "WORKFLOW_SCREENSHOT_EXPECTED_DIR", str(tmp_path)
    )
    # A run without a GPU kind, unless a test gives it one.
    monkeypatch.delenv(GPU_KIND_ENV, raising=False)
    monkeypatch.setattr(e2e_utils, "REMINT_GPU_KIND_FRAMES", (), raising=False)
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
        monkeypatch.setattr(e2e_utils, "REMINT_GPU_KIND_FRAMES", (), raising=False)

    def test_a_gpu_kind_remint_needs_a_remint(self):
        with pytest.raises(pytest.UsageError) as exc:
            e2e_utils.allow_baseline_writes(
                mint=False, remint=False, gpu_kind="utk-gpu:07-x.png",
                environ={"GITHUB_ACTIONS": "true", GPU_KIND_ENV: "utk-gpu"})
        assert "--remint-gpu-kind" in str(exc.value)
        assert e2e_utils.REMINT_GPU_KIND_FRAMES == ()

    @pytest.mark.parametrize("value", [
        "07-x.png",            # no kind
        "h100:07-x.png",       # not a GPU kind
        "utk-gpu:",            # no frame
        "utk-gpu: , ",         # no frame either
    ])
    def test_a_gpu_kind_remint_names_a_kind_and_its_frames(self, value):
        with pytest.raises(pytest.UsageError) as exc:
            e2e_utils.allow_baseline_writes(
                mint=False, remint=True, gpu_kind=value,
                environ={"GITHUB_ACTIONS": "true", GPU_KIND_ENV: "utk-gpu"})
        assert "--remint-gpu-kind" in str(exc.value)
        assert "utk-gpu" in str(exc.value) and "arcade-gpu" in str(exc.value)
        assert e2e_utils.REMINT_GPU_KIND_FRAMES == ()

    @pytest.mark.parametrize("run_kind", ["arcade-gpu", None])
    def test_a_gpu_kind_remint_runs_only_on_that_kind(self, run_kind):
        # A baseline of a GPU kind is what that GPU draws: a job on another
        # GPU, or on none, would write its own drawing under that kind's name.
        environ = {"GITHUB_ACTIONS": "true"}
        if run_kind:
            environ[GPU_KIND_ENV] = run_kind
        with pytest.raises(pytest.UsageError) as exc:
            e2e_utils.allow_baseline_writes(
                mint=False, remint=True, gpu_kind="utk-gpu:07-x.png", environ=environ)
        assert "utk-gpu" in str(exc.value)
        assert "gpu_pool" in str(exc.value)
        assert e2e_utils.REMINT_BASELINES is False
        assert e2e_utils.REMINT_GPU_KIND_FRAMES == ()

    def test_a_gpu_kind_remint_is_refused_off_ci(self):
        with pytest.raises(pytest.UsageError) as exc:
            e2e_utils.allow_baseline_writes(
                mint=False, remint=True, gpu_kind="utk-gpu:07-x.png",
                environ={GPU_KIND_ENV: "utk-gpu"})
        assert "--remint-baselines runs on CI only" in str(exc.value)
        assert e2e_utils.REMINT_GPU_KIND_FRAMES == ()

    def test_a_gpu_kind_remint_is_kept_on_a_job_of_that_kind(self):
        e2e_utils.allow_baseline_writes(
            mint=False, remint=True, gpu_kind="utk-gpu: 07-x.png, ,08-y.png",
            environ={"GITHUB_ACTIONS": "true", GPU_KIND_ENV: "utk-gpu"})
        assert e2e_utils.REMINT_BASELINES is True
        assert e2e_utils.REMINT_GPU_KIND_FRAMES == ("07-x.png", "08-y.png")

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


def _default_drawing() -> Image.Image:
    return _painted_at((1, 1))


def _other_gpus_drawing() -> Image.Image:
    """The same frame from another GPU model: a quarter of it, past any budget."""
    return _painted_at(*[(x, y) for x in range(20) for y in range(20)])


def _holds(path, img) -> bool:
    return Image.open(path).convert("RGB").tobytes() == img.tobytes()


class TestBaselinesPerGpuKind:
    """A frame two GPU models draw differently keeps a baseline per GPU kind.

    Example 07's plot close-up draws 6.06% differently on utk-gpu (an RTX PRO
    6000) than on the arcade runners (an H100), past its 5% budget, so a run
    whose GPU job landed on utk-gpu failed against arcade's baseline. Such a
    frame also has ``<name>.<kind>.png``, and a run of that GPU kind compares
    with it. Every other run, and every frame without one, uses the default
    baseline as before.
    """

    DEFAULT = "screenshot_some-scene_a-step.png"
    UTK = "screenshot_some-scene_a-step.utk-gpu.png"

    @pytest.fixture(autouse=True)
    def _ordinary_run(self, expected_dir, monkeypatch):
        monkeypatch.setattr(e2e_utils, "MINT_BASELINES", False)
        monkeypatch.setattr(e2e_utils, "REMINT_BASELINES", False)
        monkeypatch.setattr(e2e_utils, "REMINT_FORCE", ())
        monkeypatch.setattr(e2e_utils, "_wait_for_webfont", lambda page: True)

    def _baselines(self, expected_dir, *, utk=True):
        _default_drawing().save(expected_dir / self.DEFAULT)
        if utk:
            _other_gpus_drawing().save(expected_dir / self.UTK)
        return expected_dir / self.DEFAULT, expected_dir / self.UTK

    def _captures(self, monkeypatch, *images):
        taken = list(images)
        monkeypatch.setattr(e2e_utils, "_capture_full_page", lambda page: taken.pop(0))
        return taken

    def test_the_kinds_baseline_sits_beside_the_default_one(self):
        # Built from the default name, never parsed back out of a file name:
        # baseline names hold dots of their own.
        default = "/x/screenshot_agent-run_agent.curio.dataflow-builder.png"
        assert e2e_utils.kind_baseline(default, "utk-gpu") == (
            "/x/screenshot_agent-run_agent.curio.dataflow-builder.utk-gpu.png")
        assert e2e_utils.GPU_KINDS == ("arcade-gpu", "utk-gpu", "utk-desktop")

    def test_a_run_of_a_kind_compares_with_its_kinds_baseline(self, expected_dir, monkeypatch):
        _, utk = self._baselines(expected_dir)
        monkeypatch.setenv(GPU_KIND_ENV, "utk-gpu")
        self._captures(monkeypatch, _other_gpus_drawing())
        assert _save() == str(utk)

    def test_a_run_without_a_kind_compares_with_the_default(self, expected_dir, monkeypatch):
        # A local run or a CPU runner: nothing changes.
        default, _ = self._baselines(expected_dir)
        self._captures(monkeypatch, _default_drawing())
        assert _save() == str(default)

    def test_a_run_of_another_kind_compares_with_the_default(self, expected_dir, monkeypatch):
        default, _ = self._baselines(expected_dir)
        monkeypatch.setenv(GPU_KIND_ENV, "arcade-gpu")
        self._captures(monkeypatch, _other_gpus_drawing())
        with pytest.raises(AssertionError, match=r"Screenshot regression for screenshot_some-scene_a-step\.png"):
            _save()

    def test_a_frame_without_a_baseline_of_the_runs_kind_compares_with_the_default(self, expected_dir, monkeypatch):
        default, _ = self._baselines(expected_dir, utk=False)
        monkeypatch.setenv(GPU_KIND_ENV, "utk-gpu")
        self._captures(monkeypatch, _default_drawing())
        assert _save() == str(default)

    def test_an_unknown_kind_is_refused(self, expected_dir, monkeypatch):
        self._baselines(expected_dir)
        monkeypatch.setenv(GPU_KIND_ENV, "h100")
        self._captures(monkeypatch, _default_drawing())
        with pytest.raises(ValueError) as exc:
            _save()
        assert "arcade-gpu" in str(exc.value) and "utk-gpu" in str(exc.value)

    def test_a_remint_on_a_kind_rewrites_that_kinds_baseline_not_the_default(self, expected_dir, monkeypatch):
        # Re-mint a frame on the GPU kind its baseline came from: a utk-gpu
        # capture written over the default would fail every arcade run.
        monkeypatch.setattr(e2e_utils, "REMINT_BASELINES", True)
        default, utk = self._baselines(expected_dir)
        before = default.read_bytes()
        monkeypatch.setenv(GPU_KIND_ENV, "utk-gpu")
        new = _painted_at(*[(x, 30) for x in range(40)])
        self._captures(monkeypatch, new, new.copy())
        assert _save() == str(utk)
        assert _holds(utk, new)
        assert default.read_bytes() == before

    def test_a_frame_named_for_its_kind_gets_a_baseline_of_that_kind(self, expected_dir, monkeypatch):
        monkeypatch.setattr(e2e_utils, "REMINT_BASELINES", True)
        monkeypatch.setattr(e2e_utils, "REMINT_GPU_KIND_FRAMES", ("some-scene_a-step.png",), raising=False)
        default, utk = self._baselines(expected_dir, utk=False)
        before = default.read_bytes()
        monkeypatch.setenv(GPU_KIND_ENV, "utk-gpu")
        left = self._captures(monkeypatch, _other_gpus_drawing(), _other_gpus_drawing())
        assert _save() == str(utk)
        assert _holds(utk, _other_gpus_drawing())
        assert default.read_bytes() == before
        assert left == []  # captured twice: the new baseline, and the check that it held

    def test_a_named_frame_its_kind_draws_like_the_default_gets_no_baseline_of_its_own(self, expected_dir, monkeypatch):
        monkeypatch.setattr(e2e_utils, "REMINT_BASELINES", True)
        monkeypatch.setattr(e2e_utils, "REMINT_GPU_KIND_FRAMES", ("some-scene_a-step.png",), raising=False)
        default, utk = self._baselines(expected_dir, utk=False)
        before = default.read_bytes()
        monkeypatch.setenv(GPU_KIND_ENV, "utk-gpu")
        self._captures(monkeypatch, _default_drawing())
        assert _save() == str(default)
        assert not utk.exists()
        assert default.read_bytes() == before

    def test_a_gpu_kind_remint_writes_only_the_frames_it_names(self, expected_dir, monkeypatch):
        # The run is on another GPU than most baselines came from, so every
        # frame it does not name is compared, never written: not over its
        # default baseline, and not as a baseline of the kind.
        monkeypatch.setattr(e2e_utils, "REMINT_BASELINES", True)
        monkeypatch.setattr(e2e_utils, "REMINT_GPU_KIND_FRAMES", ("another-scene",), raising=False)
        default, _ = self._baselines(expected_dir, utk=False)
        before = default.read_bytes()
        monkeypatch.setenv(GPU_KIND_ENV, "utk-gpu")
        moved = _painted_at((1, 1), *[(x, 30) for x in range(4)])  # over the re-mint floor, within budget
        left = self._captures(monkeypatch, moved, moved.copy())
        assert _save() == str(default)
        assert default.read_bytes() == before
        assert sorted(p.name for p in expected_dir.iterdir()) == [self.DEFAULT]
        assert len(left) == 1  # one capture: a comparison, not a re-mint

    def test_a_gpu_kind_remint_compares_the_frames_it_does_not_name(self, expected_dir, monkeypatch):
        monkeypatch.setattr(e2e_utils, "REMINT_BASELINES", True)
        monkeypatch.setattr(e2e_utils, "REMINT_GPU_KIND_FRAMES", ("another-scene",), raising=False)
        self._baselines(expected_dir, utk=False)
        monkeypatch.setenv(GPU_KIND_ENV, "utk-gpu")
        self._captures(monkeypatch, _other_gpus_drawing(), _other_gpus_drawing())
        with pytest.raises(AssertionError, match="Screenshot regression"):
            _save()
        assert sorted(p.name for p in expected_dir.iterdir()) == [
            self.DEFAULT, "screenshot_some-scene_a-step_actual.png"]

    def test_a_new_kind_baseline_that_did_not_settle_is_taken_away(self, expected_dir, monkeypatch):
        monkeypatch.setattr(e2e_utils, "REMINT_BASELINES", True)
        monkeypatch.setattr(e2e_utils, "REMINT_GPU_KIND_FRAMES", ("some-scene_a-step.png",), raising=False)
        default, utk = self._baselines(expected_dir, utk=False)
        before = default.read_bytes()
        monkeypatch.setenv(GPU_KIND_ENV, "utk-gpu")
        self._captures(monkeypatch, _other_gpus_drawing(), Image.new("RGB", (40, 40), (0, 0, 0)))
        with pytest.raises(AssertionError) as exc:
            _save()
        assert "had not settled" in str(exc.value)
        assert not utk.exists()
        assert default.read_bytes() == before

    def test_force_names_a_frame_by_its_default_name_when_it_has_a_kinds_baseline(self, expected_dir, monkeypatch):
        # `remint_force` parts end in the default name's `.png`; that must
        # still reach the kind's baseline the frame is compared with.
        monkeypatch.setattr(e2e_utils, "REMINT_BASELINES", True)
        monkeypatch.setattr(e2e_utils, "REMINT_MIN_RATIO", 0.001)
        monkeypatch.setattr(e2e_utils, "REMINT_FORCE", ("some-scene_a-step.png",))
        default, utk = self._baselines(expected_dir)
        before = default.read_bytes()
        monkeypatch.setenv(GPU_KIND_ENV, "utk-gpu")
        new = _other_gpus_drawing()
        new.putpixel((30, 30), (0, 0, 0))  # 1 pixel of 1,600, under the floor
        self._captures(monkeypatch, new, new.copy())
        _save()
        assert _holds(utk, new)
        assert default.read_bytes() == before


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
        raise capture_waits.PlaywrightTimeoutError("still running")


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
