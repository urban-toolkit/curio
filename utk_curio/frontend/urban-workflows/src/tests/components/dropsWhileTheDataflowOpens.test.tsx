/**
 * What is dropped on the canvas while the dataflow its link names is still
 * opening waits for it, then is made by the canvas the dataflow opens as.
 *
 * ProjectLoader fills the canvas once the server answers, and that answer says
 * whose dataflow it is; the dataflow's room names the tab's role apart from
 * it, often first. A drop in that window was made at once: a node on a canvas
 * the load then replaced, and an invited editor's file the owner's way,
 * refused as the dataflow still opening (#1251's e2e met it). Now the drop
 * waits: an owner's until the load is in, an invited editor's until the room
 * has named him too, whichever comes last. A watcher's canvas makes nothing of
 * it, as of any drop there, and a dataflow that cannot be opened says why once.
 *
 * MainCanvas is drawn under the real ProjectLoader, whose load the test holds
 * until it lets it land; React Flow is real, and the canvas's providers, menus
 * and panels are stubbed as in mainCanvasShiftDrag. The file import and the
 * ask of the owner (#1251) are stubbed to say which canvas they were made by:
 * whose dataflow the load said it was, and the role the room named.
 */
import React from "react";
import { act, fireEvent, render, waitFor } from "@testing-library/react";
import { ReactFlowProvider } from "reactflow";

jest.mock("vega", () => ({}), { virtual: true });
jest.mock("vega-lite", () => ({}), { virtual: true });

const mockRouteId = "36363636-1111-4222-8333-000000000036";
let mockFlow: any = null;
let mockCollab: any = {};
const mockShowToast = jest.fn();
const mockCreateCodeNode = jest.fn((_type: string, _options?: unknown) => ({ id: "dropped" }));
const mockLoadTrill = jest.fn(() => ({ nodes: [], edges: [] }));
const mockImport = jest.fn(async (_madeBy: string, _files: string[]) => null);
const mockAsk = jest.fn(async (_madeBy: string, _datasetId: string, _how?: unknown) => true);
const mockMotionHint = { onMoveStart: jest.fn(), onMove: jest.fn(), onMoveEnd: jest.fn() };

