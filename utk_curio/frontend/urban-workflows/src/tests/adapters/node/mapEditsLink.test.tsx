/**
 * The Map Edits node (`curio.builtin/edit-features`) and the Autark map it
 * feeds, joined by an interaction edge, with the flow's own routing of
 * selections (providers/flow/useInteractions): a pick on the map is the map's
 * selection, which the edge carries to the node, as a selection crosses
 * between two views, and what the node picks, or a rule matches, goes back
 * the same way and lights up on the map. A map the node feeds but is not
 * linked to draws the edits, and a click there selects nothing in the node.
 * A layer the node makes is drawn on top once it has features. The map keeps
 * its view when an edit draws it again, and after Commit edits. A click on the
 * map picks the feature under it, and a shift-click adds or drops one, while
 * the map draws an edit again too. The map lights a pick, every part of a
 * building, on the layer an action works on, and nothing is drawn over it; a
 * play of the map drops the pick. The drawing tools, the shape being drawn,
 * a shape's corners and midpoints, are layers of the map itself, and a
 * building being reshaped is drawn by them instead of its own layer.
 *
 * Each node is the behavior the canvas registers for its type, with the
 * node's own state (hook/useNodeState) for the Map Edits node; the map draws
 * with the stand-in grammar of _support/autkNodeMocks, whose pick is a pick
 * on the map, as autk-grammar reports one.
 */
import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { NodeBehaviorData, UseNodeStateReturn } from "../../../registry/types";

// The flow, as a canvas that keeps what its nodes write and routes their selections.
const mockFlowContext = React.createContext<Record<string, any>>({});
jest.mock("../../../providers/FlowProvider", () => ({
  useFlowContext: () => require("react").useContext(mockFlowContext),
}));
// The map's toasts, its input's artifacts and its grammar.
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
// The node's own state reads the starters and the user.
jest.mock("../../../providers/StarterProvider", () => ({ useStarterContext: () => ({ editUserStarter: () => {} }) }));
jest.mock("../../../providers/UserProvider", () => ({ useUserContext: () => ({ user: null }) }));

import { useEditFeaturesBehavior } from "../../../adapters/node/editFeaturesBehavior";
import { useAutkViewBehavior } from "../../../adapters/node/autkViewBehavior";
import { useNodeState } from "../../../hook/useNodeState";
import { useInteractions } from "../../../providers/flow/useInteractions";
import ProvenanceProvider, { useProvenanceContext } from "../../../providers/ProvenanceProvider";
import { editFeaturesCode, readEditFeaturesCode, type EditFeaturesSettings } from "../../../utils/editFeatures/editFeatures";
import { editSelection } from "../../../utils/editFeatures/mapEditSelection";
import { toMercator } from "../../../utils/editFeatures/mapEditBus";
import { drawnMaps, grammarRuns, heldDraws, nodeInput, resetAutkNodeMocks } from "../../_support/autkNodeMocks";
import { stubWebGpu, unstubWebGpu } from "../../_support/autkNode";

const LOADER = "buildings";
const NODE = "interaction";
const MAP = "map";
const EDIT_FEATURES = "curio.builtin/edit-features";

/** What the loader handed on: the node's input. */
const LOADED = { path: "art-buildings", dataType: "geodataframe" };
/** What the node handed the map at its last run. */
const COMMITTED = { path: "art-interaction", dataType: "outputs" };
/** The map's document: the node's layer, which it picks on. */
const MAP_SPEC = JSON.stringify({ map: { layerRefs: [{ dataRef: "input_0", isPick: true }] } });

/** Buildings 119, 136 and 200, 10, 20 and 30 m tall. */
const BUILDINGS = {
  type: "FeatureCollection",
  features: [119, 136, 200].map((id, i) => ({
    type: "Feature",
    geometry: { type: "Polygon", coordinates: [[[i, 0], [i + 1, 0], [i + 1, 1], [i, 1], [i, 0]]] },
    properties: { building_id: id, height: 10 * (i + 1) },
  })),
};

/** The node's layer and the column that identifies its features, before any edit. */
const KEYED: EditFeaturesSettings = { layer: "input_0", key: "building_id" };

const LINK = { id: "link", source: NODE, target: MAP, sourceHandle: "in/out", targetHandle: "in/out", type: "BIDIRECTIONAL_EDGE" };

/**
 * The node fed by the loader, feeding the map, and, with *link*, joined to
 * it by an interaction edge; its code holds *settings*.
 */
