"""The sandbox's reader of a Map Edits node's code
(``utk_curio/sandbox/util/feature_edits_code.py``), which holds what agents
write for the node to what the node itself reads.

It is a port of the node's own reader, ``readEditFeaturesCode`` in
``utils/editFeatures/editFeatures.ts``, and reads every code of
``editFeaturesCode.cases.json`` as Jest checks the node reads it: the code
the node writes, other code it reads, each as the same settings, circles and
comment lines, and the code it refuses with the same problem, word for word.

Every test imports the reader itself, so a checkout without it fails test by
test rather than at collection.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CASES = REPO_ROOT / "utk_curio/frontend/urban-workflows/src/utils/editFeatures/editFeaturesCode.cases.json"
READER = REPO_ROOT / "utk_curio/sandbox/util/feature_edits_code.py"
#: The comment lines a new node's code starts with (``EDIT_CODE_NOTE``).
NOTE = [
    "# Map Edits writes this code from its edit list: each edit, in the",
    "# order it was made, on the features whose key is one of its ids. It is",
    "# written again when the list changes.",
]


def _part(name):
    """One part of the cases file; read at collection, so a checkout without
    it fails these tests rather than the whole module."""
    try:
        return json.loads(CASES.read_text(encoding="utf-8"))[name]
    except FileNotFoundError:
        return [{"name": "editFeaturesCode.cases.json is missing", "code": None}]


@pytest.mark.parametrize("case", _part("cases"), ids=lambda c: c["name"])
def test_the_code_the_node_writes_is_read_as_the_node_reads_it(case):
    from utk_curio.sandbox.util.feature_edits_code import read_edit_features_code

    assert case["code"] is not None, case["name"]
    assert read_edit_features_code(case["code"]) == {
        "settings": case["settings"],
        "circles": case.get("circles", 1),
        "comments": case.get("comments", NOTE),
    }


@pytest.mark.parametrize("case", _part("read"), ids=lambda c: c["name"])
def test_code_the_node_did_not_write_is_read_as_the_node_reads_it(case):
    from utk_curio.sandbox.util.feature_edits_code import read_edit_features_code

    assert case["code"] is not None, case["name"]
    assert read_edit_features_code(case["code"]) == {
        "settings": case["settings"],
        "circles": case["circles"],
        "comments": case["comments"],
    }


@pytest.mark.parametrize("case", _part("refused"), ids=lambda c: c["name"])
def test_code_the_node_refuses_is_refused_with_the_same_words(case):
    from utk_curio.sandbox.util.feature_edits_code import read_edit_features_code

    assert case["code"] is not None, case["name"]
    assert read_edit_features_code(case["code"]) == {"problem": case["problem"]}


def test_blank_code_is_a_new_node_with_no_edits():
    from utk_curio.sandbox.util.feature_edits_code import read_edit_features_code

    assert read_edit_features_code("") == {"settings": None}
    assert read_edit_features_code("  \n") == {"settings": None}
    assert read_edit_features_code(None) == {"settings": None}


def test_values_are_spelled_as_javascript_spells_them():
    """A reason shows values as the browser writes them: these are what
    ``String`` and ``JSON.stringify`` give in Node."""
    from utk_curio.sandbox.util import js_values

    numbers = [1e21, 1e20, 0.000001, 1e-7, 123.456, -0.0, 2 ** 53, 5e-324, 1.5e300, 0.1 + 0.2, 100, 1e16]
    assert [js_values.number(n) for n in numbers] == [
        "1e+21", "100000000000000000000", "0.000001", "1e-7", "123.456", "0", "9007199254740992",
        "5e-324", "1.5e+300", "0.30000000000000004", "100", "10000000000000000",
    ]
    record = {"b": 1, "2": [1.5, None, True, 'x"y'], "a": {"10": 2, "1": 3}}
    assert js_values.stringify(record) == '{"2":[1.5,null,true,"x\\"y"],"b":1,"a":{"1":3,"10":2}}'
    spaces = "".join(chr(code) for code in (0xFEFF, 0x2028, 0x20))
    assert js_values.trim(spaces + "a b" + chr(0xA0) + chr(0x3000)) == "a b"


def test_the_keywords_the_reader_takes_are_the_steps():
    """The call takes, after its input and its edits, exactly the keywords
    ``curio_edit_features`` has, in its order."""
    import inspect

    from utk_curio.sandbox.util.feature_edits import edit_features
    from utk_curio.sandbox.util.feature_edits_code import KEYWORDS

    assert list(inspect.signature(edit_features).parameters)[2:] == list(KEYWORDS)


def test_the_reader_reads_by_its_own_rules_never_by_python():
    """Python would take code the node refuses (a comment inside the call, a
    triple-quoted text, a name where a value goes), so the reader reads by the
    node's rules alone: no ``ast``, no ``eval``."""
    tree = ast.parse(READER.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    calls = [node.func for node in ast.walk(tree) if isinstance(node, ast.Call)]
    functions = {func.id for func in calls if isinstance(func, ast.Name)}
    methods = {func.attr for func in calls if isinstance(func, ast.Attribute)}
    assert "ast" not in imported, imported
    assert not functions & {"eval", "exec", "compile", "__import__"}, functions
    assert "literal_eval" not in functions | methods
