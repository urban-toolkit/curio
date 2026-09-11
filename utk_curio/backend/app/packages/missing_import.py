"""Read a node's traceback and say which library it was missing (#299).

Running a node whose code imports something the interpreter does not have ends
in a raw ``ModuleNotFoundError`` traceback, and the user is left to work out
what to install and where. Everything needed to fix that already exists - the
import-name to PyPI-name table in ``dependency_scanner``, the installer in
``pip_runner``, the per-user record in ``libraries.py``, and the
``POST /api/packages/libraries`` route the Installed-libraries modal calls. The
only thing missing was a machine-readable "it was *this* library", which is what
this module produces.

**Why it parses the traceback instead of catching the exception.** The live
exception object is more precise, and it lives in the sandbox, on two separate
code paths (in-process ``worker.py`` and the forked ``isolation/child.py``) that
would each need the hook and would then be free to drift. Carrying it back from
the isolated child means adding a field to the child-result protocol, which is a
validated boundary precisely because node code controls what crosses it - and a
``ModuleNotFoundError`` can be raised by user code with any ``name`` it likes,
so the name would have to be re-validated at the far end regardless. Both paths
already converge on one string, ``traceback.format_exc()``, so parsing it once
in the backend covers both with no second implementation and leaves the sandbox
``/exec`` contract untouched. ``build_pipeline`` already reads the same message
the same way.

**What the answer promises, and what it does not.** ``installable`` means the
name is a legal distribution name, is not stdlib, is not something Curio itself
provides, is not already installed under some distribution, and survives
``pip_runner.validate_python_requirement``. It does **not** promise the
distribution exists on PyPI: the alias table is curated, so an unknown module
resolves to itself, and ``import totally_made_up`` yields a name no index
carries. Checking would mean a network round trip on every failed node run,
which breaks air-gapped and offline-wheel-cache deployments to pre-empt an
answer pip gives a moment later anyway. So the UI offers to *try*, and pip's own
failure is what the user sees when the name is wrong.
"""
from __future__ import annotations

import re
import sys

from utk_curio.backend.app.packages import dependency_scanner, pip_runner

#: The terminating line of a traceback, when that line is a missing module.
#:
#: Anchored to the LAST line rather than searched for anywhere in the text. A
#: chained traceback ("During handling of the above exception...") can carry a
#: ``No module named`` for an optional dependency that a library caught and
#: re-raised as something else entirely; offering to install that one would be
#: answering a question nobody asked. The exception name may be qualified when
#: it crosses a module boundary, hence the optional dotted prefix.
#:
#: Deliberately not ``$``-anchored: the submodule form appends
#: ``; 'x' is not a package``, and that suffix must not defeat the match.
_LAST_LINE_RE = re.compile(
    r"^(?:[\w.]+\.)?ModuleNotFoundError: No module named '([^']+)'"
)

#: Neither of these is repaired by installing anything, so neither matches
#: above and neither should: ``ImportError: cannot import name X from Y`` means
#: the library is present and the symbol is not, and ``DLL load failed`` means
#: it is present and broken - which has its own surface already.


def _reason(module: str, distribution: str | None, reason: str, detail: str | None = None) -> dict:
    return {
        "module": module,
        "distribution": distribution,
        "installable": False,
        "reason": reason,
        "detail": detail,
    }


def detect(stderr: str | None) -> dict | None:
    """The missing library named by *stderr*, or ``None``.

    Returns ``{"module", "distribution", "installable", "reason", "detail"}``.
    ``installable`` is the only field a caller needs to decide whether to offer
    an install; ``reason`` says why not when it is false.

    Never raises. This runs on the response path of a node execution that has
    already failed, and a diagnostic that turns one failure into two is worse
    than no diagnostic - the traceback is reported either way.
    """
    try:
        return _detect(stderr)
    except Exception:  # pragma: no cover - defensive; the traceback still ships
        return None


def _detect(stderr: str | None) -> dict | None:
    if not stderr:
        return None
    lines = stderr.rstrip().splitlines()
    if not lines:
        return None
    match = _LAST_LINE_RE.match(lines[-1].strip())
    if not match:
        return None

    # "No module named 'a.b.c'" is reported for the first segment that is
    # absent, but the fix is always the distribution providing the root.
    module = match.group(1).split(".")[0]

    # Gate one. The capture is `[^']+`, which is a far wider input than a
    # manifest's declared dependency: a crafted ModuleNotFoundError could carry
    # "requests --index-url http://elsewhere". Anything that is not a plain
    # distribution name stops here and is never offered.
    if not module or not pip_runner._PY_NAME_RE.match(module):
        return _reason(module, None, "unsafe-name")

    if module in getattr(sys, "stdlib_module_names", frozenset()):
        # A stdlib module cannot be pip-installed. The real cause is a partial
        # or mis-built Python, and an Install button would be a lie.
        return _reason(module, None, "stdlib")

    if module in dependency_scanner._CURIO_PROVIDED:
        return _reason(module, None, "curio-provided")

    # Is something already providing this import? Metadata only, no subprocess.
    providers = pip_runner.distributions_for_module(module)
    if providers:
        distribution = providers[0]
        # The backend can see it and the node still could not import it, so ask
        # the authority on importability rather than guessing. Memoised per
        # (dist, version), so this costs at most one probe per distribution.
        failures = pip_runner.import_failures([distribution])
        if distribution in failures:
            # pip would report this satisfied and change nothing; reinstalling
            # is not the fix and must not be offered as one.
            return _reason(
                module, distribution, "installed-but-broken", failures[distribution],
            )
        # It imports here but not there: a different interpreter, or a worker
        # holding an older state. Installing again cannot help either.
        return _reason(module, distribution, "installed-not-visible")

    distribution = dependency_scanner.pypi_name_for_import(module)

    # Gate two, and the one every other path to pip also passes through.
    try:
        pip_runner.validate_python_requirement(distribution)
    except pip_runner.PipSpecError:
        return _reason(module, None, "unsafe-name")

    return {
        "module": module,
        "distribution": distribution,
        "installable": True,
        "reason": None,
        "detail": None,
    }