function mountCanvas({ settings = KEYED, link = true }: { settings?: EditFeaturesSettings; link?: boolean } = {}) {
  const code = editFeaturesCode(settings, 1);
  const firstEdges: any[] = [
    { id: "data-in", source: LOADER, target: NODE, sourceHandle: "out", targetHandle: "in" },
    { id: "data-out", source: NODE, target: MAP, sourceHandle: "out", targetHandle: "in" },
    ...(link ? [LINK] : []),
  ];
  const outputCallback = jest.fn();
  const seed: any[] = [
    { id: LOADER, type: "curio.builtin/data-loading", data: { nodeId: LOADER, title: "Buildings" } },
    { id: NODE, type: EDIT_FEATURES, data: { nodeId: NODE, input: LOADED, code, defaultCode: code } },
    { id: MAP, type: "curio.builtin/autk-grammar", data: { nodeId: MAP, title: "Downtown map", input: COMMITTED, code: MAP_SPEC, defaultCode: MAP_SPEC, outputCallback } },
  ];
  const latest: {
    nodes: any[];
    interactions: any[];
    setNodes: (update: (nodes: any[]) => any[]) => void;
    setEdges: (edges: any[]) => void;
  } = { nodes: seed, interactions: [], setNodes: () => {}, setEdges: () => {} };
  const play: { current: (spec: string) => Promise<void> } = { current: async () => {} };
  const provenance: { current: ReturnType<typeof useProvenanceContext> | null } = { current: null };

  function Canvas({ children }: { children: React.ReactNode }) {
    const [nodes, setNodes] = React.useState<any[]>(seed);
    const [edges, setEdges] = React.useState<any[]>(firstEdges);
    const [interactions, setInteractions] = React.useState<any[]>([]);
    const nodesRef = React.useRef(nodes);
    nodesRef.current = nodes;
    latest.nodes = nodes;
    latest.interactions = interactions;
    latest.setNodes = setNodes;
    latest.setEdges = setEdges;
    const reactFlow = React.useMemo(() => ({ getNode: (id: string) => nodesRef.current.find((n) => n.id === id) }), []);
    const { interactionsCallback } = useInteractions({ interactions, setInteractions, nodes, edges, reactFlow: reactFlow as any, setNodes });
    // Every node records its selections through the one callback, as useCode gives it.
    for (const node of nodes) if (!node.data.interactionsCallback) node.data.interactionsCallback = interactionsCallback;
    const flow = {
      nodes,
      edges,
      nodeExecStatus: {},
      dashboardOn: false,
      scenarios: [],
      workflowNameRef: { current: "Downtown edits" },
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
  function Probe() {
    provenance.current = useProvenanceContext();
    return null;
  }

  render(
    <ProvenanceProvider>
      <Probe />
      <Canvas>
        <InteractionNode />
        <MapNode />
      </Canvas>
    </ProvenanceProvider>,
  );
  const dataOf = (nodeId: string) => latest.nodes.find((n) => n.id === nodeId).data;
  return {
    outputCallback,
    /** The edits the node's code holds now. */
    settings: (): EditFeaturesSettings | undefined => {
      const read = readEditFeaturesCode(dataOf(NODE).code);
      return "problem" in read ? undefined : read.settings;
    },
    /** What the interaction edges brought *nodeId* last. */
    interactionsOf: (nodeId: string) => dataOf(nodeId).interactions,
    /** Every node's latest selection, as the flow keeps them. */
    selections: () => latest.interactions,
    /** What the map's overlay sends for a click: the map's selection, through the map's node. */
    sendAsMap: (details: Record<string, any>) =>
      act(() => {
        dataOf(MAP).interactionsCallback(details, MAP);
      }),
    /** The map's play: its document run, to the end of the run. */
    playMap: async () => {
      await act(async () => {
        await play.current(MAP_SPEC);
      });
    },
    /** The map fed a new output, as the node's run hands one on. */
    feedMap: (input: unknown) =>
      act(() => {
        latest.setNodes((prev) => prev.map((n) => (n.id === MAP ? { ...n, data: { ...n.data, input } } : n)));
      }),
    /** The interaction edge taken off the canvas. */
    unlink: () =>
      act(() => {
        latest.setEdges(firstEdges.filter((edge) => edge.id !== LINK.id));
      }),
    runsOf: (nodeId: string) => provenance.current?.getAllNodeProvenance()[nodeId] ?? [],
  };
}

/** A pick on the map, as autk-grammar reports one: the drawn positions it names. */
function pickOnMap(positions: number[]) {
  act(() => {
    grammarRuns[grammarRuns.length - 1].pick(positions);
  });
}

/** The building ids the map drew at its last draw. */
const drawnIds = () => (grammarRuns[grammarRuns.length - 1]?.spec?.data ?? [])
  .flatMap((source: any) => source?.geojsonObject?.features ?? [])
  .map((feature: any) => feature?.properties?.building_id);

/** What the map lit up last on the layer *table*: its positions. */
const litUp = (table = "input_0") => {
  const lit = grammarRuns[grammarRuns.length - 1]?.highlights.filter(([name]) => name === table) ?? [];
  return lit.length > 0 ? lit[lit.length - 1][1] : [];
};

const body = () => document.querySelector("[data-edit-body]") as HTMLElement;

async function openAction(action: "remove" | "edit" | "add") {
  fireEvent.click(await screen.findByTestId("interaction-layer-input_0"));
  fireEvent.click(screen.getByTestId(`interaction-action-${action}`));
}

beforeEach(() => {
  jest.clearAllMocks();
  resetAutkNodeMocks();
  nodeInput.current = BUILDINGS;
  stubWebGpu();
});

afterEach(() => {
  unstubWebGpu();
});

test("a pick on the linked map selects that feature in the Map Edits node, and Remove removes it", async () => {
  const canvas = mountCanvas();
  await canvas.playMap();
  await openAction("remove");
  expect(screen.getByTestId("interaction-remove-picked")).toBeDisabled();

  // The map's selection, which the interaction edge carries to the node.
  pickOnMap([2]);
  expect(canvas.interactionsOf(NODE)).toEqual([expect.objectContaining({ nodeId: MAP })]);
  await waitFor(() => expect(screen.getByTestId("interaction-remove-picked")).toHaveTextContent("Remove 1 area"));
  fireEvent.click(screen.getByTestId("interaction-remove-picked"));
  expect(canvas.settings()?.edits).toEqual([{ op: "remove", ids: [200] }]);
  // The map draws the removal at once, and that draw is no run of the map.
  await waitFor(() => expect(drawnIds()).toEqual([119, 136]));
  expect(canvas.runsOf(MAP)).toHaveLength(1);
  expect(canvas.outputCallback).toHaveBeenCalledTimes(1);
});

test("a node's first edit, which gives its code the layer's id column, names that column in its Provenance entry", async () => {
  // A node with no edits yet: its code names no layer and no id column.
  const canvas = mountCanvas({ settings: {} });
  await canvas.playMap();
  await openAction("remove");
  pickOnMap([2]);
  await waitFor(() => expect(screen.getByTestId("interaction-remove-picked")).toHaveTextContent("Remove 1 area"));
  fireEvent.click(screen.getByTestId("interaction-remove-picked"));
  expect(canvas.settings()).toMatchObject({ layer: "input_0", key: "building_id", edits: [{ op: "remove", ids: [200] }] });
  expect(canvas.runsOf(NODE)).toEqual([expect.objectContaining({ kind: "edit", label: "Remove building_id 200" })]);
});

test("the selection the map's overlay sends names features by the layer's id column, each pick replacing the one before", async () => {
  const canvas = mountCanvas();
  await canvas.playMap();
  await openAction("remove");
  canvas.sendAsMap(editSelection([136], "building_id", "input_0"));
  await waitFor(() => expect(screen.getByTestId("interaction-remove-picked")).toHaveTextContent("Remove 1 area"));
  // A shift-click on 119: the map sends both.
  canvas.sendAsMap(editSelection([136, 119], "building_id", "input_0"));
  await waitFor(() => expect(screen.getByTestId("interaction-remove-picked")).toHaveTextContent("Remove 2 areas"));
  // A selection of another layer of the map picks nothing here.
  canvas.sendAsMap(editSelection([200], "building_id", "table_osm_roads"));
  await waitFor(() => expect(canvas.interactionsOf(NODE)?.[0]?.details?.autk_selection?.layerRef).toBe("table_osm_roads"));
  expect(screen.getByTestId("interaction-remove-picked")).toHaveTextContent("Remove 2 areas");
  fireEvent.click(screen.getByTestId("interaction-remove-picked"));
  expect(canvas.settings()?.edits).toEqual([{ op: "remove", ids: [119, 136] }]);
});

test("what the Map Edits node picks, or a rule matches, lights up on the map, by the selection it sends back", async () => {
  const canvas = mountCanvas();
  await canvas.playMap();
  await openAction("remove");
  pickOnMap([1]);
  // The node's pick, back on the map: building 136, drawn second.
  await waitFor(() => expect(litUp()).toEqual([1]));
  expect(canvas.interactionsOf(MAP)).toEqual([expect.objectContaining({ nodeId: NODE })]);

  // A rule: what it matches lights up as it is written.
  fireEvent.click(screen.getByTestId("interaction-remove-by-rule"));
  fireEvent.change(screen.getByLabelText("Test"), { target: { value: ">" } });
  fireEvent.change(screen.getByTestId("interaction-rule-value-0"), { target: { value: "15" } });
  expect(screen.getByTestId("interaction-matching")).toHaveTextContent("Matches 2 areas of 3");
  await waitFor(() => expect(litUp()).toEqual([1, 2]));

  // Back on the list of layers, nothing is lit up.
  fireEvent.click(screen.getByTestId("interaction-back"));
  fireEvent.click(screen.getByText("← All layers"));
  await waitFor(() => expect(litUp()).toEqual([]));
});

test("on a map the node feeds but is not linked to, the edits show and a click selects nothing", async () => {
  const canvas = mountCanvas({ settings: { ...KEYED, edits: [{ op: "remove", ids: [119] }] }, link: false });
  await canvas.playMap();
  expect(drawnIds()).toEqual([136, 200]);
  expect(screen.getByTestId("interaction-unlinked")).toHaveTextContent("Not linked to a map");
  // No tools on the map, so a click there is the map's own pick, which no
  // interaction edge carries to the node.
  expect(screen.queryByTestId("map-edit-overlay")).toBeNull();
  pickOnMap([1]);
  expect(canvas.selections()).toEqual([expect.objectContaining({ nodeId: MAP })]);
  expect(canvas.interactionsOf(NODE)).toBeUndefined();
});

test("a layer the node makes is drawn on top of the map once it has features", async () => {
  const centers = { name: "cooling_centers", geometry: "Point" as const };
  const tables = () => (grammarRuns[grammarRuns.length - 1]?.spec?.map?.layerRefs ?? []).map((ref: any) => ref.dataRef);
  await mountCanvas({ settings: { ...KEYED, newLayers: [centers] } }).playMap();
  expect(tables()).toEqual(["input_0"]);
  cleanup();
  const library = { op: "add" as const, layer: "cooling_centers", id: "c1", geometry: { type: "Point", coordinates: [0.5, 0.5] }, values: {} };
  await mountCanvas({ settings: { ...KEYED, newLayers: [centers], edits: [library] } }).playMap();
  expect(tables()).toEqual(["input_0", "cooling_centers"]);
});

test("Delete removes the picked features and Escape clears the pick, while the body, not a field, has the keys", async () => {
  const canvas = mountCanvas();
  await canvas.playMap();
  await openAction("remove");
  pickOnMap([0]);
  await waitFor(() => expect(screen.getByTestId("interaction-remove-picked")).toHaveTextContent("Remove 1 area"));
  // Escape clears the pick, and the map lights up nothing.
  fireEvent.keyDown(body(), { key: "Escape" });
  expect(screen.getByTestId("interaction-remove-picked")).toBeDisabled();
  await waitFor(() => expect(litUp()).toEqual([]));
  // Picked again, Delete removes it; handled here, the canvas neither deletes the node nor moves it.
  pickOnMap([0]);
  await waitFor(() => expect(screen.getByTestId("interaction-remove-picked")).toHaveTextContent("Remove 1 area"));
  expect(fireEvent.keyDown(body(), { key: "Delete" })).toBe(false);
  expect(canvas.settings()?.edits).toEqual([{ op: "remove", ids: [119] }]);
  // Nothing picked: the node leaves Delete alone.
  expect(fireEvent.keyDown(body(), { key: "Delete" })).toBe(true);
});

test("a feature picked on the map shows its values as the log leaves them, and takes a value typed into its field, a number in a column of numbers", async () => {
  const raised = { op: "offset" as const, ids: [136], column: "height", value: 3 };
  const canvas = mountCanvas({ settings: { ...KEYED, edits: [raised] } });
  await canvas.playMap();
  await openAction("edit");
  pickOnMap([1]);
  const field = (await screen.findByTestId("interaction-field-height")) as HTMLInputElement;
  // 20 m as loaded, and 3 m more by the edit before.
  expect(field.value).toBe("23");
  // Text in a column of numbers is no value.
  fireEvent.change(field, { target: { value: "tall" } });
  expect(screen.getByTestId("interaction-form-submit")).toBeDisabled();
  fireEvent.change(field, { target: { value: "30" } });
  fireEvent.click(screen.getByTestId("interaction-form-submit"));
  expect(canvas.settings()?.edits).toEqual([raised, { op: "set", ids: [136], column: "height", value: 30 }]);
});

test("the link taken off, the node drops the picks that came from the map, and says to link one", async () => {
  const canvas = mountCanvas();
  await canvas.playMap();
  await openAction("remove");
  pickOnMap([2]);
  await waitFor(() => expect(screen.getByTestId("interaction-remove-picked")).toHaveTextContent("Remove 1 area"));
  canvas.unlink();
  expect(await screen.findByTestId("interaction-unlinked")).toHaveTextContent("Not linked to a map");
  expect(screen.queryByTestId("interaction-remove-picked")).toBeNull();
});

/** A map as autk-map draws it, its camera where a run leaves it, its layers drawn relative to *origin*. */
function fakeMap(origin: number[] = [1000, 2000]) {
  const camera: any = {
    eye: [0, 0, 10000],
    lookAt: [0, 0, 0],
    up: [0, 1, 0],
    getEye: () => [...camera.eye],
    getLookAt: () => [...camera.lookAt],
    getUp: () => [...camera.up],
    getFovyRadians: () => Math.PI / 4,
    getFar: () => 1e7,
    resize: jest.fn(),
  };
  camera.resetCamera = jest.fn((up: number[], lookAt: number[], eye: number[]) => {
    camera.up = [...up];
    camera.lookAt = [...lookAt];
    camera.eye = [...eye];
  });
  // autk-map's own reset, which puts the camera 10,000 units above the origin.
  const ownReset = jest.fn();
  return {
    camera,
    ownReset,
    renderer: { pixelWidth: 960, pixelHeight: 600 },
    canvas: { offsetWidth: 960, offsetHeight: 600 },
    // What its layers drew: 100 by 50 world units from the origin.
    layerManager: { layers: [{ position: new Float32Array([0, 0, 100, 50]), _dimension: 2 }], hasOrigin: true, origin },
    resetCamera: ownReset,
    requestRender: jest.fn(),
    updateRenderInfo: jest.fn(),
    destroy: jest.fn(),
  };
}

test("the map keeps the view it was zoomed to when an edit draws it again, a Remove at the layer's edge included, and after Commit edits", async () => {
  // Each draw makes a new map. A Remove at the layer's edge moves the middle
  // of the layer autk-map draws relative to: from the second map on, the
  // origin is 10 units east of the first's, and the camera moves with it.
  const origins = [[1000, 2000], [1010, 2000], [1010, 2000]];
  let made = 0;
  drawnMaps.make = () => fakeMap(origins[Math.min(made++, origins.length - 1)]);
  const canvas = mountCanvas();
  await canvas.playMap();
  // The first draw frames the layers.
  const first = grammarRuns[0].maps[0];
  expect(first.camera.resetCamera).toHaveBeenCalledTimes(1);
  expect(first.camera.resetCamera.mock.calls[0][1]).toEqual([50, 25, 0]);
  // The person zooms in.
  first.camera.lookAt = [120, -40, 0];
  first.camera.eye = [120, -40, 300];

  await openAction("remove");
  pickOnMap([1]);
  await waitFor(() => expect(screen.getByTestId("interaction-remove-picked")).toHaveTextContent("Remove 1 area"));
  fireEvent.click(screen.getByTestId("interaction-remove-picked"));
  await waitFor(() => expect(grammarRuns).toHaveLength(2));
  await waitFor(() => expect(grammarRuns[1].maps[0].camera.resetCamera).toHaveBeenCalled());
  const second = grammarRuns[1].maps[0];
  // Put back on the same ground, moved with the origin, not framed again.
  expect(second.camera.resetCamera).toHaveBeenCalledTimes(1);
  expect(second.camera.resetCamera).toHaveBeenCalledWith([0, 1, 0], [110, -40, 0], [110, -40, 300]);
  expect(second.ownReset).not.toHaveBeenCalled();

  // Commit edits: the node's run hands the map a new output, and the map's
  // own run draws it, where it was.
  canvas.feedMap({ path: "art-interaction-2", dataType: "outputs" });
  await canvas.playMap();
  await waitFor(() => expect(grammarRuns).toHaveLength(3));
  const third = grammarRuns[2].maps[0];
  expect(third.camera.resetCamera).toHaveBeenLastCalledWith([0, 1, 0], [110, -40, 0], [110, -40, 300]);
  expect(third.camera.getLookAt()).toEqual([110, -40, 0]);
  expect(third.ownReset).not.toHaveBeenCalled();
});

/** How many pixels wide and tall each map canvas is while it is on the page. */
const SIZE = 400;

/**
 * jsdom lays nothing out: each map canvas measures SIZE pixels square, at the
 * page's top left corner, while it is on the page, and nothing once it left
 * it, as a browser measures one. Returns what puts jsdom's measures back.
 */
function layOutCanvases(): () => void {
  const canvases = HTMLCanvasElement.prototype as any;
  const side = (canvas: HTMLCanvasElement) => (canvas.isConnected ? SIZE : 0);
  Object.defineProperty(canvases, "offsetWidth", { configurable: true, get() { return side(this); } });
  Object.defineProperty(canvases, "offsetHeight", { configurable: true, get() { return side(this); } });
  canvases.getBoundingClientRect = function (this: HTMLCanvasElement) {
    const s = side(this);
    return { x: 0, y: 0, left: 0, top: 0, right: s, bottom: s, width: s, height: s, toJSON: () => ({}) };
  };
  return () => {
    delete canvases.offsetWidth;
    delete canvases.offsetHeight;
    delete canvases.getBoundingClientRect;
  };
}

/**
 * A map as autk-map draws it, on the canvas its run made, looking straight
 * down on World Mercator metres: its origin at the canvas's bottom left
 * corner, a kilometre to a pixel. Destroyed, it keeps its camera, and its
 * renderer the canvas's size as it was laid out, as autk-map's map does.
 *
 * A layer loaded from a collection is added last to its layers, with its id,
 * type and features, and a layer removed leaves them; the positions skipped
 * in each layer are kept by its id, each toggled as autk-map's vector layers
 * do, until the layer's are cleared.
 */
function projectingMap() {
  const span = SIZE * 1000;
  const layers: any[] = [{ position: new Float32Array([0, 0, 100, 50]), _dimension: 2 }];
  const skipped: Record<string, number[]> = {};
  const camera: any = {
    eye: [span / 2, span / 2, 10000],
    lookAt: [span / 2, span / 2, 0],
    up: [0, 1, 0],
    getEye: () => [...camera.eye],
    getLookAt: () => [...camera.lookAt],
    getUp: () => [...camera.up],
    getFovyRadians: () => Math.PI / 4,
    getFar: () => 1e7,
    resize: jest.fn(),
    // Clip space, column by column: the span across, from -1 to 1, both ways.
    getViewProjectionMatrix: () => [2 / span, 0, 0, 0, 0, 2 / span, 0, 0, 0, 0, 1, 0, -1, -1, 0, 1],
    // From the eye to the ground under a point of the canvas, at x and y from 0 to 1 from its bottom left.
    getWorldRayDirection: (x: number, y: number) => [x * span - camera.eye[0], y * span - camera.eye[1], -camera.eye[2]],
  };
  camera.resetCamera = jest.fn((up: number[], lookAt: number[], eye: number[]) => {
    camera.up = [...up];
    camera.lookAt = [...lookAt];
    camera.eye = [...eye];
  });
  return {
    camera,
    canvas: document.getElementById(`autk-grammar-map-${MAP}`),
    renderer: { pixelWidth: SIZE, pixelHeight: SIZE, cssWidth: SIZE, cssHeight: SIZE },
    layerManager: { layers, hasOrigin: true, origin: [0, 0] },
    // autk-map's highlight, #5dade2.
    style: { getHighlightColor: () => ({ r: 93, g: 173, b: 226 }) },
    loadCollection: jest.fn((id: string, { collection, type }: { collection: { features: any[] }; type?: string }) => {
      layers.push({ layerInfo: { id, typeLayer: type }, layerRenderInfo: {}, features: collection.features });
    }),
    removeLayer: jest.fn((id: string) => {
      const at = layers.findIndex((layer) => layer.layerInfo?.id === id);
      if (at >= 0) layers.splice(at, 1);
    }),
    setSkippedIds: jest.fn((id: string, positions: number[]) => {
      const now = new Set(skipped[id] ?? []);
      for (const position of positions) {
        if (now.has(position)) now.delete(position);
        else now.add(position);
      }
      skipped[id] = [...now].sort((a, b) => a - b);
    }),
    clearSkippedIds: jest.fn((id: string) => {
      skipped[id] = [];
    }),
    skipped,
    resetCamera: jest.fn(),
    requestRender: jest.fn(),
    updateRenderInfo: jest.fn(),
    destroy: jest.fn(),
  };
}

/** The layers loaded into *map* besides its document's: each with its id, type and features. */
const loadedLayers = (map: any): any[] => map.layerManager.layers.filter((layer: any) => layer.layerInfo);

/** The positions of the points *map*'s loaded points layers draw. */
const pointsOn = (map: any): number[][] =>
  loadedLayers(map)
    .filter((layer) => layer.layerInfo.typeLayer === "points")
    .flatMap((layer) => layer.features.map((feature: any) => feature.geometry.coordinates));

/** The lines *map*'s loaded line and area layers draw: each line's points, and each area's outer ring. */
const linesOn = (map: any): number[][][] =>
  loadedLayers(map)
    .filter((layer) => layer.layerInfo.typeLayer === "polylines" || layer.layerInfo.typeLayer === "polygons")
    .flatMap((layer) => layer.features.map((feature: any) => (feature.geometry.type === "Polygon" ? feature.geometry.coordinates[0] : feature.geometry.coordinates)));

/** A position in World Mercator metres, in whole kilometres: the map's own pixels here (a -0 read as 0). */
const km = (xy: readonly number[]) => xy.map((v) => Math.round(v / 1000) || 0);

/** Positions in the order of their x, then their y. */
const byPlace = (a: number[], b: number[]) => a[0] - b[0] || a[1] - b[1];

/** The map the stand-in grammar drew last. */
const lastMap = () => grammarRuns[grammarRuns.length - 1].maps[0];

/** What the overlay holds over the map but its tip and buttons: nothing, since the map draws the tools. */
const drawnOverMap = () =>
  Array.from(screen.getByTestId("map-edit-overlay").children).filter((child) => !child.hasAttribute("data-map-edit-ui"));

/** The middles of buildings 136 and 200, in degrees. */
const MIDDLE_136: [number, number] = [1.5, 0.5];
const MIDDLE_200: [number, number] = [2.5, 0.5];

/**
 * A click on the map where it draws *lonLat*, with *shift* a shift-click: a
 * press and a release in place on the map's canvas, as a person makes one,
 * which the overlay a linked Map Edits node lends the map hears.
 */
function clickMap(lonLat: [number, number], shift = false) {
  const canvas = document.getElementById(`autk-grammar-map-${MAP}`) as HTMLCanvasElement;
  const [x, y] = toMercator(lonLat);
  const at = { bubbles: true, cancelable: true, button: 0, shiftKey: shift, clientX: Math.round(x / 1000), clientY: Math.round(SIZE - y / 1000) };
  act(() => {
    canvas.dispatchEvent(new MouseEvent("pointerdown", { ...at, buttons: 1 }));
    canvas.dispatchEvent(new MouseEvent("pointerup", { ...at, buttons: 0 }));
  });
}

/**
 * One step of a drag on the map: a press, a move or a release on the map's
 * canvas at *xy*, in the map's own pixels, the main button held while *held*.
 */
function pointerOnMap(type: "pointerdown" | "pointermove" | "pointerup", [x, y]: [number, number], held: boolean) {
  const canvas = document.getElementById(`autk-grammar-map-${MAP}`) as HTMLCanvasElement;
  act(() => {
    canvas.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, button: 0, buttons: held ? 1 : 0, clientX: x, clientY: y }));
  });
}

