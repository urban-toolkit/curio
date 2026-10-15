"""Helpers for the per-project package lockfile inside ``spec.trill.json``.

A project's required-package list lives at ``spec["dataflow"]["packages"]``
as a sorted list of dirNames (``<packageId>@<major>``). These helpers are
the single read/write path for that field so callers don't have to know
the in-spec shape.

The backfill path here is the **backwards-compat bridge** for projects
saved before the lockfile became load-bearing: when the field is missing
or empty, we derive it by scanning ``dataflow.nodes`` for canonical
node-type strings. Each canonical id is one of two forms:

  * Versioned: ``<packageId>/<templateId>@<major>`` → dirName is
    ``<packageId>@<major>``.
  * Unversioned: ``<packageId>/<templateId>`` → caller must supply a
    ``installed_majors_by_pkg`` map (highest installed major per pkg)
    so we can resolve to a concrete dirName. Without that map,
    unversioned references are silently skipped.

Node types that don't match either form (e.g. legacy plain strings) are
skipped, not raised; backfill is best-effort.
"""

from __future__ import annotations

import re
from typing import Callable, Iterable, Mapping


_PKG_SEGMENT = r"[a-z][a-z0-9-]{0,62}"
_PKG_ID = rf"{_PKG_SEGMENT}(?:\.{_PKG_SEGMENT}){{1,5}}"
_TEMPLATE_ID = r"[a-z][a-z0-9-]{0,62}"
_MAJOR = r"(?:0|[1-9][0-9]{0,3})"

_NODE_TYPE_VERSIONED_RE = re.compile(
    rf"^({_PKG_ID})/{_TEMPLATE_ID}@({_MAJOR})$"
)
_NODE_TYPE_UNVERSIONED_RE = re.compile(
    rf"^({_PKG_ID})/{_TEMPLATE_ID}$"
)
_VERSION_SUFFIX_RE = re.compile(rf"@{_MAJOR}$")


def unversioned_node_type(node_type: object) -> object:
    """Strip a trailing ``@<major>`` from a canonical node type.

    Palette-dragged nodes carry the versioned canonical form
    (``curio.builtin/vis-vega@1``) while programmatic nodes use the unversioned
    enum — both coexist in specs and canvases, so any membership check against
    an unversioned set must normalize first. Non-strings pass through unchanged.
    """
    if not isinstance(node_type, str):
        return node_type
    return _VERSION_SUFFIX_RE.sub("", node_type)


def dir_name_from_node_type(
    node_type: str,
    installed_majors_by_pkg: Mapping[str, Iterable[int]] | None = None,
) -> str | None:
    """Best-effort dirName derivation for one node type string.

    Returns ``None`` when the type is malformed or unversioned-with-no-resolver.
    """
    if not isinstance(node_type, str):
        return None
    m = _NODE_TYPE_VERSIONED_RE.match(node_type)
    if m:
        return f"{m.group(1)}@{m.group(2)}"
    m = _NODE_TYPE_UNVERSIONED_RE.match(node_type)
    if m and installed_majors_by_pkg:
        majors = list(installed_majors_by_pkg.get(m.group(1), ()))
        if majors:
            return f"{m.group(1)}@{max(majors)}"
    return None


def _backfill_from_nodes(
    spec: dict,
    installed_majors_by_pkg: Mapping[str, Iterable[int]] | None,
) -> set[str]:
    dataflow = spec.get("dataflow") if isinstance(spec, dict) else None
    if not isinstance(dataflow, dict):
        return set()
    nodes = dataflow.get("nodes") or []
    out: set[str] = set()
    for n in nodes:
        if not isinstance(n, dict):
            continue
        dn = dir_name_from_node_type(n.get("type", ""), installed_majors_by_pkg)
        if dn:
            out.add(dn)
    return out


def project_packages(
    spec: dict | None,
    installed_majors_by_pkg: Mapping[str, Iterable[int]] | None = None,
) -> set[str]:
    """Return the project's declared package dirNames.

    Reads ``spec["dataflow"]["packages"]`` when present and non-empty;
    otherwise falls back to scanning node types for backfill.
    """
    if not isinstance(spec, dict):
        return set()
    dataflow = spec.get("dataflow")
    if not isinstance(dataflow, dict):
        return set()
    declared = dataflow.get("packages")
    if isinstance(declared, list) and declared:
        return {x for x in declared if isinstance(x, str)}
    return _backfill_from_nodes(spec, installed_majors_by_pkg)


