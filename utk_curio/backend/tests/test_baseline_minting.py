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

The switch it replaced, ``CURIO_E2E_REQUIRE_BASELINES``, keyed the decision off
run shape: mint in a serial run, refuse under xdist. Wrong axis. Serialness says
nothing about whether a capture deserves to become the reference, and the
capture that would have broken CI was minted serially.

These tests drive ``save_workflow_test_screenshot``'s control flow directly with
a stub page, so they need no browser and no stack.
"""
from __future__ import annotations

import os

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
        **kw,
    )


def test_the_default_is_not_to_mint():
    # The module default is what every ordinary run gets: local or CI, serial or
    # parallel. Only --mint-baselines flips it (tests/conftest.py).
    assert e2e_utils.MINT_BASELINES is False


class TestWithoutTheFlag:
    def test_a_missing_baseline_fails(self, expected_dir, monkeypatch):
        monkeypatch.setattr(e2e_utils, "MINT_BASELINES", False)
        with pytest.raises(AssertionError) as exc:
            _save()
        assert "--mint-baselines" in str(exc.value)

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
