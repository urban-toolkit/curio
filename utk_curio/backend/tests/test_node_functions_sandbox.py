"""The page of the functions node code calls, against what node code gets in each engine.

``skills/node-functions/SKILL.md`` gives each function Curio gives a node's
code, with the engines whose code has it and its arguments. Here node code runs as the sandbox runs it and reports every
``curio_*`` function it can call, with its arguments:

- Python in process: ``worker.execute_code``, over the namespace
  ``worker._worker_init`` seeds and what ``execute_code`` adds to it
  (``curio_secret``, ``install_catalog_helpers``);
- Python isolated: ``child.run_node`` over ``zygote.build_namespace_template``,
  with what ``run_node`` adds to it;
- JavaScript: each ``curio_*`` binding at the top of ``js_wrapper.mjs``, as
  node code run by ``run_js_script`` reads it.

Each function an engine's code has must be on the page for that engine, with
the same arguments, defaults and keyword-only arguments, and each function
the page gives an engine must be in that engine's code. The names a rename
retired, which only raise to name what replaced them
(``catalog_helpers._renamed``), are no functions. A failure gives the call as
the sandbox has it, as the page writes calls.

New names are read inside each test, so this module imports on a checkout
without them and each test fails on its own.
"""

from __future__ import annotations

import ast
import json
import re
import textwrap
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
WRAPPER = REPO_ROOT / "utk_curio" / "sandbox" / "util" / "js_wrapper.mjs"

#: Node code that prints, one line each, every curio_* function it can call,
#: with its arguments: name, kind and default (repr), as Python reads them.
PROBE = """
import inspect as _inspect
import json as _json

for _name, _value in sorted(globals().items()):
    if _name.startswith("curio_") and callable(_value):
        print(_json.dumps([_name, {
            "qualname": getattr(_value, "__qualname__", type(_value).__qualname__),
            "parameters": [
                [p.name, p.kind.name, None if p.default is p.empty else repr(p.default)]
                for p in _inspect.signature(_value).parameters.values()
            ],
        }]))
return 1
"""

#: A binding at the top of the wrapper: const, let, var or a function.
_JS_BINDING_RE = re.compile(r"^(?:const|let|var|(?:async\s+)?function\*?)\s+(curio_[A-Za-z0-9_$]*)", re.MULTILINE)
#: A global the wrapper sets.
_JS_GLOBAL_RE = re.compile(r"\bglobalThis\.(curio_[A-Za-z0-9_$]*)\s*=")
#: The parameters at the head of a function's source, an arrow's or not.
_JS_PARAMETERS_RE = re.compile(r"^(?:async\s+)?(?:function\s*\*?\s*[\w$]*\s*)?\(([^)]*)\)\s*(?:=>|\{)")
_JS_LITERALS = {"null": None, "undefined": None, "true": True, "false": False}
_MISSING = object()


def _indented(code: str) -> str:
    """Code as a node posts it: each line indented four spaces."""
    return "".join("    " + line + "\n" for line in textwrap.dedent(code).strip("\n").split("\n"))


def _page():
    from utk_curio.backend.app.agents.domain import node_functions

    return node_functions.read()


def _same(a, b) -> bool:
    return a is b or (type(a) is type(b) and a == b)


def _written(value) -> str:
    return json.dumps(value) if isinstance(value, str) else repr(value)


def _call(name: str, parameters: list[tuple[str, object, bool]]) -> str:
    """*name*'s call as the page writes calls."""
    parts, starred = [], False
    for parameter, default, keyword_only in parameters:
        if keyword_only and not starred:
            parts.append("*")
            starred = True
        parts.append(parameter if default is _MISSING else f"{parameter}={_written(default)}")
    return f"{name}({', '.join(parts)})"


def _python_functions(lines: list[str]) -> dict[str, list[tuple[str, object, bool]]]:
    """``{name: [(argument, default, keyword_only)]}`` from what PROBE
    printed, without the retired names."""
    from utk_curio.sandbox.util.catalog_helpers import _renamed

    retired = _renamed("old", "new").__qualname__
    found = {}
    for line in lines:
        if not line.startswith('["curio_'):
            continue
        name, info = json.loads(line)
        if info["qualname"] == retired:
            continue
        parameters = []
        for parameter, kind, default in info["parameters"]:
            assert kind in ("POSITIONAL_OR_KEYWORD", "KEYWORD_ONLY"), f"{name} takes *{parameter} or **{parameter}"
            parameters.append((parameter, _MISSING if default is None else ast.literal_eval(default),
                               kind == "KEYWORD_ONLY"))
        found[name] = parameters
    return found


