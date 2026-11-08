"""A run's worked examples are read once, not at each turn.

``examples.used_examples`` gives a run the "Used" dataflows of the index
(``examples.md``) to choose its worked examples from. It read them anew at
each call: it resolved the path of every dataflow Curio ships (61), resolved
each indexed entry's path up to three times, and read and parsed every "Used"
file. Matching an example by name (``select``, ``listing``, ``find``) resolved
its path again. Each resolve walks every component of a path with an lstat,
letting the GIL go at each one. With 100 agent turns at once (``tests/stress``,
run 42528241074 of the stage with agents), the GIL's holder was in
``examples.py`` in 6.6% of py-spy's samples, and a turn's examples step took
7.9 s of wall time at p50.

So the index and the dataflows are read once per examples folder and index
and kept, as the agents' text is rendered once when the backend starts, and
an entry's path is resolved once. Under ``curio.py start --dev``
(``CURIO_DEV=1``) they are read at each call, so an edit shows on the next
run.

New names are read inside each test, so this module imports on a checkout
without them and each test fails on its own.
"""
from __future__ import annotations

import json
import pathlib
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
#: The base entry, which holds the index.
BASE = REPO_ROOT / "agents" / "agent.curio.builtin@1"
MILAN = "Milan heat and thermal comfort"
NINE = "09-heterogeneous-data-linked-views"
SIXTEEN = "16-simple-view-tables-and-images"
#: A task no shipped dataflow has, for an edited example.
EDITED_TASK = "Count the zebras crossing each street"


def _dataflow_files(monkeypatch, name: str) -> list:
    """The dataflow files (``.json``) ``Path.<name>`` runs on from now on."""
    seen: list = []
    original = getattr(pathlib.Path, name)

    def counted(self, *args, **kwargs):
        if self.suffix == ".json":
            seen.append(str(self))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, name, counted)
    return seen


def _by_key() -> dict:
    from utk_curio.backend.app.agents.application.turns import examples

    return {example.key: example for example in examples.used_examples()}


def test_a_turn_walks_and_reads_no_dataflow_again(monkeypatch):
    """What a turn asks of the examples, after the first time: the pool, a
    choice leaving one out, the list ``examples.read`` gives and one example
    by key."""
    from utk_curio.backend.app.agents.application.turns import examples

    monkeypatch.delenv("CURIO_DEV", raising=False)
    first = [example.key for example in examples.used_examples()]
    examples.select(MILAN, exclude=(NINE,))
    walked = _dataflow_files(monkeypatch, "resolve")
    read = _dataflow_files(monkeypatch, "read_text")

    again = [example.key for example in examples.used_examples()]
    chosen = [example.key for example in examples.select(MILAN, exclude=(NINE,))]
    listed = [row["key"] for row in examples.listing(exclude=(NINE,))]
    found = examples.find(SIXTEEN)

    assert again == first and {NINE, SIXTEEN} <= set(first)
    assert chosen and NINE not in chosen and NINE not in listed and found.key == SIXTEEN
    assert walked == [], f"a turn walked {len(walked)} dataflow paths again: {walked[:5]}"
    assert read == [], f"a turn read {len(read)} dataflows again: {read[:5]}"


def test_under_dev_an_edited_example_shows_at_the_next_call_and_without_it_the_kept_one_stays(monkeypatch):
    """``curio.py start --dev`` reads the examples at each call, as it renders
    the agents' text at each read; otherwise a call returns what was read
    first. The edit is a read of example 09 that returns another task."""
    monkeypatch.delenv("CURIO_DEV", raising=False)
    kept = _by_key()[NINE]
    file = kept.entry.path
    edited = {**kept.spec, "dataflow": {**kept.spec["dataflow"], "task": EDITED_TASK}}
    original = pathlib.Path.read_text

    def read_text(self, *args, **kwargs):
        return json.dumps(edited) if self == file else original(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "read_text", read_text)

    assert _by_key()[NINE].spec == kept.spec
    monkeypatch.setenv("CURIO_DEV", "1")
    shown = _by_key()[NINE]
    assert shown.spec["dataflow"]["task"] == EDITED_TASK
    assert "zebra" in shown.words


def test_another_index_gives_its_own_examples(tmp_path, monkeypatch):
    """The examples are kept per index: a copy of the base entry whose index
    moves example 09 under "Not used" gives a pool without it, though the
    shipped index's pool was read first."""
    from utk_curio.backend.app.agents.application.turns import examples
    from utk_curio.backend.app.agents.domain import agent_text

    monkeypatch.delenv("CURIO_DEV", raising=False)
    assert NINE in _by_key()
    copy = tmp_path / BASE.name
    shutil.copytree(BASE, copy)
    index = copy / examples.INDEX_FILE
    lines = index.read_text(encoding="utf-8").splitlines()
    nine = next(line for line in lines if f"/{NINE}.json)" in line)
    # "Not used" is the index's last section, so a line at the end is under it.
    index.write_text("\n".join([line for line in lines if line != nine] + [nine]) + "\n", encoding="utf-8")
    monkeypatch.setattr(agent_text, "base_dir", lambda: copy)

    pool = _by_key()
    assert NINE not in pool and SIXTEEN in pool
