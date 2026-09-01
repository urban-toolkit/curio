"""Filesystem-backed agent **definition** store.

Agent definitions are immutable artifacts on disk, exactly like node packages —
Curio keeps catalog state on the filesystem (datasets, packages), reserving the
database for users and the project index only. A definition lives in a directory
named ``<agentId>@<version>`` holding ``manifest.json`` (validated by
``app/agents/manifest.py``) and a ``prompts/`` directory.

This module resolves and lists definitions under a user's store, reusing the
same ``.curio/users/<user_key>/`` root as node packages and the shared
path-containment guard in ``app/common/safe_paths.py``. Companion modules:
``imports.py`` (the account-level "My Imports" registry) and ``project_agents.py``
(the per-project installed-template lockfile).

User-facing overview: ``docs/AGENT-CATALOG.md``.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from utk_curio.backend.app.common.safe_paths import PathTraversalError, is_within
from utk_curio.backend.app.packages.storage import _user_key_segment, _users_base

from utk_curio.backend.app.agents.manifest import (
    AGENT_ID_RE,
    VERSION_RE,
    AgentManifest,
    AgentManifestError,
    load_agent_manifest,
)

log = logging.getLogger(__name__)

# On-disk directory for one definition: ``<agentId>@<version>`` (agent id and
# semver grammars come straight from the manifest module so the dir name and
# the manifest can never disagree on what a valid coordinate looks like).
AGENT_DIR_RE = re.compile(
    AGENT_ID_RE.pattern[:-1] + r"@" + VERSION_RE.pattern[1:]
)


def parse_agent_dir_name(dir_name: str) -> tuple[str, str]:
    """Split ``<agentId>@<version>`` into ``(agent_id, version)``; validate first."""
    if not isinstance(dir_name, str) or not AGENT_DIR_RE.match(dir_name):
        raise AgentManifestError(
            f"invalid agent directory name {dir_name!r}; expected '<agentId>@<version>' "
            f"matching {AGENT_DIR_RE.pattern}"
        )
    agent_id, version = dir_name.rsplit("@", 1)
    return agent_id, version


def user_agents_dir(user_key: str) -> Path:
    """Return ``.../users/<user_key>/agents/`` (may not exist yet)."""
    return _users_base() / _user_key_segment(user_key) / "agents"


def agent_definition_dir(user_key: str, dir_name: str) -> Path:
    """Resolve a single ``<agentId>@<version>`` under a user's agent store.

    Validates the directory name against :data:`AGENT_DIR_RE` and the shared
    containment check before returning, mirroring ``packages.storage.package_dir``.
    """
    parse_agent_dir_name(dir_name)  # raises on malformed names
    base = user_agents_dir(user_key).resolve()
    target = (base / dir_name).resolve()
    if not is_within(target, base):
        raise PathTraversalError(
            f"Path traversal blocked: agent path {target!s} escapes base {base!s}"
        )
    return target


def write_definition(
    user_key: str, dir_name: str, manifest: dict, prompt_files: dict[str, str]
) -> Path:
    """Materialize a definition into the user store: ``manifest.json`` + prompt assets.

    Each prompt path must stay contained inside the definition directory. Overwrites
    an existing definition (idempotent). Returns the definition directory.
    """
    target = agent_definition_dir(user_key, dir_name)  # validated + contained
    target.mkdir(parents=True, exist_ok=True)
    (target / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    for rel, text in prompt_files.items():
        dest = (target / rel).resolve()
        if not is_within(dest, target.resolve()):
            raise PathTraversalError(
                f"Path traversal blocked: prompt asset {dest!s} escapes {target!s}"
            )
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
    return target


def read_definition_bundle(user_key: str, dir_name: str) -> dict | None:
    """The full on-disk definition: its manifest and every prompt asset.

    The inverse of :func:`write_definition`, and the thing the product had no
    way to do at all. There was an import path for agents
    (``POST /api/agents/imports/upload``) with no export on the other side, so a
    definition could go into a Curio and never come back out, and the "View
    details" screen could describe an agent's prompts only by not showing them.

    Returns ``{"manifest": {...}, "prompts": {"prompts/x.txt": "..."}}`` with
    prompt keys relative to the definition directory - the exact shape
    ``write_definition`` and ``upload_import`` consume, so the two round-trip.
    ``None`` when there is no such definition.
    """
    target = agent_definition_dir(user_key, dir_name)
    manifest_path = target / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    prompts: dict[str, str] = {}
    for path in sorted(target.rglob("*")):
        if not path.is_file() or path.name == "manifest.json":
            continue
        # Skip anything that is not text we could hand back to an import.
        if path.suffix.lower() not in {".txt", ".md"}:
            continue
        try:
            prompts[path.relative_to(target).as_posix()] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
    return {"manifest": manifest, "prompts": prompts}


def load_installed_agent_definition(user_key: str, dir_name: str) -> AgentManifest | None:
    """Load one installed definition by dir name, or ``None`` if absent."""
    target = agent_definition_dir(user_key, dir_name)
    if not (target / "manifest.json").is_file():
        return None
    return load_agent_manifest(target)


def list_installed_agent_definitions(user_key: str) -> list[AgentManifest]:
    """Load every valid definition in the user's store, sorted by id then version.

    A directory whose manifest is missing or invalid is skipped with a warning
    rather than raising — one bad artifact must never make the whole store
    unreadable (same tolerance the packages/defaults readers use).
    """
    base = user_agents_dir(user_key)
    if not base.is_dir():
        return []
    out: list[AgentManifest] = []
    for child in base.iterdir():
        if not child.is_dir() or not AGENT_DIR_RE.match(child.name):
            continue
        try:
            out.append(load_agent_manifest(child))
        except AgentManifestError:
            log.warning("Skipping invalid agent definition at %s", child, exc_info=True)
    out.sort(key=lambda m: (m.agent_id, m.version))
    return out


def write_definition_atomic(
    user_key: str, dir_name: str, manifest: dict, prompt_files: dict[str, str]
) -> Path:
    """Atomic variant of :func:`write_definition` for user uploads (memo dev/36).

    Stages the definition in a temp directory inside the user's agents store and
    ``os.replace``s it into place, so a failed/interrupted upload never leaves a
    partially visible artifact (``RISK-IMPORT-001``). Refuses to replace an
    existing definition — uploads are immutable (``DEC-029``); callers pre-check
    and surface a 409.
    """
    import os
    import shutil
    import tempfile

    target = agent_definition_dir(user_key, dir_name)  # validated + contained
    if target.exists():
        raise FileExistsError(f"definition {dir_name!r} already exists")
    base = user_agents_dir(user_key)
    base.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".upload-", dir=base))
    try:
        (staging / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        for rel, text in prompt_files.items():
            dest = (staging / rel).resolve()
            if not is_within(dest, staging.resolve()):
                raise PathTraversalError(
                    f"Path traversal blocked: prompt asset {dest!s} escapes {staging!s}"
                )
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text, encoding="utf-8")
        os.replace(staging, target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return target