jest.mock("react-router-dom", () => ({
  useParams: () => ({ id: mockRouteId }),
  useNavigate: () => jest.fn(),
}));
jest.mock("../../providers/FlowProvider", () => ({ useFlowContext: () => mockFlow }));
jest.mock("../../providers/CollaborationProvider", () => ({ useCollab: () => mockCollab }));
jest.mock("../../providers/packages/PackagePaletteContext", () => ({
  usePackagePalette: () => ({ setActivePackageKey: jest.fn() }),
}));
jest.mock("../../providers/ToastProvider", () => ({ useToastContext: () => ({ showToast: mockShowToast }) }));
jest.mock("../../providers/StarterProvider", () => ({ useStarterContext: () => ({ getStarters: jest.fn() }) }));
jest.mock("../../providers/modelCatalog", () => ({
  useModelCatalogDrawer: () => ({ openModelCatalogDrawer: jest.fn() }),
}));
jest.mock("../../providers/agents", () => ({
  AgentAttachmentsProvider: ({ children }: any) => <>{children}</>,
  useAgentsDataflowId: () => null,
}));
jest.mock("../../providers/packages/useEnsureWorkflowDeps", () => ({ useEnsureWorkflowDeps: () => jest.fn() }));
jest.mock("../../TrillGenerator", () => ({ TrillGenerator: { reset: jest.fn() } }));
jest.mock("../../components/datasets/catalog/datasetDetailsContext", () => ({
  useDatasetDetails: () => ({ openDatasetDetails: jest.fn() }),
  viewDatasetDetailsToast: jest.fn(),
}));
// The canvas's gates as canvasRole draws them: another account's dataflow is
// changed only by an editor the room named, and is read-only meanwhile.
jest.mock("../../hook/useGraphEditGates", () => ({
  useGraphEditGates: () => {
    const edits = mockFlow?.viewerMode !== "shared" || mockCollab?.role === "editor";
    return { connect: edits, drop: edits, delete: edits };
  },
}));
jest.mock("../../hook/useSharedView", () => ({
  useSharedView: () => mockFlow?.viewerMode === "shared" && mockCollab?.role !== "editor",
}));
jest.mock("../../hook/usePosition", () => ({ usePosition: () => ({ getPosition: () => ({ x: 0, y: 0 }) }) }));
jest.mock("../../hook/useRunSelectedNodeShortcut", () => ({ useRunSelectedNodeShortcut: () => undefined }));
jest.mock("../../hook/useViewportMotionHint", () => ({ useViewportMotionHint: () => mockMotionHint }));
jest.mock("../../hook/useCode", () => ({
  useCode: () => ({ createCodeNode: mockCreateCodeNode, loadTrill: mockLoadTrill }),
}));
// The file import, by the canvas that made it: whose dataflow the load said
// it was, and the role the room named.
jest.mock("../../components/datasets/useDataFileImport", () => ({
  hasFileDrag: (dataTransfer: any) => Array.from(dataTransfer?.types || []).includes("Files"),
  useDataFileImport: () => {
    const madeBy = `${mockFlow?.viewerMode ?? "owner"}, ${mockCollab?.role ?? "no role"}`;
    return (files: File[]) => mockImport(madeBy, files.map((file) => file.name));
  },
}));
// The ask of the owner, offered on an invited editor's canvas only.
jest.mock("../../components/datasets/useAskTheOwner", () => ({
  useAskTheOwner: () => {
    if (mockFlow?.viewerMode !== "shared" || mockCollab?.role !== "editor") return null;
    const madeBy = `${mockFlow.viewerMode}, ${mockCollab.role}`;
    return (dataset: any, how?: unknown) => mockAsk(madeBy, dataset.datasetId, how);
  },
}));
jest.mock("../../components/UniversalNode", () => ({
  __esModule: true,
  default: ({ id }: any) => <div data-testid={`node-${id}`} />,
}));
jest.mock("../../components/edges/BiDirectionalEdge", () => ({ __esModule: true, default: () => null }));
jest.mock("../../components/edges/UniDirectionalEdge", () => ({ __esModule: true, default: () => null }));
jest.mock("../../components/VersionBadge", () => ({ __esModule: true, default: () => null }));
jest.mock("../../components/menus", () => ({ ToolsMenu: () => null, UpMenu: () => null }));
jest.mock("../../components/notebook/NotebookRunAll", () => ({ NotebookRunAll: () => null }));
jest.mock("../../components/agents/attach/AgentDockOverlay", () => ({ AgentDockOverlay: () => null }));
jest.mock("../../components/agents/attach/AgentDock", () => ({ AgentDock: () => null }));
jest.mock("../../components/scenarios/useScenarioDrop", () => ({ useScenarioDrop: () => jest.fn() }));
jest.mock("../../components/scenarios/ScenarioLayers", () => ({ BOX_WIDTH: 0, boxLayout: () => ({ height: 0 }) }));
jest.mock("../../components/scenarios/CanvasScenarioLayers", () => ({ CanvasScenarioLayers: () => null }));
// A Data Catalog card's drag, carried here under a type of the test's own.
jest.mock("../../services/datasetCatalog", () => ({
  buildDatasetLoaderNodeOptions: () => ({}),
  buildDatasetWidgetNodeOptions: () => ({}),
  hasDatasetDrag: (dataTransfer: any) => Array.from(dataTransfer?.types || []).includes("test/dataset-card"),
  readDatasetDragPayload: (dataTransfer: any) => JSON.parse(dataTransfer?.getData("test/dataset-card") || "null"),
}));
// ProjectLoader's: an unsaved dataflow's defaults, never asked for here.
jest.mock("../../services/packages", () => ({
  packagesApi: { getDefaults: jest.fn().mockResolvedValue({ packages: [] }) },
}));
jest.mock("../../services/packages/modelApplication", () => ({
  hasModelDrag: () => false,
  modelNodeForCanvas: () => null,
  packageCardNodeOptions: () => ({}),
  readModelDragPayload: () => null,
}));
jest.mock("../../services/scenarioCatalog/scenarioDrag", () => ({
  endScenarioDrag: jest.fn(),
  hasScenarioDrag: () => false,
  readScenarioDragPayload: () => null,
}));
jest.mock("../../services/agents", () => ({
  agentsApi: {},
  agentsOnCanvas: (role: string) => ({ drives: role !== "watcher", installsWaitForOwner: role === "editor" }),
  readAgentDragCoord: () => null,
  notifyAgentDockRefresh: jest.fn(),
  resolveAgentDropTarget: jest.fn(),
  hasAgentDrag: () => false,
}));
jest.mock("../../adapters/node/packageNodeBehavior", () => ({ packageStarterCode: jest.fn() }));
jest.mock("../../registry/nodeRegistry", () => ({
  getAllNodeTypes: () => [],
  getPaletteNodeTypes: () => [],
  tryGetNodeDescriptor: () => undefined,
}));
jest.mock("../../registry/packageKeys", () => ({ packageKeyFromCanonicalNodeType: () => null }));
jest.mock("../../registry/packageRegistryBootstrap", () => ({
  refreshPackageRegistry: jest.fn().mockResolvedValue(undefined),
}));
jest.mock("../../utils/flowNodeCanonicalType", () => ({ getFlowNodeCanonicalType: () => "" }));
jest.mock("../../utils/agentDropHover", () => ({ clearAgentDropHover: jest.fn(), setAgentDropHoverEdgeId: jest.fn() }));
jest.mock("../../utils/agentDropAttach", () => ({ attachAgentOnDrop: jest.fn() }));
jest.mock("../../utils/focusDatasetNodes", () => ({ frameNodesInView: jest.fn(), revealRectInView: jest.fn() }));
jest.mock("../../utils/scenarios/scenarioCanvasView", () => ({
  scenarioCanvasView: (nodes: unknown, edges: unknown) => ({ nodes, edges, boxes: [] }),
}));
jest.mock("../../utils/canvasExtent", () => ({
  computeTranslateExtent: () => [[-100000, -100000], [100000, 100000]],
}));
jest.mock("../../utils/notebookLayout", () => ({ notebookFlowProps: () => ({}) }));
jest.mock("../../utils/fitViewWithMenuOffset", () => ({
  CANVAS_TITLE_ATTR: "data-curio-canvas-title",
  fitViewWithMenuOffset: jest.fn(),
  fitViewWithMenuOffsetNow: jest.fn(),
  topOverlayBottom: () => null,
}));

