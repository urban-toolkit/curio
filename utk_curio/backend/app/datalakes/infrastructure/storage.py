"""Where source manifests live on disk, and how they are found.

Transcribes ``datasets/infrastructure/storage.py``'s shape so the two catalog
roots are configured and resolved the same way. Like that one, the root is
never created eagerly: a deployment with no lake sources should have no empty
directory suggesting otherwise.
"""

from __future__ import annotations

import os
from pathlib import Path

from utk_curio.backend.app.common.safe_paths import is_within
from utk_curio.backend.app.datalakes.domain.source_id import SOURCE_DIR_RE, SourceId

ENV_ROOT = "CURIO_DATALAKE_ROOT"


def datalake_root() -> Path:
    """The shared catalog root: ``<repo>/datalakes`` unless overridden."""
    override = os.environ.get(ENV_ROOT)
    if override and override.strip():
        return Path(override).expanduser().resolve()
    # storage.py -> infrastructure/ -> datalakes/ -> app/ -> backend/ ->
    # utk_curio/ -> <repo root>/datalakes
    return Path(__file__).resolve().parents[5] / "datalakes"


def list_lake_sources() -> list[Path]:
    """Every well-formed source directory under the root, sorted.

    A directory whose name does not parse, or which carries no manifest, is
    skipped rather than raised on - one malformed folder must not take the
    whole catalog listing down with it.
    """
    root = datalake_root()
    if not root.is_dir():
        return []
    found = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or not SOURCE_DIR_RE.match(entry.name):
            continue
        if not (entry / "manifest.json").is_file():
            continue
        found.append(entry)
    return found


def source_dir(dir_name: str) -> Path:
    """Resolve one source directory, refusing anything outside the root.

    ``SourceId.parse_dir`` already rejects separators and traversal, so the
    containment check is belt-and-braces - but it is the check that stays
    correct if the id grammar is ever loosened.
    """
    SourceId.parse_dir(dir_name)
    root = datalake_root()
    candidate = (root / dir_name).resolve()
    if not is_within(candidate, root.resolve()):
        raise ValueError(f"{dir_name!r} resolves outside the data lake root")
    return candidate
