/**
 * Who may save a dataflow from the canvas: everyone but a hosted guest
 * (`isHostedGuest`: a guest on a Curio started with --deploy, where every
 * visitor shares the one guest account). Without --deploy the shared guest is
 * the one local user, and it saves like a signed-in account.
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
let mockUserContext: { user: UserData | null; enableUserAuth: boolean } = { user: null, enableUserAuth: false };
jest.mock("../../providers/UserProvider", () => ({
  useUserContext: () => mockUserContext,
}));
jest.mock("../../api/projectsApi", () => ({
  projectsApi: { create: jest.fn(), update: jest.fn(), get: jest.fn() },
}));
jest.mock("../../TrillGenerator", () => ({
  TrillGenerator: {
    generateTrill: jest.fn(() => ({ dataflow: { datasets: [] } })),
    getSerializableDataflowProvenance: jest.fn(() => ({})),
    reset: jest.fn(),
  },
}));
jest.mock("../../utils/saveOutputDataset", () => ({
  buildSaveableLiveOutputs: jest.fn(() => []),
}));
jest.mock("../../registry/projectPackagesStore", () => ({
  ...jest.requireActual("../../registry/projectPackagesStore"),
  getCurrentProjectPackagesList: jest.fn(() => []),
  setCurrentProject: jest.fn(),
  setCurrentProjectPackages: jest.fn(),
  subscribe: jest.fn(() => jest.fn()),
}));

import { useWorkflowOperations } from "../../hook/useWorkflowOperations";
import { projectsApi } from "../../api/projectsApi";
import { TrillGenerator } from "../../TrillGenerator";
import type { UserData } from "../../utils/authApi";

const GUEST: UserData = {
  id: 1,
  username: "guest_shared",
  name: "Guest",
  email: null,
  profile_image: null,
  type: null,
  is_guest: true,
};
const SIGNED_IN: UserData = { ...GUEST, id: 2, username: "ada", name: "Ada", is_guest: false };

const HOSTED_GUEST = { user: GUEST, enableUserAuth: true };
const LOCAL_GUEST = { user: GUEST, enableUserAuth: false };
const SIGNED_IN_USER = { user: SIGNED_IN, enableUserAuth: true };

const makeDeps = () =>
  ({
    nodes: [],
    edges: [],
    setNodes: jest.fn(),
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

const CREATED = {
  id: "proj-new",
  name: "wf",
  spec: { dataflow: { datasets: [], packages: [] } },
  spec_revision: 1,
};

let warnSpy: jest.SpyInstance;

beforeEach(() => {
  jest.clearAllMocks();
  (TrillGenerator.generateTrill as jest.Mock).mockReturnValue({ dataflow: { datasets: [] } });
  (projectsApi.create as jest.Mock).mockResolvedValue(CREATED);
  warnSpy = jest.spyOn(console, "warn").mockImplementation(() => {});
});

afterEach(() => warnSpy.mockRestore());

describe("a hosted guest", () => {
  beforeEach(() => {
    mockUserContext = HOSTED_GUEST;
  });

  it("cannot save the dataflow, and nothing is sent", async () => {
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));

    await expect(result.current.saveCurrentProject()).rejects.toThrow("Guest users cannot save projects");
    expect(projectsApi.create).not.toHaveBeenCalled();
    expect(projectsApi.update).not.toHaveBeenCalled();
  });

  it("cannot save a copy either", async () => {
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));

    await expect(result.current.saveAsNewProject("A copy")).rejects.toThrow("Guest users cannot save projects");
    expect(projectsApi.create).not.toHaveBeenCalled();
  });
});

describe.each([
  ["the local shared guest", LOCAL_GUEST],
  ["a signed-in account", SIGNED_IN_USER],
])("%s", (_who, context) => {
  beforeEach(() => {
    mockUserContext = context;
  });

  it("saves the dataflow", async () => {
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));

    await act(async () => {
      await result.current.saveCurrentProject();
    });
    expect(projectsApi.create).toHaveBeenCalledTimes(1);
    expect(result.current.projectId).toBe("proj-new");
  });

  it("saves a copy", async () => {
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));

    await act(async () => {
      await result.current.saveAsNewProject("A copy");
    });
    expect(projectsApi.create).toHaveBeenCalledWith(expect.objectContaining({ name: "A copy" }));
    expect(result.current.projectId).toBe("proj-new");
  });
});
