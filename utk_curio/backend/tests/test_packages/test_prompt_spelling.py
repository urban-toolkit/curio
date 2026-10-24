"""No built-in prompt repeats a misspelling that has shipped in one (#430).

The Node Explainer's instruction opened with "YOU EXPLANATION SHOULD HAVE
MAXIMUM 500 WORDS", and users read it as the first message of their chat.
#417 deleted that prompt, which left nothing to keep the slip out of the
others. The scan reads every page of the base entry
(``agents/agent.curio.builtin@1/``) and every prompt in each shipped agent's
``prompts/`` (``agents/<id>@<major>/prompts/``), each as written and as an
agent reads it, rendered. A phrase can wrap onto the next line, so its words
match across any whitespace.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
#: The base entry: the pages the agents share.
BASE = REPO_ROOT / "agents" / "agent.curio.builtin@1"
#: Each shipped agent's own prompts.
AGENT_PROMPTS = sorted((REPO_ROOT / "agents").glob("*/prompts"))
# Each misspelling a shipped prompt carried, and where it was.
MISSPELLINGS = {
    "you explanation": "the Node Explainer's instruction (#430)",
    "recieved": "the default preamble",
    "foward": "the default preamble",
}


def _pattern(phrase: str) -> re.Pattern[str]:
    words = r"\s+".join(re.escape(word) for word in phrase.split())
    return re.compile(rf"\b{words}\b", re.IGNORECASE)


def _files() -> list[Path]:
    """Every page of the base entry, then every shipped agent's prompts."""
    pages = [path for path in sorted(BASE.rglob("*.md")) if path != BASE / "README.md"]
    return pages + [path for folder in AGENT_PROMPTS for path in sorted(folder.rglob("*")) if path.is_file()]


def _offenders() -> list[str]:
    from utk_curio.backend.app.agents.domain import agent_text

    found = []
    for path in _files():
        for how, text in (
            ("as written", path.read_text(encoding="utf-8", errors="replace")),
            ("as read", agent_text.read(path)),
        ):
            for phrase, where in MISSPELLINGS.items():
                for match in _pattern(phrase).finditer(text):
                    line = text.count("\n", 0, match.start()) + 1
                    found.append(f"{path.relative_to(REPO_ROOT).as_posix()}, {how}, line {line}: "
                                 f"{match.group(0)!r}, as in {where}")
    return found


def test_no_prompt_repeats_a_shipped_misspelling():
    names = [path.relative_to(BASE).as_posix() for path in BASE.rglob("*.md")]
    # Guards the walk itself: without the pages the agents share, the
    # preamble and the rules they include, the scan passes vacuously.
    assert {"default_preamble.md", "rules/research_verify_rules.md"} <= set(names), f"no pages in {BASE}"
    # And without each shipped agent's own prompts it would miss most of them.
    assert len(AGENT_PROMPTS) == 7 and all(list(folder.glob("*.md")) for folder in AGENT_PROMPTS), AGENT_PROMPTS

    offenders = _offenders()
    assert not offenders, "misspelled prompt text:\n" + "\n".join(offenders)
