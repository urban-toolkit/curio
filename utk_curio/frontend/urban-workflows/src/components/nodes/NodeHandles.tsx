// A node's handles: on the canvas where its kind puts them, and in the notebook
// view as dots on the cell's right edge, where the bar draws the connections.
// Every node draws its handles here, a node whose type did not resolve
// (UnresolvedNode) as much as any other, so every cell's connections reach the
// bar at the same places.
import React from "react";
import { Handle, Position, type Edge, type Node } from "reactflow";
import type { HandleDef } from "../../registry/types";
import { notebookHandlePlaces, notebookInputLabel } from "../../utils/notebookLayout";
import { resolveNodeDisplayLabel } from "../../utils/palettePackageFactoryDraft";

/** What a dot in the notebook's bar says on hover: which input it is and what feeds it. */
function notebookDotTitle(
  handle: HandleDef,
  nodeId: string,
  edges: readonly Edge[],
  nodes: readonly Node[] | undefined,
): string {
  if (handle.id === "in/out") return "interaction";
  if (handle.type === "source") return "output";
  const edge = edges.find((e) => e.target === nodeId && (e.targetHandle ?? "in") === handle.id);
  const source = edge ? (nodes ?? []).find((n) => n.id === edge.source) : undefined;
  let name: string | null = null;
  try {
    name = source ? resolveNodeDisplayLabel(source.data) || null : null;
  } catch {
    name = null;
  }
  // A circle is named as code names it (`input_0`); a named port by its name.
  const label = notebookInputLabel(handle.id);
  const input = /^\d+$/.test(label) ? `input_${label}` : `input ${label}`;
  return name ? `${input} · ${name}` : input;
}

export function NodeHandles({
  nodeId,
  data,
  handles,
  isConnectable,
  notebookOn,
  edges,
  nodes,
}: {
  nodeId: string;
  /** What a kind's own handle rules (`dynamicStyle`, `isConnectableOverride`) read. */
  data: any;
  handles: readonly HandleDef[];
  isConnectable: boolean;
  /** The node is a notebook cell. */
  notebookOn: boolean;
  edges: Edge[];
  /** The flow's nodes, to name what feeds each input dot. */
  nodes: readonly Node[] | undefined;
}) {
  const notebookPlaces = notebookOn ? notebookHandlePlaces(handles) : null;
  return (
    <>
      {handles.map((h) => {
        const connectable = h.isConnectableOverride
          ? h.isConnectableOverride(data, isConnectable, edges)
          : isConnectable;
        const style = h.dynamicStyle ? h.dynamicStyle(data, edges) : h.style;
        if (notebookPlaces) {
          // Every dot on the right edge, inputs numbered as the chips count
          // them, each anchored to the top, the middle or the bottom so it
          // follows the cell as it grows. React Flow measures the dots again
          // whenever the cell resizes, and the arcs follow them.
          const label = h.type === "target" && h.id !== "in/out" ? notebookInputLabel(h.id) : "";
          return (
            <Handle
              key={h.id}
              id={h.id}
              type={h.type}
              position={Position.Right}
              isConnectable={connectable}
              style={{ ...(style ?? {}), ...notebookPlaces.get(h.id) }}
              title={notebookDotTitle(h, nodeId, edges, nodes)}
              className="curio-notebook-dot"
            >
              {label.length > 0 && label.length <= 2 ? (
                <span className="curio-notebook-dot-label">{label}</span>
              ) : null}
            </Handle>
          );
        }
        return (
          <Handle
            key={h.id}
            id={h.id}
            type={h.type}
            position={h.position}
            isConnectable={connectable}
            style={style}
          />
        );
      })}
    </>
  );
}
