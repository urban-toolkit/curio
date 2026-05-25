"""Source-code import scanners for the Node Factory / Save-As flow.

When a draft lands in ``/api/packages/factory/install`` (or ``/factory/build``),
each template's source body is scanned for top-level imports and the union is
written to ``manifest.dependencies.python`` / ``.js`` — replacing whatever the
draft carried. This removes the manual dependency-entry step that used to live
in the wizard (now deleted) and keeps a package's declared deps in sync with
what its sources actually import.

Scope:

* **Python** — parsed via :mod:`ast`. Top-level imports only (i.e., not
  conditionally imported behind ``if``/``try`` blocks — that's fine for v1).
  Stdlib modules are filtered out via :data:`sys.stdlib_module_names`. A
  small alias table maps a few common cases where the importable name
  differs from the PyPI package name (``cv2`` → ``opencv-python`` etc.).
  Curio-provided modules (declared in :data:`_CURIO_PROVIDED`) are also
  filtered. Returns ``[]`` if the source has a :class:`SyntaxError`.
* **JavaScript** — regex-scanned for ``import ... from "X"``,
  ``import("X")``, and ``require("X")`` forms. Relative paths
  (``./x``, ``../y``, absolute paths starting with ``/``) are skipped.
  Subpath imports collapse to the top-level package
  (``lodash/fp`` → ``lodash``); scoped packages keep both segments
  (``@scope/pkg``).
"""

from __future__ import annotations

import ast
import logging
import re
import sys

log = logging.getLogger(__name__)


# Importable name → PyPI install name for the small set of mismatches users
# trip on most often. Anything not in this map passes through unchanged, so the
# emitted manifest entry is just the import name (which is correct for the
# overwhelming majority of packages).
_PY_NAME_ALIAS: dict[str, str] = {
    "cv2": "opencv-python",
    "sklearn": "scikit-learn",
    "PIL": "pillow",
    "yaml": "pyyaml",
    "bs4": "beautifulsoup4",
    "skimage": "scikit-image",
}

# Modules supplied by the Curio runtime that user code may import without
# declaring them as deps. Conservative starting set; expand as needed.
_CURIO_PROVIDED: frozenset[str] = frozenset({
    "curio",
    "curio_kernel",
    "utk_curio",
})


def scan_python_imports(source: str) -> list[str]:
    """Return a sorted, deduplicated list of top-level imports in *source*.

    Stdlib modules and Curio-provided modules are filtered out; recognised
    importable names are mapped to their PyPI install names via
    :data:`_PY_NAME_ALIAS`. Unparseable source returns ``[]``.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        log.warning("scan_python_imports: SyntaxError, returning []: %s", exc)
        return []

    stdlib = getattr(sys, "stdlib_module_names", frozenset())
    out: set[str] = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".", 1)[0]
                out.add(top)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue  # relative import; package-internal
            module = node.module or ""
            top = module.split(".", 1)[0]
            if top:
                out.add(top)

    filtered: set[str] = set()
    for name in out:
        if name in stdlib:
            continue
        if name in _CURIO_PROVIDED:
            continue
        filtered.add(_PY_NAME_ALIAS.get(name, name))
    return sorted(filtered)


# Matches ES-module / CommonJS import forms with single or double quotes.
# Captures the bare specifier inside the quotes.
_JS_IMPORT_RE = re.compile(
    r"""(?xs)
    (?:
      \bimport\s+[^'"]*?\bfrom\s*  # `import ... from`
      | \bimport\s*\(\s*           # `import(`
      | \brequire\s*\(\s*          # `require(`
    )
    (['"])([^'"\n]+)\1
    """
)


def _js_top_level_specifier(spec: str) -> str | None:
    """Collapse `lodash/fp` → `lodash`; keep `@scope/pkg`; skip relative/abs paths."""
    s = spec.strip()
    if not s or s.startswith(".") or s.startswith("/"):
        return None
    if s.startswith("@"):
        parts = s.split("/", 2)
        if len(parts) < 2:
            return None
        return f"{parts[0]}/{parts[1]}"
    return s.split("/", 1)[0]


def scan_js_imports(source: str) -> list[str]:
    """Return a sorted, deduplicated list of top-level JS package specifiers."""
    out: set[str] = set()
    for m in _JS_IMPORT_RE.finditer(source or ""):
        top = _js_top_level_specifier(m.group(2))
        if top:
            out.add(top)
    return sorted(out)


def scan_imports_for_filename(filename: str, source: str) -> tuple[list[str], list[str]]:
    """Dispatch on *filename* extension; returns ``(python_deps, js_deps)``."""
    lower = filename.lower()
    if lower.endswith(".py"):
        return scan_python_imports(source), []
    if lower.endswith(".js") or lower.endswith(".mjs") or lower.endswith(".cjs") or lower.endswith(".ts"):
        return [], scan_js_imports(source)
    return [], []
