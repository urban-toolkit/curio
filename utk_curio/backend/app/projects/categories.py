"""What a dataflow is about, for the Projects rail and the canvas title chips.

A dataflow's categories come from three places, and each has exactly one:

* **source** - where the dataflow came from: a use case, an example or a test
  Curio ships, or ``None`` for the account's own. Decided by ``seed.py`` from
  the project id and never written into the spec, so a duplicate or an imported
  copy of an example is the user's, not a second example.
* **automatic** - ``tags`` and ``data_type``, read off the saved spec by
  :func:`derive`: what the rules in ``category_rules.json`` find in it (the
  modules its code imports and the files it names, the grammar its nodes'
  templates draw with, the type of a model it uses, the format and collection
  kind of a dataset it names), and what the manifests of its nodes' packages,
  of the models its code loads and of its datasets declare in
  ``dataflowCategories`` (:class:`ManifestLookup`). This module names no
  package, model or dataset. Nothing stores them: they are recomputed on every
  read, so they follow the nodes and the manifests, and a dataflow saved
  before this existed gets them without a back-fill.
* **hand-set** - ``dataflow.categories`` in the spec: the user's own tags plus
  city, topic and complexity. Stored in the spec so they travel with export,
  duplicate and "Load dataflow".

The same lookup gives each node the ``category`` its template declares, which
colors the node's box in the dataflow's thumbnail (:func:`template_categories`).
"""
from __future__ import annotations

import functools
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator, Optional

from utk_curio.backend.app.projects.template_grammars import (
    Declared,
    TemplateGrammar,
    TemplateGrammars,
    union_of_declarations,
)

#: The sections a user can write. Everything else on the rail is derived.
HAND_SECTIONS = ("tags", "city", "topic", "complexity")

#: Sections that hold one value; a new pick replaces the old one.
_SINGLE_VALUE = frozenset({"complexity"})

_MAX_VALUE_LENGTH = 40
_MAX_VALUES = 20

#: ``(format, collection kind)`` for a dataset id, or ``(None, None)``.
DatasetKind = Callable[[str], tuple[Optional[str], Optional[str]]]


# ---------------------------------------------------------------------------
# Hand-set
# ---------------------------------------------------------------------------

def _clean_values(raw: object, single: bool) -> list[str]:
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for value in raw:
        if not isinstance(value, str):
            continue
        cleaned = " ".join(value.split())[:_MAX_VALUE_LENGTH].strip()
        if not cleaned or cleaned.casefold() in seen:
            continue
        seen.add(cleaned.casefold())
        out.append(cleaned)
    if single:
        return out[-1:]
    return out[:_MAX_VALUES]


def normalize_hand(raw: object) -> dict[str, list[str]]:
    """The hand-set sections of *raw*, cleaned: known keys only, trimmed,
    de-duplicated ignoring case (first spelling wins), empty sections dropped."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[str]] = {}
    for section in HAND_SECTIONS:
        values = _clean_values(raw.get(section), section in _SINGLE_VALUE)
        if values:
            out[section] = values
    return out


def hand_categories(spec: object) -> dict[str, list[str]]:
    dataflow = spec.get("dataflow") if isinstance(spec, dict) else None
    raw = dataflow.get("categories") if isinstance(dataflow, dict) else None
    return normalize_hand(raw)


# ---------------------------------------------------------------------------
# Automatic: the rules
# ---------------------------------------------------------------------------

#: The signals a dataflow shows by itself, and the names each gives.
RULES_FILE = Path(__file__).with_name("category_rules.json")

#: The table's two lists, and the section of :func:`derive`'s answer each fills.
_SECTIONS = {"tags": "tags", "dataTypes": "data_type"}

_DATASET_CALL = re.compile(r"(?:curio_load_data|curio_data_path|curio_load_collection)\(\s*[\"']([^\"']+)")

#: A compiled pattern, and the row of the table that gives its names.
_Rule = tuple[re.Pattern, dict]


@dataclass(frozen=True)
class _Rules:
    """``category_rules.json``, its patterns compiled."""

    code: tuple[_Rule, ...]
    #: ``{grammarId: (row, its spec keys' rules)}``.
    grammars: dict[str, tuple[dict, tuple[_Rule, ...]]]
    model_types: dict[str, dict]
    dataset_formats: dict[str, dict]
    collection_kinds: dict[str, dict]
    display_order: dict[str, list[str]]


def _code_pattern(row: dict) -> Optional[re.Pattern]:
    """What a ``code`` row looks for in a dataflow's code: an import of one of
    its modules, a file name with one of its extensions, or a data URI of one
    of its media types. None for a row that names none."""
    parts = []
    if row.get("imports"):
        parts.append(r"^\s*(?:import|from)\s+(?:%s)\b" % "|".join(map(re.escape, row["imports"])))
    if row.get("fileExtensions"):
        parts.append(r"\.(?:%s)\b" % "|".join(map(re.escape, row["fileExtensions"])))
    parts += [re.escape(f"data:{media}") for media in row.get("dataUris") or []]
    if not parts:
        return None
    return re.compile("|".join(f"(?:{part})" for part in parts), re.M)


def _spec_key_pattern(key: str) -> re.Pattern:
    """A key of a grammar node's document: ``"<key>":``."""
    return re.compile(rf"\"{re.escape(key)}\"\s*:")


