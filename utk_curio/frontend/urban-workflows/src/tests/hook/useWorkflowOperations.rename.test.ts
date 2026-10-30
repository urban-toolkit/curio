import { renderHook, act } from "@testing-library/react";

/**
 * A rename writes both name stores (#230): the dataflow's, which the canvas
 * title renders, and the project row's, which the Projects list renders. On a
 * dataflow bound to its doc, the doc takes the dataflow's name and the rename
 * sends the row's as the Projects page does; on a canvas never saved, its
 * create sends the name it holds when it leaves (#270).
 */
jest.mock("reactflow", () => ({
  useReactFlow: () => ({ getNodes: () => [], getEdges: () => [] }),
  useNodesInitialized: () => false,
}));
jest.mock("../../providers/ProvenanceProvider", () => ({
  useProvenanceContext: () => ({ getAllNodeProvenance: () => ({}) }),
}));
const mockShowToast = jest.fn();
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));
jest.mock("../../providers/UserProvider", () => ({
  useUserContext: () => ({ user: null, enableUserAuth: false }),
}));
jest.mock("../../api/projectsApi", () => ({
  projectsApi: {
    create: jest.fn(), update: jest.fn(), get: jest.fn(), getShared: jest.fn(),
    recordOutputs: jest.fn(), renameShared: jest.fn(),
  },
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
  getCurrentProjectPackagesList: jest.fn(() => []),
  // No routed dataflow and nothing loading: the id is the hook's own.
  getCurrentProjectId: jest.fn(() => undefined),
  whenProjectSettled: jest.fn(async () => {}),
  setCurrentProject: jest.fn(),
  setCurrentProjectPackages: jest.fn(),
  subscribe: jest.fn(() => jest.fn()),
}));

import { useWorkflowOperations } from "../../hook/useWorkflowOperations";
import { projectsApi } from "../../api/projectsApi";

/** The canvas's binding to the dataflow's doc. */
const bridge = (bound: boolean) => ({
  bound: () => bound,
  whenBound: jest.fn(async () => bound),
  whenKept: jest.fn(async () => bound),
  canvasNow: jest.fn(() => ({})),
});

/**
 * `setWorkflowName` is threaded in from FlowProvider, so the fake has to write
 * `workflowNameRef` too — that ref is what the spec serializer reads, and the
 * whole bug is the two drifting apart. `setWorkflowDescription` comes from the
 * same place and writes its ref the same way.
 */
const makeDeps = (bound = false) => {
  const workflowNameRef = { current: "Loaded name" };
  const workflowDescriptionRef = { current: "" };
  return {
    nodes: [],
    edges: [],
    setNodes: jest.fn(),
    setEdges: jest.fn(),
    setOutputs: jest.fn(),
    outputsRef: { current: [] },
    setInteractions: jest.fn(),
    setDashboardPins: jest.fn(),
    setWorkflowName: jest.fn((n: string) => {
      workflowNameRef.current = n;
    }),
    workflowNameRef,
    setWorkflowDescription: jest.fn((d: string) => {
      workflowDescriptionRef.current = d || "";
    }),
    workflowDescriptionRef,
    onEdgesDelete: jest.fn(),
    onNodesDelete: jest.fn(),
    onNodesChange: jest.fn(),
    onConnect: jest.fn(),
    addNode: jest.fn(),
    defaultSaveOutputDataset: false,
    docBridgeRef: { current: bridge(bound) },
  } as any;
};

/** A project loaded from the server. */
async function loadedProject(result: any, name = "Loaded name") {
  (projectsApi.get as jest.Mock).mockResolvedValue({
    project: { id: "proj-1", name, updated_at: null },
    spec: { dataflow: { nodes: [], edges: [] } },
    outputs: [],
  });
  await act(async () => {
    await result.current.loadProject("proj-1");
  });
}

