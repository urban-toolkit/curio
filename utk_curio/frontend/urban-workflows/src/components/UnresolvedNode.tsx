import React, { useMemo } from "react";
import { Handle, Position, useEdges } from "reactflow";

import { useNodeCatalogDrawer } from "../providers/NodeCatalogDrawerProvider";

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
 * not only the ones we know about.
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

function useDerivedHandles(nodeId: string) {
  const edges = useEdges();
  return useMemo(() => {
    // Always offer the default pair, so an unconnected placeholder still shows
    // where its ports would be and can be wired up by hand.
    const targets = new Set<string>(["in"]);
    const sources = new Set<string>(["out"]);
    for (const edge of edges) {
      if (edge.target === nodeId) targets.add(edge.targetHandle || "in");
      if (edge.source === nodeId) sources.add(edge.sourceHandle || "out");
    }
    return { targets: [...targets], sources: [...sources] };
  }, [edges, nodeId]);
}

function HandleColumn({
  ids,
  type,
  position,
}: {
  ids: string[];
  type: "source" | "target";
  position: Position;
}) {
  return (
    <>
      {ids.map((id, index) => (
        <Handle
          key={id}
          id={id}
          type={type}
          position={position}
          // Spread evenly down the side. The exact geometry does not matter -
          // what matters is that each handle EXISTS in the DOM, so React Flow
          // can measure a port for it and draw the edge.
          style={{ top: `${((index + 1) / (ids.length + 1)) * 100}%` }}
          isConnectable={false}
        />
      ))}
    </>
  );
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
  const { targets, sources } = useDerivedHandles(nodeId);
  const { openNodeCatalogDrawer } = useNodeCatalogDrawer();
  const packageId = packageIdFromNodeType(nodeType);

  const handles = (
    <>
      <HandleColumn ids={targets} type="target" position={Position.Left} />
      <HandleColumn ids={sources} type="source" position={Position.Right} />
    </>
  );

  if (!registryReady || !packageId) {
    // Still genuinely loading - or a node type with no package coordinate to
    // act on, where naming a package would be a guess.
    return (
      <div
        style={{
          ...SHELL,
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

  const name = packageDisplayName(packageId);
  return (
    <div
      style={{
        ...SHELL,
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
