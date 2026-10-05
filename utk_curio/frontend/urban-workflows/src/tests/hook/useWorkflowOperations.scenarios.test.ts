/**
 * A dataflow's scenarios (#662) in the flow state: a load restores them, the
 * load's version snapshots carry them, an edit makes the dataflow dirty, and a
 * save writes them.
 *
 * TrillGenerator is real here, as in the provenance tests: what matters is
 * what lands in the snapshots and in the saved spec.
 */
import { renderHook, act } from "@testing-library/react";

let mockCanvasNodes: any[] = [];
jest.mock("reactflow", () => ({
  useReactFlow: () => ({ getNodes: () => mockCanvasNodes, getEdges: () => [] }),
  useNodesInitialized: () => false,
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
  projectsApi: { create: jest.fn(), update: jest.fn() },
}));
jest.mock("../../utils/saveOutputDataset", () => ({
  buildSaveableLiveOutputs: jest.fn(() => []),
}));
jest.mock("../../registry/projectPackagesStore", () => ({
  getCurrentProjectPackagesList: jest.fn(() => []),
  getCurrentProjectId: jest.fn(() => undefined),
  whenProjectSettled: jest.fn(async () => {}),
  setCurrentProject: jest.fn(),
  setCurrentProjectPackages: jest.fn(),
  subscribe: jest.fn(() => jest.fn()),
}));

import { useWorkflowOperations } from "../../hook/useWorkflowOperations";
import { TrillGenerator } from "../../TrillGenerator";
import { projectsApi } from "../../api/projectsApi";
import type { Scenario } from "../../utils/scenarios/scenarioModel";

const makeNode = (id: string) => ({
  id,
  type: "curioUniversalNode",
  position: { x: 0, y: 0 },
  data: { nodeId: id, nodeType: "curio.builtin/data-loading@1", input: "" },
});

const makeDeps = () =>
  ({
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
  }) as any;

const NODES = [makeNode("a"), makeNode("b"), makeNode("c")];

const BASELINE: Scenario = { id: "s1", name: "Baseline", color: "#2a9d8f", nodes: ["a"] };
const TALL: Scenario = { id: "s2", name: "Twice as tall", color: "#e76f51", nodes: ["b", "gone"] };

beforeEach(() => {
  jest.clearAllMocks();
  TrillGenerator.reset();
  mockCanvasNodes = [];
});

describe("loading a dataflow with scenarios", () => {
  test("restores them, without the ids of nodes it does not have, and without dirtying it", async () => {
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));
    await act(async () => {
      await result.current.loadParsedTrill("wf", "", NODES, [], false, false, [], "", [], {}, [BASELINE, TALL]);
    });
    expect(result.current.scenarios).toEqual([BASELINE, { ...TALL, nodes: ["b"] }]);
    expect(result.current.projectDirty).toBe(false);
  });

  test("its version snapshots carry them", async () => {
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));
    await act(async () => {
      await result.current.loadParsedTrill("wf", "", NODES, [], true, false, [], "", [], {}, [BASELINE]);
    });
    const versions = Object.values(TrillGenerator.list_of_trills) as any[];
    expect(versions.length).toBeGreaterThan(1);
    // The empty initial version has no nodes, so its scenario has no members.
    const last = versions.at(-1);
    expect(last.dataflow.scenarios).toEqual([BASELINE]);
  });

  test("an absent list keeps the scenarios, and an empty one clears them", async () => {
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));
    await act(async () => {
      await result.current.loadParsedTrill("wf", "", NODES, [], false, false, [], "", [], {}, [BASELINE]);
    });
    await act(async () => {
      await result.current.loadParsedTrill("wf", "", NODES, [], false, false, [], "", []);
    });
    expect(result.current.scenarios).toEqual([BASELINE]);
    expect(TrillGenerator.scenarios).toEqual([BASELINE]);
    await act(async () => {
      await result.current.loadParsedTrill("wf", "", NODES, [], false, false, [], "", [], {}, []);
    });
    expect(result.current.scenarios).toEqual([]);
    expect(TrillGenerator.scenarios).toEqual([]);
  });
});

describe("editing the scenarios", () => {
  test("makes the dataflow dirty, and the next snapshot carries them", () => {
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));
    act(() => {
      result.current.setScenarios([BASELINE]);
    });
    expect(result.current.projectDirty).toBe(true);
    TrillGenerator.addNewVersionProvenance(NODES, [], "wf", "", "scenario");
    const last = (Object.values(TrillGenerator.list_of_trills) as any[]).at(-1);
    expect(last.dataflow.scenarios).toEqual([BASELINE]);
  });

  test("a save writes them, against the nodes on the canvas", async () => {
    (projectsApi.create as jest.Mock).mockResolvedValue({
      id: "proj-1",
      name: "wf",
      spec: { dataflow: { datasets: [], packages: [] } },
    });
    mockCanvasNodes = NODES;
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));
    act(() => {
      result.current.setScenarios([BASELINE, TALL]);
    });
    await act(async () => {
      await result.current.saveCurrentProject();
    });
    const sent = (projectsApi.create as jest.Mock).mock.calls[0][0];
    expect(sent.spec.dataflow.scenarios).toEqual([BASELINE, { ...TALL, nodes: ["b"] }]);
  });

  test("a save with none writes an empty list, so the server clears them", async () => {
    (projectsApi.create as jest.Mock).mockResolvedValue({
      id: "proj-1",
      name: "wf",
      spec: { dataflow: { datasets: [], packages: [] } },
    });
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));
    await act(async () => {
      await result.current.saveCurrentProject();
    });
    const sent = (projectsApi.create as jest.Mock).mock.calls[0][0];
    expect(sent.spec.dataflow.scenarios).toEqual([]);
  });
});
