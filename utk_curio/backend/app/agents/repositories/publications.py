"""Shared publications catalog — the global Catalog Hub for user-published agents.

Filesystem-backed (``DEC-040``), deployment-shared: publishing copies an owned
definition into ``.curio/agents-catalog/<agentId>@<version>/`` (a sibling of
``.curio/users/``), where every user's Global Catalog can then browse it. This is
the agent analogue of the node-package shared catalog under ``<repo_root>/packages/``.

Only an owned, store-backed, non-built-in definition may be published — enforced
in ``services.publish_agent``; this module just does the validated copy/list/remove.

User-facing overview: ``docs/AGENT-CATALOG.md``.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from utk_curio.backend.app.common.safe_paths import PathTraversalError, is_within
from utk_curio.backend.app.common.user_storage import users_base as _users_base

from utk_curio.backend.app.agents.domain.manifest import (
    AgentManifest,
    AgentManifestError,
    load_agent_manifest,
)
from utk_curio.backend.app.agents.repositories.storage import AGENT_DIR_RE
from utk_curio.backend.app.packages.repositories import publisher_record

log = logging.getLogger(__name__)


def _catalog_base() -> Path:
    """``.curio/agents-catalog/`` — the deployment-shared published-agents catalog."""
    return (_users_base().parent / "agents-catalog").resolve()


def published_agent_dir(dir_name: str) -> Path:
    """Resolve a published ``<agentId>@<version>`` dir with containment + grammar checks."""
    if not (isinstance(dir_name, str) and AGENT_DIR_RE.match(dir_name)):
        raise AgentManifestError(f"invalid agent directory name {dir_name!r}")
    base = _catalog_base()
    target = (base / dir_name).resolve()
    if not is_within(target, base):
        raise PathTraversalError(
            f"Path traversal blocked: published agent path {target!s} escapes base {base!s}"
        )
    return target


def is_published(dir_name: str) -> bool:
    try:
        return (published_agent_dir(dir_name) / "manifest.json").is_file()
    except (AgentManifestError, PathTraversalError):
        return False


def publish_from_dir(src_dir: Path, dir_name: str) -> Path:
    """Copy a definition directory into the shared catalog (idempotent overwrite)."""
    target = published_agent_dir(dir_name)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(src_dir, target)
    return target


def unpublish(dir_name: str) -> bool:
    """Remove a published definition; return True if it was present."""
    target = published_agent_dir(dir_name)
    if target.is_dir():
        shutil.rmtree(target)
        return True
    return False


def record_publisher(dir_name: str, user_key: str) -> None:
    """Record who published *dir_name*, beside it, the way the node-package
    catalog does: every account that added the agent holds a copy of it, so a
    store copy cannot stand for ownership (#438)."""
    publisher_record.record_publisher(_catalog_base(), dir_name, user_key)


def is_publisher(dir_name: str, user_key: str) -> bool:
    """True only for the recorded publisher; False for a publication with no record."""
    return publisher_record.is_publisher(_catalog_base(), dir_name, user_key)


def get_published_manifest(dir_name: str) -> AgentManifest | None:
    """Resolve a published ``<agentId>@<version>`` coordinate, or None."""
    try:
        d = published_agent_dir(dir_name)
    except (AgentManifestError, PathTraversalError):
        return None
    if not (d / "manifest.json").is_file():
        return None
    return load_agent_manifest(d)


def list_published() -> list[AgentManifest]:
    """Validated manifests for every published definition, sorted by coordinate."""
    base = _catalog_base()
    if not base.is_dir():
        return []
    out: list[AgentManifest] = []
    for child in base.iterdir():
        if not child.is_dir() or not AGENT_DIR_RE.match(child.name):
            continue
        try:
            out.append(load_agent_manifest(child))
        except AgentManifestError:
            log.warning("Skipping invalid published agent at %s", child, exc_info=True)
    out.sort(key=lambda m: (m.agent_id, m.version))
    return out
