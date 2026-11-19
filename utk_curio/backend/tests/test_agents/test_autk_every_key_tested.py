"""Every key of the vendored Autark grammar schema names the test that runs it.

``utk_curio/backend/tests/autk_grammar_key_tests.json`` maps each key path of
``app/agents/schemas/autk-grammar.v1.json`` (``_support/autk_key_paths``) to
the tests that run it on a path Curio runs a document on: a node's run, a run
on the server, a compute step, the agents' document check. Each entry names:

- ``test``: a test file, from the repository's root, and the test in it,
  ``::`` between them: a pytest test as ``function`` or ``Class::function``,
  with a case in brackets, and a Jest test by its titles, a ``describe``'s
  first;
- ``document``, where the test reads its documents from a file: that file, a
  dataflow (its Autark nodes' code) or any JSON file holding documents under
  ``spec`` or ``document`` keys; one of them writes the key;
- ``refused``, where the test shows the key refused: a key autk-grammar 5
  renamed (``renamedKeys`` here, by its old name, autkGrammar.json's
  ``renamedKeys``) or one a node does not run yet (autkGrammar.json's
  ``notRunYet``). Every other key names a test that runs it.

So a key a later grammar release adds fails here until a test runs it. Every
problem is listed, sorted, in one message. The files are read inside each
test, so a checkout without one fails each test on its own.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
MAP_FILE = REPO_ROOT / "utk_curio" / "backend" / "tests" / "autk_grammar_key_tests.json"
SCHEMA_FILE = REPO_ROOT / "utk_curio" / "backend" / "app" / "agents" / "schemas" / "autk-grammar.v1.json"
SHARED_FILE = REPO_ROOT / "utk_curio" / "frontend" / "urban-workflows" / "src" / "contracts" / "autkGrammar.json"

#: The entries' fields.
FIELDS = {"test", "document", "refused"}


def _read(path: Path) -> dict:
    assert path.is_file(), f"{path.relative_to(REPO_ROOT)} is missing"
    return json.loads(path.read_text(encoding="utf-8"))


def _key_paths() -> list[str]:
    from utk_curio.backend.tests._support.autk_key_paths import key_paths

    return key_paths(_read(SCHEMA_FILE))


def _entries(section: str) -> dict[str, list[dict]]:
    return _read(MAP_FILE).get(section) or {}


def _section(path: str) -> str:
    """The document's section a path is in, as autkGrammar.json's rules name
    it: "" for a key of the document, else "data[]", "compute[]", ..."""
    head = re.split(r"[.\[(]", path, maxsplit=1)[0]
    return f"{head}[]" if "." in path or "[" in path or "(" in path else ""


def _last_key(path: str) -> str:
    """The key a path ends with, or the kind it names."""
    kind = re.search(r"[\[(]([^\[\]()]+)[\])]$", path)
    if kind:
        return kind.group(1).split("|")[0]
    return re.split(r"[.\[\]()]+", path.rstrip("]).*"))[-1]


def _refusing_rule(path: str) -> dict | None:
    """The notRunYet rule of autkGrammar.json that refuses *path*: a document's
    key it names, with every key under it."""
    for rule in _read(SHARED_FILE).get("notRunYet", []):
        if "value" in rule:
            continue
        if rule["in"] == "" and (path == rule["key"] or path.startswith(rule["key"] + "[")
                                 or path.startswith(rule["key"] + ".")):
            return rule
    return None


def test_every_key_of_the_vendored_schema_names_a_test():
    keys = _key_paths()
    mapped = _entries("keys")
    missing = sorted(set(keys) - set(mapped))
    unknown = sorted(set(mapped) - set(keys))
    empty = sorted(path for path, entries in mapped.items() if not entries)
    problems = [f"no test runs {path}" for path in missing]
    problems += [f"{path} is no key of the vendored schema" for path in unknown]
    problems += [f"{path} names no test" for path in empty]
    assert not problems, (
        f"{MAP_FILE.relative_to(REPO_ROOT)} and the vendored schema disagree, "
        f"{len(problems)} problem(s):\n" + "\n".join(problems)
    )


def test_every_renamed_key_names_the_test_that_refuses_it():
    keys = set(_key_paths())
    renamed = _entries("renamedKeys")
    rules = _read(SHARED_FILE)["renamedKeys"]
    problems = []
    for rule in rules:
        if not any(_last_key(path) == rule["key"] and _section(path) == rule["in"] for path in renamed):
            problems.append(f'no test refuses "{rule["key"]}" in {rule["in"]}, which autk-grammar 5 renamed')
    for path, entries in renamed.items():
        if path in keys:
            problems.append(f"{path} is a key of the vendored schema, not a renamed one")
        if not any(_last_key(path) == rule["key"] and _section(path) == rule["in"] for rule in rules):
            problems.append(f"{path} is no key autkGrammar.json names as renamed")
        if not entries or not all(entry.get("refused") for entry in entries):
            problems.append(f"{path} names a test that does not refuse it")
    assert not problems, "\n".join(sorted(problems))


def test_a_key_a_node_does_not_run_yet_names_its_refusal_and_every_other_key_a_run():
    problems = []
    for path, entries in _entries("keys").items():
        refused = [entry for entry in entries if entry.get("refused")]
        if _refusing_rule(path):
            if not refused:
                problems.append(f"{path}: a node does not run it yet, and no test named here refuses it")
        elif len(refused) == len(entries):
            problems.append(f"{path}: a node runs it, and every test named here refuses it")
    assert not problems, "\n".join(sorted(problems))


def _python_test_exists(source: str, names: list[str]) -> bool:
    tree = ast.parse(source)
    scope = tree.body
    for depth, name in enumerate(names):
        found = next((node for node in scope if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                      and node.name == name), None)
        if found is None:
            return False
        if depth < len(names) - 1:
            if not isinstance(found, ast.ClassDef):
                return False
            scope = found.body
    return True


def _jest_test_exists(source: str, titles: list[str]) -> bool:
    """Whether each of *titles* is a string of *source*, its quotes escaped or not."""
    plain = source.replace("\\'", "'").replace('\\"', '"')
    return all(any(f"{quote}{title}{quote}" in plain for quote in ('"', "'", "`")) for title in titles)


def _test_problem(entry: dict) -> str | None:
    """What is wrong with the test *entry* names, or None."""
    if set(entry) - FIELDS or "test" not in entry:
        return f"has fields {sorted(set(entry))}; an entry holds {sorted(FIELDS)}, a test always"
    file_name, _, name = entry["test"].partition("::")
    path = REPO_ROOT / file_name
    if not name:
        return f"{entry['test']} names no test in its file"
    if not path.is_file():
        return f"{file_name} is no file of the repository"
    case = re.search(r"\[(.*)\]$", name)
    names = (name[: case.start()] if case else name).split("::")
    source = path.read_text(encoding="utf-8")
    exists = _python_test_exists(source, names) if path.suffix == ".py" else _jest_test_exists(source, names)
    if not exists:
        return f"{entry['test']}: {file_name} holds no such test"
    if case:
        places = [source, *([(path.parent / "conftest.py").read_text(encoding="utf-8")]
                            if (path.parent / "conftest.py").is_file() else [])]
        if entry.get("document") and (REPO_ROOT / entry["document"]).is_file():
            places.append((REPO_ROOT / entry["document"]).read_text(encoding="utf-8"))
        if not any(case.group(1) in place for place in places):
            return f"{entry['test']}: no case {case.group(1)!r} in the test's file, its conftest or its document"
    return None


def test_every_test_named_exists():
    problems = []
    for section in ("keys", "renamedKeys"):
        for path, entries in _entries(section).items():
            for entry in entries:
                problem = _test_problem(entry)
                if problem:
                    problems.append(f"{path}: {problem}")
    assert not problems, f"{len(problems)} test(s) named that do not exist:\n" + "\n".join(sorted(problems))


def test_every_test_named_writes_its_key():
    """An entry with a document holds a document that writes the key, by its
    path (a renamed key, which the schema does not know, by its name); one
    without names the key in its test's file. A refused key's document writes
    the key a rule refuses, which refuses every key under it."""
    from utk_curio.backend.tests._support.autk_key_paths import documents_in, written_paths

    schema = _read(SCHEMA_FILE)
    written: dict[str, set] = {}
    problems = []
    for section in ("keys", "renamedKeys"):
        for path, entries in _entries(section).items():
            rule = _refusing_rule(path) if section == "keys" else None
            for entry in entries:
                if _test_problem(entry):
                    continue
                document = entry.get("document")
                if document is None:
                    text = (REPO_ROOT / entry["test"].partition("::")[0]).read_text(encoding="utf-8")
                    named = rule["key"] if entry.get("refused") and rule else _last_key(path)
                    if not re.search(r"(?<![\w$])" + re.escape(named) + r"(?![\w$])", text):
                        problems.append(f"{path}: {entry['test']} names no {named!r}")
                    continue
                if not (REPO_ROOT / document).is_file():
                    problems.append(f"{path}: {document} is no file of the repository")
                    continue
                if section == "renamedKeys":
                    if f'"{_last_key(path)}"' not in (REPO_ROOT / document).read_text(encoding="utf-8"):
                        problems.append(f"{path}: no document of {document} writes {_last_key(path)!r}")
                    continue
                if document not in written:
                    written[document] = set().union(*[written_paths(schema, held)
                                                     for held in documents_in(REPO_ROOT / document)])
                wanted = rule["key"] if entry.get("refused") and rule else path
                if wanted not in written[document]:
                    problems.append(f"{path}: no document of {document} writes {wanted}")
    assert not problems, f"{len(problems)} test(s) that do not write their key:\n" + "\n".join(sorted(problems))
