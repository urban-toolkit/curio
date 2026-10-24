/**
 * The Map Editor node (`curio.builtin/edit-features`) and the Autark map it
 * edits on, wired as the node's guide wires them: a loader feeds the node on a
 * data edge, the node feeds the map on a data edge, and an interaction edge
 * joins the node and the map. Each node is the behavior the canvas registers
 * for its type (registry/builtinBehaviors), with the node's own state
 * (hook/useNodeState) as UniversalNode gives it; the map draws with the
 * stand-in grammar of _support/autkNodeMocks.
 *
 * What a person sees: a run's code put back from the Provenance drawer brings
 * back that run's edits, in the node's panel and on the map; an edit leaves
 * the dataflow Unsaved; the map's redraw for an edit before Commit edits is
 * no run of the map and hands nothing on; a property added to a new layer is
 * one of the layer's properties; and the log says its edits are committed
 * only once the nodes below ran with them.
 */
import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { NodeBehaviorData, UseNodeStateReturn } from "../../../registry/types";

// The flow, as a canvas that keeps what its nodes write.
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
// Its editor, as the editor suites mount it.
jest.mock("@monaco-editor/react", () => ({
  __esModule: true,
  default: ({ value }: any) => <textarea data-testid="monaco" value={value ?? ""} readOnly />,
}));
jest.mock("../../../providers/CollaborationProvider", () => ({
  useCollab: () => ({
    enabled: false,
    connected: false,
    users: [],
    proposals: [],
    currentUserId: null,
    requestCodeChange: jest.fn(),
    approveCodeChange: jest.fn(),
    rejectCodeChange: jest.fn(),
    onRemote: jest.fn(() => jest.fn()),
  }),
}));
jest.mock("../../../components/editing/WidgetsEditor", () => ({ __esModule: true, default: () => null }));

import { useEditFeaturesBehavior } from "../../../adapters/node/editFeaturesBehavior";
import { useAutkViewBehavior } from "../../../adapters/node/autkViewBehavior";
import NodeEditor from "../../../components/editing/NodeEditor";
import { useNodeState } from "../../../hook/useNodeState";
import ProvenanceProvider, { useProvenanceContext, type NodeExecRecord } from "../../../providers/ProvenanceProvider";
import { ProvenanceDrawerContext, type NodeProvenanceTarget } from "../../../providers/provenanceDrawerContext";
import { editFeaturesCode, normalizeEditFeatures, readEditFeaturesCode, type EditFeaturesSettings } from "../../../utils/editFeatures/editFeatures";
import { grammarRuns, nodeInput, resetAutkNodeMocks } from "../../_support/autkNodeMocks";
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

/** Buildings 119 and 136, which the log removes, and 200, which no edit touches. */
const BUILDINGS = {
  type: "FeatureCollection",
  features: [119, 136, 200].map((id, i) => ({
    type: "Feature",
    geometry: { type: "Polygon", coordinates: [[[i, 0], [i + 1, 0], [i + 1, 1], [i, 1], [i, 0]]] },
    properties: { building_id: id, height: 10 * (i + 1) },
  })),
};

/** Two removals on the node's layer, as the node writes them when a person removes each on the map. */
const TWO_REMOVALS: EditFeaturesSettings = {
  layer: "input_0",
  key: "building_id",
  edits: [
    { op: "remove", ids: [119] },
    { op: "remove", ids: [136] },
  ],
};

const EDGES = [
  { id: "data-in", source: LOADER, target: NODE, sourceHandle: "out", targetHandle: "in" },
  { id: "data-out", source: NODE, target: MAP, sourceHandle: "out", targetHandle: "in" },
  { id: "link", source: NODE, target: MAP, sourceHandle: "in/out", targetHandle: "in/out", type: "BIDIRECTIONAL_EDGE" },
];

/** What the map hands to the nodes it feeds. */
const mockOutputCallback = jest.fn();

/**
 * The Map Editor node as UniversalNode mounts it: its state, its behavior,
 * and, with *editor*, its editor, whose output pane holds the body.
 */
function InteractionNode({ editor }: { editor: boolean }) {
  const data = React.useContext(mockFlowContext).nodes.find((n: any) => n.id === NODE).data;
  const nodeState = useNodeState(data, EDIT_FEATURES);
  const behavior = useEditFeaturesBehavior(data as NodeBehaviorData, nodeState as UseNodeStateReturn);
  if (!editor) return <>{behavior.contentComponent}</>;
  return (
    <NodeEditor
      setSendCodeCallback={nodeState.setSendCodeCallback}
      code={true}
      grammar={false}
      widgets={false}
      setOutputCallback={nodeState.setOutput}
      data={data}
      output={nodeState.output as any}
      nodeType={EDIT_FEATURES}
      readOnly={false}
      defaultValue={behavior.defaultValueOverride ?? data.defaultCode}
      floatCode={nodeState.setCode}
      contentComponent={behavior.contentComponent}
    />
  );
}

