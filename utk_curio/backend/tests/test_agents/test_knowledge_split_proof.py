"""Proof of the preamble's split into knowledge pages: agents get the same text, byte for byte.

``preamble_before_the_split.txt`` beside this file is the preamble's source
before the split, when every section was written in it (a ``.txt`` file, since
no Markdown but a README lives under ``utk_curio/``). Rendered now, it must
equal the preamble the backend renders now, which includes one page of
``knowledge/`` per section, and each agent that reads the preamble must read
that same text. Every difference is reported with its first differing line.
The next commit deletes this test and that file.
"""

from __future__ import annotations

from pathlib import Path

BEFORE = Path(__file__).resolve().parent / "preamble_before_the_split.txt"


def _first_difference(new: str, before: str) -> str:
    for number, (line, old) in enumerate(zip(new.splitlines(), before.splitlines()), 1):
        if line != old:
            return f"line {number}: {line[:100]!r}, before {old[:100]!r}"
    return f"{len(new)} characters, before {len(before)}; it ends {new[-20:]!r}, before {before[-20:]!r}"


def test_the_preamble_renders_as_it_did_before_the_split(monkeypatch):
    from utk_curio.backend.app.agents.domain import agent_text, builtin, contracts

    monkeypatch.delenv("CURIO_DEV", raising=False)
    monkeypatch.setattr(agent_text, "_TEXTS", {})
    monkeypatch.setattr(agent_text, "_STARTED", False)
    source = BEFORE.read_text(encoding="utf-8")
    assert "## Scenarios" in source and "{{include:" not in source, "the copy is the preamble before the split"
    before = contracts.render_template(source, "curio:default_preamble.md", including=("default_preamble.md",))

    preamble = agent_text.base_dir() / "default_preamble.md"
    written = preamble.read_text(encoding="utf-8")
    assert written.count("{{include:knowledge/") == 10, "the preamble includes one page per section"
    after = agent_text.render_at_start()[preamble]
    assert after == before, f"the preamble differs from before the split: {_first_difference(after, before)}"

    readers = [m.dir_name for m in builtin.list_builtin_manifests() if "system" in m.prompts]
    assert len(readers) == 7, readers
    for coord in readers:
        read = builtin.read_prompt_text(coord, "system") or ""
        assert read == before, f"{coord} reads another preamble: {_first_difference(read, before)}"