import { MainCanvas } from "../../components/MainCanvas";
import { ProjectLoader } from "../../components/ProjectLoader";
import { clearCurrentProject } from "../../registry/projectPackagesStore";

// jsdom polyfills React Flow needs (as in mainCanvasShiftDrag).
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(global as any).ResizeObserver = ResizeObserverStub;
if (!(global as any).DOMMatrixReadOnly) {
  (global as any).DOMMatrixReadOnly = class { m22 = 1; constructor() {} };
}

const TILE = "curio.builtin/data-transformation";
const LOADED = { spec: { dataflow: { name: "Bus plan", nodes: [], edges: [] } }, outputs: [] };

/** A load the test lets land, or fail, when it chooses. */
function heldLoad() {
  let land!: (result: unknown) => void;
  let fail!: (err: unknown) => void;
  const promise = new Promise((resolve, reject) => {
    land = resolve;
    fail = reject;
  });
  return { promise, land, fail };
}

const notFound = () => Object.assign(new Error("not found"), { status: 404 });

/** A built-in node's tile, dragged from the rail. */
function tileDrag() {
  return {
    types: ["application/reactflow"],
    files: [],
    getData: (type: string) => (type === "application/reactflow" ? TILE : ""),
  };
}

/** A file from the computer. */
function fileDrag(name: string) {
  return {
    types: ["Files"],
    files: [new File(["stop_id,routes\n1,22\n"], name, { type: "text/csv" })],
    getData: () => "",
  };
}

/** A card of the dropper's own Data Catalog. */
function cardDrag(datasetId: string) {
  const card = JSON.stringify({ datasetId, title: "Bus stops" });
  return {
    types: ["test/dataset-card"],
    files: [],
    getData: (type: string) => (type === "test/dataset-card" ? card : ""),
  };
}

