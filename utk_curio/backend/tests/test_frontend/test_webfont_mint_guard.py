"""The mint guard must tell a loaded webfont from a fallback (#333).

The app's first font is Rubik, fetched from Google Fonts at runtime
(``src/index.html``); everything after it in the stack is a system fallback. So
whether that fetch lands decides the TYPEFACE, not just the antialiasing, and a
baseline minted while it was down disagrees with every later run forever, for a
reason no diff percentage explains.

This test exists because the obvious check is wrong. ``document.fonts.check(
'12px Rubik')`` answers "would this render?", and when the stylesheet never
arrived there is no ``@font-face`` for Rubik at all, so the family resolves
straight to a system font and check() reports **true**. Measured while writing
the guard, with ``fonts.googleapis.com`` blackholed: check() said true, the
capture came out in a different typeface, and it sat 9.05% away from the real
baseline - past the budget of both scenes the guard protects.

``_wait_for_webfont`` therefore asks whether a ``FontFace`` for the family is
actually loaded, which is the thing that is empty when the stylesheet is gone.
"""
from __future__ import annotations

import pytest

from utk_curio.backend.tests.test_frontend.utils import (
    WEBFONT_FAMILY,
    _wait_for_webfont,
)

_WITH_FONT = """<!doctype html><html><head>
<link href="https://fonts.googleapis.com/css2?family=Rubik:wght@300;400;600&display=swap"
      rel="stylesheet">
<style>body{font-family:Rubik,Arial,sans-serif}</style></head>
<body><span>boundaries neighborhoods chicago</span></body></html>"""

# The failure mode reproduced without touching DNS: no stylesheet, so no
# @font-face, so nothing for the family to resolve to but a system fallback.
_WITHOUT_FONT = """<!doctype html><html><head>
<style>body{font-family:Rubik,Arial,sans-serif}</style></head>
<body><span>boundaries neighborhoods chicago</span></body></html>"""


def test_it_reports_false_when_the_stylesheet_never_arrived(page):
    page.set_content(_WITHOUT_FONT, wait_until="load")
    assert _wait_for_webfont(page) is False, (
        f"the guard believed {WEBFONT_FAMILY} was loaded with no @font-face for "
        f"it; a baseline minted in this state would be in a fallback typeface"
    )


def test_it_reports_true_when_the_webfont_loads(page):
    page.set_content(_WITH_FONT, wait_until="load")
    if not _wait_for_webfont(page):
        pytest.skip(
            "fonts.googleapis.com is unreachable from this runner, so the "
            "positive case cannot be told apart from the bug it guards"
        )
    assert _wait_for_webfont(page) is True