@functools.lru_cache(maxsize=1)
def _rules() -> _Rules:
    raw = json.loads(RULES_FILE.read_text(encoding="utf-8"))
    code = [(_code_pattern(row), row) for row in raw["code"]]
    return _Rules(
        code=tuple((pattern, row) for pattern, row in code if pattern is not None),
        grammars={
            grammar: (row, tuple(
                (_spec_key_pattern(key), gives) for key, gives in (row.get("specKeys") or {}).items()
            ))
            for grammar, row in raw["grammars"].items()
        },
        model_types=raw["modelTypes"],
        dataset_formats=raw["datasetFormats"],
        collection_kinds=raw["collectionKinds"],
        display_order=raw["displayOrder"],
    )


class _Found:
    """The tags and data types found for one dataflow, each name once ignoring
    case, its first spelling kept."""

    def __init__(self) -> None:
        self._names: dict[str, dict[str, str]] = {section: {} for section in _SECTIONS}

    def add(self, gives: Optional[dict]) -> None:
        """The names a row of the table gives; None gives none."""
        for section, names in self._names.items():
            for name in (gives or {}).get(section) or []:
                names.setdefault(name.casefold(), name)

    def add_declared(self, declared: Declared) -> None:
        self.add({"tags": declared.tags, "dataTypes": declared.data_types})

    def in_order(self, display_order: dict[str, list[str]]) -> dict[str, list[str]]:
        """The table's names first, in its order and its spelling, then any
        other name alphabetically, ignoring case."""
        out: dict[str, list[str]] = {}
        for section, answer in _SECTIONS.items():
            names = self._names[section]
            listed = [name for name in display_order.get(section, []) if name.casefold() in names]
            taken = {name.casefold() for name in listed}
            others = [name for folded, name in names.items() if folded not in taken]
            out[answer] = listed + sorted(others, key=lambda name: (name.casefold(), name))
        return out


# ---------------------------------------------------------------------------
# Automatic: reading a dataflow
# ---------------------------------------------------------------------------

def _dataset_ids(dataflow: dict, code: str) -> list[str]:
    """The datasets a dataflow names, in its code and its datasets, first
    seen first."""
    ids = dict.fromkeys(_DATASET_CALL.findall(code))
    for ref in dataflow.get("datasets") or []:
        if not isinstance(ref, dict):
            continue
        for key in ("dirName", "datasetId", "id"):
            value = ref.get(key)
            if isinstance(value, str) and value:
                ids.setdefault(value)
                break
    return list(ids)


def _lockfile_majors(dataflow: dict) -> dict[str, str]:
    """``{package id: major}`` of the packages the dataflow's lockfile names
    (``dataflow.packages``); the highest, for a package named twice."""
    from utk_curio.backend.app.packages.service import PACKAGE_DIR_RE

    packages = dataflow.get("packages")
    majors: dict[str, str] = {}
    for dir_name in packages if isinstance(packages, list) else []:
        if isinstance(dir_name, str) and PACKAGE_DIR_RE.match(dir_name):
            package_id, _, major = dir_name.rpartition("@")
            if package_id not in majors or int(major) > int(majors[package_id]):
                majors[package_id] = major
    return majors


def _at_lockfile_major(ref: object, package_id: str, majors: dict[str, str]) -> object:
    """*ref*, a node type or a model id of *package_id*, at the major the
    lockfile names for the package when it names none itself."""
    if not isinstance(ref, str) or "@" in ref or package_id not in majors:
        return ref
    return f"{ref}@{majors[package_id]}"