test("a building picked in Edit, clicked again in Remove while the map draws the Apply, is picked again, and a shift-click adds one and drops it", async () => {
  const putBack = layOutCanvases();
  let release = () => {};
  try {
    drawnMaps.make = projectingMap;
    const canvas = mountCanvas();
    await canvas.playMap();
    const remove = () => screen.getByTestId("interaction-remove-picked");

    // Edit: a click on building 136 picks it, before any edit.
    await openAction("edit");
    const drawnFirst = document.getElementById(`autk-grammar-map-${MAP}`);
    clickMap(MIDDLE_136);
    const height = (await screen.findByTestId("interaction-field-height")) as HTMLInputElement;
    expect(height.value).toBe("20");

    // An Apply: the map draws the edit again, on a canvas of its own, and the
    // first one leaves the page. The test holds that draw under way.
    heldDraws.until = new Promise<void>((resolve) => {
      release = () => resolve();
    });
    fireEvent.change(height, { target: { value: "99" } });
    fireEvent.click(screen.getByTestId("interaction-form-submit"));
    await waitFor(() => expect(grammarRuns).toHaveLength(2));
    expect(drawnFirst?.isConnected).toBe(false);

    // Back, then Remove: the new action starts with nothing picked, and a
    // click on the same building, while the map still draws, picks it again,
    // as the map's selection over the interaction edge.
    fireEvent.click(screen.getByTestId("interaction-back"));
    fireEvent.click(screen.getByTestId("interaction-action-remove"));
    expect(remove()).toBeDisabled();
    clickMap(MIDDLE_136);
    await waitFor(() => expect(remove()).toHaveTextContent("Remove 1 area"));
    const [selection] = canvas.interactionsOf(NODE);
    expect(selection.nodeId).toBe(MAP);
    expect(selection.details.autk_selection.data).toEqual([{ building_id: 136 }]);

    // The draw ends: the pick stays, and the new map lights it up.
    await act(async () => {
      release();
    });
    await waitFor(() => expect(litUp()).toEqual([1]));
    expect(remove()).toHaveTextContent("Remove 1 area");

    // A shift-click on building 200 adds it, and another drops it.
    clickMap(MIDDLE_200, true);
    await waitFor(() => expect(remove()).toHaveTextContent("Remove 2 areas"));
    clickMap(MIDDLE_200, true);
    await waitFor(() => expect(remove()).toHaveTextContent("Remove 1 area"));
    fireEvent.click(remove());
    expect(canvas.settings()?.edits).toEqual([
      { op: "set", ids: [136], column: "height", value: 99 },
      { op: "remove", ids: [136] },
    ]);
  } finally {
    release();
    putBack();
  }
});

