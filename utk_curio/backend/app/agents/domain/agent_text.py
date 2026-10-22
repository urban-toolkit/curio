"""Agent text: the pages and prompts Curio's agents read, rendered once.

Everything an agent Curio ships reads lives in ``agents/``, the Agent
Catalog's folder:

- The base entry, the folder whose manifest says ``kind: base``
  (``agents/agent.curio.builtin@1``), holds the pages every agent Curio ships
  reads: the preamble, the rules the agents' prompts include, and the index
  of the worked examples. Its manifest lists them (``pages``). Any agent, a
  user's included, names a page as ``curio:<path>``. The base entry is no
  agent: no catalog lists it and no agent delegates to it.
- Each agent Curio ships keeps its own prompts in its folder,
  ``agents/<id>@<major>/prompts/``, named by its manifest.

Each file is a hand-written source. A fact the code owns is a marker in it,
``{{field}}`` or ``{{field:argument}}``, which ``contracts.render_template``
fills from ``contracts.PROMPT_FIELDS``. ``{{include:<path>}}`` puts another
page of the base entry there whole. Nothing is generated or committed.

When the backend starts (``create_app``), :func:`render_at_start` renders
every page and every prompt once, and a read returns that render. Under
``curio.py start --dev`` (``CURIO_DEV=1``) a read renders the file again, so an
edit shows on the next run.

A user's agent is never rendered: its own prompts are read as written, and
only the pages it names as ``curio:<path>`` are Curio's renders.
"""

from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache
from pathlib import Path

from utk_curio import shipped
from utk_curio.backend.app.agents.domain import contracts

log = logging.getLogger(__name__)

#: The Agent Catalog's folder, by its repository path (``utk_curio/shipped.py``
#: finds it).
AGENTS_DIR = "agents"
#: What the base entry's manifest says it is (``kind``).
KIND_BASE = "base"
#: The field of the base entry's manifest that lists its pages.
PAGES_FIELD = "pages"
#: How a manifest names a page of the base entry: this, then the page's path.
PAGE_PREFIX = "curio:"
#: A page's path in the base entry: segments of letters, digits, ``_``, ``.``
#: and ``-``, none starting with a dot, ending in a ``.md`` file.
_PAGE_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*(?:/[A-Za-z0-9_][A-Za-z0-9_.-]*)*\.md$")
#: What ``curio.py start --dev`` sets for the processes it starts.
_DEV_ENV = "CURIO_DEV"

#: Every render a read returns, by file: the start-up render, and each file
#: read since that the start-up render did not cover.
_TEXTS: dict[Path, str] = {}
#: Whether this process has rendered every page and prompt at start.
_STARTED = False


class AgentTextError(ValueError):
    """A ``curio:`` path that names no page of the base entry, or leads out of it."""


# --- The base entry ------------------------------------------------------------


def base_dir() -> Path | None:
    """The base entry Curio ships: the folder in ``agents/`` whose manifest
    says ``kind: base``. None, logged, when there is none."""
    return _base_in(shipped.path(AGENTS_DIR))


@lru_cache(maxsize=8)
def _base_in(root: Path) -> Path | None:
    found = [folder for folder in sorted(root.iterdir()) if is_base(folder)] if root.is_dir() else []
    if len(found) > 1:
        raise AgentTextError(
            f"{root} holds {len(found)} folders whose manifest says kind 'base' "
            f"({', '.join(folder.name for folder in found)}); Curio ships one"
        )
    if not found:
        log.error(
            "Curio ships no base entry in %s (a folder whose manifest says kind 'base'), so its "
            "agents run without the pages they share. If this is an installed Curio, the package "
            "is missing its agents/ folder (see MANIFEST.in).", root,
        )
        return None
    return found[0]


