import { useEffect, useRef } from "react";
import { useReactFlow } from "reactflow";
import { useCode } from "../../../hook/useCode";
import { useFlowContext } from "../../../providers/FlowProvider";
import { useProvenanceContext } from "../../../providers/ProvenanceProvider";
import { useNotebookViewContext } from "../../../providers/flow/notebookViewContext";
import { fitViewWithMenuOffset } from "../../../utils/fitViewWithMenuOffset";
import {
  AgentCanvasMutation,
  AgentCreatedNode,
  subscribeAgentCanvasMutations,
} from "../../../services/agents";
import { refreshPackageRegistry } from "../../../registry/packageRegistryBootstrap";
import {
  getCurrentProjectPackages,
  setCurrentProjectPackages,
} from "../../../registry/projectPackagesStore";
import { EdgeType } from "../../../constants";
import { normalizeWidgets } from "../../../utils/widgets/widgetModel";
import { dataPoolFromSpec } from "../../../utils/dataPoolSpec";
import { lineageFromSpec } from "../../../utils/scenarios/duplicateSelection";
import { joinScenarios } from "../../../utils/scenarios/scenarioEdits";
import type { Scenario } from "../../../utils/scenarios/scenarioModel";

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
 *   but out of view, and only the load-time fitView made it visible). A node
 *   the apply names its agent on, added with code, starts its Provenance
 *   history with an edit named after that agent.
 * - ``node-content-applied`` → `FlowProvider.applyNodeContent` (provider
 *   state — dev/51 defect 2: direct RF-store writes are clobbered by the
 *   controlled re-sync and never reached the serializer or editor), with the
 *   name of the agent that wrote it, which a node keeping a history of its
 *   changes names the entry after.
 * - ``node-settings-applied`` → `FlowProvider.applyNodeSettings`, which hands
 *   each setting to the node's own setter (`utils/nodeSettingsWriters`).
 *
 * Idempotent per node id at two levels (dev/51 defect 3): a processed-ids ref
 * catches re-fired events before the store has synced, and the live-graph
 * check catches replays across remounts.
 */
/** dev/112: ONE materialization of an applied spec edge for the live canvas —
 * parity with loadTrill's `add_edge` (useCode): a Trill `Interaction` edge is
 * bidirectional on `in/out` handles with arrows both ends; a data edge keeps
 * the explicit handles the apply assigned (input circles, dev/67-3). Both bridge
 * paths (bulk plan, per-edge connect) go through here. */
function appliedEdgeToCanvasEdge(edge: {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string;
  targetHandle?: string;
  type?: string;
}) {
  const interaction = edge.type === "Interaction";
  return {
    id: edge.id,
    source: edge.source,
    target: edge.target,
    sourceHandle: interaction ? "in/out" : edge.sourceHandle ?? "out",
    targetHandle: interaction ? "in/out" : edge.targetHandle ?? "in",
    type: interaction ? EdgeType.BIDIRECTIONAL_EDGE : EdgeType.UNIDIRECTIONAL_EDGE,
    markerEnd: { type: "arrow" },
    ...(interaction ? { markerStart: { type: "arrow" } } : {}),
    // Parity with loadTrill's add_edge (dev/58): the edge components read
    // display flags off `data` — it must always exist.
    data: {},
  };
}

