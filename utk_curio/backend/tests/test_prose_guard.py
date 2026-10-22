"""No text an agent reads is left in utk_curio/'s Python: a string over 200 characters is for people, or code.

Everything an agent reads lives in ``agents/`` as Markdown: the pages of the
base entry, ``messages.md`` among them (what a check tells a model when it
refuses or corrects what the model wrote), and each agent's own prompts.
``utk_curio/`` is the plumbing that reads, renders and fills them, and checks.

This test reads every string in ``utk_curio/``'s Python, the tests left out,
and fails on any whose words run past 200 characters: its literal text, with
adjacent and ``+``-joined literals joined and an f-string's values left out.
Such a string passes only when it is

- a docstring, or a string statement that does nothing;
- a message to users by where it goes: the text of a log line or a warning,
  the help, description or epilog of a command-line argument, or an exception
  raised outside the agents package, which its feature reports;
- one of ``USERS``, an error, a notice or a report people read, with who reads
  it; or
- one of ``CODE``, code another program runs, or a pattern.

An entry of those lists that matches no string fails too, so the lists hold
only what is there.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
#: How long a string's words may run before it must be a message to users.
MAX_CHARS = 200
#: The agents package: an exception raised in it may be a model's refusal, so
#: it is no message to users by where it goes.
AGENTS_PACKAGE = "utk_curio/backend/app/agents/"
#: Calls whose text is a log line or a warning, by the name they are called by.
_LOG_CALL_RE = re.compile(
    r"^(?:\w+\.)?(?:log|logger|logging|_log|_logger|LOG|LOGGER)\.(?:debug|info|warning|warn|error|exception|critical)$"
    r"|^warnings\.warn$"
)
#: A command-line argument's text, by the call and the keyword that hold it.
_ARGPARSE_CALLS = ("add_argument", "ArgumentParser", "add_parser", "add_argument_group", "add_subparsers")
_ARGPARSE_TEXT = ("help", "description", "epilog")

#: Strings over the limit that are messages to users: (file, the def that holds
#: it, how its words start) and who reads it.
USERS = {
    ("utk_curio/backend/app/agents/evaluation/report.py", "RunReport.as_markdown",
     "**This is an evaluation report, not a re"): "the evaluation report a person reads",
    ("utk_curio/backend/app/datasets/infrastructure/left_out_files.py", "_could_not_download",
     "Curio could not download : . A pip insta"): "the error of a download the Data Catalog makes",
    ("utk_curio/backend/app/packages/builder/deps.py", "resolve_js_dependencies",
     "this deployment has no approved JS regis"): "a package build's check, on the build's review",
    ("utk_curio/backend/app/packages/builder/models.py", "_coordinate_grammar_error",
     " is not a valid package coordinate: the "): "a package build's error",
    ("utk_curio/backend/app/packages/builder/preview.py", "run_preview",
     "no pinned preview runner is configured f"): "a package preview's result, on the build's review",
    ("utk_curio/backend/app/packages/domain/default_cells.py", "<module>",
     "Label every pixel of each image with a M"): "a starter cell's comment, in the node's code",
    ("utk_curio/backend/app/packages/infrastructure/workspace.py", "check_build_isolation",
     "This platform cannot bound a package bui"): "a warning to the operator who starts a build",
    ("utk_curio/backend/app/projects/dashboard_payload.py", "DashboardCannotBeStandaloneError.describe",
     "These tiles load their own data when the"): "the dashboard's refusal to publish",
    ("utk_curio/backend/app/upgrade_notices.py", "check_upgrade_notices",
     "Street Vision caches are now per user un"): "an upgrade notice to the operator",
    ("utk_curio/cli/environment.py", "set_environment_variables",
     "--exec-memory-mb  is below the MB floor "): "a warning on the command line",
    ("utk_curio/sandbox/isolation/hardening.py", "apply_and_report",
     "No execution user is configured, so isol"): "the sandbox's start-up report to the operator",
    ("utk_curio/sandbox/isolation/mode.py", "resolve_mode",
     "Isolation is explicitly disabled on an i"): "the sandbox's start-up report to the operator",
    ("utk_curio/sandbox/isolation/mode.py", "resolve_mode",
     "Isolation was requested but is unavailab"): "the sandbox's start-up report to the operator",
    ("utk_curio/sandbox/isolation/mode.py", "resolve_mode",
     "Node execution is NOT isolated: it runs "): "the sandbox's start-up report to the operator",
    ("utk_curio/sandbox/isolation/supervisor.py", "describe_child_death",
     "This node was stopped after s. It is sti"): "a node's error on Play",
    ("utk_curio/sandbox/util/input_names.py", "<module>",
     "This node's code reads `{name}`, which C"): "a node's error on Play",
    ("utk_curio/sandbox/util/input_names.py", "<module>",
     "This node's code reads `{name}`, but not"): "a node's error on Play",
    ("utk_curio/sandbox/util/models.py", "<module>",
     "Model '{model_id}' is not one of your mo"): "a node's error on Play",
    ("utk_curio/sandbox/util/secrets.py", "<module>",
     "No connection key named '{name}' is save"): "a node's error on Play",
}

#: Strings over the limit that are code another program runs, or a pattern.
CODE = {
    ("utk_curio/backend/app/agents/domain/contracts.py", "render_autk_grammar_ts",
     "\n/** The top-level keys an Autark docume"): "the TypeScript the generator writes into src/generated/",
    ("utk_curio/backend/app/agents/domain/contracts.py", "render_render_causes_ts",
     "\n/** The kind prefix of an empty render:"): "the TypeScript the generator writes into src/generated/",
    ("utk_curio/backend/app/agents/domain/contracts.py", "render_agent_categories_ts",
     "\n/** The categories an agent manifest ca"): "the TypeScript the generator writes into src/generated/",
    ("utk_curio/backend/app/agents/domain/contracts.py", "render_solve_stop_reasons_ts",
     "\n/** Every reason a node's repair loop c"): "the TypeScript the generator writes into src/generated/",
    ("utk_curio/backend/app/agents/domain/contracts.py", "render_vis_defaults_ts",
     "\n/** The `$schema` of a Vega-Lite spec C"): "the TypeScript the generator writes into src/generated/",
    ("utk_curio/backend/app/agents/domain/contracts.py", "render_note_colors_ts",
     "\n/** The colors a note's appearance can "): "the TypeScript the generator writes into src/generated/",
    ("utk_curio/backend/app/datasets/domain/catalog_item.py", "<module>",
     "bundle_path = {bundle_path_expr}\ndef _cu"): "the Python a node runs to load a bundle",
    ("utk_curio/backend/app/datasets/domain/catalog_item.py", "loader_snippet",
     "dataset_path = \ntry:\n    df = gpd.read_p"): "the Python a node runs to load a dataset",
    ("utk_curio/backend/app/datasets/domain/catalog_item.py", "loader_snippet",
     "dataset_path = \nwith open(dataset_path, "): "the Python a node runs to load a dataset",
    ("utk_curio/backend/app/packages/builder/preview.py", "<module>",
     "\n(function () {\n  'use strict';\n  var re"): "the JavaScript a package preview runs",
    ("utk_curio/backend/app/packages/builder/preview.py", "build_preview_document",
     "<!doctype html>\n<html><head>\n<meta chars"): "the HTML of a package preview",
    ("utk_curio/backend/app/packages/infrastructure/bounded_exec.py", "<module>",
     "\nimport json, os, resource, sys\nspec = j"): "the Python a bounded build step runs",
    ("utk_curio/backend/app/packages/infrastructure/pip_runner.py", "<module>",
     "\nimport importlib, json, sys\nmapping = j"): "the Python pip's probe runs",
    ("utk_curio/backend/app/packages/infrastructure/pip_runner.py", "<module>",
     "\nimport importlib, json, re, sys\nfrom im"): "the Python pip's probe runs",
    ("utk_curio/sandbox/util/db.py", "_init_db_locked",
     "\n        CREATE TABLE IF NOT EXISTS arti"): "SQL",
    ("utk_curio/sandbox/util/edit_expr.py", "<module>",
     "(?P<num>[0-9]+(?:\\.[0-9]*)?(?:[eE][+-]?["): "a pattern",
    ("utk_curio/tools/preview_runner.py", "<module>",
     "\nwindow.__curioDrive = function (stateNa"): "the JavaScript the preview runner runs",
}


def _literal(node: ast.AST) -> str | None:
    """The literal text of a string expression: a string, an f-string's
    literal parts, or a ``+`` chain of them; None for anything else."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(part.value for part in node.values if isinstance(part, ast.Constant))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _literal(node.left), _literal(node.right)
        if left is not None or right is not None:
            return (left or "") + (right or "")
    return None


