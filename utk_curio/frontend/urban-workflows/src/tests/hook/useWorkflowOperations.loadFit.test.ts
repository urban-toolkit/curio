/**
 * The canvas's load fit frames nodes at the size they will keep (#683).
 *
 * A node whose package has not registered yet renders as `UnresolvedNode`, a
 * small placeholder, and grows to its full size when the descriptor lands. The
 * fit used to run as soon as every node had a measured size, placeholders
 * included, so on a slow load the grown nodes ended past the window's edge (a
 * chart's rightmost bar sat at x=1311 in a 1280-wide window in CI). The fit now
 * waits for the package registry while a node has no descriptor, within a
 * bound, because without a session the registry never loads.
 */
import { faCircle } from "@fortawesome/free-solid-svg-icons";
import { renderHook, act } from "@testing-library/react";
import { Position } from "reactflow";

const mockFitViewWithMenuOffset = jest.fn((..._args: any[]) => true);
jest.mock("../../utils/fitViewWithMenuOffset", () => ({
  fitViewWithMenuOffset: (...args: any[]) => mockFitViewWithMenuOffset(...args),
}));
// What React Flow reports for the nodes on the canvas: measured, so only the
// registry decides whether the fit may run.
let mockFlowNodes: any[] = [];
jest.mock("reactflow", () => {
  // One instance, as React Flow gives: the fit's effect is keyed on it.
  const instance = { getNodes: () => mockFlowNodes, getEdges: () => [], fitView: jest.fn() };
  return {
    ...jest.requireActual("reactflow"),
    useReactFlow: () => instance,
    useNodesInitialized: () => true,
  };
});
let mockRegistryReady = false;
jest.mock("../../registry/registryReadiness", () => ({
  isRegistryReady: () => mockRegistryReady,
  subscribeToRegistryReady: () => () => {},
}));
jest.mock("../../providers/ProvenanceProvider", () => ({
  useProvenanceContext: () => ({ getAllNodeProvenance: () => ({}) }),
}));
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));
jest.mock("../../providers/UserProvider", () => ({
  useUserContext: () => ({ user: null, enableUserAuth: false }),
}));
jest.mock("../../api/projectsApi", () => ({
  projectsApi: { create: jest.fn(), update: jest.fn(), get: jest.fn() },
}));
jest.mock("../../registry/projectPackagesStore", () => ({
  getCurrentProjectPackagesList: jest.fn(() => []),
  getCurrentProjectPackages: jest.fn(() => null),
  getCurrentProjectId: jest.fn(() => undefined),
  whenProjectSettled: jest.fn(async () => {}),
  setCurrentProject: jest.fn(),
  setCurrentProjectPackages: jest.fn(),
  subscribe: jest.fn(() => jest.fn()),
}));

import { CURIO_UNIVERSAL_NODE_TYPE, NodeType, SupportedType } from "../../constants";
import { LOAD_FIT_REGISTRY_WAIT_MS, useWorkflowOperations } from "../../hook/useWorkflowOperations";
import { clearPackageNodes, registerNode } from "../../registry/nodeRegistry";
import { NodeDescriptor } from "../../registry/types";

// The fit is scheduled through requestAnimationFrame; run it inline so the
// timers below are the only clock.
(global as any).requestAnimationFrame = (cb: FrameRequestCallback) => {
  cb(0);
  return 0;
};
(global as any).cancelAnimationFrame = () => {};

const CHART = "acme.charts/chart@1";

function descriptor(id: string): NodeDescriptor {
  return {
    id: id as NodeType,
    category: "data",
    label: id,
    icon: faCircle,
    inputPorts: [{ types: [SupportedType.DATAFRAME] }],
    outputPorts: [],
    editor: "grammar",
    inPalette: true,
    paletteOrder: 1,
    description: "",
    hasCode: false,
    hasWidgets: false,
    hasGrammar: true,
    adapter: {
      handles: [{ id: "in", type: "target", position: Position.Left }],
      editor: { code: false, grammar: true, widgets: false },
      container: {},
      useNodeBehavior: () => ({}),
    },
  } as unknown as NodeDescriptor;
}

function chartNode(id: string) {
  return {
    id,
    type: CURIO_UNIVERSAL_NODE_TYPE,
    position: { x: 0, y: 0 },
    width: 214,
    height: 72,
    data: { nodeId: id, nodeType: CHART, input: "" },
  };
}

function render() {
  const deps = {
    nodes: [],
    edges: [],
    setNodes: jest.fn((u: any) => (typeof u === "function" ? u([]) : u)),
    setEdges: jest.fn(),
    setOutputs: jest.fn(),
    outputsRef: { current: [] },
    setInteractions: jest.fn(),
    setDashboardPins: jest.fn(),
    setWorkflowName: jest.fn(),
    workflowNameRef: { current: "wf" },
    setWorkflowDescription: jest.fn(),
    workflowDescriptionRef: { current: "" },
    onEdgesDelete: jest.fn(),
    onNodesDelete: jest.fn(),
    onNodesChange: jest.fn(),
    onConnect: jest.fn(),
    addNode: jest.fn(),
    defaultSaveOutputDataset: false,
  } as any;
  return renderHook(() => useWorkflowOperations(deps));
}

async function load(api: any) {
  mockFlowNodes = [chartNode("chart")];
  await act(async () => {
    await api.loadParsedTrill("wf", "", mockFlowNodes, [], false, false, [], "", []);
    await Promise.resolve();
  });
}

function advance(ms: number) {
  act(() => {
    jest.advanceTimersByTime(ms);
  });
}

beforeEach(() => {
  jest.useFakeTimers();
  mockFitViewWithMenuOffset.mockClear();
  mockRegistryReady = false;
});

afterEach(() => {
  clearPackageNodes();
  jest.useRealTimers();
});

test("the fit waits while a node's package has not registered", async () => {
  const { result } = render();
  await load(result.current);
  advance(1000);
  // The chart is still a placeholder: fitting now frames the wrong size.
  expect(mockFitViewWithMenuOffset).not.toHaveBeenCalled();

  registerNode(descriptor(CHART));
  advance(150);
  expect(mockFitViewWithMenuOffset).toHaveBeenCalled();
});

test("the fit also runs once the registry has loaded", async () => {
  const { result } = render();
  await load(result.current);
  advance(500);
  expect(mockFitViewWithMenuOffset).not.toHaveBeenCalled();

  // Loaded without providing the type: the placeholder is permanent, so
  // waiting longer gains nothing.
  mockRegistryReady = true;
  advance(150);
  expect(mockFitViewWithMenuOffset).toHaveBeenCalled();
});

test("the fit runs at once when every node is known", async () => {
  registerNode(descriptor(CHART));
  const { result } = render();
  await load(result.current);
  expect(mockFitViewWithMenuOffset).toHaveBeenCalled();
});

test("the wait has a bound, for a canvas whose registry never loads", async () => {
  const { result } = render();
  await load(result.current);
  advance(LOAD_FIT_REGISTRY_WAIT_MS - 200);
  expect(mockFitViewWithMenuOffset).not.toHaveBeenCalled();

  advance(400);
  expect(mockFitViewWithMenuOffset).toHaveBeenCalled();
});
