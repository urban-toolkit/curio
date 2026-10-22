"""THE shared node-appearance utility (memo dev/89 §3).

One validation/normalization/derivation truth for the per-node
``appearance.backgroundColor`` used by: build-request parsing
(``build_models``), proposal minting and Apply (``agents.services``), and the
frontend's color logic. The rules take the palette, the inks, the links and
the contrast as a :class:`NotePalette`: Curio's is ``noteColors.json`` in the
frontend's ``src/contracts/``, which the built-in Note draws with and
``application/note_palette.py`` reads, so this layer reads no file. No caller
re-implements color rules; forking this logic is the bug the memo forbids.

Contract (dev/89 §3, the research notes' definition-of-done profile):

* Named palette — ``yellow`` (default), ``pink``, ``blue``, ``green``,
  ``orange``, ``lavender`` — mapped centrally to design-token hex values.
* Custom colors: a normalized six-digit ``#RRGGBB`` only. Shorthand hex,
  alpha channels, ``rgb()``/gradients/``url()``/CSS expressions, and
  whitespace tricks are rejected loudly.
* Accessibility is part of validity: a background no foreground can reach
  WCAG AA (4.5:1) against is REJECTED at normalization time, not rendered
  unreadable (dev/89 §6).
* Legacy tolerance lives in ONE place: :func:`resolve_background` maps a
  missing/invalid stored value to the default yellow for rendering — new
  writes always go through :func:`normalize_appearance`, which raises.

Derivations (:func:`derived_colors`) hand the behavior its foreground,
muted-foreground, border, link, and focus colors — the model and the stored
spec never carry raw text/border CSS (dev/89 §3).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class NotePalette:
    """What a node's appearance is checked and drawn in."""

    #: The central palette: design tokens, by the name a note's appearance gives.
    colors: Mapping[str, str]
    #: The palette name of a note that names none or one that cannot be read.
    default_name: str
    #: The ink pair the behavior renders with.
    dark_foreground: str
    light_foreground: str
    #: The link colors under dark ink and under light ink, falling back to the
    #: ink when neither clears the contrast against the background.
    link_on_light: str
    link_on_dark: str
    #: The contrast an ink must reach (WCAG AA for normal text).
    min_contrast: float

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "NotePalette":
        """The palette as ``noteColors.json`` writes it."""
        return cls(
            colors=dict(data["colors"]),
            default_name=data["defaultColor"],
            dark_foreground=data["inks"]["dark"],
            light_foreground=data["inks"]["light"],
            link_on_light=data["links"]["onLight"],
            link_on_dark=data["links"]["onDark"],
            min_contrast=data["minContrast"],
        )

    @property
    def default_background(self) -> str:
        return self.colors[self.default_name]


_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class AppearanceError(ValueError):
    """Raised when a requested appearance value is invalid or inaccessible."""


def _rgb(hex_color: str) -> tuple[int, int, int]:
    return (int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16))


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02x}" for c in rgb)


