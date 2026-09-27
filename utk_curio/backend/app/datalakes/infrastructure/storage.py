"""Where source manifests live on disk, and how they are found.

Transcribes ``datasets/infrastructure/storage.py``'s shape so the two catalog
roots are configured and resolved the same way. Like that one, the roots are
never created eagerly: a deployment with no lake sources should have no empty
directory suggesting otherwise.

Two roots are read:

- the **shipped** catalog, ``<repo>/datalakes`` (``CURIO_DATALAKE_ROOT`` moves
  it), which comes with Curio;
- the **instance** directory, ``.curio/datalakes/``, where an operator adds
  their own sources without rebuilding an image. It persists wherever
  ``.curio`` does. No HTTP route writes to it.

A source id is unique across both. A shipped source wins, and an instance
manifest reusing its id is skipped.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from utk_curio.backend.app.common.safe_paths import is_within
from utk_curio.backend.app.datalakes.domain.errors import StorageUnavailable
from utk_curio.backend.app.datalakes.domain.source_id import SOURCE_DIR_RE, SourceId

logger = logging.getLogger(__name__)

ENV_ROOT = "CURIO_DATALAKE_ROOT"

SHIPPED = "shipped"
INSTANCE = "instance"


class StorageRootError(StorageUnavailable):
    """A folder source's root that cannot be used."""


def datalake_root() -> Path:
    """The shipped catalog root: ``<repo>/datalakes`` unless overridden."""
    override = os.environ.get(ENV_ROOT)
    if override and override.strip():
        return Path(override).expanduser().resolve()
    # storage.py -> infrastructure/ -> datalakes/ -> app/ -> backend/ ->
    # utk_curio/ -> <repo root>/datalakes
    return Path(__file__).resolve().parents[5] / "datalakes"


def instance_root() -> Path:
    """``.curio/datalakes/``: the operator's own sources."""
    from utk_curio.backend.app.common.user_storage import curio_root

    return curio_root() / "datalakes"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


def _scan(root: Path) -> list[Path]:
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


def list_lake_sources() -> list[Path]:
    """Every well-formed source directory, shipped first, sorted within each.

    A directory whose name does not parse, or which carries no manifest, is
    skipped rather than raised on - one malformed folder must not take the
    whole catalog listing down with it.
    """
    shipped = _scan(datalake_root())
    names = {path.name for path in shipped}
    out = list(shipped)
    for path in _scan(instance_root()):
        if path.name in names:
            logger.warning(
                "lake source %s in %s reuses a shipped id and is ignored", path.name, path.parent
            )
            continue
        out.append(path)
    return out


def origin_of(path: Path) -> str:
    """``shipped`` or ``instance``: which root *path* was found under."""
    try:
        if is_within(Path(path), instance_root().resolve()):
            return INSTANCE
    except OSError:
        pass
    return SHIPPED


def source_dir(dir_name: str) -> Path:
    """Resolve one source directory, refusing anything outside the roots.

    ``SourceId.parse_dir`` already rejects separators and traversal, so the
    containment check is belt-and-braces - but it is the check that stays
    correct if the id grammar is ever loosened. The shipped root is asked
    first, matching :func:`list_lake_sources`.
    """
    SourceId.parse_dir(dir_name)
    candidates = []
    for root in (datalake_root(), instance_root()):
        candidate = (root / dir_name).resolve()
        if not is_within(candidate, root.resolve()):
            raise ValueError(f"{dir_name!r} resolves outside the data lake root")
        candidates.append(candidate)
    for candidate in candidates:
        if (candidate / "manifest.json").is_file():
            return candidate
    return candidates[0]


def storage_root(manifest) -> Path:
    """A ``folder`` source's root, resolved and checked.

    An absolute root is used as written. A relative one is only honoured for a
    shipped manifest, against the repository, so the example sources travel
    with a checkout. An instance manifest must name an absolute path, which is
    what an operator mounting a folder writes anyway.
    """
    raw = manifest.provider.root
    if not raw:
        raise StorageRootError(f"{manifest.name} declares no folder")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        if getattr(manifest, "origin", SHIPPED) != SHIPPED:
            raise StorageRootError(
                f"{manifest.name}: an instance source's root must be an absolute path"
            )
        path = repo_root() / path
    resolved = path.resolve()
    if not resolved.is_dir():
        raise StorageRootError(f"{manifest.name}: the folder {raw} is not available")
    return resolved
