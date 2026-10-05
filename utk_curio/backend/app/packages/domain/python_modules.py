"""Which top-level Python modules a package ships beside its templates (#468). Pure.

A module is a ``<name>.py`` file in ``sources/``, or a ``<name>/`` folder
there holding a ``.py`` file at any depth, where ``<name>`` is a Python
identifier. A file a template names as its ``source`` is that template's
code, not a module: two packages may each have a ``loader`` template, and a
template named like a library must not hide that library.

One rule over a package's file paths, asked by the installer and a run
(``repositories/python_modules.py``, over a directory), by Save into a package
(``builder/factory.py``) and by the Package Builder (``builder/deps.py``), over
the files they are about to write. The last two hand the names to the import
scanner, which leaves them out of the detected dependencies.
"""

from __future__ import annotations

import keyword
from typing import Iterable

#: The package folder that holds template sources and the modules they import.
SOURCES_DIR = "sources"


def _parts(path: str) -> list[str]:
    return [part for part in str(path).replace("\\", "/").split("/") if part and part != "."]


def module_names_in(paths: Iterable[str], template_sources: Iterable[object] = ()) -> frozenset[str]:
    """The top-level module names among *paths*, a package's files as
    package-relative paths; *template_sources* are its templates' ``source``
    values, whose files are not modules."""
    templates = {"/".join(_parts(source)) for source in template_sources if isinstance(source, str)}
    names: set[str] = set()
    for path in paths:
        parts = _parts(path)
        if len(parts) < 2 or parts[0] != SOURCES_DIR or not parts[-1].endswith(".py"):
            continue
        if "/".join(parts) in templates:
            continue
        name = parts[1][: -len(".py")] if len(parts) == 2 else parts[1]
        if name.isidentifier() and not keyword.iskeyword(name):
            names.add(name)
    return frozenset(names)