def set_project_packages(spec: dict, dirs: Iterable[str]) -> dict:
    """Write the sorted dirName list back into ``spec["dataflow"]["packages"]``.

    Mutates and returns the spec for convenience. Creates the ``dataflow``
    sub-dict if missing.
    """
    if not isinstance(spec, dict):
        raise TypeError("spec must be a dict")
    dataflow = spec.setdefault("dataflow", {})
    if not isinstance(dataflow, dict):
        raise TypeError("spec['dataflow'] must be a dict")
    dataflow["packages"] = sorted(set(dirs))
    return spec


def dir_name_from_model_ref(
    model_id: object,
    installed_majors_by_pkg: Mapping[str, Iterable[int]] | None = None,
) -> str | None:
    """The dirName of the model package a node's ``modelRefs`` entry names:
    ``<id>@<major>`` as it is, a bare ``<id>`` at its highest installed major,
    or ``None`` without one."""
    if not isinstance(model_id, str):
        return None
    package_id, _, major = model_id.partition("@")
    if not re.fullmatch(_PKG_ID, package_id):
        return None
    if major:
        return f"{package_id}@{major}" if re.fullmatch(_MAJOR, major) else None
    majors = list((installed_majors_by_pkg or {}).get(package_id, ()))
    return f"{package_id}@{max(majors)}" if majors else None


#: Reads the model ids a node's code names through literal
#: ``curio_load_model("<id>")`` calls (``datasets.domain.code_refs``, which the
#: callers hand in: this module imports no other feature).
ModelIdsInCode = Callable[[object], Iterable[str]]


def _model_ref_dir_names(
    node: dict,
    installed_majors_by_pkg: Mapping[str, Iterable[int]] | None,
    model_ids_in: ModelIdsInCode | None = None,
) -> set[str]:
    """The model packages *node* is bound to: what its ``metadata.modelRefs``
    names, as a drop of a model onto the node writes it. With *model_ids_in*,
    a ref counts only while the node's code still names its model, as the
    frontend's ``nodeLinkedModelIds`` counts it: a hand edit to another model
    leaves the drop's ref behind, and that ref keeps nothing."""
    metadata = node.get("metadata")
    refs = metadata.get("modelRefs") if isinstance(metadata, dict) else None
    named = None
    if model_ids_in is not None:
        named = {str(model_id).partition("@")[0] for model_id in model_ids_in(node.get("content"))}
    out: set[str] = set()
    for ref in refs if isinstance(refs, list) else ():
        model_id = ref.get("id") if isinstance(ref, dict) else None
        if named is not None and str(model_id).partition("@")[0] not in named:
            continue
        dir_name = dir_name_from_model_ref(model_id, installed_majors_by_pkg)
        if dir_name:
            out.add(dir_name)
    return out


def model_ref_packages(
    spec: dict | None,
    installed_majors_by_pkg: Mapping[str, Iterable[int]] | None = None,
    model_ids_in: ModelIdsInCode | None = None,
) -> set[str]:
    """The model packages the canvas nodes of *spec* are bound to
    (``metadata.modelRefs``, see :func:`_model_ref_dir_names`). A dataflow uses
    each of them as it uses the packages its lockfile names. A literal
    ``curio_load_model`` call in node code is only a code reference, and is not
    one of them."""
    dataflow = spec.get("dataflow") if isinstance(spec, dict) else None
    if not isinstance(dataflow, dict):
        return set()
    out: set[str] = set()
    for node in dataflow.get("nodes") or []:
        if isinstance(node, dict):
            out |= _model_ref_dir_names(node, installed_majors_by_pkg, model_ids_in)
    return out


