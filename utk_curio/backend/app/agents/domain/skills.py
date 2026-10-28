"""Skills: folders that tell Curio's agents how to do a task, in the Agent Skills format.

A skill is a folder holding a ``SKILL.md``, as the open Agent Skills format
lays it out (https://agentskills.io/specification): YAML frontmatter between
two ``---`` lines, then the skill's instructions in Markdown, its body. The
frontmatter holds the format's fields only: ``name``, the folder's name;
``description``, when to use the skill; and optionally ``license``,
``compatibility``, ``metadata`` (strings by string keys) and
``allowed-tools``. Any other file in the folder is the skill's too, such as
its ``references/``.

Curio ships its skills in the root ``skills/`` folder, one folder each
(``utk_curio/shipped.py`` finds it). A skill's body may hold Curio's markers,
which ``agent_text`` fills when it renders the skill, and
``{{skill:<name>}}`` puts a rendered body in a page or a prompt.

:func:`parse` reads a skill in one of two modes:

- strict, for the skills Curio ships, follows the specification's rules: only
  its fields; a ``name`` of 1 to 64 lowercase letters, digits and single
  hyphens, neither first nor last, that is its folder's name; a
  ``description`` of 1 to 1,024 characters; a ``compatibility`` of 1 to 500;
  strings in ``metadata``; and a ``SKILL.md`` under 500 lines. Any break of
  them refuses the skill.
- lenient, for a skill brought from elsewhere, follows agentskills.io's
  guide for clients: frontmatter that is no YAML mapping, and a missing or
  empty ``description``, refuse the skill; every other break is a warning on
  the skill it reads, and it reads the skill anyway.

The body is the text after the line that closes the frontmatter, as written,
without the blank lines before its first line.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import MappingProxyType

import yaml

from utk_curio import shipped

#: The folder of the skills Curio ships, by its repository path
#: (``utk_curio/shipped.py`` finds it).
SKILLS_DIR = "skills"
#: The file a skill's folder holds: its frontmatter, then its body.
SKILL_FILE = "SKILL.md"
#: The line that opens the frontmatter and the line that closes it.
DELIMITER = "---"
#: The frontmatter's fields, as the specification names them: no other is one.
FIELDS = ("name", "description", "license", "compatibility", "metadata", "allowed-tools")
#: The most characters a name, a description and a compatibility hold.
NAME_MAX = 64
DESCRIPTION_MAX = 1024
COMPATIBILITY_MAX = 500
#: A ``SKILL.md`` holds fewer lines than this.
LINES_UNDER = 500
#: A name: lowercase letters and digits, in runs joined by single hyphens.
_NAME_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
#: Folders a skill's listing of its files leaves out, besides hidden ones.
_NOT_FILES = ("__pycache__",)


class SkillError(ValueError):
    """A ``SKILL.md`` the parser refuses: in strict mode, one that breaks any
    rule of the specification; in either mode, one whose frontmatter is no
    YAML mapping or that has no description."""


@dataclass(frozen=True)
class Skill:
    """One skill, as its ``SKILL.md`` gives it."""

    name: str
    #: When to use the skill, as an agent is told it.
    description: str
    license: str | None
    compatibility: str | None
    #: The ``metadata`` field: strings by string keys.
    metadata: Mapping[str, str]
    #: The ``allowed-tools`` field, as written: tool names, a space between each.
    allowed_tools: str | None
    #: The instructions: the Markdown after the frontmatter, as written, its
    #: markers not filled.
    body: str
    #: The folder that holds the ``SKILL.md``.
    folder: Path
    #: The folder's other files, by their paths in it, such as
    #: ``references/REFERENCE.md``.
    files: tuple[str, ...]
    #: The line of the ``SKILL.md`` its body starts on, counted from 1.
    body_line: int
    #: What lenient mode let through, one line each. Strict mode has none.
    warnings: tuple[str, ...] = ()

    @property
    def file(self) -> Path:
        """Its ``SKILL.md``."""
        return self.folder / SKILL_FILE


def is_name(name) -> bool:
    """Whether *name* is a skill's name as the specification has it: 1 to 64
    lowercase letters, digits and single hyphens, neither first nor last. A
    lenient read keeps a name that is not one, with a warning, so code that
    names a folder after a skill checks its name first."""
    return isinstance(name, str) and len(name) <= NAME_MAX and bool(_NAME_RE.fullmatch(name))


# --- Reading one skill ---------------------------------------------------------


def parse(folder, *, strict: bool = True, text: str | None = None) -> Skill:
    """The skill in *folder*, from its ``SKILL.md``, or from *text* when the
    caller has read the file already. *strict* chooses the mode (the module's
    docstring says what each refuses). Raises :class:`SkillError`, naming the
    file and every problem it found."""
    folder = Path(folder)
    where = f"{folder.name}/{SKILL_FILE}"
    if text is None:
        file = folder / SKILL_FILE
        if not file.is_file():
            raise SkillError(f"{folder} holds no {SKILL_FILE}")
        text = file.read_text(encoding="utf-8")
    if strict and "\r" in text:
        raise SkillError(f"{where} holds a carriage return; its lines end in a line break alone")
    if not strict:
        text = text.removeprefix("﻿").replace("\r\n", "\n").replace("\r", "\n")
    front, body, body_line = _split(text, where, strict)
    try:
        fields = yaml.safe_load(front)
    except yaml.YAMLError as exc:
        raise SkillError(f"{where}: its frontmatter is not YAML ({_one_line(exc)})") from None
    if not isinstance(fields, dict):
        raise SkillError(f"{where}: its frontmatter is no YAML mapping of the fields {', '.join(FIELDS)}")

    problems: list[str] = []
    name = _name(fields, folder.name, problems)
    description = _description(fields, problems, strict, where)
    license_ = _text_field(fields, "license", problems)
    compatibility = _text_field(fields, "compatibility", problems)
    if compatibility is not None and not 1 <= len(compatibility) <= COMPATIBILITY_MAX:
        problems.append(f"its compatibility is {len(compatibility)} characters, not 1 to {COMPATIBILITY_MAX}")
    metadata = _metadata(fields.get("metadata"), problems)
    allowed_tools = _allowed_tools(fields.get("allowed-tools"), problems)
    unknown = [str(key) for key in fields if key not in FIELDS]
    if unknown:
        problems.append(f"it holds {', '.join(unknown)}, which the format does not define; its fields are "
                        + ", ".join(FIELDS))
    lines = text.count("\n") + (not text.endswith("\n"))
    if lines >= LINES_UNDER:
        problems.append(f"it is {lines} lines, where a {SKILL_FILE} holds fewer than {LINES_UNDER}")
    if strict and problems:
        raise SkillError(f"{where}: " + "; ".join(problems))
    return Skill(
        name=name, description=description, license=license_, compatibility=compatibility,
        metadata=MappingProxyType(metadata), allowed_tools=allowed_tools, body=body, folder=folder,
        files=_files(folder), body_line=body_line, warnings=tuple(f"{where}: {problem}" for problem in problems),
    )


def _split(text: str, where: str, strict: bool) -> tuple[str, str, int]:
    """*text*'s frontmatter, its body and the line its body starts on. The
    first line is ``---``, and the next ``---`` line closes the frontmatter;
    lenient mode lets either carry spaces after it."""
    lines = text.split("\n")

    def delimiter(line: str) -> bool:
        return line == DELIMITER if strict else line.rstrip() == DELIMITER

    if not delimiter(lines[0]):
        raise SkillError(f"{where} starts with its frontmatter, a {DELIMITER} line, not {lines[0][:40]!r}")
    end = next((at for at in range(1, len(lines)) if delimiter(lines[at])), None)
    if end is None:
        raise SkillError(f"{where}: no {DELIMITER} line closes its frontmatter")
    start = end + 1
    while start < len(lines) - 1 and not lines[start].strip():
        start += 1
    return "\n".join(lines[1:end]), "\n".join(lines[start:]), start + 1


def _one_line(exc: Exception) -> str:
    return " ".join(str(exc).split())


def _as_text(value) -> str | None:
    """*value* as text when YAML read a scalar: a string as it is, a number,
    a truth value or a date as written. None for a list, a mapping or null."""
    if isinstance(value, str):
        return value
    if isinstance(value, (bool, int, float, date)):
        return str(value).lower() if isinstance(value, bool) else str(value)
    return None


def _name(fields: dict, folder_name: str, problems: list[str]) -> str:
    """The name, or the folder's name when lenient mode reads a skill that
    gives none it can use."""
    if "name" not in fields:
        problems.append(f"it gives no name, which is its folder's, {folder_name}")
        return folder_name
    raw = fields["name"]
    if not isinstance(raw, str):
        problems.append(f"its name is no string but {raw!r}")
        raw = _as_text(raw)
        if raw is None:
            return folder_name
    if not 1 <= len(raw) <= NAME_MAX:
        problems.append(f"its name is {len(raw)} characters, not 1 to {NAME_MAX}")
    if raw and not _NAME_RE.fullmatch(raw):
        problems.append(f"its name {raw!r} is not lowercase letters, digits and single hyphens, "
                        "with no hyphen first or last")
    if raw != folder_name:
        problems.append(f"its name {raw!r} is not its folder's name, {folder_name!r}")
    return raw if raw else folder_name


def _description(fields: dict, problems: list[str], strict: bool, where: str) -> str:
    """The description. Lenient mode refuses a skill with none, since an agent
    knows a skill by it."""
    raw = fields.get("description")
    text = _as_text(raw)
    if text is not None and not isinstance(raw, str):
        problems.append(f"its description is no string but {raw!r}")
    if text is None or not text.strip():
        if not strict:
            raise SkillError(f"{where} gives no description, which says when to use it")
        problems.append("it gives no description, which says when to use it")
        return ""
    if len(text) > DESCRIPTION_MAX:
        problems.append(f"its description is {len(text)} characters, more than {DESCRIPTION_MAX}")
    return text


def _text_field(fields: dict, key: str, problems: list[str]) -> str | None:
    """An optional field that holds a string, or None when it is absent or no
    scalar."""
    if key not in fields:
        return None
    raw = fields[key]
    if isinstance(raw, str):
        return raw
    problems.append(f"its {key} is no string but {raw!r}")
    return _as_text(raw)


def _metadata(raw, problems: list[str]) -> dict[str, str]:
    """``metadata``: strings by string keys. Lenient mode keeps a scalar as
    its text and leaves out a list or a mapping."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        problems.append(f"its metadata is no mapping but {raw!r}")
        return {}
    kept: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            problems.append(f"its metadata holds {key!r}: {value!r}, where it holds strings by string keys")
        key_text, value_text = _as_text(key), _as_text(value)
        if key_text is not None and value_text is not None:
            kept[key_text] = value_text
    return kept