/** The Autark map as the canvas registers it; *play* is its play. */
function MapNode({ play }: { play: { current: (spec: string) => Promise<void> } }) {
  const data = React.useContext(mockFlowContext).nodes.find((n: any) => n.id === MAP).data;
  const state = React.useRef({ output: { code: "", content: "" }, setOutput: jest.fn(), code: MAP_SPEC, setCode: jest.fn(), templateData: {} }).current;
  const behavior = useAutkViewBehavior(data as NodeBehaviorData, state as unknown as UseNodeStateReturn);
  play.current = behavior.applyGrammar as (spec: string) => Promise<void>;
  return <>{behavior.contentComponent}</>;
}

function ProvenanceProbe({ into }: { into: { current: ReturnType<typeof useProvenanceContext> | null } }) {
  into.current = useProvenanceContext();
  return null;
}

/**
 * The canvas: the node holding *editFeatures*, in its settings and in its code
 * as the node writes them, the nodes' run states *status*, and, with *map*,
 * the map mounted too.
 */
function mountCanvas({
  editFeatures,
  status = {},
  map = false,
  editor = false,
}: { editFeatures?: EditFeaturesSettings; status?: Record<string, string>; map?: boolean; editor?: boolean } = {}) {
  const settings = normalizeEditFeatures(editFeatures);
  const code = editFeaturesCode(settings, 1);
  const seed: Record<string, any> = {
    [LOADER]: { nodeId: LOADER, title: "Buildings" },
    [NODE]: { nodeId: NODE, input: LOADED, editFeatures: settings, code, defaultCode: code },
    [MAP]: { nodeId: MAP, title: "Downtown map", input: COMMITTED, code: MAP_SPEC, defaultCode: MAP_SPEC, outputCallback: mockOutputCallback, interactionsCallback: jest.fn() },
  };
  const latest = { current: seed };
  const markDirty = jest.fn();
  const fns = { markNodeStale: jest.fn(), markNodeErrored: jest.fn(), clearSelectionTagsOf: jest.fn(), runDownstream: jest.fn(), requestAutoRun: jest.fn() };
  const openNodeProvenance = jest.fn<void, [NodeProvenanceTarget]>();
  const drawer = { openDataflowProvenance: jest.fn(), openNodeProvenance, closeProvenance: jest.fn(), isProvenanceOpen: false };
  const provenance: { current: ReturnType<typeof useProvenanceContext> | null } = { current: null };
  const play: { current: (spec: string) => Promise<void> } = { current: async () => {} };

  function Canvas({ children }: { children: React.ReactNode }) {
    const [data, setData] = React.useState<Record<string, any>>(seed);
    latest.current = data;
    const flow = {
      nodes: [
        { id: LOADER, type: "curio.builtin/data-loading", data: data[LOADER] },
        { id: NODE, type: EDIT_FEATURES, data: data[NODE] },
        { id: MAP, type: "curio.builtin/autk-grammar", data: data[MAP] },
      ],
      edges: EDGES,
      nodeExecStatus: status,
      dashboardOn: false,
      scenarios: [],
      workflowNameRef: { current: "Downtown edits" },
      updateDataNode: (id: string, next: any) => setData((prev) => ({ ...prev, [id]: { ...next } })),
      markDirty,
      ...fns,
    };
    return <mockFlowContext.Provider value={flow}>{children}</mockFlowContext.Provider>;
  }

  render(
    <ProvenanceProvider>
      <ProvenanceProbe into={provenance} />
      <ProvenanceDrawerContext.Provider value={drawer}>
        <Canvas>
          <div data-testid="interaction-node">
            <InteractionNode editor={editor} />
          </div>
          {map ? <MapNode play={play} /> : null}
        </Canvas>
      </ProvenanceDrawerContext.Provider>
    </ProvenanceProvider>,
  );
  return {
    /** The node's settings as its code holds them, its only state. */
    settings: (): EditFeaturesSettings | undefined => {
      const read = readEditFeaturesCode(latest.current[NODE].code);
      return "problem" in read ? undefined : read.settings;
    },
    markDirty,
    openNodeProvenance,
    /** The map's play: its document run, to the end of the run. */
    playMap: async () => {
      await act(async () => {
        await play.current(MAP_SPEC);
      });
    },
    /** The runs the Provenance drawer lists for *nodeId*. */
    runsOf: (nodeId: string): NodeExecRecord[] => provenance.current?.getAllNodeProvenance()[nodeId] ?? [],
  };
}

/**
 * Whether the Map Editor node's panel says building *id* is removed: an
 * element whose own text names it after "Remove", whatever the markup.
 */
function saysRemoved(id: number): boolean {
  const says = new RegExp(`\\bremov(e|ed|es)\\b[^]*\\b${id}\\b`, "i");
  return Array.from(screen.getByTestId("interaction-node").querySelectorAll("*")).some(
    (element) =>
      says.test(element.textContent ?? "")
      && Array.from(element.children).every((child) => !says.test(child.textContent ?? "")),
  );
}

/** The features the map handed its grammar to draw at its last draw, every layer's. */
function drawnFeatures(): any[] {
  const run = grammarRuns[grammarRuns.length - 1];
  return (run?.spec?.data ?? []).flatMap((source: any) => source?.geojsonObject?.features ?? []);
}

