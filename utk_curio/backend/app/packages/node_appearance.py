"""THE shared node-appearance utility (memo dev/89 §3).

One validation/normalization/derivation truth for the per-node
``appearance.backgroundColor`` used by: build-request parsing
(``build_models``), proposal minting and Apply (``agents.services``), and —
mirrored constant-for-constant — the frontend behavior's color logic. No
caller re-implements color rules; forking this logic is the bug the memo
forbids.

Contract (dev/89 §3 "Node Researcher DOD profile"):

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
from typing import Any, Mapping

#: Central palette — design tokens, mirrored by the frontend utility.
NAMED_COLORS: dict[str, str] = {
    "yellow": "#fef3c0",
    "pink": "#fbd3e0",
    "blue": "#cfe8f7",
    "green": "#d5f0d1",
    "orange": "#ffddc0",
    "lavender": "#e4dcf7",
}

DEFAULT_COLOR_NAME = "yellow"
DEFAULT_BACKGROUND = NAMED_COLORS[DEFAULT_COLOR_NAME]

# WCAG AA for normal text.
MIN_CONTRAST = 4.5

# Foreground candidates: the ink pair the behavior renders with.
_DARK_FOREGROUND = "#1f2430"
_LIGHT_FOREGROUND = "#ffffff"
# Link candidates (light-bg blue / dark-bg blue), falling back to the
# foreground when neither clears AA against the background.
_LINK_ON_LIGHT = "#1d4ed8"
_LINK_ON_DARK = "#93c5fd"

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


def _best_foreground(background: str) -> tuple[str, float]:
    dark = contrast_ratio(background, _DARK_FOREGROUND)
    light = contrast_ratio(background, _LIGHT_FOREGROUND)
    return (_DARK_FOREGROUND, dark) if dark >= light else (_LIGHT_FOREGROUND, light)


def normalize_background(value: Any) -> str:
    """Normalize one requested background to a lowercase ``#RRGGBB``.

    Accepts a palette name (case-insensitive) or a six-digit hex. Everything
    else — shorthand hex, alpha, CSS functions/keywords, embedded whitespace
    — raises :class:`AppearanceError`, as does a hex no foreground can read
    at WCAG AA.
    """
    if not isinstance(value, str) or not value:
        raise AppearanceError(
            "backgroundColor must be a palette name "
            f"({', '.join(sorted(NAMED_COLORS))}) or a six-digit #RRGGBB hex"
        )
    candidate = value.strip()
    if candidate != value or any(c.isspace() for c in candidate):
        raise AppearanceError(f"backgroundColor {value!r} contains whitespace — refused")
    named = NAMED_COLORS.get(candidate.lower())
    if named is not None:
        return named
    if not _HEX_RE.match(candidate):
        raise AppearanceError(
            f"backgroundColor {value!r} is not a palette name or six-digit "
            "#RRGGBB hex (shorthand hex, alpha channels, and CSS expressions "
            "are refused)"
        )
    normalized = candidate.lower()
    _, best = _best_foreground(normalized)
    if best < MIN_CONTRAST:
        raise AppearanceError(
            f"backgroundColor {value!r} cannot produce WCAG AA text contrast "
            f"(best foreground reaches {best:.2f}:1, needs {MIN_CONTRAST}:1) — "
            "choose a lighter or darker color"
        )
    return normalized


def normalize_appearance(raw: Any) -> dict[str, str] | None:
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
    return {"backgroundColor": normalize_background(raw["backgroundColor"])}


def resolve_background(stored: Any) -> str:
    """Render-path tolerance: a stored value that is missing or no longer
    valid falls back to the default yellow — QUIETLY, because legacy specs
    are data to render, not requests to refuse (dev/89 §6)."""
    try:
        return normalize_background(stored)
    except AppearanceError:
        return DEFAULT_BACKGROUND


def _shade(hex_color: str, factor: float) -> str:
    """factor < 1 darkens toward black; factor > 1 lightens toward white."""
    r, g, b = _rgb(hex_color)
    if factor <= 1:
        return _hex((r * factor, g * factor, b * factor))
    t = min(1.0, factor - 1.0)
    return _hex((r + (255 - r) * t, g + (255 - g) * t, b + (255 - b) * t))


def derived_colors(background: Any) -> dict[str, str]:
    """Foreground, muted text, border, link, and focus colors for one
    background — every pair AA-safe by construction. Computed at render
    time, never persisted (dev/89 §4)."""
    bg = resolve_background(background)
    foreground, _ = _best_foreground(bg)
    dark_ink = foreground == _DARK_FOREGROUND
    link = _LINK_ON_LIGHT if dark_ink else _LINK_ON_DARK
    if contrast_ratio(bg, link) < MIN_CONTRAST:
        link = foreground
    # Muted text: pull the ink 25% toward the background; step back toward
    # full ink until it clears AA (always terminates at the foreground).
    fr, fg_, fb = _rgb(foreground)
    br, bgc, bb = _rgb(bg)
    for mix in (0.25, 0.15, 0.0):
        muted = _hex((fr + (br - fr) * mix, fg_ + (bgc - fg_) * mix, fb + (bb - fb) * mix))
        if contrast_ratio(bg, muted) >= MIN_CONTRAST:
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
