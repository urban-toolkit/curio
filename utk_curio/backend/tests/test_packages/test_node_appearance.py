"""Tests for :mod:`utk_curio.backend.app.packages.node_appearance` (dev/89
commit 8): the ONE shared color truth — palette mapping, six-digit hex
normalization, refusals (shorthand/alpha/CSS/whitespace/inaccessible),
legacy render fallback, and AA-safe derived colors.
"""

from __future__ import annotations

import pytest

from utk_curio.backend.app.packages.node_appearance import (
    DEFAULT_BACKGROUND,
    MIN_CONTRAST,
    NAMED_COLORS,
    AppearanceError,
    contrast_ratio,
    derived_colors,
    normalize_appearance,
    normalize_background,
    resolve_background,
)


class TestNormalize:
    def test_named_palette_maps_centrally(self):
        assert set(NAMED_COLORS) == {"yellow", "pink", "blue", "green",
                                     "orange", "lavender"}
        assert normalize_background("yellow") == DEFAULT_BACKGROUND
        assert normalize_background("PINK") == NAMED_COLORS["pink"]
        assert normalize_background("Lavender") == NAMED_COLORS["lavender"]

    def test_six_digit_hex_normalizes_lowercase(self):
        assert normalize_background("#336699") == "#336699"
        assert normalize_background("#AABBCC") == "#aabbcc"

    @pytest.mark.parametrize("bad", [
        "#abc",            # shorthand
        "#aabbccdd",       # alpha
        "rgb(1,2,3)", "linear-gradient(red, blue)", "url(x)",
        "red",             # CSS keyword, not in the palette
        " #aabbcc", "#aabbcc ", "#aab bcc",  # whitespace tricks
        "", None, 42,
    ])
    def test_refusals(self, bad):
        with pytest.raises(AppearanceError):
            normalize_background(bad)

    def test_inaccessible_hex_refused(self):
        # Mid-gray: neither dark ink nor white reaches 4.5:1.
        with pytest.raises(AppearanceError, match="WCAG AA"):
            normalize_background("#777777")

    def test_appearance_object_shape(self):
        assert normalize_appearance(None) is None
        assert normalize_appearance({"backgroundColor": "blue"}) == {
            "backgroundColor": NAMED_COLORS["blue"]}
        with pytest.raises(AppearanceError, match="unknown keys"):
            normalize_appearance({"backgroundColor": "blue", "border": "red"})
        with pytest.raises(AppearanceError, match="requires backgroundColor"):
            normalize_appearance({})
        with pytest.raises(AppearanceError, match="must be an object"):
            normalize_appearance("blue")


class TestResolveLegacy:
    def test_invalid_or_missing_falls_back_quietly(self):
        assert resolve_background(None) == DEFAULT_BACKGROUND
        assert resolve_background("chartreuse-ish") == DEFAULT_BACKGROUND
        assert resolve_background("#777777") == DEFAULT_BACKGROUND  # stored legacy
        assert resolve_background("green") == NAMED_COLORS["green"]


class TestDerivedColors:
    @pytest.mark.parametrize("value", sorted(NAMED_COLORS) + ["#336699", "#1a1a2e"])
    def test_every_pair_is_aa_safe(self, value):
        d = derived_colors(value)
        assert contrast_ratio(d["background"], d["foreground"]) >= MIN_CONTRAST
        assert contrast_ratio(d["background"], d["mutedForeground"]) >= MIN_CONTRAST
        assert contrast_ratio(d["background"], d["link"]) >= MIN_CONTRAST
        assert set(d) == {"background", "foreground", "mutedForeground",
                          "border", "link", "focus"}

    def test_dark_background_gets_light_ink(self):
        d = derived_colors("#1a1a2e")
        assert d["foreground"] == "#ffffff"

    def test_light_background_gets_dark_ink_and_light_link(self):
        d = derived_colors("yellow")
        assert d["foreground"] == "#1f2430"
        assert d["link"] == "#1d4ed8"

    def test_render_path_never_raises(self):
        # Derivations ride resolve_background's legacy tolerance.
        assert derived_colors("garbage")["background"] == DEFAULT_BACKGROUND


class TestContrastRatio:
    def test_known_values(self):
        assert contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0, abs=0.01)
        assert contrast_ratio("#ffffff", "#ffffff") == pytest.approx(1.0, abs=0.001)
        # Symmetric.
        assert contrast_ratio("#336699", "#ffffff") == contrast_ratio("#ffffff", "#336699")
