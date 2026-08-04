import { useEffect, useRef } from "react";
import { useReactFlow } from "reactflow";
import { useCode } from "../../../hook/useCode";
import {
  AgentCanvasMutation,
  subscribeAgentCanvasMutations,
} from "../../../utils/agentCanvasEvents";
import { refreshPackageRegistry } from "../../../registry/packageRegistryBootstrap";
import {
  getCurrentProjectPackages,
  setCurrentProjectPackages,
} from "../../../registry/projectPackagesStore";

/**
 * Canvas-side listener of the apply→canvas bridge (memo dev/48 §3.3).
 *
 * Mounted where React Flow is reachable (the {@link AgentDockOverlay}).
 * - ``node-created`` → insert the applied node into the LIVE graph through
 *   the existing `useCode.createCodeNode` factory (same interpreters and
 *   callbacks as a palette drop), with the SERVER-minted id so live and
 *   saved state agree. A new node type first lands in the project-packages
 *   store + client registry (the same bootstrap refresh the Save-as flow
 *   uses) so `UniversalNode` resolves its descriptor without a reload.
 * - ``node-content-applied`` → update the live node's ``data.code`` (the
 *   field the next save serializes), closing the dev/41 clobber gap.
 *
 * Idempotent per node id: a re-fired event (double dispatch, hot reload)
 * never double-inserts.
 */
export function useAgentCanvasMutations(): void {
  const { createCodeNode } = useCode();
  const { getNodes, setNodes } = useReactFlow();
  // The subscription is registered once; the handler reads live refs.
  const handlerRef = useRef<(mutation: AgentCanvasMutation) => void>(() => undefined);

  handlerRef.current = (mutation: AgentCanvasMutation) => {
    if (mutation.kind === "node-content-applied") {
      setNodes((nds: any[]) =>
        nds.map((n) =>
          n.id === mutation.nodeId
            ? { ...n, data: { ...n.data, code: mutation.content, defaultCode: mutation.content } }
            : n,
        ),
      );
      return;
    }
    const { node, createdPackageDir } = mutation;
    if (getNodes().some((n) => n.id === node.id)) return; // double event — no-op
    const insert = () => {
      if (getNodes().some((n) => n.id === node.id)) return;
      createCodeNode(node.type, {
        nodeId: node.id,
        code: node.content,
        goal: node.goal ?? "",
        position: { x: node.x, y: node.y },
      });
      // ``createCodeNode`` seeds ``defaultCode``; the serializer reads
      // ``data.code`` — set it too so the very next save round-trips the
      // applied content without an editor touch.
      setNodes((nds: any[]) =>
        nds.map((n) =>
          n.id === node.id ? { ...n, data: { ...n.data, code: node.content } } : n,
        ),
      );
    };
    if (createdPackageDir) {
      // A brand-new node type (dev/48 §3.2b): make its descriptor
      // client-resolvable first — store entry, then the registry pulse.
      const current = getCurrentProjectPackages();
      setCurrentProjectPackages([...(current ?? []), createdPackageDir]);
      void refreshPackageRegistry().then(insert);
      return;
    }
    insert();
  };

  useEffect(
    () => subscribeAgentCanvasMutations((m) => handlerRef.current(m)),
    [],
  );
}
