"""Per-user "Installed libraries" list.

The `/api/libraries` surface backs the "Installed libraries" menu (formerly
"Python packages"). Two distinct populations live here:

- **Standalone**: libraries the user added directly through the modal —
  things like ``numpy`` or ``scikit-learn==1.4.0`` that aren't tied to any
  installed node package. Persisted globally per user (one file per user),
  so the same set is available across every project. Stored as a JSON
  file at ``.curio/users/<user_key>/installed-libraries.json`` with shape::

      { "version": 1, "python": ["numpy", ...], "js": [...] }

- **Package-derived**: libraries declared by an installed node package's
  ``manifest.dependencies.{python,js}``. These are *read-only* from the
  modal's perspective — they get installed automatically by the catalog
  flow (see ``pip_runner.py``) and removed by ``prune_unreferenced_packages``.
  We surface them in the list so the user knows what's on their machine
  and why.

A corrupt or missing file is treated as an empty list (matches the
defaults/seed-state convention — startup is never blockable by a bad JSON).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from utk_curio.backend.app.packages.storage import (
    _user_key_segment,
    _users_base,
    list_user_packageages,
)

log = logging.getLogger(__name__)

_FILENAME = "installed-libraries.json"
_SCHEMA_VERSION = 1
_KINDS = ("python", "js")


@dataclass(frozen=True)
class LibraryEntry:
    name: str
    spec: str  # PEP 440 / npm-ish spec, or "" for "latest"
    kind: str  # "python" or "js"
    source: str  # "standalone" or "<packageId>@<major>"


@dataclass(frozen=True)
class LibraryList:
    standalone: dict[str, list[str]] = field(default_factory=dict)
    """``{"python": [...], "js": [...]}`` — bare spec strings as written
    by the user (``"numpy"``, ``"scikit-learn==1.4.0"``)."""
    from_packages: list[LibraryEntry] = field(default_factory=list)
    """Flat list with attribution; one entry per (package, library)."""


def _path(user_key: str) -> Path:
    return _users_base() / _user_key_segment(user_key) / _FILENAME


def _load_raw(user_key: str) -> dict:
    p = _path(user_key)
    if not p.is_file():
        return {"python": [], "js": []}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("Corrupt %s for %s — treating as empty", _FILENAME, user_key)
        return {"python": [], "js": []}
    if not isinstance(raw, dict):
        return {"python": [], "js": []}
    return {
        kind: [s for s in (raw.get(kind) or []) if isinstance(s, str) and s.strip()]
        for kind in _KINDS
    }


def _save_raw(user_key: str, data: dict) -> None:
    p = _path(user_key)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": _SCHEMA_VERSION,
        **{kind: sorted(set(data.get(kind) or [])) for kind in _KINDS},
    }
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def list_standalone(user_key: str) -> dict[str, list[str]]:
    """Return the user's standalone library list, kind-keyed."""
    return _load_raw(user_key)


def add_library(user_key: str, kind: str, spec: str) -> dict[str, list[str]]:
    """Add *spec* to the user's standalone list under *kind*; idempotent."""
    if kind not in _KINDS:
        raise ValueError(f"unknown kind {kind!r}; expected one of {_KINDS}")
    spec = (spec or "").strip()
    if not spec:
        raise ValueError("library spec must be non-empty")
    current = _load_raw(user_key)
    if spec not in current[kind]:
        current[kind].append(spec)
        _save_raw(user_key, current)
    return current


def remove_library(user_key: str, kind: str, spec: str) -> dict[str, list[str]]:
    """Drop *spec* from the user's standalone list; idempotent."""
    if kind not in _KINDS:
        raise ValueError(f"unknown kind {kind!r}; expected one of {_KINDS}")
    spec = (spec or "").strip()
    current = _load_raw(user_key)
    if spec in current[kind]:
        current[kind].remove(spec)
        _save_raw(user_key, current)
    return current


def package_derived(user_key: str) -> list[LibraryEntry]:
    """Read every installed package's manifest and collect their
    declared python + js deps. One entry per ``(package, lib)`` pair —
    no de-dup across packages so the user sees which package brought
    each library in.
    """
    from utk_curio.backend.app.packages.manifest import (
        ManifestError,
        load_packageage_manifest,
    )

    out: list[LibraryEntry] = []
    for package_path in list_user_packageages(user_key):
        try:
            m = load_packageage_manifest(package_path)
        except ManifestError:
            continue
        source = package_path.name
        for name, spec in (m.python_deps or {}).items():
            out.append(LibraryEntry(name=name, spec=spec, kind="python", source=source))
        for name, spec in (m.js_deps or {}).items():
            out.append(LibraryEntry(name=name, spec=spec, kind="js", source=source))
    return out


def aggregate(user_key: str) -> LibraryList:
    """One-shot read of everything the modal needs to render."""
    return LibraryList(
        standalone=_load_raw(user_key),
        from_packages=package_derived(user_key),
    )
