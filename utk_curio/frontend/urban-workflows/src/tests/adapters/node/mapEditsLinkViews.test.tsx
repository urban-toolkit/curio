/**
 * The Map Editor node (`curio.builtin/edit-features`) on an Autark node of
 * several views: it edits the map its interaction edge names at the Autark
 * node's end (`in/out@<id>`), else the node's first map. The tools lie over
 * that map's pane alone, a pick there reaches the Map Editor node and a pick
 * on another map does not, and what the Map Editor node picks lights on that
 * map alone.
 *
 * Harness as in mapEditsLink.test.tsx: the Map Editor node and the map node
 * are the behaviors the canvas registers, the flow's own routing of
 * selections between them (providers/flow/useInteractions), and the stand-in
 * grammar of _support/autkNodeMocks, which draws one map per map of the
 * document here (`drawnMaps.makeEach`).
 */
import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { NodeBehaviorData, UseNodeStateReturn } from "../../../registry/types";

const mockFlowContext = React.createContext<Record<string, any>>({});
jest.mock("../../../providers/FlowProvider", () => ({
  useFlowContext: () => require("react").useContext(mockFlowContext),
}));
jest.mock("../../../providers/ToastProvider", () => require("../../_support/autkNodeMocks").toastProviderModule);
jest.mock("../../../services/api", () => require("../../_support/autkNodeMocks").apiModule);
jest.mock("../../../JavaScriptInterpreter", () => ({ JavaScriptInterpreter: class {} }));
jest.mock("@urban-toolkit/autk-grammar", () => require("../../_support/autkNodeMocks").autkGrammarModule, { virtual: true });
jest.mock("@urban-toolkit/autk-compute", () => ({ ComputeGpgpu: jest.fn() }), { virtual: true });
jest.mock(
  "@urban-toolkit/autk-db",
  () => ({ AutkDb: class { async init() { throw new Error("no autk-db in this test"); } } }),
  { virtual: true },
);
jest.mock("../../../providers/StarterProvider", () => ({ useStarterContext: () => ({ editUserStarter: () => {} }) }));
jest.mock("../../../providers/UserProvider", () => ({ useUserContext: () => ({ user: null }) }));

import { useEditFeaturesBehavior } from "../../../adapters/node/editFeaturesBehavior";
import { useAutkViewBehavior } from "../../../adapters/node/autkViewBehavior";
import { useNodeState } from "../../../hook/useNodeState";
import { useInteractions } from "../../../providers/flow/useInteractions";
import ProvenanceProvider from "../../../providers/ProvenanceProvider";
import { editFeaturesCode, readEditFeaturesCode, type EditFeaturesSettings } from "../../../utils/editFeatures/editFeatures";
import { editMap } from "../../../utils/editFeatures/mapEditBus";
import { drawnMaps, grammarRuns, nodeInput, resetAutkNodeMocks } from "../../_support/autkNodeMocks";
import { stubWebGpu, unstubWebGpu } from "../../_support/autkNode";

const LOADER = "buildings";
const NODE = "interaction";
const MAP = "map";
const EDIT_FEATURES = "curio.builtin/edit-features";
const LOADED = { path: "art-buildings", dataType: "geodataframe" };
const COMMITTED = { path: "art-interaction", dataType: "outputs" };
/** Two maps of the node's layer, `north` and `south`, each picking on it. */
const MAP_SPEC = JSON.stringify({
  map: [
    { id: "north", layerRefs: [{ dataRef: "input_0", isPick: true }] },
    { id: "south", layerRefs: [{ dataRef: "input_0", isPick: true }] },
  ],
});

/** Buildings 119, 136 and 200. */
const BUILDINGS = {
  type: "FeatureCollection",
  features: [119, 136, 200].map((id, i) => ({
    type: "Feature",
    geometry: { type: "Polygon", coordinates: [[[i, 0], [i + 1, 0], [i + 1, 1], [i, 1], [i, 0]]] },
    properties: { building_id: id, height: 10 * (i + 1) },
  })),
};
const KEYED: EditFeaturesSettings = { layer: "input_0", key: "building_id" };