def _declared_nodes(
    nodes: list[dict], majors: dict[str, str], lookup: "ManifestLookup",
) -> Iterator[tuple[dict, str, Declared]]:
    """Each of *nodes* whose type is a string, with its type at the major the
    lockfile names when it names none (*majors*, :func:`_lockfile_majors`),
    and what its package and its template declare."""
    for node in nodes:
        node_type = node.get("type")
        if not isinstance(node_type, str):
            continue
        node_type = _at_lockfile_major(node_type, node_type.rpartition("/")[0], majors)
        yield node, node_type, lookup.packages.node(node_type)


def derive(
    spec: object,
    dataset_kind: Optional[DatasetKind] = None,
    template_grammar: Optional[TemplateGrammar] = None,
    lookup: Optional["ManifestLookup"] = None,
) -> dict[str, list[str]]:
    """``{"tags": [...], "data_type": [...]}`` for *spec*, in display order.

    Reads what is in the dataflow and what the manifests of what it uses say.
    The rules in ``category_rules.json`` read the import lines and file names
    in its code, the grammar each node's template draws with (and the keys of
    the node's document), the type of each model it uses (a node of a model
    package, or a ``curio_load_model`` call), and the format and collection
    kind of each dataset it names. A node's package and template, a loaded
    model's package and a dataset add what they declare in
    ``dataflowCategories``. The table's names come first, in its
    ``displayOrder``; any other name follows, alphabetically ignoring case.

    *lookup* reads the manifests (:class:`ManifestLookup`); without one, the
    packages and datasets Curio ships, as committed. A node type without a
    major is read at the major the dataflow's lockfile names for its package.
    *dataset_kind* and *template_grammar* answer a dataset's format and
    collection kind, and a node type's grammar, in the lookup's place.
    """
    from utk_curio.backend.app.datasets.domain.code_refs import model_ids_in_code

    dataflow = spec.get("dataflow") if isinstance(spec, dict) else None
    if not isinstance(dataflow, dict):
        return {"tags": [], "data_type": []}
    lookup = lookup if lookup is not None else ManifestLookup.shipped()
    grammar_of = template_grammar or lookup.packages
    kind_of = dataset_kind or lookup.datasets
    rules = _rules()
    majors = _lockfile_majors(dataflow)
    nodes = [n for n in dataflow.get("nodes") or [] if isinstance(n, dict)]
    code = "\n".join(str(n.get("content") or "") for n in nodes)
    found = _Found()

    for pattern, row in rules.code:
        if pattern.search(code):
            found.add(row)
    for node, node_type, declared in _declared_nodes(nodes, majors, lookup):
        found.add_declared(declared)
        found.add(rules.model_types.get(declared.model_type))
        grammar = rules.grammars.get(grammar_of(node_type))
        if grammar is not None:
            row, spec_keys = grammar
            found.add(row)
            document = str(node.get("content") or "")
            for pattern, gives in spec_keys:
                if pattern.search(document):
                    found.add(gives)
    for model_id in dict.fromkeys(m for n in nodes for m in model_ids_in_code(n.get("content"))):
        declared = lookup.packages.model(_at_lockfile_major(model_id, model_id, majors))
        found.add_declared(declared)
        found.add(rules.model_types.get(declared.model_type))
    for dataset_id in _dataset_ids(dataflow, code):
        fmt, kind = kind_of(dataset_id)
        found.add(rules.dataset_formats.get(fmt))
        found.add(rules.collection_kinds.get(kind))
        found.add_declared(lookup.datasets.declared(dataset_id))
    return found.in_order(rules.display_order)


def template_categories(spec: object, lookup: Optional["ManifestLookup"] = None) -> dict[str, str]:
    """``{node type: category}`` for the node types in *spec* whose template
    names a ``category`` (``data``, ``computation``, ``vis_grammar``,
    ``vis_simple`` or ``flow``): the color of the node's box in the dataflow's
    thumbnail. Keyed by each type as the spec writes it.

    Read as :func:`derive` reads a node's package and template: through
    *lookup* (without one, the packages Curio ships, as committed), with a
    type that names no major read at the major the dataflow's lockfile names.
    A type no manifest holds is left out.
    """
    dataflow = spec.get("dataflow") if isinstance(spec, dict) else None
    if not isinstance(dataflow, dict):
        return {}
    lookup = lookup if lookup is not None else ManifestLookup.shipped()
    nodes = [n for n in dataflow.get("nodes") or [] if isinstance(n, dict)]
    return {
        node["type"]: declared.category
        for node, _node_type, declared in _declared_nodes(nodes, _lockfile_majors(dataflow), lookup)
        if declared.category is not None
    }


