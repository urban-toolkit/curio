import { useEffect, useRef } from "react";
import { useReactFlow } from "reactflow";
import { useCode } from "../../../hook/useCode";
import { useFlowContext } from "../../../providers/FlowProvider";
import {
  AgentCanvasMutation,
  subscribeAgentCanvasMutations,
} from "../../../utils/agentCanvasEvents";
import { refreshPackageRegistry } from "../../../registry/packageRegistryBootstrap";
import {
  getCurrentProjectPackages,
  setCurrentProjectPackages,
} from "../../../registry/projectPackagesStore";

// Approximate node footprint for viewport centering — the node isn't measured
// yet at insert time; half-extent offsets are all setCenter needs.
const NODE_CENTER_X = 175;
const NODE_CENTER_Y = 100;
const CENTER_ANIMATION_MS = 400;

/**
 * Canvas-side listener of the apply→canvas bridge (memos dev/48 §3.3, dev/51).
 *
 * Mounted where React Flow is reachable (the {@link AgentDockOverlay}).
 * - ``node-created`` → insert the applied node into the LIVE graph through
 *   the existing `useCode.createCodeNode` factory (same interpreters and
 *   callbacks as a palette drop) with the SERVER-minted id, then **center the
 *   viewport on it** — the backend places new nodes right of the whole graph
 *   extent, which is usually off-screen (dev/51 defect 1: the node existed
 *   but out of view, and only the load-time fitView made it visible). A new
 *   node type first lands in the project-packages store + client registry
 *   (the same bootstrap refresh the Save-as flow uses) so `UniversalNode`
 *   resolves its descriptor without a reload.
 * - ``node-content-applied`` → `FlowProvider.applyNodeContent` (provider
 *   state — dev/51 defect 2: direct RF-store writes are clobbered by the
 *   controlled re-sync and never reached the serializer or editor).
 *
 * Idempotent per node id at two levels (dev/51 defect 3): a processed-ids ref
 * catches re-fired events before the store has synced, and the live-graph
 * check catches replays across remounts.
 */
export function useAgentCanvasMutations(): void {
  const { createCodeNode } = useCode();
  const { applyNodeContent } = useFlowContext();
  const { getNodes, setCenter, getZoom } = useReactFlow();
  // Event-level idempotence: survives the store-sync lag between an insert
  // and the next controlled re-render.
  const processedRef = useRef<Set<string>>(new Set());
  // The subscription is registered once; the handler reads live refs.
  const handlerRef = useRef<(mutation: AgentCanvasMutation) => void>(() => undefined);

  handlerRef.current = (mutation: AgentCanvasMutation) => {
    if (mutation.kind === "node-content-applied") {
      applyNodeContent(mutation.nodeId, mutation.content);
      return;
    }
    const { node, createdPackageDir } = mutation;
    if (processedRef.current.has(node.id)) return; // re-fired event — no-op
    if (getNodes().some((n) => n.id === node.id)) return; // already live — no-op
    processedRef.current.add(node.id);
    const insert = () => {
      createCodeNode(node.type, {
        nodeId: node.id,
        code: node.content,
        goal: node.goal ?? "",
        position: { x: node.x, y: node.y },
      });
      // The backend placement is right of the whole graph extent — bring the
      // node into view so "created" is visible, not off-screen (dev/51).
      setCenter(node.x + NODE_CENTER_X, node.y + NODE_CENTER_Y, {
        zoom: getZoom(),
        duration: CENTER_ANIMATION_MS,
      });
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