def is_base(folder: Path) -> bool:
    """Whether *folder* is a base entry: its manifest says ``kind: base``."""
    try:
        raw = json.loads((Path(folder) / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(raw, dict) and raw.get("kind") == KIND_BASE


def pages() -> tuple[str, ...]:
    """The base entry's pages, by their paths in its folder, as its manifest
    lists them: what ``curio:<path>`` may name. Empty when there is no base."""
    base = base_dir()
    return _pages_of(base) if base is not None else ()


@lru_cache(maxsize=8)
def _pages_of(base: Path) -> tuple[str, ...]:
    where = base / "manifest.json"
    listed = json.loads(where.read_text(encoding="utf-8")).get(PAGES_FIELD)
    if (
        not isinstance(listed, list)
        or not listed
        or not all(isinstance(page, str) and _PAGE_RE.match(page) for page in listed)
        or len(set(listed)) != len(listed)
    ):
        raise AgentTextError(
            f"{where}: {PAGES_FIELD} lists each page of the base entry once, by its path in the "
            f"folder, a .md file inside it, not {listed!r}"
        )
    return tuple(listed)


def page_file(page: str) -> Path:
    """The file of *page*, a page of the base entry named by its path there,
    as ``curio:<page>`` names it.

    Raises :class:`AgentTextError` when *page* leads out of the base entry
    (``..``, an absolute path, a symbolic link to a file outside it) or is no
    page its manifest lists."""
    if not isinstance(page, str) or not _PAGE_RE.match(page):
        raise AgentTextError(
            f"{PAGE_PREFIX}{page} leads out of Curio's agent text: a curio: path names a page by "
            f"its path inside the base entry, such as {PAGE_PREFIX}default_preamble.md"
        )
    base = base_dir()
    if base is None:
        raise AgentTextError(f"{PAGE_PREFIX}{page} names a page of Curio's agent text, which this Curio lacks")
    listed = _pages_of(base)
    if page not in listed:
        raise AgentTextError(
            f"{PAGE_PREFIX}{page} names no page of Curio's agent text; a curio: path is one of: "
            + ", ".join(PAGE_PREFIX + name for name in listed)
        )
    file = base / page
    if not file.resolve().is_relative_to(base.resolve()):
        raise AgentTextError(f"{PAGE_PREFIX}{page} leads out of Curio's agent text, to {file.resolve()}")
    return file


def _page_of(file: Path) -> str | None:
    """*file*'s path in the base entry, when it is a page's, else None."""
    base = base_dir()
    if base is None:
        return None
    try:
        return Path(file).relative_to(base).as_posix()
    except ValueError:
        return None


# --- Rendering -----------------------------------------------------------------


def _source(file: Path) -> str:
    """The hand-written text of *file*."""
    return Path(file).read_text(encoding="utf-8")


def render(file: Path) -> str:
    """*file*, a page of the base entry or a prompt of an agent Curio ships,
    rendered now: every marker filled (``contracts.render_template``).

    Raises ``contracts.PromptTemplateError`` on a marker no field defines and
    on a page that includes itself."""
    page = _page_of(file)
    if page is None:
        return contracts.render_template(_source(file), str(file))
    return contracts.render_template(_source(file), PAGE_PREFIX + page, including=(page,))


def include(page: str, including: tuple[str, ...]) -> str:
    """The page *page* names, rendered, without its final line breaks: what
    ``{{include:<page>}}`` puts in place. *including* holds the pages being
    rendered around it, outermost first, so a page that includes itself
    raises ``contracts.PromptTemplateError``."""
    if page in including:
        chain = " includes ".join(PAGE_PREFIX + name for name in (*including, page))
        raise contracts.PromptTemplateError(f"{chain}: a page cannot include itself")
    try:
        file = page_file(page)
        text = _source(file)
    except (AgentTextError, OSError) as exc:
        raise contracts.PromptTemplateError(f"{{{{include:{page}}}}} cannot be read: {exc}") from None
    return contracts.render_template(text, PAGE_PREFIX + page, including=(*including, page)).rstrip("\n")


def read(file: Path) -> str:
    """What an agent reads of *file*, a page of the base entry or a prompt of
    an agent Curio ships: its start-up render. Under ``curio.py start --dev``
    it is rendered at each read, so an edit shows on the next run. A file the
    start-up render did not cover is rendered now and kept."""
    if os.environ.get(_DEV_ENV) == "1":
        return render(file)
    text = _TEXTS.get(file)
    if text is None:
        text = _TEXTS[file] = render(file)
    return text


def shipped_files() -> list[Path]:
    """Every file :func:`render_at_start` renders: each page the base entry
    lists, then each prompt each agent Curio ships names in its own folder,
    each once. A listed file that is missing is left out and logged, as a read
    of it is."""
    from utk_curio.backend.app.agents.domain import builtin

    files: list[Path] = []
    if base_dir() is not None:
        files += [page_file(page) for page in pages()]
    for m in builtin.list_builtin_manifests():
        folder = builtin.agents_dir() / m.dir_name
        files += [folder / asset.path for asset in m.prompts.values() if asset.shared is None]
    present = []
    for file in dict.fromkeys(files):
        if file.is_file():
            present.append(file)
        else:
            log.error(
                "%s is missing, so the agents that read it run without it. If this is an installed "
                "Curio, the package is missing its agents/ folder (see MANIFEST.in).", file,
            )
    return present


def render_at_start() -> dict[Path, str]:
    """Render every page of the base entry and every prompt of every agent
    Curio ships, and keep the renders for every read: the backend calls this
    when it starts. Once per process: another app in the same process reads
    the same renders. Raises ``contracts.PromptTemplateError`` on a marker no
    field defines, so broken text stops the start, not a run."""
    global _STARTED
    if not _STARTED:
        _TEXTS.update({file: render(file) for file in shipped_files()})
        _STARTED = True
    return rendered()


def rendered() -> dict[Path, str]:
    """Every render a read returns now, by file."""
    return dict(_TEXTS)