/** A map as a run of the stand-in grammar makes one, the *index*-th of its document. */
function madeMap(index: number) {
  const camera: any = {
    eye: [0, 0, 10000], lookAt: [0, 0, 0], up: [0, 1, 0],
    getEye: () => [...camera.eye], getLookAt: () => [...camera.lookAt], getUp: () => [...camera.up],
    getFovyRadians: () => Math.PI / 4, getFar: () => 1e7, resize: jest.fn(),
    resetCamera: jest.fn(),
  };
  return {
    index,
    camera,
    renderer: { pixelWidth: 400, pixelHeight: 400 },
    canvas: { offsetWidth: 400, offsetHeight: 400 },
    layerManager: { layers: [{ position: new Float32Array([0, 0, 100, 50]), _dimension: 2 }], hasOrigin: true, origin: [1000, 2000] },
    resetCamera: jest.fn(),
    requestRender: jest.fn(),
    updateRenderInfo: jest.fn(),
    destroy: jest.fn(),
  };
}

/** The Map Editor node fed by the loader, feeding the map, joined to the map's view *view* (none: the map node's own dot). */
function mountCanvas(view: string | null) {
  const code = editFeaturesCode(KEYED, 1);
  const edges: any[] = [
    { id: "data-in", source: LOADER, target: NODE, sourceHandle: "out", targetHandle: "in" },
    { id: "data-out", source: NODE, target: MAP, sourceHandle: "out", targetHandle: "in" },
    { id: "link", source: NODE, target: MAP, sourceHandle: "in/out", targetHandle: view === null ? "in/out" : `in/out@${view}`, type: "BIDIRECTIONAL_EDGE" },
  ];
  const seed: any[] = [
    { id: LOADER, type: "curio.builtin/data-loading", data: { nodeId: LOADER, title: "Buildings" } },
    { id: NODE, type: EDIT_FEATURES, data: { nodeId: NODE, input: LOADED, code, defaultCode: code } },
    { id: MAP, type: "curio.builtin/autk-grammar", data: { nodeId: MAP, title: "Two maps", input: COMMITTED, code: MAP_SPEC, defaultCode: MAP_SPEC, outputCallback: jest.fn() } },
  ];
  const latest: { nodes: any[] } = { nodes: seed };
  const play: { current: (spec: string) => Promise<void> } = { current: async () => {} };

  function Canvas({ children }: { children: React.ReactNode }) {
    const [nodes, setNodes] = React.useState<any[]>(seed);
    const [interactions, setInteractions] = React.useState<any[]>([]);
    const nodesRef = React.useRef(nodes);
    nodesRef.current = nodes;
    latest.nodes = nodes;
    const reactFlow = React.useMemo(() => ({ getNode: (id: string) => nodesRef.current.find((n) => n.id === id) }), []);
    const { interactionsCallback } = useInteractions({ interactions, setInteractions, nodes, edges, reactFlow: reactFlow as any, setNodes });
    for (const node of nodes) if (!node.data.interactionsCallback) node.data.interactionsCallback = interactionsCallback;
    const flow = {
      nodes,
      edges,
      nodeExecStatus: {},
      dashboardOn: false,
      scenarios: [],
      workflowNameRef: { current: "Two maps" },
      updateDataNode: (id: string, next: any) => setNodes((prev) => prev.map((n) => (n.id === id ? { ...n, data: { ...next } } : n))),
      markDirty: jest.fn(),
      markNodeStale: jest.fn(),
      markNodeErrored: jest.fn(),
      clearSelectionTagsOf: jest.fn(),
      runDownstream: jest.fn(),
      requestAutoRun: jest.fn(),
      interactionsCallback,
    };
    return <mockFlowContext.Provider value={flow}>{children}</mockFlowContext.Provider>;
  }
  function InteractionNode() {
    const data = React.useContext(mockFlowContext).nodes.find((n: any) => n.id === NODE).data;
    const nodeState = useNodeState(data, EDIT_FEATURES);
    const behavior = useEditFeaturesBehavior(data as NodeBehaviorData, nodeState as UseNodeStateReturn);
    return <div data-testid="interaction-node">{behavior.contentComponent}</div>;
  }
  function MapNode() {
    const data = React.useContext(mockFlowContext).nodes.find((n: any) => n.id === MAP).data;
    const state = React.useRef({ output: { code: "", content: "" }, setOutput: jest.fn(), code: MAP_SPEC, setCode: jest.fn(), templateData: {} }).current;
    const behavior = useAutkViewBehavior(data as NodeBehaviorData, state as unknown as UseNodeStateReturn);
    play.current = behavior.applyGrammar as (spec: string) => Promise<void>;
    return <div data-testid="map-node">{behavior.contentComponent}</div>;
  }

  render(
    <ProvenanceProvider>
      <Canvas>
        <InteractionNode />
        <MapNode />
      </Canvas>
    </ProvenanceProvider>,
  );
  return {
    settings: (): EditFeaturesSettings | undefined => {
      const read = readEditFeaturesCode(latest.nodes.find((n) => n.id === NODE).data.code);
      return "problem" in read ? undefined : read.settings;
    },
    playMap: async () => {
      await act(async () => {
        await play.current(MAP_SPEC);
      });
    },
  };
}

