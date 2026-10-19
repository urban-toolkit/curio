"""The grammar a node's template draws with, read off the package manifests.

A package template can draw with a built-in node's grammar: SCOUT Comparison's
charts (``packages/scout.comparison@1``) name ``grammarId: "vega-lite"`` and
draw with the Vega-Lite node's own behavior. So every rule keyed on the
Vega-Lite node asks :func:`draws_with_vega_lite` instead of comparing a node's
type with the built-in one's: a dashboard or a scenario walks through such a
chart (``dashboard_payload``, ``scenario_catalog/domain/parts``), a run on the
server forwards it (``execution/run_plan``), and a save keeps no output of its
own for it (``services._is_sink_node_type``), as the canvas does through
``registry/vegaLiteNodes.ts``. A dataflow's automatic Vega-Lite and Autark
tags read the same grammars (``categories``).

A node type is ``<package id>/<template id>``, with or without ``@<major>``:
the major picks the package folder, and without one the highest wins. A
manifest is read once, and again only when its file changes.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Iterable, Optional

#: The grammar a template names to draw as the Vega-Lite node does.
VEGA_LITE = "vega-lite"
#: The grammar a template names to draw as the Autark node does.
AUTK_GRAMMAR = "autk-grammar"

#: ``node type -> the grammar its template draws with``, or None.
TemplateGrammar = Callable[[object], Optional[str]]

_BUILTIN_VEGA = "curio.builtin/vis-vega"

#: ``{manifest path: (mtime_ns, {template id: grammarId or None})}``.
_READ: dict[str, tuple[int, dict[str, Optional[str]]]] = {}


def _split(node_type: object) -> Optional[tuple[str, str, Optional[str]]]:
    """``(package id, template id, major or None)`` of a namespaced node type."""
    if not isinstance(node_type, str) or "/" not in node_type:
        return None
    unversioned, _, major = node_type.partition("@")
    package_id, _, template_id = unversioned.rpartition("/")
    if not package_id or not template_id:
        return None
    return package_id, template_id, major if major.isdigit() else None


def _grammars_of(manifest: Path) -> Optional[dict[str, Optional[str]]]:
    """``{template id: grammarId or None}`` of the manifest at *manifest*, or
    None when it cannot be read."""
    try:
        stamp = manifest.stat().st_mtime_ns
    except OSError:
        return None
    key = str(manifest)
    read = _READ.get(key)
    if read is not None and read[0] == stamp:
        return read[1]
    try:
        raw = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    grammars: dict[str, Optional[str]] = {}
    for template in (raw.get("templates") if isinstance(raw, dict) else None) or []:
        if isinstance(template, dict) and isinstance(template.get("id"), str):
            grammar = template.get("grammarId")
            grammars[template["id"]] = grammar if isinstance(grammar, str) else None
    _READ[key] = (stamp, grammars)
    return grammars


def _package_folders(root: Path, package_id: str, major: Optional[str]) -> list[Path]:
    """The folders of *package_id* under *root*: its *major*'s, else every
    major's, highest first."""
    if major is not None:
        return [root / f"{package_id}@{major}"]
    if not root.is_dir():
        return []
    found = []
    for folder in root.glob(f"{package_id}@*"):
        number = folder.name.rsplit("@", 1)[1]
        if number.isdigit() and folder.is_dir():
            found.append((int(number), folder))
    return [folder for _number, folder in sorted(found, reverse=True)]


def _grammar_in(roots: Iterable[Path], node_type: object) -> Optional[str]:
    parts = _split(node_type)
    if parts is None:
        return None
    package_id, template_id, major = parts
    for root in roots:
        for folder in _package_folders(root, package_id, major):
            grammars = _grammars_of(folder / "manifest.json")
            if grammars is not None and template_id in grammars:
                return grammars[template_id]
    return None


def template_grammar(node_type: object) -> Optional[str]:
    """The grammar *node_type*'s template draws with, read off the package
    catalog (``packages/``, which holds the packages Curio ships); None for a
    template that names none, or that the catalog does not hold."""
    from utk_curio.backend.app.packages.service import catalog_root

    return _grammar_in([catalog_root()], node_type)


def draws_with_vega_lite(node_type: object, grammar_of: Optional[TemplateGrammar] = None) -> bool:
    """Whether a node of *node_type* is a Vega-Lite chart: the built-in
    Vega-Lite node, or a node of a template whose grammar is ``vega-lite``, as
    *grammar_of* reads it (:func:`template_grammar` when None)."""
    from utk_curio.backend.app.packages.service import unversioned_node_type

    if unversioned_node_type(node_type) == _BUILTIN_VEGA:
        return True
    return (grammar_of or template_grammar)(node_type) == VEGA_LITE


class TemplateGrammars:
    """:func:`template_grammar` for one account, memoized: the account's own
    package store first, then the catalog, as ``categories.DatasetKinds``
    reads datasets. One instance per request, so a listing reads each
    manifest once."""

    def __init__(self, user_key: Optional[str]):
        from utk_curio.backend.app.packages.service import catalog_root, user_packages_dir

        self._roots: list[Path] = []
        if user_key:
            self._roots.append(user_packages_dir(user_key))
        self._roots.append(catalog_root())
        self._memo: dict[str, Optional[str]] = {}

    def __call__(self, node_type: object) -> Optional[str]:
        if not isinstance(node_type, str):
            return None
        if node_type not in self._memo:
            self._memo[node_type] = _grammar_in(self._roots, node_type)
        return self._memo[node_type]
