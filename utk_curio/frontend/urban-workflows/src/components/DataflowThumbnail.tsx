import React, { useMemo } from "react";
import { GraphPreview } from "../api/projectsApi";

const NODE_COLORS: Record<string, string> = {
  DATA_LOADING: "#3498db",
  DATA_EXPORT: "#3498db",
  DATA_TRANSFORMATION: "#3498db",
  DATA_SUMMARY: "#3498db",
  COMPUTATION_ANALYSIS: "#8e44ad",
  MERGE_FLOW: "#8e44ad",
  DATA_POOL: "#8e44ad",
  VIS_VEGA: "#1abc9c",
  VIS_SIMPLE: "#1abc9c",
  AUTK_MAP: "#1abc9c",
  AUTK_PLOT: "#1abc9c",
  AUTK_COMPUTE: "#8e44ad",
  AUTK_DB: "#3498db",
};

const FALLBACK_COLOR = "#95a5a6";
// Coordinate space for layout calculations — the SVG scales this to fill its container
const VB_W = 260;
const VB_H = 160;
const PAD = 16;
// Visual size of each node in the thumbnail
const NODE_W = 28;
const NODE_H = 16;

interface Props {
  preview?: GraphPreview | null;
  accentColor: string;
  bgColor: string;
}

const DataflowThumbnail: React.FC<Props> = ({ preview, accentColor, bgColor }) => {
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
      <div style={{ width: "100%", height: "100%", backgroundColor: bgColor }} />
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
        const color = NODE_COLORS[n.type] ?? FALLBACK_COLOR;
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

export default DataflowThumbnail;
