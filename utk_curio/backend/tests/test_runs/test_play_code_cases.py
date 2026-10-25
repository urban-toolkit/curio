"""What a play posts, against what a run on the server sends.

An owner's kept output is found again, when the dataflow reopens
(``runs/reopen.py``), by a key of both (``runs/kept.step_key``): the code as
sent and the input reduced to the names it reads. The cases are in
``providers/flow/playCode.cases.json``, which ``src/tests/providers/playCode.test.ts``
reads too: there the canvas's side, here the server's.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from utk_curio.backend.app.execution.run_engine import play_indent
from utk_curio.backend.app.runs.kept import input_identity

REPO_ROOT = Path(__file__).resolve().parents[4]
CASES = json.loads(
    (REPO_ROOT / "utk_curio" / "frontend" / "urban-workflows" / "src" / "providers" / "flow" / "playCode.cases.json")
    .read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", CASES["code"], ids=[c["name"] for c in CASES["code"]])
def test_the_server_indents_the_code_as_a_play_posts_it(case):
    assert play_indent(case["code"]) == case["posted"]


@pytest.mark.parametrize("case", CASES["inputs"], ids=[c["name"] for c in CASES["inputs"]])
def test_a_plays_input_and_the_engines_key_the_same(case):
    assert input_identity(case["posted"]) == case["identity"]
    assert input_identity(case["engine"]) == case["identity"]