/** A pick on the map *mapId* names, as autk-grammar 5 reports one: the drawn positions it names. */
function pickOn(mapId: string, positions: number[]) {
  act(() => {
    grammarRuns[grammarRuns.length - 1].pickOn(mapId, "input_0", positions);
  });
}

/** What the last draw lit on map *index*, last: its positions. */
const litOn = (index: number) => {
  const calls = (grammarRuns[grammarRuns.length - 1]?.calls ?? []).filter((call) => call[0] === "map" && call[3] === index);
  return calls.length > 0 ? calls[calls.length - 1][2] : [];
};

async function openRemove() {
  fireEvent.click(await screen.findByTestId("interaction-layer-input_0"));
  fireEvent.click(screen.getByTestId("interaction-action-remove"));
}

beforeEach(() => {
  jest.clearAllMocks();
  resetAutkNodeMocks();
  nodeInput.current = BUILDINGS;
  drawnMaps.makeEach = madeMap;
  stubWebGpu();
});

afterEach(unstubWebGpu);

test("the Map Editor node edits the map its interaction edge names, and its tools lie over that map's pane alone", async () => {
  const canvas = mountCanvas("south");
  await canvas.playMap();
  expect(editMap(MAP)).toBe(grammarRuns[0].maps[1]);

  await openRemove();
  const overlay = await screen.findByTestId("map-edit-overlay");
  expect(overlay.closest("[data-curio-autk-pane]")?.getAttribute("data-curio-autk-pane")).toBe("map-1");
  expect(canvas.settings()?.edits ?? []).toEqual([]);
});

test("a pick on the map the edge names reaches the Map Editor node, and a pick on the other map does not", async () => {
  const canvas = mountCanvas("south");
  await canvas.playMap();
  await openRemove();

  pickOn("south", [2]);
  await waitFor(() => expect(screen.getByTestId("interaction-remove-picked")).toHaveTextContent("Remove 1 area"));
  // What the node picked lights on that map alone.
  await waitFor(() => expect(litOn(1)).toEqual([2]));
  expect(litOn(0)).toEqual([]);

  // A pick on the other map is no pick of the map it edits.
  pickOn("north", [1]);
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  fireEvent.click(screen.getByTestId("interaction-remove-picked"));
  expect(canvas.settings()?.edits).toEqual([{ op: "remove", ids: [200] }]);
});

test("guard: an edge on the map node's own dot edits the node's first map", async () => {
  const canvas = mountCanvas(null);
  await canvas.playMap();
  expect(editMap(MAP)).toBe(grammarRuns[0].maps[0]);
  expect(canvas.settings()?.edits ?? []).toEqual([]);
});