def referencing_nodes(
    spec: dict | None,
    dir_name: str,
    installed_majors_by_pkg: Mapping[str, Iterable[int]] | None = None,
    model_ids_in: ModelIdsInCode | None = None,
) -> list[str]:
    """Ids of the canvas nodes that use *dir_name* (memo dev/101): whose type
    derives to it, or which are bound to it as their model (``modelRefs``, see
    :func:`_model_ref_dir_names`).

    This is what an uninstall must refuse on: while any node of the package's
    types is on the canvas, the backfill in :func:`project_packages` would
    re-derive the package on the next read, so a "successful" uninstall would
    be a permanent no-op; and a node bound to a model runs that model. Nodes
    without an ``id`` are counted under a positional placeholder so the count
    is still truthful.
    """
    dataflow = spec.get("dataflow") if isinstance(spec, dict) else None
    if not isinstance(dataflow, dict):
        return []
    out: list[str] = []
    for index, node in enumerate(dataflow.get("nodes") or []):
        if not isinstance(node, dict):
            continue
        if (dir_name_from_node_type(node.get("type", ""), installed_majors_by_pkg) == dir_name
                or dir_name in _model_ref_dir_names(node, installed_majors_by_pkg, model_ids_in)):
            node_id = node.get("id")
            out.append(node_id if isinstance(node_id, str) else f"#{index}")
    return out


def package_usage_in_spec(
    spec: dict | None,
    dir_name: str,
    installed_majors_by_pkg: Mapping[str, Iterable[int]] | None = None,
    model_ids_in: ModelIdsInCode | None = None,
) -> tuple[list[dict], bool] | None:
    """How *spec*'s dataflow uses the package *dir_name*, as a usage read
    reports it: ``None`` when it does not, else its nodes that do
    (``[{nodeId, nodeType}]``) and whether it uses the package only through
    node code (``codeOnly``).

    A node uses it when its type derives to it, when it is bound to it as its
    model, or when its code names the model (a literal ``curio_load_model``
    call, read by *model_ids_in*). The lockfile naming it is a use with no
    node. ``codeOnly`` holds when node code is all there is: no lockfile
    entry, no node of the package, no node bound to it. Such a dataflow keeps
    nothing (see :func:`model_ref_packages`), as a dataset's usage read marks
    a dataflow that loads the dataset in code alone."""
    dataflow = spec.get("dataflow") if isinstance(spec, dict) else None
    if not isinstance(dataflow, dict):
        return None
    package_id = dir_name.partition("@")[0]
    kept = dir_name in project_packages(spec, installed_majors_by_pkg)
    nodes: list[dict] = []
    for index, node in enumerate(dataflow.get("nodes") or []):
        if not isinstance(node, dict):
            continue
        keeps = (dir_name_from_node_type(node.get("type", ""), installed_majors_by_pkg) == dir_name
                 or dir_name in _model_ref_dir_names(node, installed_majors_by_pkg, model_ids_in))
        in_code = model_ids_in is not None and package_id in {
            str(model_id).partition("@")[0] for model_id in model_ids_in(node.get("content"))
        }
        if keeps or in_code:
            node_id = node.get("id")
            node_type = node.get("type")
            nodes.append({
                "nodeId": node_id if isinstance(node_id, str) else f"#{index}",
                "nodeType": node_type if isinstance(node_type, str) else None,
            })
            kept = kept or keeps
    if not nodes and not kept:
        return None
    return nodes, bool(nodes) and not kept


def preserve_project_packages(
    effective_spec: dict | None,
    existing_spec: dict | None,
    installed_majors_by_pkg: Mapping[str, Iterable[int]] | None = None,
) -> dict | None:
    """Carry the on-disk lockfile forward across a client save (memo dev/101).

    ``dataflow.packages`` is backend-owned on UPDATE, exactly like
    ``dataflow.datasets`` (dev/81) and the agent sections: the client
    serialises its mirror of the lockfile on every save, and honouring it let
    a stale tab overwrite what a package draft's promotion (or the
    drawer) had just written. The value carried forward is the on-disk
    *effective* lockfile — backfill included — so a legacy ``[]``-with-nodes
    spec becomes explicit on its first save after this change.

    When there is no on-disk ``dataflow`` to preserve from (fresh or corrupt
    spec), the client's value stands; that is the create-like case.
    """
    if not isinstance(effective_spec, dict):
        return effective_spec
    existing_dataflow = existing_spec.get("dataflow") if isinstance(existing_spec, dict) else None
    if not isinstance(existing_dataflow, dict):
        return effective_spec
    dataflow = effective_spec.setdefault("dataflow", {})
    if not isinstance(dataflow, dict):
        return effective_spec
    dataflow["packages"] = sorted(project_packages(existing_spec, installed_majors_by_pkg))
    return effective_spec