class _Strings(ast.NodeVisitor):
    """Each string expression of a module whose words run past the limit,
    with the def that holds it and whether it is a message to users by where
    it goes."""

    def __init__(self, relative: str):
        self.relative = relative
        self.defs: list[str] = []
        self.sinks: list[tuple[str, str | None]] = []  # (kind, detail)
        self.statements: set[int] = set()
        self.found: list[tuple[str, int, str, str, bool]] = []

    def _docstring(self, node) -> None:
        body = getattr(node, "body", None)
        if body and isinstance(body[0], ast.Expr):
            self.statements.add(id(body[0].value))

    def visit_Module(self, node):
        self._docstring(node)
        self.generic_visit(node)

    def _def(self, node):
        self._docstring(node)
        self.defs.append(node.name)
        self.generic_visit(node)
        self.defs.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _def

    def visit_Expr(self, node):
        self.statements.add(id(node.value))
        self.generic_visit(node)

    def visit_Raise(self, node):
        self.sinks.append(("raise", None))
        self.generic_visit(node)
        self.sinks.pop()

    def visit_Call(self, node):
        name = ast.unparse(node.func)
        self.sinks.append(("call", name))
        for arg in node.args:
            self.visit(arg)
        self.sinks.pop()
        for keyword in node.keywords:
            self.sinks.append(("keyword", f"{name}:{keyword.arg}"))
            self.visit(keyword.value)
            self.sinks.pop()
        self.visit(node.func)

    def _users_by_where(self) -> bool:
        for kind, detail in reversed(self.sinks):
            if kind == "call" and _LOG_CALL_RE.match(detail):
                return True
            if kind == "keyword":
                call, _, keyword = detail.rpartition(":")
                if call.rsplit(".", 1)[-1] in _ARGPARSE_CALLS and keyword in _ARGPARSE_TEXT:
                    return True
                if _LOG_CALL_RE.match(call):
                    return True
            if kind == "raise" and not self.relative.startswith(AGENTS_PACKAGE):
                return True
        return False

    def _string(self, node) -> bool:
        text = _literal(node)
        if text is None:
            return False
        if id(node) not in self.statements and len(text) > MAX_CHARS:
            self.found.append((
                self.relative, node.lineno, ".".join(self.defs) or "<module>", text, self._users_by_where(),
            ))
        return True

    def visit_Constant(self, node):
        self._string(node)

    def visit_JoinedStr(self, node):
        self._string(node)
        for part in node.values:
            if isinstance(part, ast.FormattedValue):
                self.visit(part.value)

    def visit_BinOp(self, node):
        if isinstance(node.op, ast.Add) and _literal(node) is not None:
            self._string(node)
            for operand in (node.left, node.right):
                if _literal(operand) is None:
                    self.visit(operand)
                else:
                    self._inside(operand)
            return
        self.generic_visit(node)

    def _inside(self, node):
        """The values inside a string expression already counted."""
        if isinstance(node, ast.JoinedStr):
            for part in node.values:
                if isinstance(part, ast.FormattedValue):
                    self.visit(part.value)
        elif isinstance(node, ast.BinOp):
            for operand in (node.left, node.right):
                if _literal(operand) is None:
                    self.visit(operand)
                else:
                    self._inside(operand)


