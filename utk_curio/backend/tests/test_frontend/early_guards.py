"""Skip a sign-in test before its page opens, on a stack without sign-in.

Most e2e tests that need sign-in start their body with ``require_user_auth()``,
often right after ``require_project_page()``. On a stack without sign-in (CI's
test-isolated job) such a test skips, but only after its fixtures have opened a
browser page and reset the database: about half a second each, for hundreds of
tests.

At collection, :class:`EarlyGuards` finds each test whose body starts with bare
calls of the guards in ``utils/environment.py`` that include
``require_user_auth()``. When the test's setup starts, before any of its
fixtures, it calls those same guards in the same order, up to and including
``require_user_auth()``. A guard that skips raises the very skip the body would
have raised, from the same line with the same reason, so JUnit records it the
same way. When none skips, the test runs as before and its body calls them
again.

This only happens against a stack that is already up (``CURIO_E2E_USE_EXISTING``,
which ``scripts/test.sh`` always sets) and only once its backend has answered
``/api/config/public``, the answer the guards read and keep for the session. In
any other run, and for any other test, the body decides as before: a guard
called after another statement, inside an ``if``, through a helper or a
fixture, or in a test wrapped by a decorator, which runs before the body.
"""

from __future__ import annotations

import ast
import inspect
import os

import pytest

from .utils import environment

#: The guards a test body may start with. They read only the backend's public
#: config (or the environment), so calling them before the fixtures gives the
#: answer the body would get.
GUARDS = ("require_project_page", "require_no_project_mode", "require_user_auth")

#: The guards to run before a test's fixtures, found at collection.
_EARLY = pytest.StashKey[tuple]()

#: Each parsed file's functions: by the line their code starts on, the
#: function's name and the guards its body starts with. Not the trees, which
#: would hold every e2e module in memory for the whole run.
_FUNCTIONS: dict[str, dict[int, tuple[str, tuple[str, ...]]]] = {}


def _functions_in(filename: str) -> dict[int, tuple[str, tuple[str, ...]]]:
    """Each function defined in ``filename`` and the guards its body starts with."""
    found = _FUNCTIONS.get(filename)
    if found is None:
        found = {}
        try:
            with open(filename, encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), filename)
        except (OSError, SyntaxError, ValueError):
            tree = None
        for node in ast.walk(tree) if tree is not None else ():
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # A decorated function's code starts on its first decorator.
                first = node.decorator_list[0].lineno if node.decorator_list else node.lineno
                found[first] = (node.name, tuple(_leading_guard_calls(node)))
        _FUNCTIONS[filename] = found
    return found


def _leading_guard_calls(node: ast.AST) -> list[str]:
    """The guards the body calls, bare and without arguments, before anything else."""
    body = list(node.body)
    if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]  # the docstring
    names = []
    for statement in body:
        call = statement.value if isinstance(statement, ast.Expr) else None
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                and call.func.id in GUARDS and not call.args and not call.keywords):
            break
        names.append(call.func.id)
    return names


def leading_guards(function) -> tuple:
    """The guards to call before ``function``'s fixtures, in order; empty for none.

    That is the run of guard calls its body starts with, up to and including
    ``require_user_auth()``, when the run has it. Each name must be the guard
    itself in the function's module, not a local, a closure or another
    function of that name. A function wrapped by a decorator gets nothing,
    since the wrapper runs before the body.
    """
    code = getattr(function, "__code__", None)
    if code is None or inspect.unwrap(function) is not function:
        return ()
    defined, names = _functions_in(code.co_filename).get(code.co_firstlineno, (None, ()))
    if defined != code.co_name or "require_user_auth" not in names:
        return ()
    local = set(code.co_varnames) | set(code.co_cellvars) | set(code.co_freevars)
    guards = []
    for name in names[: names.index("require_user_auth") + 1]:
        guard = getattr(environment, name)
        if name in local or function.__globals__.get(name) is not guard:
            return ()
        guards.append(guard)
    return tuple(guards)


class EarlyGuards:
    """Runs each test's leading guards before its fixtures (module docstring)."""

    def __init__(self, environ=os.environ):
        self._environ = environ

    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(self, items):
        if not self._environ.get("CURIO_E2E_USE_EXISTING"):
            return
        for item in items:
            guards = leading_guards(getattr(item, "function", None))
            if guards:
                item.stash[_EARLY] = guards

    # Not tryfirst: pytest's own skip and skipif marks are judged first, as
    # before, and this still runs before the runner sets up the fixtures.
    def pytest_runtest_setup(self, item):
        guards = item.stash.get(_EARLY, ())
        if guards and environment._fetch_public_config() is not None:
            for guard in guards:
                guard()
