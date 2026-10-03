"""Worked examples: shipped dataflows chosen per run, for the run's runtime slot.

``llm-prompts/examples.md`` indexes every dataflow Curio ships, one line each,
under "Used" or "Not used". A line links its file and says what the dataflow
shows; the file itself holds the name, task, categories, node types and
datasets, so the index never repeats them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from utk_curio.backend.app.agents.domain import builtin

#: The index, beside the prompts in ``llm-prompts/``.
INDEX_FILE = "examples.md"
#: The index's two sections: the dataflows a run may be given, and the rest.
USED = "Used"
NOT_USED = "Not used"

_LINE_RE = re.compile(r"^- \[(?P<title>[^\]]+)\]\((?P<target>[^)\s]+)\): (?P<text>\S.*)$")


@dataclass(frozen=True)
class IndexEntry:
    """One line of the index: its section, its link and what it says."""

    section: str
    title: str
    #: The link as written, relative to ``llm-prompts/`` so it works on GitHub.
    target: str
    text: str

    @property
    def path(self) -> Path:
        return (builtin.PROMPT_SOURCE_DIR / self.target).resolve()

    @property
    def line(self) -> str:
        """The line as a run shows it: the title and what it says, without the link."""
        return f"{self.title}: {self.text}"


def parse_index(text: str) -> list[IndexEntry]:
    """Every linked line of *text*, in order, with the ``## `` section above it."""
    entries: list[IndexEntry] = []
    section = None
    for raw in text.splitlines():
        if raw.startswith("## "):
            section = raw[3:].strip()
            continue
        match = _LINE_RE.match(raw.strip())
        if section is not None and match:
            entries.append(IndexEntry(section, match["title"], match["target"], match["text"]))
    return entries


def read_index() -> list[IndexEntry]:
    """The index as it is on disk now, read on every call like the prompts; empty when missing."""
    text = builtin.read_prompt_file(INDEX_FILE, wanted_by="the worked examples")
    return parse_index(text) if text else []
