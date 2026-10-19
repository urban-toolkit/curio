"""What a node's template declares, read off the package manifests.

A node is what its template declares, never what its type is named. A
template's ``behavior`` says how the node behaves: a dashboard walks through
the nodes that show what reaches them (``dashboard_payload``,
``scenario_catalog/domain/parts``), a run on the server hands on what a
download, a Parameter node or a note receives (``execution/run_plan``), and
the Data Catalog counts a dataset's consumers after the node that loads it, a
template in the ``data`` category with no input port
(``datasets/application/export``). A package template that declares a built-in
behavior is that built-in node to every one of these rules, and one that is
only named like a built-in is not.

A template's ``grammarId`` says what it draws with. A package template can
draw with the Vega-Lite node's grammar and behavior, so every rule keyed on
the Vega-Lite node asks :func:`draws_with_vega_lite`, and a save keeps no
output of its own for such a chart (``services._is_sink_node_type``), as the
canvas does through ``registry/vegaLiteNodes.ts``. A dataflow's automatic Vega-Lite and Autark
tags read the same grammars (``categories``), through :class:`TemplateGrammars`,
which also reads what the package manifests declare for the Projects rail.

A node type is ``<package id>/<template id>``, with or without ``@<major>``:
the major picks the package folder, and without one the highest wins. It is
read only through the package id grammar (``dir_name_from_node_type``), so a
type of any other shape names no folder and reads nothing. A
:class:`TemplateGrammars` reads each manifest once, so one serves one request:
the rules above take one from their caller, else read the catalog through
:meth:`TemplateGrammars.catalog`.
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


def draws_with_vega_lite(node_type: object, grammar_of: Optional[TemplateGrammar] = None) -> bool:
    """Whether a node of *node_type* is a Vega-Lite chart: the built-in
    Vega-Lite node, or a node of a template whose grammar is ``vega-lite``, as
    *grammar_of* reads it (:meth:`TemplateGrammars.catalog` when None)."""
    from utk_curio.backend.app.packages.service import unversioned_node_type

    if unversioned_node_type(node_type) == _BUILTIN_VEGA:
        return True
    return (grammar_of or TemplateGrammars.catalog())(node_type) == VEGA_LITE


def node_template(node_type: object, packages: Optional["TemplateGrammars"] = None) -> "Declared":
    """What *node_type*'s template declares, read through *packages*
    (:meth:`TemplateGrammars.catalog` when None)."""
    return (packages or TemplateGrammars.catalog()).node(node_type)


@dataclass(frozen=True)
class Declared:
    """What the manifests of one node type, model or dataset tell: the names
    they declare in ``dataflowCategories`` and the core fields the rules in
    ``category_rules.json`` read, and for a node what its template declares
    it is."""

    tags: tuple[str, ...] = ()
    data_types: tuple[str, ...] = ()
    #: The grammar a node's template draws with.
    grammar: Optional[str] = None
    #: The type of a model package's model.
    model_type: Optional[str] = None
    #: The behavior a node's template declares (``code``, ``vega``, ``data-pool``, ...).
    behavior: Optional[str] = None
    #: The palette category a node's template declares (``data``, ``flow``, ...).
    category: Optional[str] = None
    #: How many input ports a node's template declares.
    input_ports: Optional[int] = None


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
    with. :meth:`node` gives that too, with what the node's package and its
    template declare in ``dataflowCategories``, the template's behavior,
    category and input ports and, for a model package, its model's type.
    :meth:`model` gives what the model package a ``curio_load_model`` call
    names declares, and its model's type.

    A package is read in the account's own store, then in the catalog, as
    ``categories.DatasetKinds`` reads datasets. The account's copy dates from
    when the package was added to the store, so what the two copies declare is
    unioned, and a grammar, a behavior, a category, input ports or a model type
    is the first copy's that names one. Without a major, a node type or a model
    id takes the highest major the places hold. A node type with no package in
    it, or of any other shape than ``<package id>/<template id>[@<major>]``,
    matches nothing. Each manifest is read once, so one instance serves one
    request.
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

    @classmethod
    def catalog(cls) -> "TemplateGrammars":
        """The package catalog, then the packages Curio ships, which hold the
        built-in nodes wherever the catalog is (``CURIO_PACKAGES_ROOT``)."""
        from utk_curio import shipped
        from utk_curio.backend.app.packages.service import catalog_root

        roots = [catalog_root()]
        committed = shipped.path("packages")
        if committed.resolve() != roots[0].resolve():
            roots.append(committed)
        return cls(None, roots=roots)

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
            behavior=_first_string(template.get("behavior") for template in templates),
            category=_first_string(template.get("category") for template in templates),
            input_ports=next(
                (len(t["inputPorts"]) for t in templates if isinstance(t.get("inputPorts"), list)),
                None,
            ),
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
