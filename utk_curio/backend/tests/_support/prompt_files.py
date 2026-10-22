"""Every prompt file Curio ships, wherever it is.

The prompts the agents share are in ``utk_curio/llm-prompts/``: the preamble,
the templates and fragments the generator reads, and the files read at run
time. Each shipped agent's own prompts are in its folder,
``agents/<id>@<major>/prompts/``. A scan of the prompts reads both, and a
file name is one prompt's wherever it is.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
SHARED = REPO_ROOT / "utk_curio" / "llm-prompts"
AGENTS = REPO_ROOT / "agents"


def prompt_folders() -> list[Path]:
    """The shared prompts' folder, then each shipped agent's ``prompts/``."""
    return [SHARED, *sorted(AGENTS.glob("*/prompts"))]


def prompt_files(pattern: str = "*.md") -> list[Path]:
    """Every prompt file matching *pattern*, folder by folder; no two share a name."""
    files = [path for folder in prompt_folders() for path in sorted(folder.glob(pattern)) if path.is_file()]
    names = [path.name for path in files]
    shared = sorted({name for name in names if names.count(name) > 1})
    assert not shared, f"prompt files in different folders share a name: {shared}"
    return files


def prompt_path(name: str) -> Path:
    """The prompt file named *name*, wherever it is."""
    found = [path for path in prompt_files("*") if path.name == name]
    assert len(found) == 1, f"no prompt file is named {name!r}"
    return found[0]
