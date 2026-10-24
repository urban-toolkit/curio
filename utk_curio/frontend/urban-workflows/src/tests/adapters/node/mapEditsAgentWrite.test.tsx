/**
 * An agent's applied change to a Map Edits node goes through the node's own
 * writer, as an edit made in the node does: its code lands in the node, the
 * dataflow reads Unsaved, the node and every node below it that ran are out
 * of date, and the change is an entry of the node's Provenance drawer, named
 * after the agent that made it. The canvas takes an applied change through
 * `applyNodeContent` (the agent bridge, `useAgentCanvasMutations`), so the
 * test applies one there.
 */
import React from "react";
import { act, render } from "@testing-library/react";
import type { Edge, Node, ReactFlowInstance } from "reactflow";
import type { NodeBehaviorData, UseNodeStateReturn } from "../../../registry/types";

const mockFlowContext = React.createContext<Record<string, any>>({});
jest.mock("../../../providers/FlowProvider", () => ({
  useFlowContext: () => require("react").useContext(mockFlowContext),
}));
// The node's map reads no layers here: the change comes from an agent.
jest.mock("../../../utils/autkInput", () => ({
  readAutkInput: jest.fn(() => Promise.resolve({ frames: [] })),
  autkSourcesFrom: jest.fn(() => ({ sources: [] })),
}));
jest.mock("vega", () => ({}), { virtual: true });
jest.mock("vega-lite", () => ({}), { virtual: true });

import { useEditFeaturesBehavior } from "../../../adapters/node/editFeaturesBehavior";
import { useGraphEdits } from "../../../providers/flow/useGraphEdits";
import ProvenanceProvider, { useProvenanceContext, type NodeExecRecord } from "../../../providers/ProvenanceProvider";
import { editFeaturesCode } from "../../../utils/editFeatures/editFeatures";

const NODE = "edit-1";
const MAP = "map";
const AGENT = "Node Builder";
/** What the node held: no edits yet. */
const BEFORE = editFeaturesCode(undefined, 1);
/** What the agent wrote: building 2 removed. */
const AGENT_CODE = editFeaturesCode({ key: "building_id", edits: [{ op: "remove", ids: [2] }] }, 1);

/** The loader feeds the node, the node its map, the map a count; a chart is linked to the map only. */
const MORE = [
  { id: "load", type: "curio.builtin/data-loading", data: {} },
  { id: MAP, type: "curio.builtin/autk-grammar", data: {} },
  { id: "count", type: "curio.builtin/computation-analysis", data: {} },
  { id: "chart", type: "curio.builtin/vis-vega", data: {} },
];
const EDGES = [
  { id: "d1", source: "load", target: NODE, sourceHandle: "out", targetHandle: "in" },
  { id: "d2", source: NODE, target: MAP, sourceHandle: "out", targetHandle: "in" },
  { id: "link", source: NODE, target: MAP, sourceHandle: "in/out", targetHandle: "in/out", type: "BIDIRECTIONAL_EDGE" },
  { id: "d3", source: MAP, target: "count", sourceHandle: "out", targetHandle: "in" },
  { id: "i1", source: MAP, target: "chart", sourceHandle: "in/out", targetHandle: "in/out", type: "BIDIRECTIONAL_EDGE" },
];
const RAN = { load: "executed", [NODE]: "executed", [MAP]: "executed", count: "executed", chart: "executed" };

type ApplyNodeContent = (nodeId: string, content: string, agent?: string) => void;

/**
 * The node on a canvas that keeps what is written into it, under the
 * provider of its Provenance drawer, and the canvas's own `applyNodeContent`
 * (`useGraphEdits`) beside it.
 */
