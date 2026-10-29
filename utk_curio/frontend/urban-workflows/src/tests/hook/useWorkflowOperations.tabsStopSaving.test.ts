import { renderHook, act } from "@testing-library/react";

/**
 * No tab saves a dataflow it is bound to: the doc keeps each change as it is
 * made. What used to save it does something else now.
 *
 * - File > Save of a bound canvas records the outputs the canvas holds, waits
 *   for the server to keep every change, and adds a version named Saved. It
 *   sends no PUT of the dataflow, nor does anything else on a bound canvas,
 *   so two writes of one dataflow never meet (#909, #941), and a tab never
 *   puts back what the server wrote since it loaded (dev/124).
 * - A canvas never saved is made into a dataflow by one create, which every
 *   caller while it is out shares (#340): never two dataflows. The canvas as
 *   it was sent goes with the load the canvas then binds on.
 * - A saved dataflow's canvas that changed before it bound acts on the
 *   server's copy (a run, a record, a drop) once the bind has written that
 *   change, as a save before the action used to carry it.
 * - No timer saves anything.
 */

// What the canvas holds when a create reads it.
let mockCanvasNodes: object[] = [];
// One object for every render.
const mockReactFlow = { getNodes: () => mockCanvasNodes, getEdges: () => [] };
jest.mock("reactflow", () => ({
  useReactFlow: () => mockReactFlow,
  useNodesInitialized: () => false,
}));
const mockEntries = { n1: [{ id: 1, parentId: null, code: "x = 1", inputs: [], outputs: [], startTime: "", endTime: "" }] };
jest.mock("../../providers/ProvenanceProvider", () => ({
  useProvenanceContext: () => ({ getAllNodeProvenance: () => mockEntries }),
}));
const mockShowToast = jest.fn();
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));
jest.mock("../../providers/UserProvider", () => ({
  useUserContext: () => ({ user: null, enableUserAuth: false }),
}));
jest.mock("../../api/projectsApi", () => ({
  projectsApi: { create: jest.fn(), update: jest.fn(), get: jest.fn(), recordOutputs: jest.fn() },
}));
const mockVersions = { id: "wf", latest: "wf_1", graph: { nodes: [{ id: "wf_1" }], edges: [] }, versions: { wf_1: {} } };
jest.mock("../../TrillGenerator", () => ({
  TrillGenerator: {
    generateTrill: jest.fn(() => ({ dataflow: { datasets: [] } })),
    getSerializableDataflowProvenance: jest.fn(() => mockVersions),
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
const mockNoteSaved = jest.fn();
jest.mock("../../providers/history/serverHistory", () => ({
  noteSaved: (...args: unknown[]) => mockNoteSaved(...args),
  setServerHistory: jest.fn(),
}));

import { SAVE_OFFLINE_MESSAGE, useWorkflowOperations } from "../../hook/useWorkflowOperations";
import { projectsApi } from "../../api/projectsApi";

const CATEGORIES = { source: "mine", auto: { tags: ["census"] } };

/** The canvas's binding to the doc: bound, or bound to none. */
function bridge(bound: boolean, calls: string[] = []) {
  return {
    bound: () => bound,
    whenBound: jest.fn(async () => {
      calls.push("whenBound");
      return bound;
    }),
    whenKept: jest.fn(async () => {
      calls.push("whenKept");
      return bound;
    }),
    canvasNow: jest.fn(() => ({ nodes: [{ id: "as-sent" }] })),
  };
}

/** Made once per test, so every render gets the same refs. */
const makeDeps = (docBridge: ReturnType<typeof bridge> | null) => {
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
    docBridgeRef: { current: docBridge },
    flushOutputsRef: { current: jest.fn() },
    recordSourcesRef: { current: jest.fn() },
  } as any;
};

/** A dataflow loaded from the server. */
async function loadedProject(result: any) {
  (projectsApi.get as jest.Mock).mockResolvedValue({
    project: { id: "proj-1", name: "Loaded name", updated_at: null },
    spec: { dataflow: { nodes: [], edges: [] } },
    outputs: [],
  });
  await act(async () => {
    await result.current.loadProject("proj-1");
  });
}

const CREATED = {
  id: "new-1",
  name: "Loaded name",
  spec: { dataflow: { datasets: [], packages: ["curio.builtin@1"] } },
  categories: {},
};

beforeEach(() => {
  jest.clearAllMocks();
  mockCanvasNodes = [];
  (projectsApi.create as jest.Mock).mockResolvedValue(CREATED);
  (projectsApi.update as jest.Mock).mockResolvedValue({ id: "proj-1", name: "Loaded name", categories: {} });
  (projectsApi.recordOutputs as jest.Mock).mockResolvedValue({ outputs: [], dataset_install_warnings: [] });
  mockNoteSaved.mockResolvedValue({ categories: CATEGORIES });
});

afterEach(() => {
  jest.useRealTimers();
});

describe("File > Save of a dataflow bound to its doc", () => {
  it("sends no save of the dataflow: it records the outputs, waits for the server to keep every change, then adds the Saved version", async () => {
    const calls: string[] = [];
    const deps = makeDeps(bridge(true, calls));
    (projectsApi.recordOutputs as jest.Mock).mockImplementation(async () => {
      calls.push("recordOutputs");
      return { outputs: [], dataset_install_warnings: [] };
    });
    mockNoteSaved.mockImplementation(async () => {
      calls.push("noteSaved");
      return { categories: CATEGORIES };
    });
    const { result } = renderHook(() => useWorkflowOperations(deps));
    await loadedProject(result);

    let saved: any;
    await act(async () => {
      saved = await result.current.saveDataflow();
    });

    expect(saved).toEqual({ id: "proj-1", created: false });
    expect(deps.flushOutputsRef.current).toHaveBeenCalled();
    expect(calls.indexOf("recordOutputs")).toBeLessThan(calls.lastIndexOf("whenKept"));
    expect(calls[calls.length - 1]).toBe("noteSaved");
    expect(calls.lastIndexOf("whenBound")).toBeLessThan(calls.lastIndexOf("whenKept"));
    // The Saved version's answer gives the title its categories, as a save's did.
    expect(result.current.serverCategories).toEqual(CATEGORIES);
    expect(projectsApi.update).not.toHaveBeenCalled();
    expect(projectsApi.create).not.toHaveBeenCalled();
  });

  it("waits for a canvas that has not bound yet, and reads its binding again once it has", async () => {
    // The bridge of a render before the bind holds no doc: its wait for the
    // server answers false. The one read after the bind holds it.
    const before = bridge(false);
    const after = bridge(true);
    let bind!: () => void;
    before.whenBound.mockImplementation(
      () => new Promise<boolean>((resolve) => {
        bind = () => {
          deps.docBridgeRef.current = after;
          resolve(true);
        };
      }),
    );
    const deps = makeDeps(before);
    const { result } = renderHook(() => useWorkflowOperations(deps));
    await loadedProject(result);

    let saving!: Promise<any>;
    act(() => {
      saving = result.current.saveDataflow();
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(mockNoteSaved).not.toHaveBeenCalled();
    await act(async () => {
      bind();
      await expect(saving).resolves.toEqual({ id: "proj-1", created: false });
    });

    // The wait for the server to keep every change is the bound canvas's.
    expect(after.whenKept).toHaveBeenCalled();
    expect(mockNoteSaved).toHaveBeenCalledTimes(1);
  });

  it("says Curio cannot reach the server when the canvas does not bind in time", async () => {
    const deps = makeDeps(bridge(false));
    const { result } = renderHook(() => useWorkflowOperations(deps));
    await loadedProject(result);

    await act(async () => {
      await expect(result.current.saveDataflow()).rejects.toThrow(SAVE_OFFLINE_MESSAGE);
    });

    expect(mockNoteSaved).not.toHaveBeenCalled();
    expect(projectsApi.update).not.toHaveBeenCalled();
  });
});

describe("a dataflow bound to its doc", () => {
  it("is never Unsaved: the doc keeps each change", async () => {
    const deps = makeDeps(bridge(true));
    const { result } = renderHook(() => useWorkflowOperations(deps));
    await loadedProject(result);

    act(() => {
      result.current.markDirty();
    });

    expect(result.current.projectDirty).toBe(false);
  });

  it("sends a rename as the name alone, as the Projects page does", async () => {
    const deps = makeDeps(bridge(true));
    const { result } = renderHook(() => useWorkflowOperations(deps));
    await loadedProject(result);

    await act(async () => {
      result.current.renameDataflow("Renamed");
    });

    expect(projectsApi.update).toHaveBeenCalledTimes(1);
    expect(projectsApi.update).toHaveBeenCalledWith("proj-1", { name: "Renamed" });
  });

  it("records the outputs it holds once the server has its every change", async () => {
    const calls: string[] = [];
    const deps = makeDeps(bridge(true, calls));
    (projectsApi.recordOutputs as jest.Mock).mockImplementation(async () => {
      calls.push("recordOutputs");
      return { outputs: [], dataset_install_warnings: [] };
    });
    const { result } = renderHook(() => useWorkflowOperations(deps));
    await loadedProject(result);

    await act(async () => {
      await result.current.recordOutputs(["n1"]);
    });

    expect(calls).toEqual(["whenKept", "recordOutputs"]);
    expect(projectsApi.recordOutputs).toHaveBeenCalledWith("proj-1", []);
    expect(projectsApi.update).not.toHaveBeenCalled();
  });

  it("sends nothing as the minutes pass: no timer saves it", async () => {
    jest.useFakeTimers();
    const deps = makeDeps(bridge(true));
    const { result } = renderHook(() => useWorkflowOperations(deps));
    await loadedProject(result);
    act(() => {
      result.current.markDirty();
    });

    await act(async () => {
      await jest.advanceTimersByTimeAsync(5 * 60 * 1000);
    });

    expect(projectsApi.update).not.toHaveBeenCalled();
    expect(projectsApi.create).not.toHaveBeenCalled();
    expect(projectsApi.recordOutputs).not.toHaveBeenCalled();
  });
});

describe("a canvas bound to no doc, with a dataflow", () => {
  it("sends nothing as the minutes pass, though it holds changes", async () => {
    jest.useFakeTimers();
    const deps = makeDeps(bridge(false));
    const { result } = renderHook(() => useWorkflowOperations(deps));
    await loadedProject(result);
    act(() => {
      result.current.markDirty();
    });
    expect(result.current.projectDirty).toBe(true);

    await act(async () => {
      await jest.advanceTimersByTimeAsync(5 * 60 * 1000);
    });

    expect(projectsApi.update).not.toHaveBeenCalled();
    expect(projectsApi.create).not.toHaveBeenCalled();
  });

  it("acts on the server's copy only once it has bound, when it changed since its load", async () => {
    // What it changed before the bind goes in with the bind, and no save
    // carries it: a run, a record or a drop waits for the bind, or the server
    // acts on a dataflow without that change.
    const before = bridge(false);
    const after = bridge(true);
    let bind!: () => void;
    before.whenBound.mockImplementation(
      () => new Promise<boolean>((resolve) => {
        bind = () => {
          deps.docBridgeRef.current = after;
          resolve(true);
        };
      }),
    );
    const deps = makeDeps(before);
    const { result } = renderHook(() => useWorkflowOperations(deps));
    await loadedProject(result);
    act(() => {
      result.current.markDirty();
    });

    let id: unknown = "waiting";
    act(() => {
      void result.current.ensureProjectId().then((answer: unknown) => {
        id = answer;
      });
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(id).toBe("waiting");
    expect(before.whenBound).toHaveBeenCalledTimes(1);

    await act(async () => {
      bind();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(id).toBe("proj-1");
    // The wait for the server to keep every change is the bound canvas's.
    expect(after.whenKept).toHaveBeenCalled();
    expect(projectsApi.update).not.toHaveBeenCalled();
  });

  it("acts on the server's copy at once when it changed nothing since its load", async () => {
    const docBridge = bridge(false);
    docBridge.whenBound.mockImplementation(() => new Promise<boolean>(() => {}));
    const deps = makeDeps(docBridge);
    const { result } = renderHook(() => useWorkflowOperations(deps));
    await loadedProject(result);

    await act(async () => {
      await expect(result.current.ensureProjectId()).resolves.toBe("proj-1");
    });

    expect(docBridge.whenBound).not.toHaveBeenCalled();
  });
});

describe("a canvas never saved", () => {
  it("is made into a dataflow by File > Save, the history it recorded with it", async () => {
    const deps = makeDeps(bridge(false));
    const { result } = renderHook(() => useWorkflowOperations(deps));

    let saved: any;
    await act(async () => {
      saved = await result.current.saveDataflow();
    });

    expect(saved).toEqual({ id: "new-1", created: true });
    expect(projectsApi.create).toHaveBeenCalledTimes(1);
    const [body] = (projectsApi.create as jest.Mock).mock.calls[0];
    expect(body.spec.nodeProvenance).toEqual(mockEntries);
    expect(body.spec.dataflowProvenance).toEqual(mockVersions);
    expect(mockNoteSaved).not.toHaveBeenCalled();
  });

  it("notes the canvas as it was sent with the load it binds on", async () => {
    const docBridge = bridge(false);
    const deps = makeDeps(docBridge);
    const { result } = renderHook(() => useWorkflowOperations(deps));

    await act(async () => {
      await result.current.saveDataflow();
    });

    expect(docBridge.canvasNow).toHaveBeenCalledTimes(1);
    expect(result.current.loadedDataflowRef.current).toMatchObject({
      projectId: "new-1",
      canvas: { nodes: [{ id: "as-sent" }] },
    });
  });

  it("is made once, whoever asks while the create is out (#340)", async () => {
    const deps = makeDeps(bridge(false));
    let answer!: () => void;
    (projectsApi.create as jest.Mock).mockImplementationOnce(
      () => new Promise((resolve) => {
        answer = () => resolve(CREATED);
      }),
    );
    const { result } = renderHook(() => useWorkflowOperations(deps));

    let ids!: Promise<unknown[]>;
    act(() => {
      ids = Promise.all([
        result.current.saveDataflow().then((saved: any) => saved.id),
        result.current.ensureProjectId(),
        result.current.ensureProjectId(),
      ]);
    });
    await act(async () => {
      answer();
      expect(await ids).toEqual(["new-1", "new-1", "new-1"]);
    });

    expect(projectsApi.create).toHaveBeenCalledTimes(1);
  });

  it("stays Unsaved when it changed while its create was out, until it binds", async () => {
    const deps = makeDeps(bridge(false));
    let answer!: () => void;
    (projectsApi.create as jest.Mock).mockImplementationOnce(
      () => new Promise((resolve) => {
        answer = () => resolve(CREATED);
      }),
    );
    const { result } = renderHook(() => useWorkflowOperations(deps));

    let saving!: Promise<unknown>;
    act(() => {
      saving = result.current.saveDataflow();
    });
    act(() => {
      result.current.markDirty();
    });
    await act(async () => {
      answer();
      await saving;
    });
    expect(result.current.projectDirty).toBe(true);

    act(() => {
      result.current.noteBound();
    });
    expect(result.current.projectDirty).toBe(false);
  });

  it("gives up on a create the server never answers after 2 minutes, and the next one goes out", async () => {
    // A POST left waiting forever would hold every caller behind the create.
    // This one goes through the real API client, down to fetch.
    jest.useFakeTimers();
    const actual = jest.requireActual("../../api/projectsApi");
    (projectsApi.create as jest.Mock).mockImplementation((body: unknown) => actual.projectsApi.create(body));
    const realFetch = global.fetch;
    const sent: RequestInit[] = [];
    global.fetch = jest.fn((_url: string, opts: RequestInit = {}) => {
      sent.push(opts);
      if (sent.length === 1) {
        // The first POST is never answered.
        return new Promise((_resolve, reject) => {
          opts.signal?.addEventListener("abort", () => {
            reject(new DOMException("The operation was aborted.", "AbortError"));
          });
        });
      }
      return Promise.resolve({ ok: true, status: 201, json: async () => CREATED });
    }) as unknown as typeof fetch;
    try {
      const deps = makeDeps(bridge(false));
      const { result } = renderHook(() => useWorkflowOperations(deps));

      let first!: Promise<unknown>;
      act(() => {
        first = result.current.saveDataflow();
      });
      let firstOutcome: unknown = "waiting";
      first.then(
        () => {
          firstOutcome = "answered";
        },
        (err: unknown) => {
          firstOutcome = err;
        },
      );
      expect(sent).toHaveLength(1);

      await act(async () => {
        await jest.advanceTimersByTimeAsync(2 * 60 * 1000);
      });
      expect(firstOutcome).toBeInstanceOf(Error);
      expect((firstOutcome as Error).message).toMatch(/longer than 2 minutes/);

      // The create given up on holds nothing: the next one goes out.
      await act(async () => {
        await expect(result.current.saveDataflow()).resolves.toEqual({ id: "new-1", created: true });
      });
      expect(sent).toHaveLength(2);
    } finally {
      global.fetch = realFetch;
    }
  });
});
