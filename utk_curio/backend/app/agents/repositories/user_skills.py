"""The skills an account holds of its own: one folder each in ``.curio/users/<key>/skills/<name>/``.

Each is laid out as Curio's ``skills/`` and a package's ``skills/`` lay theirs
(``domain/skills.py``): a ``SKILL.md`` and its other files, in a folder named
after the skill. An account holds two kinds:

- a skill it imported, which is its own to publish;
- a copy of a skill it added from the shared catalog (``publications.SKILLS``),
  which its folder's hidden :data:`SOURCE_FILE` marks, as a copy of a published
  agent is stamped ``global``: it keeps working after its publisher
  unpublishes it, and it is never this account's to publish.

A skill's listing of its files leaves hidden files out, so the mark is never
one of its files, an export never carries it and an import can never write
one. Writes go through ``storage.write_folder_atomic``, as an agent
definition's do.
"""

from __future__ import annotations

import json
import logging
import shutil
from collections.abc import Mapping
from pathlib import Path

from utk_curio.backend.app.common.safe_paths import PathTraversalError, is_within
from utk_curio.backend.app.common.user_storage import user_key_segment, users_base

from utk_curio.backend.app.agents.domain import skills as skill_format
from utk_curio.backend.app.agents.repositories.storage import write_folder_atomic

log = logging.getLogger(__name__)

#: The folder of an account's skills, in its folder of ``.curio/users/``.
SKILLS_FOLDER = "skills"
#: The hidden file that marks a copy of a skill from the shared catalog.
SOURCE_FILE = ".curio-skill.json"
#: What :data:`SOURCE_FILE` says a copy came from.
FROM_CATALOG = "catalog"
_SOURCE_VERSION = 1


def skills_dir(user_key: str) -> Path:
    """``.curio/users/<key>/skills/``, which may not exist yet."""
    return users_base() / user_key_segment(user_key) / SKILLS_FOLDER


def skill_dir(user_key: str, name: str) -> Path:
    """The folder of the account's skill *name*: raises ``SkillError`` for a
    name no skill can have, and ``PathTraversalError`` for one that leads out
    of the account's skills."""
    if not skill_format.is_name(name):
        raise skill_format.SkillError(
            f"{name!r} names no skill: a name is 1 to {skill_format.NAME_MAX} lowercase letters, digits and "
            "single hyphens"
        )
    base = skills_dir(user_key).resolve()
    target = (base / name).resolve()
    if not is_within(target, base):
        raise PathTraversalError(f"Path traversal blocked: skill path {target!s} escapes base {base!s}")
    return target


def folders(user_key: str) -> tuple[Path, ...]:
    """The folder of each skill the account holds, by name
    (``skills.folders_in``)."""
    return skill_format.folders_in(skills_dir(user_key))


def holds(user_key: str, name: str) -> bool:
    """Whether the account holds a skill named *name*."""
    try:
        return (skill_dir(user_key, name) / skill_format.SKILL_FILE).is_file()
    except (skill_format.SkillError, PathTraversalError):
        return False


def is_copy(folder: Path) -> bool:
    """Whether the skill in *folder* is a copy of one from the shared catalog."""
    path = Path(folder) / SOURCE_FILE
    if not path.is_file():
        return False
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # A mark that cannot be read still marks a copy: a copy is never
        # this account's to publish.
        return True
    return not isinstance(doc, dict) or doc.get("from") == FROM_CATALOG


def write(user_key: str, name: str, files: Mapping[str, str | bytes], *, replace: bool = False,
          copied: bool = False) -> Path:
    """Write the skill *name* the account holds: *files*, its ``SKILL.md`` and
    its other files by their paths in its folder, all at once
    (``storage.write_folder_atomic``). *copied* marks a copy of a skill from
    the shared catalog. An existing skill of that name is refused with
    ``FileExistsError`` unless *replace*. A hidden file is never written
    but the mark."""
    target = skill_dir(user_key, name)
    kept = {path: content for path, content in files.items()
            if not any(part.startswith(".") for part in Path(path).parts)}
    if copied:
        kept[SOURCE_FILE] = json.dumps({"version": _SOURCE_VERSION, "from": FROM_CATALOG}) + "\n"
    return write_folder_atomic(skills_dir(user_key), target, kept, replace=replace)


def remove(user_key: str, name: str) -> bool:
    """Delete the account's skill *name*; True if it held one."""
    target = skill_dir(user_key, name)
    if not target.is_dir():
        return False
    shutil.rmtree(target)
    return True


def read_files(folder: Path) -> dict[str, bytes]:
    """The files of the skill in *folder* as an export carries them: its
    ``SKILL.md`` and each of its other files (``skills.Skill.files``, hidden
    ones left out), by their paths in it, as bytes. Links are not followed."""
    folder = Path(folder)
    found: dict[str, bytes] = {}
    for path in (skill_format.SKILL_FILE, *skill_format.listed_files(folder)):
        file = folder / path
        if file.is_symlink() or not file.is_file():
            log.warning("A skill's export leaves out %s, which is no file", file)
            continue
        found[path] = file.read_bytes()
    return found
