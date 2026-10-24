"""Every prompt file Curio ships, wherever it is, and what an agent reads of it.

Everything an agent reads lives in ``agents/``: the pages of the base entry,
``agents/agent.curio.builtin@1/`` (its manifest says ``kind: base``), and
each shipped agent's own prompts, ``agents/<id>@<major>/prompts/``. Each is a
hand-written source whose markers the backend fills when it starts
(``agent_text``). A scan of the prompts reads every one, as written and as an
agent reads it, and a file name is one prompt's wherever it is.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
AGENTS = REPO_ROOT / "agents"
#: The base entry: the pages the agents share.
BASE = AGENTS / "agent.curio.builtin@1"
#: What the base entry holds besides its pages: no agent reads them.
_NOT_PAGES = (BASE / "manifest.json", BASE / "README.md")


def prompt_folders() -> list[Path]:
    """The base entry's folder and each folder in it, then each shipped
    agent's ``prompts/``."""
    return [BASE, *sorted(path for path in BASE.rglob("*") if path.is_dir()), *sorted(AGENTS.glob("*/prompts"))]


def prompt_files(pattern: str = "*.md") -> list[Path]:
    """Every page and prompt file matching *pattern*, folder by folder; no
    two share a name."""
    files = [
        path for folder in prompt_folders() for path in sorted(folder.glob(pattern))
        if path.is_file() and path not in _NOT_PAGES
    ]
    names = [path.name for path in files]
    shared = sorted({name for name in names if names.count(name) > 1})
    assert not shared, f"prompt files in different folders share a name: {shared}"
    return files


def prompt_path(name: str) -> Path:
    """The page or prompt file named *name*, wherever it is."""
    found = [path for path in prompt_files("*") if path.name == name]
    assert len(found) == 1, f"no prompt file is named {name!r}"
    return found[0]


def prompt_text(name: str) -> str:
    """What an agent reads of the page or prompt named *name*: the backend's
    render of it (``agent_text.read``)."""
    from utk_curio.backend.app.agents.domain import agent_text

    return agent_text.read(prompt_path(name))
