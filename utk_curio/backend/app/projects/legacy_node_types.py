"""Node types Curio no longer ships, and the types that replace them.

The Scout package (``curio.scout@1``) held SCOUT's two raster nodes and
fifteen Vega-Lite charts. Its raster nodes are the Rasterization package's now
(``curio.rasterization@1``), and its charts are built-in Vega-Lite nodes with
the same spec and widgets (#1270). A dataflow saved before reads as if saved
after: :func:`migrate_legacy_types` renames its nodes' types and the packages
it lists. ``src/utils/flowNodeCanonicalType.ts`` holds the same table for a
dataflow the page opens from a file.
"""
from __future__ import annotations

from typing import Any

#: Scout's chart templates, each now a built-in Vega-Lite node.
SCOUT_CHARTS = (
    "lines-with-band", "curves-by-group", "bars-with-error-bars", "ensemble-strips",
    "stacked-bars-with-totals", "donuts", "weighted-matrix", "dots-with-a-range",
    "bars", "grouped-bars", "lines", "points", "pie", "lollipops", "table",
)

#: A replaced node type, without its ``@<major>``, and its replacement.
REPLACED_NODE_TYPES: dict[str, str] = {
    "curio.scout/raster-calculator": "curio.rasterization/raster-calculator",
    "curio.scout/rasterize-buildings": "curio.rasterization/rasterize-buildings",
    **{f"curio.scout/{chart}": "curio.builtin/vis-vega" for chart in SCOUT_CHARTS},
}

#: A replaced package, and its replacement.
REPLACED_PACKAGES: dict[str, str] = {"curio.scout@1": "curio.rasterization@1"}


def current_node_type(node_type: Any) -> Any:
    """*node_type* as Curio ships it now: a replaced type's replacement, its
    ``@<major>`` kept when the replacement is a package's own (the built-in's
    is ``@1``, as every built-in is); anything else as it is."""
    if not isinstance(node_type, str):
        return node_type
    base, sep, major = node_type.partition("@")
    replaced = REPLACED_NODE_TYPES.get(base)
    if replaced is None:
        return node_type
    if not sep:
        return replaced
    return f"{replaced}@1" if replaced.startswith("curio.builtin/") else f"{replaced}@{major}"


def migrate_legacy_types(spec: Any) -> Any:
    """*spec* with every replaced node type and package renamed, in place.
    ``dataflow.packages`` drops the Scout package when no node of its
    replacement is left, since its charts need none. Returns *spec*."""
    dataflow = spec.get("dataflow") if isinstance(spec, dict) else None
    if not isinstance(dataflow, dict):
        return spec
    nodes = dataflow.get("nodes") if isinstance(dataflow.get("nodes"), list) else []
    for node in nodes:
        if isinstance(node, dict) and "type" in node:
            node["type"] = current_node_type(node["type"])
    packages = dataflow.get("packages")
    if isinstance(packages, list) and any(p in REPLACED_PACKAGES for p in packages):
        used = {str(node.get("type", "")).split("/", 1)[0] for node in nodes if isinstance(node, dict)}
        renamed: list = []
        for package in packages:
            new = REPLACED_PACKAGES.get(package, package)
            if package in REPLACED_PACKAGES and new.split("@", 1)[0] not in used:
                continue
            if new not in renamed:
                renamed.append(new)
        dataflow["packages"] = renamed
    return spec