function mount() {
  const markNodeStale = jest.fn();
  const markDirty = jest.fn();
  const provenance: { current: ReturnType<typeof useProvenanceContext> | null } = { current: null };
  const apply: { current: ApplyNodeContent | null } = { current: null };
  const live: { current: Record<string, any> } = { current: { nodeId: NODE, input: "", defaultCode: BEFORE, code: BEFORE } };
  const state = { output: { code: "success", content: "" }, setOutput: jest.fn(), code: "", setCode: jest.fn() } as unknown as UseNodeStateReturn;

  function Probe() {
    provenance.current = useProvenanceContext();
    return null;
  }
  function Canvas({ children }: { children: React.ReactNode }) {
    const [data, setData] = React.useState<Record<string, any>>(live.current);
    live.current = data;
    const nodes = [{ id: NODE, type: "curio.builtin/edit-features", data }, ...MORE];
    // The canvas's node list, as setNodes writes it: only the Map Edits node changes here.
    const setNodes = ((update: Node[] | ((nds: Node[]) => Node[])) => {
      const next = typeof update === "function" ? update(nodes as unknown as Node[]) : update;
      const node = next.find((n) => n.id === NODE);
      if (node) setData(node.data);
    }) as React.Dispatch<React.SetStateAction<Node[]>>;
    const edits = useGraphEdits({
      setNodes,
      setEdges: jest.fn() as unknown as React.Dispatch<React.SetStateAction<Edge[]>>,
      reactFlow: { getNodes: () => nodes, getEdges: () => EDGES } as unknown as ReactFlowInstance,
      workflowNameRef: { current: "wf" },
      collabRef: { current: { broadcastNodeAdded: jest.fn() } } as any,
      outputsRef: { current: [] },
      markNodeStaleRef: { current: markNodeStale },
      setOutputs: jest.fn(),
    });
    apply.current = edits.applyNodeContent as unknown as ApplyNodeContent;
    const flow = {
      nodes,
      edges: EDGES,
      nodeExecStatus: RAN,
      markNodeStale,
      markDirty,
      updateDataNode: (_id: string, next: any) => setData(next),
    };
    return <mockFlowContext.Provider value={flow}>{children}</mockFlowContext.Provider>;
  }
  function Host() {
    const data = React.useContext(mockFlowContext).nodes[0].data;
    const behavior = useEditFeaturesBehavior(data as unknown as NodeBehaviorData, state);
    return <>{behavior.contentComponent}</>;
  }
  render(
    <ProvenanceProvider>
      <Probe />
      <Canvas>
        <Host />
      </Canvas>
    </ProvenanceProvider>,
  );
  return {
    markNodeStale,
    markDirty,
    /** The code the node holds now. */
    code: () => String(live.current.code ?? ""),
    /** The entries of the node's Provenance drawer. */
    entries: (): NodeExecRecord[] => provenance.current?.getAllNodeProvenance()[NODE] ?? [],
    applyNodeContent: (content: string, agent?: string) => act(() => apply.current!(NODE, content, agent)),
  };
}

test("an agent's applied change is an entry of the node's Provenance drawer named after the agent, and holds the code it left", () => {
  const { applyNodeContent, entries, code } = mount();
  expect(entries()).toHaveLength(0);
  applyNodeContent(AGENT_CODE, AGENT);
  expect(code()).toBe(AGENT_CODE);
  expect(entries()).toHaveLength(1);
  expect(entries()[0]).toMatchObject({ kind: "edit", label: AGENT, code: AGENT_CODE, inputs: [], outputs: [] });
  // The node's first entry keeps the code the change replaced, for Undo.
  expect(entries()[0].before).toBe(BEFORE);
});

test("an agent's applied change leaves the dataflow Unsaved and the node and every node below it that ran out of date, as an edit made in the node does", () => {
  const { applyNodeContent, markNodeStale, markDirty } = mount();
  applyNodeContent(AGENT_CODE, AGENT);
  expect(markDirty).toHaveBeenCalled();
  // The map the node feeds and the count below it; the chart is linked to the map, not fed by it.
  expect([...new Set(markNodeStale.mock.calls.map((call) => call[0]))].sort()).toEqual([NODE, MAP, "count"].sort());
});
