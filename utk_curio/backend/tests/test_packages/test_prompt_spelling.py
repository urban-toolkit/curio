"""No built-in prompt repeats a misspelling that has shipped in one (#430).

The Node Explainer's instruction opened with "YOU EXPLANATION SHOULD HAVE
MAXIMUM 500 WORDS", and users read it as the first message of their chat.
#417 deleted that prompt, which left nothing to keep the slip out of the
others. The scan reads every file in ``utk_curio/llm-prompts/`` and in each
shipped agent's ``prompts/`` (``agents/<id>@<major>/prompts/``): the
templates and the prompts generated from them, and the prompts with no
template. A phrase can wrap onto the next line, so its words match across any
whitespace.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
PROMPTS = REPO_ROOT / "utk_curio" / "llm-prompts"
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


def _offenders() -> list[str]:
    found = []
    for path in [path for folder in (PROMPTS, *AGENT_PROMPTS) for path in sorted(folder.rglob("*"))]:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for phrase, where in MISSPELLINGS.items():
            for match in _pattern(phrase).finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                found.append(f"{path.relative_to(REPO_ROOT).as_posix()}:{line}: "
                             f"{match.group(0)!r}, as in {where}")
    return found


def test_no_prompt_repeats_a_shipped_misspelling():
    names = [path.name for path in PROMPTS.glob("*.md")]
    # Guards the walk itself: without both kinds of file the scan passes vacuously.
    assert any(name.endswith(".template.md") for name in names), f"no prompt templates in {PROMPTS}"
    assert any(not name.endswith(".template.md") for name in names), f"no generated prompts in {PROMPTS}"
    # And without each shipped agent's own prompts it would miss most of them.
    assert len(AGENT_PROMPTS) == 7 and all(list(folder.glob("*.md")) for folder in AGENT_PROMPTS), AGENT_PROMPTS

    offenders = _offenders()
    assert not offenders, "misspelled prompt text:\n" + "\n".join(offenders)