def _page_arguments(function) -> list[tuple[str, object, bool]]:
    return [
        (a.name, _MISSING if a.default is None else a.default_value, a.keyword_only) for a in function.arguments
    ]


def _compare(engine: str, found: dict[str, list[tuple[str, object, bool]]]) -> None:
    page = {function.name: function for function in _page() if engine in function.engines}
    problems = []
    for name in sorted(set(found) - set(page)):
        problems.append(f"{engine} node code has {_call(name, found[name])}, which the page does not give {engine}")
    for name in sorted(set(page) - set(found)):
        problems.append(f"the page gives {engine} {page[name].call}, which {engine} node code does not have")
    for name in sorted(set(page) & set(found)):
        written, real = _page_arguments(page[name]), found[name]
        same = len(written) == len(real) and all(
            w[0] == r[0] and w[2] == r[2] and _same(w[1], r[1]) for w, r in zip(written, real)
        )
        if not same:
            problems.append(f"the page gives {page[name].call}, and {engine} node code has {_call(name, real)}")
    assert not problems, "\n".join(problems)


@pytest.fixture(scope="module")
def _worker():
    from utk_curio.sandbox.app import worker

    worker._worker_init()
    return worker


def test_python_in_process_has_the_functions_the_page_gives_it(_worker):
    session = "node-functions-" + uuid.uuid4().hex
    try:
        result = _worker.execute_code(
            _indented(PROBE), "", "curio.builtin/computation-analysis", "str",
            session_id=session, save_dataset=False,
        )
    finally:
        _worker._session_imports.pop(session, None)
    assert not result["stderr"], result["stderr"]
    found = _python_functions(result["stdout"])
    assert "curio_secret" in found and "curio_load_data" in found, sorted(found)
    _compare("python", found)


def test_python_isolated_has_the_functions_the_page_gives_it(tmp_path):
    from utk_curio.sandbox.isolation import child, zygote

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    request = {
        "code": _indented(PROBE), "node_type": "curio.builtin/computation-analysis", "data_type": "",
        "scratch_dir": str(scratch), "input": {"kind": "none"}, "input_slots": [],
        "session_imports": [], "limits": {},
    }
    result = child.run_node(request, zygote.build_namespace_template)
    assert result["ok"], result["stderr"]
    found = _python_functions(result["stdout"])
    assert "curio_secret" in found and "curio_edit_features" in found, sorted(found)
    _compare("python", found)


def _js_parameters(source: str) -> list[tuple[str, object, bool]]:
    head = _JS_PARAMETERS_RE.match(source.strip())
    assert head, f"no parameters at the head of {source[:80]!r}"
    parameters = []
    for item in [part.strip() for part in head.group(1).split(",") if part.strip()]:
        name, _, default = (piece.strip() for piece in item.partition("="))
        assert re.fullmatch(r"[A-Za-z_$][\w$]*", name), f"{item!r} is no plain parameter"
        if not default:
            parameters.append((name, _MISSING, False))
        else:
            value = _JS_LITERALS[default] if default in _JS_LITERALS else ast.literal_eval(default)
            parameters.append((name, value, False))
    return parameters


def test_javascript_has_the_functions_the_page_gives_it():
    from utk_curio.sandbox.app.worker import run_js_script

    wrapper = WRAPPER.read_text(encoding="utf-8")
    names = sorted(set(_JS_BINDING_RE.findall(wrapper)) | set(_JS_GLOBAL_RE.findall(wrapper)))
    assert "curio_layer" in names, "the scan of js_wrapper.mjs finds nothing; this test would pass vacuously"
    found = {}
    for name in names:
        result, _logs, stderr = run_js_script(
            f"return typeof {name} === 'function' ? String({name}) : null;", {},
            cwd=".", node_type="curio.builtin/js-computation",
        )
        assert result is not None, "\n".join(stderr)
        run = json.loads(result)
        assert run["success"], run.get("error")
        assert run["value"], f"{name} is no function in node code"
        found[name] = _js_parameters(run["value"])
    _compare("javascript", found)
