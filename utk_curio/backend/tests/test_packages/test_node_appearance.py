"""Tests for :mod:`utk_curio.backend.app.packages.domain.node_appearance` (dev/89
commit 8): the ONE shared color truth — palette mapping, six-digit hex
normalization, refusals (shorthand/alpha/CSS/whitespace/inaccessible),
legacy render fallback, and AA-safe derived colors. The rules take the
palette they check against; Curio's is ``NOTE_PALETTE``, read from
``noteColors.json`` by the application layer.
"""

from __future__ import annotations

import dataclasses

import pytest

from utk_curio.backend.app.packages.application.note_palette import NOTE_PALETTE as PALETTE
from utk_curio.backend.app.packages.domain.node_appearance import (
    AppearanceError,
    contrast_ratio,
    derived_colors,
    normalize_appearance,
    normalize_background,
    resolve_background,
)


class TestNormalize:
    def test_named_palette_maps_centrally(self):
        assert set(PALETTE.colors) == {"yellow", "pink", "blue", "green",
                                       "orange", "lavender"}
        assert normalize_background("yellow", PALETTE) == PALETTE.default_background
        assert normalize_background("PINK", PALETTE) == PALETTE.colors["pink"]
        assert normalize_background("Lavender", PALETTE) == PALETTE.colors["lavender"]

    def test_six_digit_hex_normalizes_lowercase(self):
        assert normalize_background("#336699", PALETTE) == "#336699"
        assert normalize_background("#AABBCC", PALETTE) == "#aabbcc"

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
            normalize_background(bad, PALETTE)

    def test_inaccessible_hex_refused(self):
        # Mid-gray: neither dark ink nor white reaches 4.5:1.
        with pytest.raises(AppearanceError, match="WCAG AA"):
            normalize_background("#777777", PALETTE)

    def test_appearance_object_shape(self):
        assert normalize_appearance(None, PALETTE) is None
        assert normalize_appearance({"backgroundColor": "blue"}, PALETTE) == {
            "backgroundColor": PALETTE.colors["blue"]}
        with pytest.raises(AppearanceError, match="unknown keys"):
            normalize_appearance({"backgroundColor": "blue", "border": "red"}, PALETTE)
        with pytest.raises(AppearanceError, match="requires backgroundColor"):
            normalize_appearance({}, PALETTE)
        with pytest.raises(AppearanceError, match="must be an object"):
            normalize_appearance("blue", PALETTE)

    def test_the_rules_check_against_the_palette_they_are_handed(self):
        # The domain reads no file: another palette names other colors.
        mint = dataclasses.replace(PALETTE, colors={"mint": "#d5f0d1"}, default_name="mint")
        assert normalize_background("mint", mint) == "#d5f0d1"
        with pytest.raises(AppearanceError, match=r"\(mint\)"):
            normalize_background(None, mint)
        with pytest.raises(AppearanceError, match="palette name"):
            normalize_background("yellow", mint)
        assert resolve_background("yellow", mint) == "#d5f0d1"


class TestResolveLegacy:
    def test_invalid_or_missing_falls_back_quietly(self):
        assert resolve_background(None, PALETTE) == PALETTE.default_background
        assert resolve_background("chartreuse-ish", PALETTE) == PALETTE.default_background
        assert resolve_background("#777777", PALETTE) == PALETTE.default_background  # stored legacy
        assert resolve_background("green", PALETTE) == PALETTE.colors["green"]


class TestDerivedColors:
    @pytest.mark.parametrize("value", sorted(PALETTE.colors) + ["#336699", "#1a1a2e"])
    def test_every_pair_is_aa_safe(self, value):
        d = derived_colors(value, PALETTE)
        assert contrast_ratio(d["background"], d["foreground"]) >= PALETTE.min_contrast
        assert contrast_ratio(d["background"], d["mutedForeground"]) >= PALETTE.min_contrast
        assert contrast_ratio(d["background"], d["link"]) >= PALETTE.min_contrast
        assert set(d) == {"background", "foreground", "mutedForeground",
                          "border", "link", "focus"}

    def test_dark_background_gets_light_ink(self):
        d = derived_colors("#1a1a2e", PALETTE)
        assert d["foreground"] == "#ffffff"

    def test_light_background_gets_dark_ink_and_light_link(self):
        d = derived_colors("yellow", PALETTE)
        assert d["foreground"] == "#1f2430"
        assert d["link"] == "#1d4ed8"

    def test_render_path_never_raises(self):
        # Derivations ride resolve_background's legacy tolerance.
        assert derived_colors("garbage", PALETTE)["background"] == PALETTE.default_background


class TestContrastRatio:
    def test_known_values(self):
        assert contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0, abs=0.01)
        assert contrast_ratio("#ffffff", "#ffffff") == pytest.approx(1.0, abs=0.001)
        # Symmetric.
        assert contrast_ratio("#336699", "#ffffff") == contrast_ratio("#ffffff", "#336699")