/**
 * Building 119 in one part, building 136 in two side by side, as an OSM
 * building of several parts is, both its rows holding its id, then building
 * 200: positions 0, 1 and 2, and 3.
 */
const PARTED = {
  type: "FeatureCollection",
  features: [
    [119, 0, 1],
    [136, 1, 1.5],
    [136, 1.5, 2],
    [200, 2, 3],
  ].map(([id, west, east], i) => ({
    type: "Feature",
    geometry: { type: "Polygon", coordinates: [[[west, 0], [east, 0], [east, 1], [west, 1], [west, 0]]] },
    properties: { building_id: id, height: 10 * (i + 1) },
  })),
};

/** The middles of building 119, of building 136's first part, and of building 200, in degrees. */
const MIDDLE_ONE_PART: [number, number] = [0.5, 0.5];
const MIDDLE_FIRST_PART: [number, number] = [1.25, 0.5];
const MIDDLE_LAST: [number, number] = [2.5, 0.5];

/** What the map lights is Autark's own highlight: nothing is drawn over the map for a pick. */
const outlinesOverMap = () =>
  document.querySelectorAll('[data-testid="map-edit-overlay"] svg path, [data-testid="map-edit-overlay"] svg circle').length;

test("picks of a building in two parts and of others are lit by the map alone, and a plain click replaces the pick", async () => {
  const putBack = layOutCanvases();
  try {
    nodeInput.current = PARTED;
    drawnMaps.make = projectingMap;
    const canvas = mountCanvas();
    await canvas.playMap();
    const remove = () => screen.getByTestId("interaction-remove-picked");
    await openAction("remove");

    // A click on building 136 picks it: the map lights both its parts.
    clickMap(MIDDLE_FIRST_PART);
    await waitFor(() => expect(remove()).toHaveTextContent("Remove 1 area"));
    await waitFor(() => expect(litUp()).toEqual([1, 2]));
    expect(outlinesOverMap()).toBe(0);

    // A shift-click adds building 119, listed before it.
    clickMap(MIDDLE_ONE_PART, true);
    await waitFor(() => expect(remove()).toHaveTextContent("Remove 2 areas"));
    await waitFor(() => expect(litUp()).toEqual([0, 1, 2]));
    expect(outlinesOverMap()).toBe(0);

    // A plain click on building 200 replaces the pick.
    clickMap(MIDDLE_LAST);
    await waitFor(() => expect(remove()).toHaveTextContent("Remove 1 area"));
    await waitFor(() => expect(litUp()).toEqual([3]));
    expect(canvas.interactionsOf(NODE)[0].details.autk_selection.data).toEqual([{ building_id: 200 }]);
    expect(outlinesOverMap()).toBe(0);
  } finally {
    putBack();
  }
});