# ---------------------------------------------------------------------------
# Reading the manifests
# ---------------------------------------------------------------------------

class DatasetKinds:
    """Resolve dataset ids to ``(format, collection kind)`` and to what they
    declare, memoized.

    Looks in the account's store first and then in the committed catalog - the
    two places ``curio_load_data`` finds a dataset. The format and the kind
    are the first copy's; what the copies declare in ``dataflowCategories`` is
    unioned (:meth:`declared`), as the account's copy dates from when it was
    added. Accepts a bare id or a ``<id>@<major>`` directory name; a bare id
    takes its highest major in each place. One instance per request, so a
    listing reads each manifest once.
    """

    def __init__(self, user_key: Optional[str], *, roots: Optional[Iterable[Path]] = None):
        if roots is None:
            from utk_curio.backend.app.datasets.infrastructure.storage import (
                catalog_root,
                user_datasets_dir,
            )

            roots = ([user_datasets_dir(user_key)] if user_key else []) + [catalog_root()]
        self._roots: list[Path] = list(roots)
        self._memo: dict[str, list[dict]] = {}

    @classmethod
    def shipped(cls) -> "DatasetKinds":
        """The datasets Curio ships, as they are committed (``utk_curio/shipped.py``)."""
        from utk_curio import shipped

        return cls(None, roots=[shipped.path("datasets")])

    def __call__(self, dataset_id: str) -> tuple[Optional[str], Optional[str]]:
        for raw in self._copies(dataset_id):
            collection = raw.get("collection")
            kind = collection.get("kind") if isinstance(collection, dict) else None
            fmt = raw.get("format")
            return (
                fmt.lower() if isinstance(fmt, str) else None,
                kind if isinstance(kind, str) else None,
            )
        return (None, None)

    def declared(self, dataset_id: str) -> Declared:
        """What the copies of *dataset_id*'s manifest declare together."""
        tags, data_types = union_of_declarations(self._copies(dataset_id))
        return Declared(tags, data_types)

    def _copies(self, dataset_id: str) -> list[dict]:
        if dataset_id not in self._memo:
            self._memo[dataset_id] = self._read(dataset_id)
        return self._memo[dataset_id]

    def _read(self, dataset_id: str) -> list[dict]:
        """In each place, the first manifest of *dataset_id* that reads."""
        if (not isinstance(dataset_id, str) or "/" in dataset_id or "\\" in dataset_id
                or dataset_id.startswith(".")):
            return []
        copies = []
        for root in self._roots:
            for directory in self._candidates(root, dataset_id):
                try:
                    raw = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if isinstance(raw, dict):
                    copies.append(raw)
                    break
        return copies

    @staticmethod
    def _candidates(root: Path, dataset_id: str) -> Iterable[Path]:
        if "@" in dataset_id:
            return [root / dataset_id]
        if not root.is_dir():
            return []
        majors = []
        for entry in root.glob(f"{dataset_id}@*"):
            major = entry.name.rsplit("@", 1)[1]
            if entry.is_dir() and major.isdigit():
                majors.append((int(major), entry))
        return [entry for _, entry in sorted(majors, reverse=True)]


class ManifestLookup:
    """What the manifests of a dataflow's packages, models and datasets say,
    for one request. :class:`TemplateGrammars` reads the packages: a node
    template's grammar, what a node's package and template declare, and a
    model package's declaration and model type. :class:`DatasetKinds` reads
    the datasets. Both read the account's copy of a manifest and the
    catalog's, and with no account the catalog's alone. Each manifest is read
    once, so a listing reads it once for every row.
    """

    def __init__(
        self,
        user_key: Optional[str] = None,
        *,
        packages: Optional[TemplateGrammars] = None,
        datasets: Optional[DatasetKinds] = None,
    ):
        self.packages = packages if packages is not None else TemplateGrammars(user_key)
        self.datasets = datasets if datasets is not None else DatasetKinds(user_key)

    @classmethod
    def shipped(cls) -> "ManifestLookup":
        """The packages and datasets Curio ships, as they are committed."""
        return cls(packages=TemplateGrammars.shipped(), datasets=DatasetKinds.shipped())


# ---------------------------------------------------------------------------
# What the API returns
# ---------------------------------------------------------------------------

def categories_for(
    spec: object,
    source: Optional[str],
    lookup: Optional[ManifestLookup] = None,
) -> dict:
    """The ``categories`` field of a project summary or detail."""
    return {
        "source": source,
        "auto": derive(spec, lookup=lookup),
        "hand": hand_categories(spec),
    }