def _luminance(hex_color: str) -> float:
    def _lin(channel: int) -> float:
        s = channel / 255.0
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = _rgb(hex_color)
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast_ratio(hex_a: str, hex_b: str) -> float:
    """WCAG contrast ratio between two ``#RRGGBB`` colors."""
    la, lb = _luminance(hex_a), _luminance(hex_b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def _best_foreground(background: str, palette: NotePalette) -> tuple[str, float]:
    dark = contrast_ratio(background, palette.dark_foreground)
    light = contrast_ratio(background, palette.light_foreground)
    return (palette.dark_foreground, dark) if dark >= light else (palette.light_foreground, light)


def normalize_background(value: Any, palette: NotePalette) -> str:
    """Normalize one requested background to a lowercase ``#RRGGBB``.

    Accepts a palette name (case-insensitive) or a six-digit hex. Everything
    else — shorthand hex, alpha, CSS functions/keywords, embedded whitespace
    — raises :class:`AppearanceError`, as does a hex no foreground can read
    at WCAG AA.
    """
    if not isinstance(value, str) or not value:
        raise AppearanceError(
            "backgroundColor must be a palette name "
            f"({', '.join(sorted(palette.colors))}) or a six-digit #RRGGBB hex"
        )
    candidate = value.strip()
    if candidate != value or any(c.isspace() for c in candidate):
        raise AppearanceError(f"backgroundColor {value!r} contains whitespace — refused")
    named = palette.colors.get(candidate.lower())
    if named is not None:
        return named
    if not _HEX_RE.match(candidate):
        raise AppearanceError(
            f"backgroundColor {value!r} is not a palette name or six-digit "
            "#RRGGBB hex (shorthand hex, alpha channels, and CSS expressions "
            "are refused)"
        )
    normalized = candidate.lower()
    _, best = _best_foreground(normalized, palette)
    if best < palette.min_contrast:
        raise AppearanceError(
            f"backgroundColor {value!r} cannot produce WCAG AA text contrast "
            f"(best foreground reaches {best:.2f}:1, needs {palette.min_contrast}:1) — "
            "choose a lighter or darker color"
        )
    return normalized


def normalize_appearance(raw: Any, palette: NotePalette) -> dict[str, str] | None:
    """Validate one appearance object: ``None`` stays ``None``; otherwise
    exactly ``{"backgroundColor": <name-or-hex>}`` normalized to hex."""
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise AppearanceError("appearance must be an object")
    unknown = set(raw) - {"backgroundColor"}
    if unknown:
        raise AppearanceError(
            f"appearance has unknown keys {sorted(unknown)}; only "
            "backgroundColor is supported"
        )
    if "backgroundColor" not in raw:
        raise AppearanceError("appearance requires backgroundColor")
    return {"backgroundColor": normalize_background(raw["backgroundColor"], palette)}


def resolve_background(stored: Any, palette: NotePalette) -> str:
    """Render-path tolerance: a stored value that is missing or no longer
    valid falls back to the default yellow — QUIETLY, because legacy specs
    are data to render, not requests to refuse (dev/89 §6)."""
    try:
        return normalize_background(stored, palette)
    except AppearanceError:
        return palette.default_background


def _shade(hex_color: str, factor: float) -> str:
    """factor < 1 darkens toward black; factor > 1 lightens toward white."""
    r, g, b = _rgb(hex_color)
    if factor <= 1:
        return _hex((r * factor, g * factor, b * factor))
    t = min(1.0, factor - 1.0)
    return _hex((r + (255 - r) * t, g + (255 - g) * t, b + (255 - b) * t))


def derived_colors(background: Any, palette: NotePalette) -> dict[str, str]:
    """Foreground, muted text, border, link, and focus colors for one
    background — every pair AA-safe by construction. Computed at render
    time, never persisted (dev/89 §4)."""
    bg = resolve_background(background, palette)
    foreground, _ = _best_foreground(bg, palette)
    dark_ink = foreground == palette.dark_foreground
    link = palette.link_on_light if dark_ink else palette.link_on_dark
    if contrast_ratio(bg, link) < palette.min_contrast:
        link = foreground
    # Muted text: pull the ink 25% toward the background; step back toward
    # full ink until it clears AA (always terminates at the foreground).
    fr, fg_, fb = _rgb(foreground)
    br, bgc, bb = _rgb(bg)
    for mix in (0.25, 0.15, 0.0):
        muted = _hex((fr + (br - fr) * mix, fg_ + (bgc - fg_) * mix, fb + (bb - fb) * mix))
        if contrast_ratio(bg, muted) >= palette.min_contrast:
            break
    border = _shade(bg, 0.82 if dark_ink else 1.35)
    return {
        "background": bg,
        "foreground": foreground,
        "mutedForeground": muted,
        "border": border,
        "link": link,
        "focus": foreground,
    }
