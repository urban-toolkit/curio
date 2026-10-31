import { CURIO_UNIVERSAL_NODE_TYPE } from "../constants";
import { splitCanonicalNodeType } from "../registry/packageKeys";

/**
 * React Flow uses one stable ``node.type`` so the palette map never churns when
 * package descriptors reload. The real dispatcher id stays in ``data.nodeType``.
 */
export function getFlowNodeCanonicalType(node: {
    type?: string | null;
    // `| null` because a ReactFlow node's `data` legitimately is null on some
    // paths; the body already reads it with optional chaining.
    data?: { nodeType?: string | null } | null;
}): string {
    const rf = node.type ?? "";
    if (rf === CURIO_UNIVERSAL_NODE_TYPE) {
        return String(node.data?.nodeType ?? "");
    }
    return rf;
}

/**
 * Strip a trailing ``@<major>`` from a canonical node type. Palette-dragged
 * nodes carry the versioned form (``curio.builtin/vis-vega@1``) while
 * programmatic nodes use the unversioned enum — both coexist in canvases and
 * saved specs, so membership checks against unversioned sets must normalize
 * first (#169). Mirrors the backend ``unversioned_node_type``.
 */
export function unversionedNodeType(nodeType: string): string {
    return splitCanonicalNodeType(nodeType)?.unversioned ?? nodeType;
}

/** ``getFlowNodeCanonicalType`` with the ``@<major>`` suffix stripped. */
export function getUnversionedFlowNodeType(node: {
    type?: string | null;
    data?: { nodeType?: string | null };
}): string {
    return unversionedNodeType(getFlowNodeCanonicalType(node));
}

/** Scout's chart templates, each a built-in Vega-Lite node now (#1270). */
const SCOUT_CHARTS = [
    "lines-with-band", "curves-by-group", "bars-with-error-bars", "ensemble-strips",
    "stacked-bars-with-totals", "donuts", "weighted-matrix", "dots-with-a-range",
    "bars", "grouped-bars", "lines", "points", "pie", "lollipops", "table",
];

/**
 * Node types Curio no longer ships, without their ``@<major>``, and what
 * replaces them: Scout's raster nodes are the Rasterization package's, and its
 * charts are Vega-Lite nodes with the same spec and widgets. The backend's
 * ``projects/legacy_node_types.py`` holds the same table.
 */
export const REPLACED_NODE_TYPES: Readonly<Record<string, string>> = {
    "curio.scout/raster-calculator": "curio.rasterization/raster-calculator",
    "curio.scout/rasterize-buildings": "curio.rasterization/rasterize-buildings",
    ...Object.fromEntries(SCOUT_CHARTS.map((chart) => [`curio.scout/${chart}`, "curio.builtin/vis-vega"])),
};

/** A replaced package, and its replacement. */
export const REPLACED_PACKAGES: Readonly<Record<string, string>> = {
    "curio.scout@1": "curio.rasterization@1",
};

/** *nodeType* as Curio ships it now: a replaced type's replacement, its
 *  ``@<major>`` kept for a package's own (a built-in's is ``@1``); anything
 *  else as it is. */
export function currentNodeType(nodeType: string): string {
    const at = nodeType.indexOf("@");
    const base = at < 0 ? nodeType : nodeType.slice(0, at);
    const replaced = REPLACED_NODE_TYPES[base];
    if (!replaced) return nodeType;
    if (at < 0) return replaced;
    return replaced.startsWith("curio.builtin/") ? `${replaced}@1` : `${replaced}${nodeType.slice(at)}`;
}

/** A dataflow's package list as Curio ships it now: a replaced package renamed,
 *  or dropped when none of *nodeTypes* (already current) is its replacement's. */
export function currentPackages(packages: readonly string[], nodeTypes: readonly string[]): string[] {
    const used = new Set(nodeTypes.map((type) => type.split("/", 1)[0]));
    const out: string[] = [];
    for (const pkg of packages) {
        const next = REPLACED_PACKAGES[pkg] ?? pkg;
        if (pkg in REPLACED_PACKAGES && !used.has(next.split("@", 1)[0])) continue;
        if (!out.includes(next)) out.push(next);
    }
    return out;
}