function canvas() {
  return (
    <ReactFlowProvider>
      <ProjectLoader>
        <MainCanvas />
      </ProjectLoader>
    </ReactFlowProvider>
  );
}

function drawCanvas() {
  const view = render(canvas());
  const target = view.container.querySelector(".curio-canvas-drop-target") as HTMLElement;
  return { view, target };
}

function drop(target: HTMLElement, dataTransfer: unknown) {
  fireEvent.drop(target, { dataTransfer, clientX: 300, clientY: 200 });
}

/** What the canvas made of the drops so far: copies, since a mock's list of
 *  calls grows in place. */
function made() {
  return {
    nodes: mockCreateCodeNode.mock.calls.map(([type]) => type),
    imports: mockImport.mock.calls.map((call) => [...call]),
    asks: mockAsk.mock.calls.map((call) => [...call]),
  };
}

/** Nothing made. */
const NOTHING = { nodes: [], imports: [], asks: [] };

/** Effects a landed load left: the render it caused, and that render's effects. */
async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

let consoleError: jest.SpyInstance;

beforeEach(() => {
  jest.clearAllMocks();
  clearCurrentProject();
  mockCollab = {};
  mockFlow = {
    nodes: [],
    edges: [],
    loading: false,
    projectId: null,
    viewerMode: "owner",
    onNodesChange: jest.fn(),
    onEdgesChange: jest.fn(),
    onConnect: jest.fn(),
    isValidConnection: () => true,
    onEdgesDelete: jest.fn(),
    onNodesDelete: jest.fn(),
    markDirty: jest.fn(),
    requestAutoRun: jest.fn(),
    ensureProjectId: jest.fn(),
    whenChangesKept: jest.fn(),
    notebookOn: false,
    notebookContentHeight: 0,
    setNotebookPane: jest.fn(),
    registerNotebookScroller: jest.fn(),
    revealNodes: jest.fn(),
    scenarios: [],
    loadProject: jest.fn(),
    loadSharedProject: jest.fn(),
    setOutputs: jest.fn(),
    hydrateRestoredOutputs: jest.fn(),
    attachLatestRun: jest.fn(),
    setWorkflowName: jest.fn(),
  };
  consoleError = jest.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  consoleError.mockRestore();
});

test("a node dropped while the owner's dataflow opens is made once the dataflow is in", async () => {
  const load = heldLoad();
  mockFlow.loadProject.mockReturnValue(load.promise);
  const { target } = drawCanvas();
  await waitFor(() => expect(mockFlow.loadProject).toHaveBeenCalled());

  drop(target, tileDrag());
  const whileOpening = made();
  await act(async () => {
    load.land(LOADED);
  });
  await waitFor(() => expect(mockLoadTrill).toHaveBeenCalled());
  await settle();

  // Made on the canvas the load had filled, not on the one it then replaced.
  expect({ whileOpening, opened: made() }).toEqual({
    whileOpening: NOTHING,
    opened: { ...NOTHING, nodes: [TILE] },
  });
});

test("a file an invited editor drops while the dataflow opens is imported once it is in, by his canvas", async () => {
  // The room named him first, as it often does: the load is still out.
  mockCollab = { role: "editor" };
  mockFlow.loadProject.mockRejectedValue(notFound());
  const shared = heldLoad();
  mockFlow.loadSharedProject.mockReturnValue(shared.promise);
  const { target } = drawCanvas();
  await waitFor(() => expect(mockFlow.loadSharedProject).toHaveBeenCalled());

  drop(target, fileDrag("bus_stops.csv"));
  const whileOpening = made();
  await act(async () => {
    // The shared load says it is another account's dataflow as it lands.
    mockFlow = { ...mockFlow, viewerMode: "shared" };
    shared.land(LOADED);
  });
  await waitFor(() => expect(mockLoadTrill).toHaveBeenCalled());
  await settle();

  // Imported his way, once: never the owner's, which refused it as the
  // dataflow still opening.
  expect({ whileOpening, opened: made() }).toEqual({
    whileOpening: NOTHING,
    opened: { ...NOTHING, imports: [["shared, editor", ["bus_stops.csv"]]] },
  });
});

