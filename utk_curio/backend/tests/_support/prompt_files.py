"""Every prompt file Curio ships, wherever it is, and what an agent reads of it.

What an agent reads lives in ``agents/`` and ``skills/``: the pages of the
base entry, ``agents/agent.curio.builtin@1/`` (its manifest says ``kind:
base``), each shipped agent's own prompts, ``agents/<id>@<major>/prompts/``,
and each skill Curio ships, ``skills/<name>/SKILL.md``. Each is a
hand-written source whose markers the backend fills when it starts
(``agent_text``). A scan of the prompts reads every one, as written and as an
agent reads it. A file goes by its name, which is one prompt's wherever it
is, and a skill's file by its path in ``skills/``, ``<name>/SKILL.md``.
"""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
AGENTS = REPO_ROOT / "agents"
#: The base entry: the pages the agents share.
BASE = AGENTS / "agent.curio.builtin@1"
#: The skills Curio ships, one folder each.
SKILLS = REPO_ROOT / "skills"
#: The file a skill's folder holds.
SKILL_FILE = "SKILL.md"
#: What the base entry holds besides its pages: no agent reads them.
_NOT_PAGES = (BASE / "manifest.json", BASE / "README.md")


def prompt_folders() -> list[Path]:
    """The base entry's folder and each folder in it, then each shipped
    agent's ``prompts/``."""
    return [BASE, *sorted(path for path in BASE.rglob("*") if path.is_dir()), *sorted(AGENTS.glob("*/prompts"))]


def skill_files() -> list[Path]:
    """Each skill's ``SKILL.md``, by the skill's name."""
    return sorted(SKILLS.glob(f"*/{SKILL_FILE}"))


def prompt_name(path: Path) -> str:
    """What *path* goes by: a skill's file its path in ``skills/``, any other
    file its name."""
    path = Path(path)
    return path.relative_to(SKILLS).as_posix() if path.is_relative_to(SKILLS) else path.name


def prompt_files(pattern: str = "*.md") -> list[Path]:
    """Every page, prompt and skill file matching *pattern*, folder by
    folder, the skills last; no two go by one name."""
    files = [
        path for folder in prompt_folders() for path in sorted(folder.glob(pattern))
        if path.is_file() and path not in _NOT_PAGES
    ]
    files += [path for path in skill_files() if fnmatch(path.name, pattern)]
    names = [prompt_name(path) for path in files]
    shared = sorted({name for name in names if names.count(name) > 1})
    assert not shared, f"prompt files in different folders share a name: {shared}"
    return files


def prompt_path(name: str) -> Path:
    """The page, prompt or skill file that goes by *name*, wherever it is."""
    found = [path for path in prompt_files("*") if prompt_name(path) == name]
    assert len(found) == 1, f"no prompt file is named {name!r}"
    return found[0]


def prompt_text(name: str) -> str:
    """What an agent reads of the page, prompt or skill that goes by *name*:
    the backend's render of it (``agent_text.read``), a skill's without its
    frontmatter."""
    from utk_curio.backend.app.agents.domain import agent_text

    return agent_text.read(prompt_path(name))
