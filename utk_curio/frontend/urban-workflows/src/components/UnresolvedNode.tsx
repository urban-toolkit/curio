import React, { useMemo } from "react";
import { Position, useEdges, useNodes, type Edge } from "reactflow";

import { useNotebookViewContext } from "../providers/flow/notebookViewContext";
import { useNodeCatalogDrawer } from "../providers/packages/NodeCatalogDrawerProvider";
import type { HandleDef } from "../registry/types";
import { notebookCellBox } from "../utils/notebookLayout";
import { NodeHandles } from "./nodes/NodeHandles";

/**
 * What a node renders when the registry has no descriptor for its type.
 *
 * There are two reasons that happens and they used to look identical: the
 * registry has not caught up yet (transient, and the wait is right), or nothing
 * available provides this type (permanent, and waiting is pointless). Both
 * painted "Loading node…" with no timeout and no error, which is the whole of
 * what the Street-level computer vision example ever showed - three nodes
 * stuck on a spinner-less placeholder, indefinitely, for a package that was
 * never going to arrive (#233).
 *
 * The second case now says so and offers the install.
 *
 * Both cases render HANDLES, which is the other half of that report. React
 * Flow reads a node's ports out of the DOM; a placeholder with no
 * `.react-flow__handle` children has no port bounds, so `EdgeRenderer` logs
 * `error008` and returns `null` for every edge touching it. The edges existed
 * in state the whole time - they just had nowhere to attach. Handles are
 * derived from the edges themselves, so this works for any unresolved type,
 * not only the ones we know about. They are drawn as every node's are
 * (`nodes/NodeHandles`), so in the notebook view the card is a cell with its
 * dots on its right edge, as wide as the other cells.
 */

/** The package coordinate inside a canonical node type. */
export function packageIdFromNodeType(nodeType: unknown): string | null {
  if (typeof nodeType !== "string") return null;
  const slash = nodeType.indexOf("/");
  if (slash <= 0) return null;
  const packageId = nodeType.slice(0, slash);
  return packageId.includes(".") ? packageId : null;
}

