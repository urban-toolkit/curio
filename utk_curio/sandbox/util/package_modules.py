"""A package's own Python modules, importable while one of its nodes runs (#468).

For a node whose package ships modules in ``sources/``, the backend sends
``package_modules: {"root": <that sources folder>, "names": [...]}``. A node
whose package depends on other packages that ship modules
(``dependencies.packages``) gets a list of such sources, its own package's
first. Both execution modes then do the same three things, through this
module and ``staging.stage_package_modules``:

1. The named modules are linked into a folder of the run's own: a scratch
   directory in process, the child's scratch directory under isolation, where
   the package store is out of reach. Only the named modules: a template's own
   source file is never importable, so a template named like a library cannot
   hide that library.
2. :func:`importable` puts that folder first on ``sys.path`` for the run, so
   node code imports them with ordinary ``import`` statements.
3. When the run ends, the folder leaves ``sys.path`` and every module imported
   from it leaves ``sys.modules``. The next run, of this package after an
   update or of another package with a module of the same name, imports its
   own copy instead of finding a stale one.

A package's modules are its own nodes' alone, and its dependents': an import
of one is never shared with the session's later nodes the way library imports
are (#158), in either mode (:func:`without_package_imports`).
"""

import ast
import contextlib
import keyword
import os
import sys

#: At most this many top-level names per package reach a run.
MAX_NAMES = 64

#: At most this many packages' modules reach a run.
MAX_SOURCES = 16


def _shape_source(raw):
    if not isinstance(raw, dict):
        return None
    root = raw.get("root")
    names = raw.get("names")
    if not isinstance(root, str) or not root or not isinstance(names, list):
        return None
    names = sorted({
        name for name in names
        if isinstance(name, str) and name.isidentifier() and not keyword.iskeyword(name)
    })[:MAX_NAMES]
    return {"root": root, "names": names} if names else None


def shape(raw):
    """The request's ``package_modules``: one source, or a list of sources
    (malformed ones dropped); None when absent or malformed."""
    if isinstance(raw, list):
        sources = [source for source in map(_shape_source, raw[:MAX_SOURCES]) if source]
        return sources or None
    return _shape_source(raw)


def _top(dotted):
    return (dotted or "").split(".", 1)[0]


def without_package_imports(statement, names):
    """*statement*, an ``ast.Import`` or ``ast.ImportFrom``, less what it imports
    from the package's own modules; None when nothing is left."""
    if not names:
        return statement
    if isinstance(statement, ast.ImportFrom):
        return None if statement.level == 0 and _top(statement.module) in names else statement
    kept = [alias for alias in statement.names if _top(alias.name) not in names]
    if not kept:
        return None
    if len(kept) == len(statement.names):
        return statement
    return ast.copy_location(ast.Import(names=kept), statement)


def _within(path, folder):
    try:
        return os.path.commonpath([os.path.abspath(path), folder]) == folder
    except (TypeError, ValueError):
        return False


def _loaded_from(module, folder):
    """Whether *module* was imported from *folder*: its file, or for a folder
    without ``__init__.py``, its search path."""
    namespace = getattr(module, "__dict__", None) or {}
    places = [namespace.get("__file__")]
    try:
        places.extend(namespace.get("__path__") or [])
    except TypeError:
        pass
    return any(isinstance(place, str) and _within(place, folder) for place in places)


def _ours(names):
    """The ``sys.modules`` keys that could hold one of *names* or a submodule."""
    return [
        key for key in list(sys.modules)
        if isinstance(key, str) and _top(key) in names
    ]


@contextlib.contextmanager
def importable(folder, names):
    """While the block runs, the modules staged in *folder* import by name.

    Refuses, before the node's code runs, a name already loaded from somewhere
    else, typically a library of the same name: the node would silently get
    that one instead. The message names the module and where it came from.
    """
    if not folder or not names:
        yield
        return
    folder = os.path.abspath(folder)
    names = set(names)
    for name in sorted(names):
        loaded = sys.modules.get(name)
        if loaded is not None and not _loaded_from(loaded, folder):
            where = getattr(loaded, "__file__", None) or "Python itself"
            raise ImportError(
                f"This node's package, or a package it depends on, ships the module {name!r}, but a module named "
                f"{name!r} is already loaded from {where}, so the node would import "
                f"that one instead. Rename the module in the package."
            )
    sys.path.insert(0, folder)
    try:
        yield
    finally:
        # Modules first, while the path they were found on is still in place:
        # a folder without __init__.py recomputes its search path when it
        # changes.
        for key in _ours(names):
            module = sys.modules.get(key)
            if module is not None and _loaded_from(module, folder):
                sys.modules.pop(key, None)
        try:
            sys.path.remove(folder)
        except ValueError:
            pass
        for key in [key for key in list(sys.path_importer_cache) if _within(key, folder)]:
            sys.path_importer_cache.pop(key, None)
