"""The server reads a docstring's marks as the browser shows them.

``function_nodes.plain_doc`` runs the cases in ``contracts/docMarkup.cases.json``,
which ``src/tests/contracts/docMarkupCases.test.ts`` runs through the views'
own ``docParts`` and ``plainDoc`` (``contracts/docMarkup.ts``): the words of
each case without its marks are what the description of a node made from a
function holds, from the one pattern ``docMarkup.json`` holds. The cases file
is read inside each test, so a checkout without it fails each test on its own.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

CONTRACTS = (
    Path(__file__).resolve().parents[3]
    / "frontend" / "urban-workflows" / "src" / "contracts"
)
CASES_FILE = CONTRACTS / "docMarkup.cases.json"


def _cases():
    if not CASES_FILE.is_file():
        return [pytest.param(None, id="cases-file-missing")]
    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"]
    return [pytest.param(case, id=case["name"]) for case in cases]


@pytest.mark.parametrize("case", _cases())
def test_a_docstrings_words_without_its_marks_are_the_browsers(case):
    assert case is not None, f"{CASES_FILE} is missing"
    from utk_curio.backend.app.packages.application.function_nodes import plain_doc

    assert plain_doc(case["doc"]) == "".join(text for _kind, text in case["parts"])