test("a play of the map drops the pick made on it, and after an Apply lights nothing just edited", async () => {
  const putBack = layOutCanvases();
  try {
    nodeInput.current = PARTED;
    drawnMaps.make = projectingMap;
    const canvas = mountCanvas();
    await canvas.playMap();
    const remove = () => screen.getByTestId("interaction-remove-picked");

    // Remove: a click picks building 136, which the map lights.
    await openAction("remove");
    clickMap(MIDDLE_FIRST_PART);
    await waitFor(() => expect(remove()).toHaveTextContent("Remove 1 area"));
    await waitFor(() => expect(litUp()).toEqual([1, 2]));

    // Played, the map draws anew without the pick it made, and the node
    // picks nothing either.
    await canvas.playMap();
    await waitFor(() => expect(remove()).toBeDisabled());
    await waitFor(() => expect(litUp()).toEqual([]));

    // Edit: a click picks building 136 again and a height is applied, which
    // the map draws as a preview, keeping the pick to edit again.
    fireEvent.click(screen.getByTestId("interaction-back"));
    fireEvent.click(screen.getByTestId("interaction-action-edit"));
    clickMap(MIDDLE_FIRST_PART);
    const height = (await screen.findByTestId("interaction-field-height")) as HTMLInputElement;
    const drawn = grammarRuns.length;
    fireEvent.change(height, { target: { value: "99" } });
    fireEvent.click(screen.getByTestId("interaction-form-submit"));
    await waitFor(() => expect(canvas.settings()?.edits).toEqual([{ op: "set", ids: [136], column: "height", value: 99 }]));
    await waitFor(() => expect(grammarRuns).toHaveLength(drawn + 1));
    await waitFor(() => expect(litUp()).toEqual([1, 2]));

    // Played again: nothing is picked, and what was just edited is not lit.
    await canvas.playMap();
    await waitFor(() => expect(litUp()).toEqual([]));
    await waitFor(() => expect(screen.queryByTestId("interaction-field-height")).toBeNull());
  } finally {
    putBack();
  }
});