def _allowed_tools(raw, problems: list[str]) -> str | None:
    """``allowed-tools``: tool names, a space between each. Lenient mode
    joins a list of names."""
    if raw is None or isinstance(raw, str):
        return raw
    problems.append(f"its allowed-tools is no string but {raw!r}")
    if isinstance(raw, list):
        names = [_as_text(item) for item in raw]
        return " ".join(name for name in names if name)
    return _as_text(raw)


def _files(folder: Path) -> tuple[str, ...]:
    """The files in *folder* but its ``SKILL.md``, by their paths there, hidden
    files and folders left out."""
    found = []
    for here, dirs, names in os.walk(folder):
        dirs[:] = sorted(name for name in dirs if not name.startswith(".") and name not in _NOT_FILES)
        for name in names:
            path = Path(here, name).relative_to(folder).as_posix()
            if not name.startswith(".") and path != SKILL_FILE:
                found.append(path)
    return tuple(sorted(found))


# --- The skills Curio ships ----------------------------------------------------


def skills_dir() -> Path:
    """The folder of the skills Curio ships (``utk_curio/shipped.py``)."""
    return shipped.path(SKILLS_DIR)


def shipped_folders() -> tuple[Path, ...]:
    """Each folder of the skills Curio ships, by name: each folder of
    ``skills/`` that holds a ``SKILL.md``."""
    root = skills_dir()
    if not root.is_dir():
        return ()
    return tuple(
        folder for folder in sorted(root.iterdir())
        if folder.is_dir() and not folder.name.startswith(".") and (folder / SKILL_FILE).is_file()
    )


def shipped_skills() -> tuple[Skill, ...]:
    """Every skill Curio ships, read strictly, by name. Raises
    :class:`SkillError` on the first that breaks a rule."""
    return tuple(parse(folder) for folder in shipped_folders())


def shipped_skill_file(name: str) -> Path:
    """The ``SKILL.md`` of the skill Curio ships as *name*. Raises
    :class:`SkillError` when *name* is no skill's name, Curio ships no such
    skill, or its file leads out of ``skills/``."""
    if not is_name(name):
        raise SkillError(f"{name!r} names no skill: a name is 1 to {NAME_MAX} lowercase letters, digits and "
                         "single hyphens")
    root = skills_dir()
    file = root / name / SKILL_FILE
    if not file.is_file():
        raise SkillError(f"Curio ships no skill named {name}: {SKILLS_DIR}/{name}/{SKILL_FILE} is missing")
    if not file.resolve().is_relative_to(root.resolve()):
        raise SkillError(f"{SKILLS_DIR}/{name}/{SKILL_FILE} leads out of {SKILLS_DIR}/, to {file.resolve()}")
    return file
