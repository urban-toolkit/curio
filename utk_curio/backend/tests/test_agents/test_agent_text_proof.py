"""Proof of the move into agents/: agents get today's text, byte for byte.

``utk_curio/llm-prompts/`` holds, unchanged, the renders and the worked
examples' index committed before the move: the four it held, and the eleven
renders that sat in the agents' folders, where each agent's source is now.
Each file the backend renders when it starts, each prompt a run reads, the
package contract a delegated call receives, and the worked examples of fixed
tasks are compared with that text. Every difference is reported, with its
first differing line. The next commit deletes the folder and this test.
"""

from __future__ import annotations

import posixpath
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
#: Today's committed text.
TODAY = REPO_ROOT / "utk_curio" / "llm-prompts"
#: Fixed tasks, and the node type each run is attached to.
TASKS = {
    "Milan heat and thermal comfort": None,
    "How do I show images in a table?": None,
    "road sunlight shadow buildings": "curio.builtin/autk-grammar",
    "compare two scenarios with a bar chart": "curio.builtin/vis-vega",
}


def _first_difference(new: str, today: str) -> str:
    for number, (line, old) in enumerate(zip(new.splitlines(), today.splitlines()), 1):
        if line != old:
            return f"line {number}: {line[:100]!r}, today {old[:100]!r}"
    return (
        f"after line {min(len(new.splitlines()), len(today.splitlines()))}: {len(new)} characters, "
        f"today {len(today)}; it ends {new[-20:]!r}, today {today[-20:]!r}"
    )


def _today(file: Path) -> Path:
    """Today's committed text of *file*: its render in ``llm-prompts/``, or,
    for a prompt that had no template, the file itself, which the move left
    as it was."""
    committed = TODAY / file.name
    return committed if committed.is_file() else file


def test_every_page_and_prompt_renders_as_todays_committed_text(monkeypatch):
    from utk_curio.backend.app.agents.application.turns import delegates
    from utk_curio.backend.app.agents.domain import agent_text, builtin

    monkeypatch.delenv("CURIO_DEV", raising=False)
    monkeypatch.setattr(agent_text, "_TEXTS", {})
    monkeypatch.setattr(agent_text, "_STARTED", False)
    rendered = agent_text.render_at_start()
    assert len(rendered) == 24, sorted(str(path) for path in rendered)
    differing = []
    for file, text in sorted(rendered.items()):
        today = _today(file).read_text(encoding="utf-8")
        if text != today:
            differing.append(f"{file.relative_to(REPO_ROOT)}: {_first_difference(text, today)}")
    reads = 0
    for m in builtin.list_builtin_manifests():
        for key, asset in m.prompts.items():
            file = (agent_text.base_dir() / asset.shared if asset.shared is not None
                    else builtin.agents_dir() / m.dir_name / asset.path)
            text = builtin.read_prompt_text(m.dir_name, key) or ""
            today = _today(file).read_text(encoding="utf-8")
            reads += 1
            if text != today:
                differing.append(f"{m.dir_name}, prompt {key!r}: {_first_difference(text, today)}")
    assert reads == 30
    contract = delegates._build_request_contract().get("backendContract") or ""
    today = (TODAY / "package_contract.md").read_text(encoding="utf-8")
    if contract != today:
        differing.append(f"the delegated package contract: {_first_difference(contract, today)}")
    assert not differing, "differs from today's committed text:\n" + "\n".join(differing)


def test_a_fixed_tasks_worked_examples_are_todays(monkeypatch):
    """The worked-examples block of each fixed task, read through the base
    entry, against the block today's index gives with its links resolved
    from ``llm-prompts/``, as they were. A link never reaches the block (a
    line shows its title and text), and the index is byte for byte today's."""
    from utk_curio import shipped
    from utk_curio.backend.app.agents.application.turns import examples
    from utk_curio.backend.app.agents.domain import agent_text

    monkeypatch.delenv("CURIO_DEV", raising=False)
    index = agent_text.base_dir() / examples.INDEX_FILE
    assert index.read_bytes() == (TODAY / examples.INDEX_FILE).read_bytes()
    moved = {task: examples.block_for(task, node_type=node_type) for task, node_type in TASKS.items()}

    class _AsToday(examples.IndexEntry):
        @property
        def path(self) -> Path:
            linked = posixpath.normpath(f"utk_curio/llm-prompts/{self.target}")
            try:
                return shipped.path(linked).resolve()
            except ValueError:
                return (TODAY / self.target).resolve()

    entries = examples.parse_index((TODAY / examples.INDEX_FILE).read_text(encoding="utf-8"))
    monkeypatch.setattr(
        examples, "read_index",
        lambda: [_AsToday(entry.section, entry.title, entry.target, entry.text) for entry in entries],
    )
    today = {task: examples.block_for(task, node_type=node_type) for task, node_type in TASKS.items()}
    assert all(today.values()), [task for task, block in today.items() if not block]
    differing = [f"{task!r}: {_first_difference(moved[task] or '', block)}"
                 for task, block in today.items() if moved[task] != block]
    assert not differing, "worked examples differ from today's:\n" + "\n".join(differing)