test("an action makes the layer it works on the layer the map picks on, with Show only this layer off", async () => {
  const putBack = layOutCanvases();
  try {
    nodeInput.current = PARTED;
    drawnMaps.make = projectingMap;
    const canvas = mountCanvas();
    await canvas.playMap();
    const map = grammarRuns[grammarRuns.length - 1].maps[0];

    await openAction("remove");
    await waitFor(() => expect(map.updateRenderInfo).toHaveBeenCalledWith("input_0", { isPick: true }));
  } finally {
    putBack();
  }
});

test("Add on a layer of areas draws the shape being drawn and its corners as layers of the Autark map, and Escape takes them off", async () => {
  const putBack = layOutCanvases();
  try {
    drawnMaps.make = projectingMap;
    await mountCanvas().playMap();
    const map = lastMap();
    await openAction("add");
    await waitFor(() => expect(screen.getByTestId("map-edit-overlay")).toHaveAttribute("data-edit-mode", "draw"));

    // Three clicks: the map draws the line so far through them, and their corners.
    const clicked: [number, number][] = [[0.5, 1.5], [1.5, 1.5], [1.5, 2.5]];
    for (const corner of clicked) clickMap(corner);
    const corners = clicked.map((corner) => km(toMercator(corner)));
    await waitFor(() => expect(pointsOn(map).map(km).sort(byPlace)).toEqual([...corners].sort(byPlace)));
    expect(linesOn(map).map((line) => line.map(km))).toContainEqual(corners);
    expect(drawnOverMap()).toEqual([]);

    // Escape gives the shape up: the map draws none of the tools.
    fireEvent.keyDown(document.body, { key: "Escape" });
    await waitFor(() => expect(loadedLayers(map)).toEqual([]));
  } finally {
    putBack();
  }
});