const created = (name: string) => ({
  id: "proj-2",
  name,
  spec: { dataflow: { datasets: [], packages: [] } },
  categories: {},
});

beforeEach(() => {
  jest.clearAllMocks();
  (projectsApi.update as jest.Mock).mockResolvedValue({ id: "proj-1", name: "Server name", categories: {} });
  (projectsApi.create as jest.Mock).mockResolvedValue(created("Server name"));
});

describe("renameDataflow on a dataflow bound to its doc", () => {
  it("sends the NEW name to the project row, not the load-time one (#230)", async () => {
    // The doc takes the dataflow's name, and no doc writes a project row: the
    // Projects card moves only because the rename sends it.
    const { result } = renderHook(() => useWorkflowOperations(makeDeps(true)));
    await loadedProject(result);

    await act(async () => {
      result.current.renameDataflow("New name");
    });

    expect(projectsApi.update).toHaveBeenCalledTimes(1);
    expect(projectsApi.update).toHaveBeenCalledWith("proj-1", { name: "New name" });
    expect(result.current.projectName).toBe("New name");
  });

  it("marks nothing Unsaved: the doc keeps it", async () => {
    const { result } = renderHook(() => useWorkflowOperations(makeDeps(true)));
    await loadedProject(result);

    await act(async () => {
      result.current.renameDataflow("New name");
    });

    expect(result.current.projectDirty).toBe(false);
  });

  it("refuses a blank entry and sends nothing", async () => {
    const { result } = renderHook(() => useWorkflowOperations(makeDeps(true)));
    await loadedProject(result);

    let accepted: boolean | undefined;
    await act(async () => {
      accepted = result.current.renameDataflow("   ");
    });

    expect(accepted).toBe(false);
    expect(projectsApi.update).not.toHaveBeenCalled();
    expect(result.current.projectName).toBe("Loaded name");
  });

  it("trims the committed name", async () => {
    const { result } = renderHook(() => useWorkflowOperations(makeDeps(true)));
    await loadedProject(result);

    await act(async () => {
      result.current.renameDataflow("  Padded  ");
    });

    expect(projectsApi.update).toHaveBeenCalledWith("proj-1", { name: "Padded" });
  });

  it("says so when the rename could not reach the project row", async () => {
    (projectsApi.update as jest.Mock).mockRejectedValue(new Error("offline"));
    const { result } = renderHook(() => useWorkflowOperations(makeDeps(true)));
    await loadedProject(result);

    await act(async () => {
      result.current.renameDataflow("New name");
    });

    expect(mockShowToast).toHaveBeenCalledWith("offline", "error");
  });
});

describe("renameDataflow on an invited editor's canvas, bound to the owner's dataflow", () => {
  /** The owner's dataflow, opened from its link as an editor opens it. */
  async function openedAsEditor(result: any) {
    const { getCurrentProjectId } = jest.requireMock("../../registry/projectPackagesStore");
    (getCurrentProjectId as jest.Mock).mockReturnValue("owners-proj");
    (projectsApi.getShared as jest.Mock).mockResolvedValue({
      project: { id: "owners-proj", name: "Owner's name", categories: {} },
      spec: { dataflow: { nodes: [], edges: [] } },
      outputs: [],
    });
    await act(async () => {
      await result.current.loadSharedProject("owners-proj");
    });
  }

  afterEach(() => {
    const { getCurrentProjectId } = jest.requireMock("../../registry/projectPackagesStore");
    (getCurrentProjectId as jest.Mock).mockReturnValue(undefined);
  });

  it("sends the new name to the owner's project row through the editors' route", async () => {
    // The doc takes the canvas's name; the row the owner's Projects page
    // lists is renamed only by this.
    (projectsApi.renameShared as jest.Mock).mockResolvedValue({ id: "owners-proj", name: "Bob's name" });
    const { result } = renderHook(() => useWorkflowOperations(makeDeps(true)));
    await openedAsEditor(result);

    await act(async () => {
      result.current.renameDataflow("Bob's name");
    });

    expect(projectsApi.renameShared).toHaveBeenCalledTimes(1);
    expect(projectsApi.renameShared).toHaveBeenCalledWith("owners-proj", "Bob's name");
    // Never the owner's PUT, which refuses anyone but the owner.
    expect(projectsApi.update).not.toHaveBeenCalled();
  });

  it("says so when the rename could not reach the row", async () => {
    (projectsApi.renameShared as jest.Mock).mockRejectedValue(new Error("refused"));
    const { result } = renderHook(() => useWorkflowOperations(makeDeps(true)));
    await openedAsEditor(result);

    await act(async () => {
      result.current.renameDataflow("Bob's name");
    });

    expect(mockShowToast).toHaveBeenCalledWith("refused", "error");
  });

  it("sends nothing from a shared view bound to no doc", async () => {
    const { result } = renderHook(() => useWorkflowOperations(makeDeps(false)));
    await openedAsEditor(result);

    await act(async () => {
      result.current.renameDataflow("Bob's name");
    });

    expect(projectsApi.renameShared).not.toHaveBeenCalled();
    expect(projectsApi.update).not.toHaveBeenCalled();
  });
});

