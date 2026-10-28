"""The shared catalogs: the agents and the skills an account publishes, for every account on this Curio.

Filesystem-backed (``DEC-040``), deployment-shared: publishing copies an
account's own entry into a folder beside ``.curio/users/``, where every
account's Agent Catalog can then browse it. An agent definition goes to
``.curio/agents-catalog/<agentId>@<major>/`` (:data:`AGENTS`), a skill to
``.curio/skills-catalog/<name>/`` (:data:`SKILLS`). Both are one
:class:`SharedCatalog`: the same copy, list and removal, and the publisher
recorded beside each entry as the node-package shared catalog under
``<repo_root>/packages/`` records it.

Which entries may be published, and by whom, is the application's to check
(``application/lifecycle.py``); this module does the validated copy, list and
removal. The module-level functions are :data:`AGENTS`'s.

User-facing overview: ``docs/AGENT-CATALOG.md``.
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from pathlib import Path

from utk_curio.backend.app.common.safe_paths import PathTraversalError, is_within
from utk_curio.backend.app.common.user_storage import users_base as _users_base

from utk_curio.backend.app.agents.domain import skills as skill_format
from utk_curio.backend.app.agents.domain.manifest import (
    AgentManifest,
    AgentManifestError,
    load_agent_manifest,
)
from utk_curio.backend.app.agents.repositories.storage import AGENT_DIR_RE
from utk_curio.backend.app.packages.repositories import publisher_record

log = logging.getLogger(__name__)


class SharedCatalog:
    """One shared catalog: a folder beside ``.curio/users/`` holding one
    folder per published entry, each named as its kind names an entry and
    holding the file every entry of the kind has."""

    def __init__(self, folder: str, *, is_name: Callable[[str], bool], error: type[Exception],
                 what: str, entry_file: str):
        #: The catalog's folder, beside ``.curio/users/``.
        self.folder = folder
        self._is_name = is_name
        #: The exception a name no entry can have raises.
        self.error = error
        self._what = what
        #: The file an entry's folder holds: what makes it published.
        self.entry_file = entry_file

    def base(self) -> Path:
        """The catalog's folder, which may not exist yet."""
        return (_users_base().parent / self.folder).resolve()

    def entry_dir(self, name: str) -> Path:
        """The folder of the entry *name*, its name and its containment
        checked: raises :attr:`error` for a name no entry can have, and
        ``PathTraversalError`` for one that leads out of the catalog."""
        if not (isinstance(name, str) and self._is_name(name)):
            raise self.error(f"invalid {self._what} {name!r}")
        base = self.base()
        target = (base / name).resolve()
        if not is_within(target, base):
            raise PathTraversalError(
                f"Path traversal blocked: published {self._what} path {target!s} escapes base {base!s}"
            )
        return target

    def is_published(self, name: str) -> bool:
        try:
            return (self.entry_dir(name) / self.entry_file).is_file()
        except (self.error, PathTraversalError):
            return False

    def publish_from_dir(self, src_dir: Path, name: str) -> Path:
        """Copy an entry's folder into the catalog (idempotent overwrite)."""
        target = self.entry_dir(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(src_dir, target)
        return target

    def unpublish(self, name: str) -> bool:
        """Remove a published entry; return True if it was present."""
        target = self.entry_dir(name)
        if target.is_dir():
            shutil.rmtree(target)
            return True
        return False

    def record_publisher(self, name: str, user_key: str) -> None:
        """Record who published *name*, beside it, the way the node-package
        catalog does: every account that added the entry holds a copy of it,
        so a store copy cannot stand for ownership (#438)."""
        publisher_record.record_publisher(self.base(), name, user_key)

    def is_publisher(self, name: str, user_key: str) -> bool:
        """True only for the recorded publisher; False for a publication with no record."""
        return publisher_record.is_publisher(self.base(), name, user_key)

    def publisher_of(self, name: str) -> str | None:
        """The account key that published *name*, or None without a record."""
        return publisher_record.publisher_of(self.base(), name)

    def names(self) -> list[str]:
        """Every published entry's name, sorted."""
        base = self.base()
        if not base.is_dir():
            return []
        return sorted(
            child.name for child in base.iterdir()
            if child.is_dir() and self._is_name(child.name) and (child / self.entry_file).is_file()
        )


#: The agents accounts publish, one ``<agentId>@<major>`` folder each.
AGENTS = SharedCatalog(
    "agents-catalog", is_name=lambda name: bool(AGENT_DIR_RE.match(name)), error=AgentManifestError,
    what="agent directory name", entry_file="manifest.json",
)
#: The skills accounts publish, one folder each, named after the skill.
SKILLS = SharedCatalog(
    "skills-catalog", is_name=skill_format.is_name, error=skill_format.SkillError,
    what="skill name", entry_file=skill_format.SKILL_FILE,
)


def _catalog_base() -> Path:
    """``.curio/agents-catalog/``, the deployment-shared published-agents catalog."""
    return AGENTS.base()


def published_agent_dir(dir_name: str) -> Path:
    """Resolve a published ``<agentId>@<major>`` dir with containment + grammar checks."""
    return AGENTS.entry_dir(dir_name)


def is_published(dir_name: str) -> bool:
    return AGENTS.is_published(dir_name)


def publish_from_dir(src_dir: Path, dir_name: str) -> Path:
    """Copy a definition directory into the shared catalog (idempotent overwrite)."""
    return AGENTS.publish_from_dir(src_dir, dir_name)


def unpublish(dir_name: str) -> bool:
    """Remove a published definition; return True if it was present."""
    return AGENTS.unpublish(dir_name)


def record_publisher(dir_name: str, user_key: str) -> None:
    """Record who published the agent *dir_name* (:meth:`SharedCatalog.record_publisher`)."""
    AGENTS.record_publisher(dir_name, user_key)


def is_publisher(dir_name: str, user_key: str) -> bool:
    """True only for the recorded publisher; False for a publication with no record."""
    return AGENTS.is_publisher(dir_name, user_key)


def get_published_manifest(dir_name: str) -> AgentManifest | None:
    """Resolve a published ``<agentId>@<major>`` coordinate, or None."""
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