test("Move points draws a building's corners, midpoints and shape as layers of the map, skipped in its own layer, and a drag from a corner reshapes it", async () => {
  const putBack = layOutCanvases();
  try {
    drawnMaps.make = projectingMap;
    const canvas = mountCanvas();
    await canvas.playMap();
    await openAction("edit");
    clickMap(MIDDLE_136);
    fireEvent.click(await screen.findByTestId("interaction-reshape"));
    const map = lastMap();
    const overlay = () => screen.getByTestId("map-edit-overlay");
    await waitFor(() => expect(overlay()).toHaveAttribute("data-edit-mode", "reshape"));

    // Building 136's corners and midpoints are points the map draws, in its
    // highlight, and its outline a line, while its own layer skips it: drawn
    // second, at position 1.
    const corners: [number, number][] = [[1, 0], [2, 0], [2, 1], [1, 1]];
    const midpoints: [number, number][] = [[1.5, 0], [2, 0.5], [1.5, 1], [1, 0.5]];
    const handles = [...corners, ...midpoints].map((xy) => km(toMercator(xy))).sort(byPlace);
    await waitFor(() => expect(pointsOn(map).map(km).sort(byPlace)).toEqual(handles));
    const ring = [...corners, corners[0]].map((xy) => km(toMercator(xy)));
    expect(linesOn(map).map((line) => line.map(km))).toContainEqual(ring);
    expect(map.skipped.input_0).toEqual([1]);
    expect(map.updateRenderInfo).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ color: { r: 93, g: 173, b: 226 } }));
    expect(drawnOverMap()).toEqual([]);

    // The overlay lists the corners where the map shows them, in the map's own pixels.
    expect(overlay()).toHaveAttribute("data-map-width", String(SIZE));
    expect(overlay()).toHaveAttribute("data-map-height", String(SIZE));
    const listed = JSON.parse(overlay().getAttribute("data-corners") ?? "[]");
    expect(listed.map((c: any) => [c.ring, c.index])).toEqual([[0, 0], [0, 1], [0, 2], [0, 3]]);
    const [cx, cy] = toMercator([2, 1]);
    expect(listed[2].x).toBeCloseTo(cx / 1000, 0);
    expect(listed[2].y).toBeCloseTo(SIZE - cy / 1000, 0);

    // A drag from that corner: while it lasts, the map draws the building
    // with the corner moved, and its layer still skips it.
    const from: [number, number] = [Math.round(listed[2].x), Math.round(listed[2].y)];
    const to: [number, number] = [from[0] + 20, from[1] - 15];
    const moved = [...ring];
    moved[2] = [to[0], SIZE - to[1]];
    pointerOnMap("pointerdown", from, true);
    pointerOnMap("pointermove", to, true);
    await waitFor(() => expect(linesOn(map).map((line) => line.map(km))).toContainEqual(moved));
    expect(map.skipped.input_0).toEqual([1]);
    expect(canvas.settings()?.edits ?? []).toEqual([]);

    // Let go: the reshape is an edit, and the map drawn with it skips the
    // building in its layer again while Move points is on.
    const drawn = grammarRuns.length;
    pointerOnMap("pointerup", to, false);
    const edits = canvas.settings()?.edits ?? [];
    expect(edits).toEqual([expect.objectContaining({ op: "geometry", ids: [136] })]);
    expect((edits[0] as any).geometry.coordinates[0].map((xy: [number, number]) => km(toMercator(xy)))).toEqual(moved);
    await waitFor(() => expect(grammarRuns).toHaveLength(drawn + 1));
    const next = lastMap();
    await waitFor(() => expect(pointsOn(next).map(km)).toContainEqual(moved[2]));
    expect(next.skipped.input_0).toEqual([1]);

    // Done: the tools leave the map, and the building is drawn by its layer again.
    fireEvent.click(screen.getByTestId("map-edit-done"));
    await waitFor(() => expect(loadedLayers(next)).toEqual([]));
    expect(next.skipped.input_0).toEqual([]);
    expect(overlay()).toHaveAttribute("data-corners", "[]");
  } finally {
    putBack();
  }
});