/** A readable name for a package id: `curio.streetvision` -> `Streetvision`. */
export function packageDisplayName(packageId: string): string {
  const tail = packageId.split(".").pop() || packageId;
  return tail
    .split("-")
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

const SHELL: React.CSSProperties = {
  padding: "10px 12px",
  minWidth: 190,
  minHeight: 50,
  borderRadius: 6,
  fontSize: 11,
  fontFamily: '"Roboto","Helvetica","Arial",sans-serif',
};

/** Each id as a handle on one side of the card, spread evenly down it. */
function handleColumn(ids: string[], type: "source" | "target", position: Position): HandleDef[] {
  // The exact geometry does not matter - what matters is that each handle
  // EXISTS in the DOM, so React Flow can measure a port for it and draw the
  // edge.
  return ids.map((id, index) => ({
    id,
    type,
    position,
    style: { top: `${((index + 1) / (ids.length + 1)) * 100}%` },
  }));
}

/** A handle for each port the node's edges name: inputs left, outputs right. */
function derivedHandles(nodeId: string, edges: readonly Edge[]): HandleDef[] {
  // Always offer the default pair, so an unconnected placeholder still shows
  // where its ports would be and can be wired up by hand.
  const targets = new Set<string>(["in"]);
  const sources = new Set<string>(["out"]);
  for (const edge of edges) {
    if (edge.target === nodeId) targets.add(edge.targetHandle || "in");
    if (edge.source === nodeId) sources.add(edge.sourceHandle || "out");
  }
  return [
    ...handleColumn([...targets], "target", Position.Left),
    ...handleColumn([...sources], "source", Position.Right),
  ];
}

export function UnresolvedNode({
  nodeId,
  nodeType,
  registryReady,
}: {
  nodeId: string;
  nodeType: string;
  registryReady: boolean;
}) {
  const edges = useEdges();
  const nodes = useNodes();
  const derived = useMemo(() => derivedHandles(nodeId, edges), [edges, nodeId]);
  const notebook = useNotebookViewContext();
  const { openNodeCatalogDrawer } = useNodeCatalogDrawer();
  const packageId = packageIdFromNodeType(nodeType);

  const handles = (
    <NodeHandles
      nodeId={nodeId}
      data={undefined}
      handles={derived}
      isConnectable={false}
      notebookOn={notebook.on}
      edges={edges}
      nodes={nodes}
    />
  );
  // In the notebook view the card is a cell's box, its padding inside that width.
  const shell: React.CSSProperties = notebook.on
    ? { ...SHELL, ...notebookCellBox(derived, notebook.cellWidth), boxSizing: "border-box" }
    : SHELL;

  if (!registryReady) {
    // Still genuinely loading: the registry may yet name a package to blame.
    return (
      <div
        style={{
          ...shell,
          border: "1px dashed #b8b8b8",
          background: "#fafafa",
          color: "#64748b",
        }}
        title={`Waiting on descriptor for ${nodeType}`}
      >
        {handles}
        <strong style={{ color: "#334155", fontSize: 12 }}>Loading node…</strong>
        <div style={{ marginTop: 4, opacity: 0.7 }}>{nodeType}</div>
      </div>
    );
  }

  if (!packageId) {
    // Terminal, not pending (#349). The registry has settled and this type
    // names no package: `packageIdFromNodeType` returns null for an empty or
    // non-string type and for a legacy plain-string one like "DATA_LOADING",
    // and no amount of waiting changes any of those. Showing "Loading node…"
    // for ever is the same dead end #233 fixed for installable packages, on a
    // node-type shape that fix did not recognise.
    //
    // Reachable outside tests: `dataflowImport.ts` deliberately skips per-node
    // type validation so older files still load, and `useCode.ts`'s loadTrill
    // pushes `node.type` straight onto the canvas unvalidated.
    //
    // Slate rather than the amber below, and no Install button: amber means
    // "one click fixes this", and here there is nothing to install - the type
    // itself is the problem.
    return (
      <div
        style={{
          ...shell,
          border: "1px dashed #94a3b8",
          background: "#f8fafc",
          color: "#475569",
        }}
        title={`Unrecognized node type: ${nodeType || "(empty)"}`}
        data-testid="unrecognized-node"
      >
        {handles}
        <strong style={{ color: "#334155", fontSize: 12 }}>
          Unrecognized node type
        </strong>
        <div style={{ marginTop: 4 }}>
          {nodeType
            ? <>This dataflow asks for <strong>{nodeType}</strong>, which is not a
              node type Curio knows. It may come from an older or hand-edited file.</>
            : <>A node in this dataflow has no type. It may come from an older or
              hand-edited file.</>}
        </div>
      </div>
    );
  }

  const name = packageDisplayName(packageId);
  return (
    <div
      style={{
        ...shell,
        border: "1px dashed #d0a215",
        background: "#fffbeb",
        color: "#7a5c00",
      }}
      // The full coordinate, for anyone reading a bug report rather than the
      // screen.
      title={`No installed package provides ${nodeType}`}
      data-testid="unresolved-node"
    >
      {handles}
      <strong style={{ color: "#7a5c00", fontSize: 12 }}>
        Missing node package
      </strong>
      <div style={{ marginTop: 4 }}>
        This node needs <strong>{name}</strong>, which is not available in this
        dataflow.
      </div>
      <button
        type="button"
        className="nodrag"
        onClick={(event) => {
          event.stopPropagation();
          // Land on the package rather than the whole catalog. Install is
          // deliberately the user's click: a package like Street Vision pulls
          // ~3 GB of torch, which is not something opening a dataflow should
          // start on its own.
          openNodeCatalogDrawer({ search: packageId });
        }}
        style={{
          marginTop: 8,
          border: "1px solid #d0a215",
          borderRadius: 6,
          background: "#fff",
          color: "#7a5c00",
          fontFamily: "inherit",
          fontSize: 11,
          fontWeight: 700,
          padding: "4px 10px",
          cursor: "pointer",
        }}
      >
        Install {name}…
      </button>
    </div>
  );
}

export default UnresolvedNode;
