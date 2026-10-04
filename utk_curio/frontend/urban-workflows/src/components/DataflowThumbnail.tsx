import React, { useMemo } from "react";
import { GraphPreview } from "../api/projectsApi";
import styles from "./DataflowThumbnail.module.css";
import {
  CATEGORY_FALLBACK_FG,
  NODE_TYPE_CATEGORY,
  colorForNodeType,
} from "../constants/nodeCategoryPalette";

// Keyed by the canonical unversioned node-type string written into trill
// `graph_preview.nodes[].type` post-Phase-B. The thumbnail runs without the
// node registry loaded (it renders on the projects list, before package
// discovery), so it cannot ask a descriptor for its category — but the type ->
// category map and the colours themselves now come from the shared palette
// instead of being restated here. This file used to hold a hand-kept copy of
// the canvas's map, which is exactly the kind of mirror that drifts.
const NODE_COLORS: Record<string, string> = Object.fromEntries(
  Object.keys(NODE_TYPE_CATEGORY).map((type) => [type, colorForNodeType(type)])
);

const FALLBACK_COLOR = CATEGORY_FALLBACK_FG;

// Local, dependency-free mirror of `unversionedNodeType`. This component renders
// on the projects list before package discovery runs, so it deliberately avoids
// importing anything that would pull in the node registry.
const VERSIONED_TYPE = /^(.+)\/([^/@]+)@(\d+)$/;
const unversionedType = (nodeType: string): string =>
  VERSIONED_TYPE.test(nodeType) ? nodeType.replace(/@\d+$/, "") : nodeType;

// Coordinate space for layout calculations — the SVG scales this to fill its container
const VB_W = 260;
const VB_H = 160;
const PAD = 16;
// Visual size of each node in the thumbnail
const NODE_W = 28;
const NODE_H = 16;

// What a highlight paints: a scenario's own nodes in its colour, the nodes
// that feed it with a dark dashed outline, and everything else faded.
const CONTEXT_STROKE = "#2f3034";
const FADED_OPACITY = 0.3;

/** A scenario marked on its project's graph. */
export interface ThumbnailHighlight {
  /** The scenario's colour. */
  color: string;
  /** Its nodes: outlined and tinted in `color`. */
  members: readonly string[];
  /** The nodes that feed them: a dark dashed outline. */
  context?: readonly string[];
}

interface Props {
  preview?: GraphPreview | null;
  /** Marks a scenario's nodes. Without it the drawing is the Projects page's,
   *  attribute for attribute. */
  highlight?: ThumbnailHighlight | null;
}

/**
 * A dataflow has no category of its own, so the thumbnail carries no
 * per-dataflow accent: the only colour in it is the node bars, which are keyed
 * to node type. The caller used to pass an accentColor/bgColor pair derived
 * from `project.thumbnail_accent`; `accentColor` was never read, and `bgColor`
 * only tinted the empty state.
 */
