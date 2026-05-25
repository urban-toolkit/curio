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
