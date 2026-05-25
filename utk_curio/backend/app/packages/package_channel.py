"""Normalised package release channel (catalog).

Kept separate from :mod:`utk_curio.backend.app.packages.manifest` helpers that
need :class:`PackageManifest` to avoid import cycles with :mod:`catalog_family`.
"""

from __future__ import annotations

_DEFAULT_CHANNEL = "stable"
_VALID_CHANNELS = frozenset({"stable", "beta", "rc", "dev"})


def normalize_distribution_channel(raw: object) -> str:
    """Return a normalised channel string; default ``stable``.

    Accepts only lowercase alphanumerics and hyphens to keep payloads safe for UI.
    Unknown non-empty tokens that fail validation fall back to ``stable``.
    """
    if raw is None:
        return _DEFAULT_CHANNEL
    if not isinstance(raw, str) or not raw.strip():
        return _DEFAULT_CHANNEL
    s = raw.strip().lower()
    if s in _VALID_CHANNELS:
        return s
    if (
        len(s) <= 32
        and s[0].isalpha()
        and all(c.isalnum() or c == "-" for c in s)
    ):
        return s
    return _DEFAULT_CHANNEL