export function useAgentCanvasMutations(): void {
  const { createCodeNode } = useCode();
  const { applyNodeContent, applyNodeSettings, onEdgesChange, applyReviewedRemovals, scenarios, setScenarios } =
    useFlowContext();
  const { nodeEditProv } = useProvenanceContext();
  const { reveal } = useNotebookViewContext();
  const reactFlow = useReactFlow();
  const { getNodes, setCenter, getZoom } = reactFlow;
  // The connections the canvas holds already are not added again: on a
  // canvas bound to the dataflow's doc, the server's write of an applied
  // plan reaches it through the doc, and can come before the apply's answer.
  const notOnCanvas = <E extends { id: string }>(edges: E[]): E[] => {
    const live = new Set(reactFlow.getEdges().map((e) => e.id));
    return edges.filter((edge) => !live.has(edge.id));
  };
  // Event-level idempotence: survives the store-sync lag between an insert
  // and the next controlled re-render.
  const processedRef = useRef<Set<string>>(new Set());
  // The subscription is registered once; the handler reads live refs.
  const handlerRef = useRef<(mutation: AgentCanvasMutation) => void>(() => undefined);

  const insertNode = (node: AgentCreatedNode) => {
    // #662: read as a load reads them (loadTrill), so the live node holds
    // what the spec does and the next save writes them back.
    const widgets = normalizeWidgets(node.metadata?.widgets);
    const copiedFrom = lineageFromSpec(node.metadata?.copiedFrom);
    const spatialJoin = node.metadata?.spatialJoin;
    // A Data Pool's modes, the ones that name a mode, and a Simple View's
    // image column, as loadTrill reads them.
    const dataPool = dataPoolFromSpec(node.metadata?.dataPool);
    const simpleVis = node.metadata?.simpleVis;
    createCodeNode(node.type, {
      nodeId: node.id,
      code: node.content,
      goal: node.goal ?? "",
      position: { x: node.x, y: node.y },
      // dev/89: the typed appearance/title round-trip — the applied spec
      // values reach live data so the next save re-persists them.
      appearance: node.metadata?.appearance,
      title: node.title,
      ...(widgets.length ? { widgets } : {}),
      ...(copiedFrom.length ? { copiedFrom } : {}),
      ...(spatialJoin ? { spatialJoin } : {}),
      ...(dataPool ? { dataPool } : {}),
      ...(simpleVis ? { simpleVis } : {}),
    });
    // Code an agent wrote starts the node's history, an edit named after the
    // agent, as its applied change to a node's code is named. Only a node.create
    // or package draft apply names the agent: a plan's node gets no entry, even
    // when its template's starter is its code, and the code later written into
    // it is its first edit.
    if (node.agent && typeof node.content === "string" && node.content.trim()) {
      nodeEditProv(node.id, node.content, node.agent);
    }
  };

  // #662: scenarios the apply saved join the canvas's, which a save writes.
  const joinSaved = (saved: Scenario[] | undefined) => {
    if (saved?.length) setScenarios(joinScenarios(scenarios, saved));
  };

  // What an applied plan removes, through the REVIEWED path (dev/62): the
  // user authorized every victim by name on the review card, and the edge
  // cascade travels in the same event, so victims and their edges leave in
  // one operation with manual-delete bookkeeping, without the manual "remove
  // the edges first" guard (which reads the not-yet-committed edge state and
  // would refuse every connected victim). Already-absent elements (user
  // deleted them live) are a no-op.
  const removeReviewed = (live: Set<string>, nodeIds: string[] | undefined, edgeIds: string[] | undefined) => {
    const removedNodeIds = (nodeIds ?? []).filter((id) => live.has(id));
    const removedEdgeIds = edgeIds ?? [];
    if (removedNodeIds.length || removedEdgeIds.length) {
      applyReviewedRemovals(removedNodeIds, removedEdgeIds);
    }
  };

  handlerRef.current = (mutation: AgentCanvasMutation) => {
    if (mutation.kind === "node-content-applied") {
      // The agent that wrote it, which the node's change is named after.
      if (mutation.agent) applyNodeContent(mutation.nodeId, mutation.content, mutation.agent);
      else applyNodeContent(mutation.nodeId, mutation.content);
      return;
    }
    if (mutation.kind === "node-settings-applied") {
      applyNodeSettings(mutation.nodeId, mutation.settings);
      return;
    }
    if (mutation.kind === "scenarios-created") {
      joinSaved(mutation.scenarios);
      return;
    }
    if (mutation.kind === "plan-removals") {
      // A plan applied a row at a time, or by Connect all, removes what it
      // names when it completes, as a whole applied plan does. Its rows
      // already placed its nodes: nothing to insert, no fit.
      const key = `removals:${mutation.planId}`;
      if (processedRef.current.has(key)) return;
      processedRef.current.add(key);
      removeReviewed(new Set(getNodes().map((n) => n.id)), mutation.removedNodeIds, mutation.removedEdgeIds);
      return;
    }
    if (mutation.kind === "edges-created") {
      // dev/67-8: the connection stage applies edges one review at a time —
      // insert quietly through the same provider path (handles + data
      // parity), no fit/center (the nodes are already where the user looks).
      if (processedRef.current.has(mutation.batchId)) return;
      processedRef.current.add(mutation.batchId);
      onEdgesChange(
        notOnCanvas(mutation.edges).map((edge) => ({
          type: "add" as const,
          item: appliedEdgeToCanvasEdge(edge) as never,
        })),
      );
      return;
    }
    if (mutation.kind === "graph-created") {
      // dev/52: a whole applied plan — bulk nodes + edges through the same
      // provider paths a manual build uses, then a fit (a plan deserves a
      // framing, not a center). Idempotent per plan id.
      if (processedRef.current.has(mutation.planId)) return;
      processedRef.current.add(mutation.planId);
      const live = new Set(getNodes().map((n) => n.id));
      // Removals FIRST (dev/59), through the reviewed path.
      removeReviewed(live, mutation.removedNodeIds, mutation.removedEdgeIds);
      for (const node of mutation.nodes) {
        if (!live.has(node.id)) insertNode(node);
      }
      onEdgesChange(
        notOnCanvas(mutation.edges).map((edge) => ({
          type: "add" as const,
          // dev/67-3: the apply assigns real handles (input circles in_N),
          // passed through; dev/112: interaction edges become bidirectional.
          item: appliedEdgeToCanvasEdge(edge) as never,
        })),
      );
      joinSaved(mutation.scenarios);
      window.setTimeout(
        () => fitViewWithMenuOffset(reactFlow, { duration: 400 }),
        50,
      );
      return;
    }
    if (mutation.kind === "package-nodes-created") {
      // dev/89: an applied package draft. Registry-BEFORE-canvas: the new
      // package's descriptors must resolve before UniversalNode paints its
      // nodes — store entry first (deduped), then the registry pulse, then
      // the inserts. Idempotent per artifact digest.
      if (processedRef.current.has(mutation.artifactDigest)) return;
      processedRef.current.add(mutation.artifactDigest);
      // The store holds a ReadonlySet (dev/90 A11: `.includes` here threw at
      // the live Apply — Sets have `.has`; spread covers both shapes).
      const current = getCurrentProjectPackages();
      if (!current?.has(mutation.packageDir)) {
        setCurrentProjectPackages([...(current ?? []), mutation.packageDir]);
      }
      void refreshPackageRegistry().then(() => {
        const live = new Set(getNodes().map((n) => n.id));
        const fresh = mutation.nodes.filter((n) => !live.has(n.id));
        for (const node of fresh) insertNode(node);
        const first = fresh[0] ?? mutation.nodes[0];
        if (first && !reveal([first.id])) {
          setCenter(first.x + NODE_CENTER_X, first.y + NODE_CENTER_Y, {
            zoom: getZoom(),
            duration: CENTER_ANIMATION_MS,
          });
        }
      });
      return;
    }
    const { node } = mutation;
    if (processedRef.current.has(node.id)) return; // re-fired event: no-op
    if (getNodes().some((n) => n.id === node.id)) return; // already live: no-op
    processedRef.current.add(node.id);
    insertNode(node);
    // The backend placement is right of the whole graph extent: bring the
    // node into view so "created" is visible, not off-screen (dev/51). In the
    // notebook view that is its cell, scrolled into view.
    if (!reveal([node.id])) {
      setCenter(node.x + NODE_CENTER_X, node.y + NODE_CENTER_Y, {
        zoom: getZoom(),
        duration: CENTER_ANIMATION_MS,
      });
    }
  };

  useEffect(
    () => subscribeAgentCanvasMutations((m) => handlerRef.current(m)),
    [],
  );
}