describe("renameDataflow on a saved dataflow not bound to its doc yet", () => {
  it("still sends the project row its name: no save sends it later", async () => {
    // The doc takes the name with the bind; the row only from the rename.
    const { result } = renderHook(() => useWorkflowOperations(makeDeps(false)));
    await loadedProject(result);

    await act(async () => {
      result.current.renameDataflow("New name");
    });

    expect(projectsApi.update).toHaveBeenCalledTimes(1);
    expect(projectsApi.update).toHaveBeenCalledWith("proj-1", { name: "New name" });
    // Unsaved until the bind writes it into the doc.
    expect(result.current.projectDirty).toBe(true);
  });
});

describe("renameDataflow on a canvas never saved", () => {
  it("marks the dataflow Unsaved, so the save indicator and the leave question notice", async () => {
    // Nothing said a rename diverged from what was kept. That went unseen only
    // because the phantom dirty flag of #229 was masking it.
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));
    expect(result.current.projectDirty).toBe(false);

    act(() => {
      result.current.renameDataflow("New name");
    });

    expect(result.current.projectDirty).toBe(true);
    // A canvas with no dataflow has no row to send it to.
    expect(projectsApi.update).not.toHaveBeenCalled();
  });

  it("makes File > Save create the dataflow under the NEW name", async () => {
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));

    act(() => {
      result.current.renameDataflow("  New name  ");
    });
    await act(async () => {
      await result.current.saveDataflow();
    });

    expect(projectsApi.create).toHaveBeenCalledWith(expect.objectContaining({ name: "New name" }));
  });
});

describe("discardProject (#428)", () => {
  it("puts the dataflow name back to the default", async () => {
    // File > New discards the project and clears the canvas. FlowProvider
    // stays mounted across /dataflow/<id> -> /dataflow/new, so a name the
    // discard leaves behind is what the new dataflow's first save sends.
    const deps = makeDeps();
    const { result } = renderHook(() => useWorkflowOperations(deps));
    await loadedProject(result, "Autark PBF loading");
    deps.workflowNameRef.current = "Autark PBF loading";

    act(() => {
      result.current.discardProject();
    });

    expect(deps.workflowNameRef.current).toBe("DefaultDataflow");
  });

  it("clears the goal and the description, so the new dataflow's first save sends neither", async () => {
    // Only loadParsedTrill ever set these two, and File > New does not go
    // through it, so the previous dataflow's goal and description rode along
    // into the new one's first save.
    const deps = makeDeps();
    const { result } = renderHook(() => useWorkflowOperations(deps));
    await loadedProject(result, "Autark PBF loading");
    act(() => {
      result.current.setWorkflowGoal("Find the hottest blocks");
      deps.setWorkflowDescription("Surface temperature per block");
    });
    expect(result.current.workflowGoal).toBe("Find the hottest blocks");

    act(() => {
      result.current.discardProject();
    });

    expect(result.current.workflowGoal).toBe("");
    expect(deps.workflowDescriptionRef.current).toBe("");

    // What the create actually serializes: generateTrill(nodes, edges, name,
    // goal, packages, description, ...).
    const { TrillGenerator } = jest.requireMock("../../TrillGenerator");
    (TrillGenerator.generateTrill as jest.Mock).mockClear();
    await act(async () => {
      await result.current.saveDataflow();
    });
    expect(projectsApi.create).toHaveBeenCalledTimes(1);
    const args = (TrillGenerator.generateTrill as jest.Mock).mock.calls[0];
    expect(args[3]).toBe("");
    expect(args[5]).toBe("");
  });
});