def _long_strings() -> list[tuple[str, int, str, str, bool]]:
    found = []
    for path in sorted((REPO_ROOT / "utk_curio").rglob("*.py")):
        relative = path.relative_to(REPO_ROOT).as_posix()
        if "/tests/" in relative or "/node_modules/" in relative:
            continue
        strings = _Strings(relative)
        strings.visit(ast.parse(path.read_text(encoding="utf-8")))
        found += strings.found
    return found


def _key(relative: str, where: str, text: str) -> tuple[str, str, str]:
    return relative, where, text[:40]


def test_no_string_over_200_characters_is_agent_text():
    """A string whose words run past 200 characters is a message to users or
    code; any other is text an agent reads, and its home is ``agents/``. Each
    entry of the lists names a long string that is there, so the lists keep
    only what they excuse."""
    found = _long_strings()
    assert len(found) > 40, f"the scan found {len(found)} long strings; it would mean nothing"
    listed = {**USERS, **CODE}
    wrong = [
        f"{relative}:{line} ({where}): {text[:100]!r}"
        for relative, line, where, text, by_where in found
        if not by_where and _key(relative, where, text) not in listed
    ]
    keys = {_key(relative, where, text) for relative, _line, where, text, _by_where in found}
    stale = sorted(key for key in listed if key not in keys)
    assert not wrong and not stale, (
        "these strings run past 200 characters and are no message to users: a text an agent reads "
        "belongs in agents/ (a check's message in agents/agent.curio.builtin@1/messages.md), and a "
        "message to users or code goes in USERS or CODE with who reads it:\n" + "\n".join(wrong)
        + (f"\nand these entries match no string over {MAX_CHARS} characters; delete them: {stale}" if stale else "")
    )