test("the overlay draws nothing over the map in any mode: picking, drawing, reshaping and moving", async () => {
  const putBack = layOutCanvases();
  try {
    drawnMaps.make = projectingMap;
    await mountCanvas().playMap();
    const inMode = async (mode: string) => {
      await waitFor(() => expect(screen.getByTestId("map-edit-overlay")).toHaveAttribute("data-edit-mode", mode));
      expect(drawnOverMap()).toEqual([]);
    };

    // Remove: building 136 picked.
    await openAction("remove");
    clickMap(MIDDLE_136);
    await waitFor(() => expect(screen.getByTestId("interaction-remove-picked")).toHaveTextContent("Remove 1 area"));
    await inMode("select");

    // Add: an area being drawn.
    fireEvent.click(screen.getByTestId("interaction-back"));
    fireEvent.click(screen.getByTestId("interaction-action-add"));
    clickMap([0.5, 1.5]);
    clickMap([1.5, 1.5]);
    await inMode("draw");
    fireEvent.keyDown(document.body, { key: "Escape" });

    // Edit: building 136 picked, then reshaped and moved.
    fireEvent.click(screen.getByTestId("interaction-back"));
    fireEvent.click(screen.getByTestId("interaction-action-edit"));
    clickMap(MIDDLE_136);
    fireEvent.click(await screen.findByTestId("interaction-reshape"));
    await inMode("reshape");
    fireEvent.click(screen.getByTestId("interaction-move"));
    await inMode("move");
  } finally {
    putBack();
  }
});