test("a card an invited editor drops while the dataflow opens makes his node once it is in, and asks the owner for it", async () => {
  mockCollab = { role: "editor" };
  mockFlow.loadProject.mockRejectedValue(notFound());
  const shared = heldLoad();
  mockFlow.loadSharedProject.mockReturnValue(shared.promise);
  const { target } = drawCanvas();
  await waitFor(() => expect(mockFlow.loadSharedProject).toHaveBeenCalled());

  drop(target, cardDrag("imported.bus_stops"));
  const whileOpening = made();
  await act(async () => {
    mockFlow = { ...mockFlow, viewerMode: "shared" };
    shared.land(LOADED);
  });
  await waitFor(() => expect(mockLoadTrill).toHaveBeenCalled());
  await settle();

  // His Data Loading node, and the owner asked for the dataset it loads, by
  // the canvas he edits on: the owner's way would have asked her nothing.
  expect({ whileOpening, opened: made() }).toEqual({
    whileOpening: NOTHING,
    opened: {
      ...NOTHING,
      nodes: ["curio.builtin/data-loading"],
      asks: [["shared, editor", "imported.bus_stops", { nodeId: "dropped" }]],
    },
  });
});

test("when the dataflow is in before the room names the tab, an editor's drop waits for the room", async () => {
  mockFlow.loadProject.mockRejectedValue(notFound());
  const shared = heldLoad();
  mockFlow.loadSharedProject.mockReturnValue(shared.promise);
  const { view, target } = drawCanvas();
  await waitFor(() => expect(mockFlow.loadSharedProject).toHaveBeenCalled());

  drop(target, fileDrag("bus_stops.csv"));
  const whileOpening = made();
  await act(async () => {
    mockFlow = { ...mockFlow, viewerMode: "shared" };
    shared.land(LOADED);
  });
  await waitFor(() => expect(mockLoadTrill).toHaveBeenCalled());
  await settle();
  // In, but the room has not said who this tab is: the canvas reads as a
  // watcher's until it does.
  const beforeTheRoom = made();

  mockCollab = { role: "editor" };
  view.rerender(canvas());
  await settle();

  expect({ whileOpening, beforeTheRoom, named: made() }).toEqual({
    whileOpening: NOTHING,
    beforeTheRoom: NOTHING,
    named: { ...NOTHING, imports: [["shared, editor", ["bus_stops.csv"]]] },
  });
});

test("a watcher's drop while the dataflow opens is let go, as any drop on a watcher's canvas", async () => {
  mockCollab = { role: "watcher" };
  mockFlow.loadProject.mockRejectedValue(notFound());
  const shared = heldLoad();
  mockFlow.loadSharedProject.mockReturnValue(shared.promise);
  const { target } = drawCanvas();
  await waitFor(() => expect(mockFlow.loadSharedProject).toHaveBeenCalled());

  drop(target, fileDrag("bus_stops.csv"));
  drop(target, tileDrag());
  drop(target, cardDrag("imported.bus_stops"));
  await act(async () => {
    mockFlow = { ...mockFlow, viewerMode: "shared" };
    shared.land(LOADED);
  });
  await waitFor(() => expect(mockLoadTrill).toHaveBeenCalled());
  await settle();

  expect({ made: made(), told: mockShowToast.mock.calls }).toEqual({
    made: NOTHING,
    told: [],
  });
});

test("a dataflow that cannot be opened says why once, and nothing dropped meanwhile is made", async () => {
  const load = heldLoad();
  mockFlow.loadProject.mockReturnValue(load.promise);
  const { target } = drawCanvas();
  await waitFor(() => expect(mockFlow.loadProject).toHaveBeenCalled());

  drop(target, fileDrag("bus_stops.csv"));
  drop(target, tileDrag());
  await act(async () => {
    load.fail(new Error("network down"));
  });
  await waitFor(() => expect(mockShowToast).toHaveBeenCalled());
  await settle();

  expect({ made: made(), told: mockShowToast.mock.calls }).toEqual({
    made: NOTHING,
    told: [["That dataflow could not be loaded: network down", "error"]],
  });
});