const drawnIds = () => drawnFeatures().map((feature) => feature?.properties?.building_id);

/** One edit through the node's forms: a property added to the node's layer. */
async function addProperty(name: string, value: string) {
  fireEvent.click(await screen.findByTestId("interaction-layer-input_0"));
  fireEvent.click(screen.getByTestId("interaction-action-property"));
  fireEvent.change(screen.getByTestId("interaction-property-name"), { target: { value: name } });
  fireEvent.change(screen.getByTestId("interaction-property-value"), { target: { value } });
  fireEvent.click(screen.getByTestId("interaction-property-add"));
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

test("a put-back restores the edits in the panel and on the map", async () => {
  const canvas = mountCanvas({ editFeatures: TWO_REMOVALS, map: true, editor: true });
  // The panel lists both removals, and the map's play draws the layer without both.
  await screen.findByTestId("interaction-layer-input_0");
  expect(saysRemoved(119)).toBe(true);
  expect(saysRemoved(136)).toBe(true);
  await canvas.playMap();
  expect(drawnIds()).toEqual([200]);

  // A run that made only the first removal, put back in the node as the
  // Provenance drawer's "Put this code back in the node" does: the drawer
  // calls the restore its pill handed it.
  const firstRun = editFeaturesCode({ ...TWO_REMOVALS, edits: [TWO_REMOVALS.edits![0]] }, 1);
  await act(async () => {
    fireEvent.click(document.querySelector('[data-rr-ui-event-key="provenance"]') as HTMLElement);
  });
  const { restore } = canvas.openNodeProvenance.mock.calls[0][0];
  await act(async () => {
    restore(firstRun);
  });

  // The node's edits are that run's: the panel lists the first removal only,
  // and the map draws the layer without its building only.
  await waitFor(() => {
    expect(saysRemoved(119)).toBe(true);
    expect(saysRemoved(136)).toBe(false);
  });
  await waitFor(() => expect(drawnIds()).toEqual([136, 200]));
});

test("an edit marks the dataflow Unsaved", async () => {
  const canvas = mountCanvas();
  await addProperty("kind", "office");
  // The edit is the node's...
  expect(canvas.settings()?.edits).toEqual([{ op: "add_column", column: "kind", value: "office" }]);
  // ...and the dataflow has a change to save.
  expect(canvas.markDirty).toHaveBeenCalled();
});

test("a preview redraw files no map run and hands nothing on", async () => {
  const canvas = mountCanvas({ map: true });
  await canvas.playMap();
  // The play is a run of the map: filed, and handed on.
  expect(canvas.runsOf(MAP)).toHaveLength(1);
  expect(mockOutputCallback).toHaveBeenCalledTimes(1);
  mockOutputCallback.mockClear();

  await addProperty("kind", "office");
  // The map draws the edit at once, before Commit edits...
  await waitFor(() => expect(grammarRuns).toHaveLength(2));
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 50));
  });
  expect(drawnFeatures().map((feature) => feature.properties.kind)).toEqual(["office", "office", "office"]);
  // ...and that draw is a preview: no run in the map's Provenance, and
  // nothing for the nodes below until Commit edits runs them.
  expect(canvas.runsOf(MAP)).toHaveLength(1);
  expect(mockOutputCallback).not.toHaveBeenCalled();
});

test("Add a property on a new layer keeps its definition", async () => {
  const canvas = mountCanvas();
  fireEvent.click(await screen.findByTestId("interaction-new-layer-open"));
  fireEvent.change(screen.getByTestId("interaction-new-layer-name"), { target: { value: "cooling_centers" } });
  fireEvent.click(screen.getByTestId("interaction-new-layer-Point"));
  fireEvent.click(screen.getByTestId("interaction-new-layer-create"));
  await waitFor(() => expect(screen.getByTestId("interaction-active-layer")).toHaveAttribute("data-layer", "cooling_centers"));
  fireEvent.click(screen.getByTestId("interaction-back"));

  fireEvent.click(screen.getByTestId("interaction-action-property"));
  fireEvent.change(screen.getByTestId("interaction-property-name"), { target: { value: "kind" } });
  fireEvent.change(screen.getByTestId("interaction-property-value"), { target: { value: "library" } });
  fireEvent.click(screen.getByTestId("interaction-property-add"));

  // The property is in the log, and in the layer's definition, which its
  // next features are asked for.
  const settings = canvas.settings();
  expect(settings?.edits).toContainEqual(expect.objectContaining({ op: "add_column", layer: "cooling_centers", column: "kind" }));
  expect(settings?.newLayers?.[0]?.properties).toContainEqual(expect.objectContaining({ name: "kind", type: "text", default: "library" }));
});

test("Edits committed shows only after the nodes below ran", async () => {
  // The node ran; the map below it never did.
  mountCanvas({ editFeatures: TWO_REMOVALS, status: { [NODE]: "executed" } });
  await screen.findByTestId("interaction-layer-input_0");
  expect(saysRemoved(119)).toBe(true);
  expect(saysRemoved(136)).toBe(true);
  expect(screen.getByTestId("interaction-node")).not.toHaveTextContent(/edits committed/i);
});