const DataflowThumbnail: React.FC<Props> = ({ preview, highlight }) => {
  // eslint-disable-next-line react-hooks/rules-of-hooks
  const { scaledNodes, nodeCenter } = useMemo(() => {
    const nodes = preview?.nodes ?? [];
    if (nodes.length === 0) return { scaledNodes: [], nodeCenter: {} };

    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const n of nodes) {
      const w = n.w ?? 200;
      const h = n.h ?? 100;
      minX = Math.min(minX, n.x);
      minY = Math.min(minY, n.y);
      maxX = Math.max(maxX, n.x + w);
      maxY = Math.max(maxY, n.y + h);
    }

    const graphW = maxX - minX || 1;
    const graphH = maxY - minY || 1;
    const usableW = VB_W - PAD * 2;
    const usableH = VB_H - PAD * 2;
    const scale = Math.min(usableW / graphW, usableH / graphH);

    const scaledGraphW = graphW * scale;
    const scaledGraphH = graphH * scale;
    const offsetX = PAD + (usableW - scaledGraphW) / 2;
    const offsetY = PAD + (usableH - scaledGraphH) / 2;

    const scaledNodes = nodes.map((n) => ({
      ...n,
      sx: offsetX + (n.x - minX) * scale,
      sy: offsetY + (n.y - minY) * scale,
    }));

    const nodeCenter: Record<string, { cx: number; cy: number }> = {};
    for (const n of scaledNodes) {
      nodeCenter[n.id] = { cx: n.sx + NODE_W / 2, cy: n.sy + NODE_H / 2 };
    }

    return { scaledNodes, nodeCenter };
  }, [preview]);

  if (!preview || preview.nodes.length === 0) {
    return (
      <div className={styles.emptyPreview} />
    );
  }

  const { edges } = preview;

  // Only with a highlight: the extra attributes each element takes. Without
  // one every spread below is empty, so the plain drawing cannot move.
  const members = new Set(highlight?.members ?? []);
  const context = new Set(highlight?.context ?? []);
  const roleOf = (id: string) =>
    members.has(id) ? "member" : context.has(id) ? "context" : "faded";
  const edgeMarks = (source: string, target: string) => {
    if (!highlight) return {};
    if (members.has(source) && members.has(target)) {
      return { stroke: highlight.color, strokeWidth: 1.5, "data-thumbnail-role": "member" };
    }
    // An edge stays as it is while both its ends are marked; any other fades.
    return roleOf(source) === "faded" || roleOf(target) === "faded"
      ? { opacity: FADED_OPACITY, "data-thumbnail-role": "faded" }
      : { "data-thumbnail-role": "context" };
  };
  const nodeMarks = (id: string) => {
    if (!highlight) return { group: {}, box: {} };
    const role = roleOf(id);
    if (role === "member") {
      return {
        group: { "data-thumbnail-role": role },
        box: { fill: highlight.color, fillOpacity: 0.18, stroke: highlight.color, strokeWidth: 1.5 },
      };
    }
    if (role === "context") {
      return {
        group: { "data-thumbnail-role": role },
        box: { stroke: CONTEXT_STROKE, strokeWidth: 1, strokeDasharray: "2 1.5" },
      };
    }
    return { group: { "data-thumbnail-role": role, opacity: FADED_OPACITY }, box: {} };
  };

  return (
    <svg
      viewBox={`0 0 ${VB_W} ${VB_H}`}
      width="100%"
      height="100%"
      preserveAspectRatio="xMidYMid meet"
      style={{ display: "block" }}
      {...(highlight ? { "data-thumbnail-highlight": "true" } : {})}
    >
      <rect x={0} y={0} width={VB_W} height={VB_H} fill="#f5f5f5" />

      {edges.map((e, i) => {
        const src = nodeCenter[e.source];
        const tgt = nodeCenter[e.target];
        if (!src || !tgt) return null;
        return (
          <line
            key={i}
            x1={src.cx} y1={src.cy}
            x2={tgt.cx} y2={tgt.cy}
            stroke="#c8c8c8"
            strokeWidth={1}
            {...edgeMarks(e.source, e.target)}
          />
        );
      })}

      {scaledNodes.map((n) => {
        // Palette-dragged nodes persist a versioned type (`.../merge-flow@1`);
        // this map is keyed unversioned, so strip the suffix first (#159).
        const color = NODE_COLORS[unversionedType(n.type)] ?? FALLBACK_COLOR;
        const marks = nodeMarks(n.id);
        return (
          <g key={n.id} {...marks.group}>
            <rect x={n.sx} y={n.sy} width={NODE_W} height={NODE_H} rx={2} fill="#ffffff" stroke="#e0e0e0" strokeWidth={0.5} {...marks.box} />
            <rect x={n.sx} y={n.sy} width={3} height={NODE_H} rx={1} fill={color} />
          </g>
        );
      })}
    </svg>
  );
};


// Exposed for the #159 parity guard in src/tests/utils/versionedNodeTypeParity.test.ts:
// the colour map is keyed unversioned, so a versioned id must resolve to the same
// entry rather than silently taking FALLBACK_COLOR.
export const __testables = { NODE_COLORS, FALLBACK_COLOR, unversionedType };

export default DataflowThumbnail;
