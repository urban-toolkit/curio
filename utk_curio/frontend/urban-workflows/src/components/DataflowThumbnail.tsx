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

interface Props {
  preview?: GraphPreview | null;
}

/**
 * A dataflow has no category of its own, so the thumbnail carries no
 * per-dataflow accent: the only colour in it is the node bars, which are keyed
 * to node type. The caller used to pass an accentColor/bgColor pair derived
 * from `project.thumbnail_accent`; `accentColor` was never read, and `bgColor`
 * only tinted the empty state.
 */
const DataflowThumbnail: React.FC<Props> = ({ preview }) => {
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

  return (
    <svg
      viewBox={`0 0 ${VB_W} ${VB_H}`}
      width="100%"
      height="100%"
      preserveAspectRatio="xMidYMid meet"
      style={{ display: "block" }}
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
          />
        );
      })}

      {scaledNodes.map((n) => {
        // Palette-dragged nodes persist a versioned type (`.../merge-flow@1`);
        // this map is keyed unversioned, so strip the suffix first (#159).
        const color = NODE_COLORS[unversionedType(n.type)] ?? FALLBACK_COLOR;
        return (
          <g key={n.id}>
            <rect x={n.sx} y={n.sy} width={NODE_W} height={NODE_H} rx={2} fill="#ffffff" stroke="#e0e0e0" strokeWidth={0.5} />
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
