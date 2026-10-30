/**
 * A dataflow's lockfile that the room changes reaches the tab's node registry.
 *
 * The lockfile is in the dataflow's doc, so a package someone else added (the
 * owner's Add to project, her Apply of an editor's request) reaches every tab
 * of the dataflow as a change of its fields (`takeDataflowFields`). The palette
 * follows the lockfile, but the registry held only the packages the tab read
 * when it loaded: on an editor's canvas the owner's copies of those the
 * dataflow used then, on hers her store as it was. So the new package's nodes
 * stayed "Missing node package" on every other canvas until a reload. Now the
 * tab reads its registry again whenever the lockfile changes, and only then.
 */
import { renderHook, act } from "@testing-library/react";

jest.mock("reactflow", () => ({
  useReactFlow: () => ({ getNodes: () => [], getEdges: () => [] }),
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
jest.mock("../../registry/packageRegistryBootstrap", () => ({
  refreshPackageRegistry: jest.fn().mockResolvedValue(undefined),
}));

import { useWorkflowOperations } from "../../hook/useWorkflowOperations";
import { setCurrentProjectPackages } from "../../registry/projectPackagesStore";
import { refreshPackageRegistry } from "../../registry/packageRegistryBootstrap";

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

beforeEach(() => {
  jest.clearAllMocks();
});

test("a lockfile the room changes refreshes the registry, and a change that leaves it alone does not", () => {
  const { result } = renderHook(() => useWorkflowOperations(makeDeps()));

  act(() => result.current.takeDataflowFields({ name: "Bus plan" }, []));
  expect(refreshPackageRegistry).not.toHaveBeenCalled();

  act(() => result.current.takeDataflowFields({ packages: ["curio.builtin@1", "test.bus-counts@1"] }, []));

  expect(setCurrentProjectPackages).toHaveBeenCalledWith(["curio.builtin@1", "test.bus-counts@1"]);
  expect(refreshPackageRegistry).toHaveBeenCalledTimes(1);
});