describe("a create's name (#270)", () => {
  // A create sends the name the canvas holds when it leaves. A rename made
  // while it is out is not in what it sent: the client keeps the new name,
  // and the dataflow stays Unsaved, its leave question with it, until the
  // canvas binds and the doc takes the rename.
  function deferredCreate() {
    let resolve!: (detail: unknown) => void;
    const promise = new Promise((r) => { resolve = r; });
    (projectsApi.create as jest.Mock).mockImplementationOnce(() => promise);
    return (name: string) => resolve(created(name));
  }

  it("re-pins the client's name to whatever the server stored", async () => {
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));
    act(() => {
      result.current.renameDataflow("Typed name");
    });

    await act(async () => {
      await result.current.saveDataflow();
    });

    expect(projectsApi.create).toHaveBeenCalledWith(expect.objectContaining({ name: "Typed name" }));
    expect(result.current.projectName).toBe("Server name");
  });

  it("a rename made while the create is out leaves the dataflow Unsaved", async () => {
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));
    const finish = deferredCreate();

    let saving!: Promise<unknown>;
    act(() => {
      saving = result.current.saveDataflow();
    });
    act(() => {
      result.current.renameDataflow("New name");
    });
    expect(result.current.projectDirty).toBe(true);

    await act(async () => {
      finish("Loaded name");
      await saving;
    });

    expect(result.current.projectName).toBe("New name");
    expect(result.current.projectDirty).toBe(true);
    // The row the create made has the name it sent: the rename goes there
    // once it exists, as no save will send it.
    expect(projectsApi.update).toHaveBeenCalledTimes(1);
    expect(projectsApi.update).toHaveBeenCalledWith("proj-2", { name: "New name" });
  });

  it("a create with nothing edited behind it clears the Unsaved flag", async () => {
    // The control: the guard above must not leave every new dataflow Unsaved
    // for ever, or the leave question would ask on a dataflow that is kept.
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));
    const finish = deferredCreate();

    act(() => {
      result.current.renameDataflow("New name");
    });
    let saving!: Promise<unknown>;
    act(() => {
      saving = result.current.saveDataflow();
    });
    await act(async () => {
      finish("New name");
      await saving;
    });

    expect(result.current.projectDirty).toBe(false);
    // The create sent the name: nothing more to send the row.
    expect(projectsApi.update).not.toHaveBeenCalled();
  });

  it("a rename made while the create is out is not undone by its echo", async () => {
    // The answer re-pins the client's name to what the server stored. When
    // the user renamed in between, the server is echoing the name we SENT,
    // and adopting it would silently revert the rename.
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));
    const finish = deferredCreate();

    let saving!: Promise<unknown>;
    act(() => {
      saving = result.current.saveDataflow();
    });
    act(() => {
      result.current.renameDataflow("New name");
    });
    await act(async () => {
      finish("Loaded name");
      await saving;
    });

    expect(result.current.projectName).toBe("New name");
  });
});
