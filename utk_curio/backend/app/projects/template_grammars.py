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
tags read the same grammars (``categories``), through :class:`TemplateGrammars`,
which also reads what the package manifests declare for the Projects rail.

A node type is ``<package id>/<template id>``, with or without ``@<major>``:
the major picks the package folder, and without one the highest wins.
:func:`template_grammar` reads a catalog manifest once, and again only when
its file changes; a :class:`TemplateGrammars` reads each manifest once.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
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


@dataclass(frozen=True)
class Declared:
    """What the manifests of one node type, model or dataset tell a dataflow's
    categories: the names they declare in ``dataflowCategories``, and the core
    fields the rules in ``category_rules.json`` read."""

    tags: tuple[str, ...] = ()
    data_types: tuple[str, ...] = ()
    #: The grammar a node's template draws with.
    grammar: Optional[str] = None
    #: The type of a model package's model.
    model_type: Optional[str] = None


#: What a node type, a model or a dataset no manifest holds tells.
NOTHING = Declared()


def union_of_declarations(manifests: Iterable[object]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The tags and the data types *manifests* (manifest objects, or templates
    of one) declare together, each name once ignoring case, its first spelling
    kept. A value of the wrong type is skipped."""
    from utk_curio.backend.app.packages.service import declared_dataflow_categories

    found: dict[str, dict[str, str]] = {"tags": {}, "dataTypes": {}}
    for manifest in manifests:
        for section, values in declared_dataflow_categories(manifest).items():
            for value in values:
                found[section].setdefault(value.casefold(), value)
    return tuple(found["tags"].values()), tuple(found["dataTypes"].values())


def _first_string(values: Iterable[object]) -> Optional[str]:
    return next((value for value in values if isinstance(value, str)), None)


def _model_type(manifests: Iterable[dict]) -> Optional[str]:
    """The first of *manifests* that names its model's type names it."""
    return _first_string(
        manifest["model"].get("type") for manifest in manifests if isinstance(manifest.get("model"), dict)
    )


class TemplateGrammars:
    """What the package manifests say about a dataflow's node types and the
    models its code loads, for one account and one request.

    Called with a node type, it gives the grammar the node's template draws
    with, as :func:`template_grammar` does. :meth:`node` gives that too, with
    what the node's package and its template declare in ``dataflowCategories``
    and, for a model package, its model's type. :meth:`model` gives what the
    model package a ``curio_load_model`` call names declares, and its model's
    type.

    A package is read in the account's own store, then in the catalog, as
    ``categories.DatasetKinds`` reads datasets. The account's copy dates from
    when the package was added to the store, so what the two copies declare is
    unioned, and a grammar or a model type is the first copy's that names one.
    Without a major, a node type or a model id takes the highest major the two
    places hold. A node type with no package in it matches nothing. Each
    manifest is read once, so one instance serves one request.
    """

    def __init__(self, user_key: Optional[str], *, roots: Optional[Iterable[Path]] = None):
        if roots is None:
            from utk_curio.backend.app.packages.service import catalog_root, user_packages_dir

            roots = ([user_packages_dir(user_key)] if user_key else []) + [catalog_root()]
        self._roots: list[Path] = list(roots)
        self._manifests: dict[str, list[dict]] = {}
        self._majors: Optional[dict[str, list[int]]] = None
        self._nodes: dict[str, Declared] = {}
        self._models: dict[str, Declared] = {}

    @classmethod
    def shipped(cls) -> "TemplateGrammars":
        """The packages Curio ships, as they are committed (``utk_curio/shipped.py``)."""
        from utk_curio import shipped

        return cls(None, roots=[shipped.path("packages")])

    def __call__(self, node_type: object) -> Optional[str]:
        return self.node(node_type).grammar

    def node(self, node_type: object) -> Declared:
        """What a node of *node_type* gets from its package and its template.
        What the package declares counts even when its manifest no longer
        holds the template."""
        if not isinstance(node_type, str):
            return NOTHING
        if node_type not in self._nodes:
            self._nodes[node_type] = self._read_node(node_type)
        return self._nodes[node_type]

    def model(self, model_id: object) -> Declared:
        """What a ``curio_load_model`` call naming *model_id* gets from its
        model package: what the package declares, and its model's type."""
        if not isinstance(model_id, str):
            return NOTHING
        if model_id not in self._models:
            self._models[model_id] = self._read_model(model_id)
        return self._models[model_id]

    def _read_node(self, node_type: str) -> Declared:
        from utk_curio.backend.app.packages.service import (
            dir_name_from_node_type,
            unversioned_node_type,
        )

        dir_name = dir_name_from_node_type(node_type, self._installed_majors())
        if dir_name is None:
            return NOTHING
        template_id = unversioned_node_type(node_type).rpartition("/")[2]
        manifests = self._copies(dir_name)
        templates = [
            template
            for manifest in manifests
            for template in manifest.get("templates") or []
            if isinstance(template, dict) and template.get("id") == template_id
        ]
        tags, data_types = union_of_declarations([*manifests, *templates])
        return Declared(
            tags,
            data_types,
            grammar=_first_string(template.get("grammarId") for template in templates),
            model_type=_model_type(manifests),
        )

    def _read_model(self, model_id: str) -> Declared:
        from utk_curio.backend.app.packages.service import dir_name_from_model_ref

        dir_name = dir_name_from_model_ref(model_id, self._installed_majors())
        if dir_name is None:
            return NOTHING
        manifests = self._copies(dir_name)
        tags, data_types = union_of_declarations(manifests)
        return Declared(tags, data_types, model_type=_model_type(manifests))

    def _copies(self, dir_name: str) -> list[dict]:
        """The manifests of the package folder *dir_name* that read, the
        account's first."""
        if dir_name not in self._manifests:
            manifests = []
            for root in self._roots:
                try:
                    raw = json.loads((root / dir_name / "manifest.json").read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if isinstance(raw, dict):
                    manifests.append(raw)
            self._manifests[dir_name] = manifests
        return self._manifests[dir_name]

    def _installed_majors(self) -> dict[str, list[int]]:
        """``{package id: majors}`` of the package folders the two places hold."""
        if self._majors is None:
            from utk_curio.backend.app.packages.service import PACKAGE_DIR_RE

            majors: dict[str, list[int]] = {}
            for root in self._roots:
                try:
                    names = [entry.name for entry in root.iterdir() if entry.is_dir()]
                except OSError:
                    continue
                for name in names:
                    if PACKAGE_DIR_RE.match(name):
                        package_id, _, major = name.rpartition("@")
                        majors.setdefault(package_id, []).append(int(major))
            self._majors = majors
        return self._majors
