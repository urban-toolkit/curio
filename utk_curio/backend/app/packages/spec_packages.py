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
from typing import Iterable, Mapping


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


def referencing_nodes(
    spec: dict | None,
    dir_name: str,
    installed_majors_by_pkg: Mapping[str, Iterable[int]] | None = None,
) -> list[str]:
    """Ids of the canvas nodes whose type derives to *dir_name* (memo dev/101).

    This is what an uninstall must refuse on: while any node of the package's
    types is on the canvas, the backfill in :func:`project_packages` would
    re-derive the package on the next read, so a "successful" uninstall would
    be a permanent no-op. Nodes without an ``id`` are counted under a
    positional placeholder so the count is still truthful.
    """
    dataflow = spec.get("dataflow") if isinstance(spec, dict) else None
    if not isinstance(dataflow, dict):
        return []
    out: list[str] = []
    for index, node in enumerate(dataflow.get("nodes") or []):
        if not isinstance(node, dict):
            continue
        if dir_name_from_node_type(node.get("type", ""), installed_majors_by_pkg) == dir_name:
            node_id = node.get("id")
            out.append(node_id if isinstance(node_id, str) else f"#{index}")
    return out


def preserve_project_packages(
    effective_spec: dict | None,
    existing_spec: dict | None,
    installed_majors_by_pkg: Mapping[str, Iterable[int]] | None = None,
) -> dict | None:
    """Carry the on-disk lockfile forward across a client save (memo dev/101).

    ``dataflow.packages`` is backend-owned on UPDATE, exactly like
    ``dataflow.datasets`` (dev/81) and the agent sections: the client
    serialises its mirror of the lockfile on every save, and honouring it let
    a stale tab overwrite what the Package Builder's promotion (or the
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
