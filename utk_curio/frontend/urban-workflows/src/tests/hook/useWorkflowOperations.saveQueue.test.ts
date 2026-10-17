import { renderHook, act, waitFor } from "@testing-library/react";

/**
 * Saves of the open dataflow run one after another, through the save queue
 * (`requestProjectSave`). Two PUTs of one dataflow at once were behind #909 (a
 * save stuck for SQLite's 30 s busy timeout) and #941 (a dashboard reading
 * outputs while a second save rewrote them), and most of them came from the
 * browser: the pin's save and the autosave saved directly, beside the queue.
 * A save the server never answers gives up after 2 minutes, so it cannot hold
 * the saves behind it, and each save is numbered so the server can refuse one
 * the page gave up on that lands after the next. Autosaves that come due
 * while a save hangs wait as one, so they do not go out one after another.
 */

// What the canvas holds when a save reads it.
let mockCanvasNodes: { id: string }[] = [];
// One object for every render. A new one per render would give
// saveCurrentProject a new identity on every render, which re-arms the
// 30 second autosave interval each time.
const mockReactFlow = { getNodes: () => mockCanvasNodes, getEdges: () => [] };
jest.mock("reactflow", () => ({
  useReactFlow: () => mockReactFlow,
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
  getCurrentProjectPackagesList: jest.fn(() => []),
  // No routed dataflow and nothing loading: saves take their id from the
  // hook's own state, as they do once a load has landed.
  getCurrentProjectId: jest.fn(() => undefined),
  whenProjectSettled: jest.fn(async () => {}),
  setCurrentProject: jest.fn(),
  setCurrentProjectPackages: jest.fn(),
  subscribe: jest.fn(() => jest.fn()),
}));

import { useWorkflowOperations } from "../../hook/useWorkflowOperations";
import { useDashboardPinSave } from "../../providers/flow/useDashboardPins";
import { projectsApi } from "../../api/projectsApi";
import { TrillGenerator } from "../../TrillGenerator";

/** Made once per test, so every render gets the same refs. */
const makeDeps = () => {
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
  } as any;
};

/** A project loaded from the server, so saves take the update branch. */
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

const SAVED = {
  id: "proj-1",
  name: "Loaded name",
  spec: { dataflow: { datasets: [], packages: [] } },
};

/** Hold the next PUT open until the returned function answers it. */
function holdNextUpdate(): () => void {
  let answer!: () => void;
  const answered = new Promise((resolve) => {
    answer = () => resolve(SAVED);
  });
  (projectsApi.update as jest.Mock).mockImplementationOnce(() => answered);
  return answer;
}

beforeEach(() => {
  jest.clearAllMocks();
  (projectsApi.update as jest.Mock).mockResolvedValue(SAVED);
  mockCanvasNodes = [];
});

afterEach(() => {
  jest.useRealTimers();
});

describe("the save queue", () => {
  it("starts the second of two saves only after the first has answered", async () => {
    const deps = makeDeps();
    const { result } = renderHook(() => useWorkflowOperations(deps));
    await loadedProject(result);

    const events: string[] = [];
    let answerFirst!: () => void;
    (projectsApi.update as jest.Mock)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            answerFirst = () => {
              events.push("first answered");
              resolve(SAVED);
            };
          }),
      )
      .mockImplementationOnce(async () => {
        events.push("second sent");
        return SAVED;
      });

    let first!: Promise<unknown>;
    let second!: Promise<unknown>;
    act(() => {
      first = result.current.requestProjectSave();
      second = result.current.requestProjectSave();
    });
    // The first PUT is out; the second waits for its answer.
    expect(projectsApi.update).toHaveBeenCalledTimes(1);
    expect(events).toEqual([]);

    await act(async () => {
      answerFirst();
      await first;
      await second;
    });

    expect(projectsApi.update).toHaveBeenCalledTimes(2);
    expect(events).toEqual(["first answered", "second sent"]);
  });

  it("holds a pin's save until the save in flight has answered", async () => {
    // A pin saves 400 ms after the click. A Save clicked in between, as the
    // dashboard e2e tests do right after pinning, used to go out beside it.
    jest.useFakeTimers();
    const deps = makeDeps();
    const savePinChangeRef = { current: () => {} };
    const { result } = renderHook(() => {
      const ops = useWorkflowOperations(deps);
      useDashboardPinSave({
        savePinChangeRef,
        dashboardOn: false,
        workflowOps: ops,
        showToast: mockShowToast,
      });
      return ops;
    });
    await loadedProject(result);
    const answerSave = holdNextUpdate();

    let save!: Promise<unknown>;
    act(() => {
      save = result.current.requestProjectSave();
    });
    act(() => {
      savePinChangeRef.current();
    });
    act(() => {
      jest.advanceTimersByTime(400);
    });
    // Past the pin's debounce: its save waits in the queue.
    expect(projectsApi.update).toHaveBeenCalledTimes(1);

    jest.useRealTimers();
    await act(async () => {
      answerSave();
      await save;
    });
    // And goes out once the save before it has answered.
    await waitFor(() => expect(projectsApi.update).toHaveBeenCalledTimes(2));
    expect(mockShowToast).not.toHaveBeenCalled();
  });

  it("holds the 30 second autosave until the save in flight has answered", async () => {
    // Autosave plus Save is one of the overlaps #909 names.
    jest.useFakeTimers();
    const deps = makeDeps();
    const { result } = renderHook(() => useWorkflowOperations(deps));
    await loadedProject(result);
    // An edit, so the autosave is armed.
    act(() => {
      result.current.renameDataflow("Edited");
    });
    expect(result.current.projectDirty).toBe(true);
    const answerSave = holdNextUpdate();

    let save!: Promise<unknown>;
    act(() => {
      save = result.current.requestProjectSave();
    });
    act(() => {
      jest.advanceTimersByTime(30_000);
    });
    // The autosave came due while the save was out: it waits in the queue.
    expect(projectsApi.update).toHaveBeenCalledTimes(1);

    jest.useRealTimers();
    await act(async () => {
      answerSave();
      await save;
    });
    // And goes out once the save before it has answered.
    await waitFor(() => expect(projectsApi.update).toHaveBeenCalledTimes(2));
  });

  it("names this tab on each save and numbers it one higher than the last", async () => {
    // A save the page gave up on may still land on the server; the number
    // lets the server refuse it once a later save of this tab has landed.
    const deps = makeDeps();
    const { result } = renderHook(() => useWorkflowOperations(deps));
    await loadedProject(result);

    await act(async () => {
      await result.current.requestProjectSave();
      await result.current.requestProjectSave();
    });

    const [first, second] = (projectsApi.update as jest.Mock).mock.calls.map(
      (call) => call[1],
    );
    expect(typeof first.saveTab).toBe("string");
    expect(first.saveTab).not.toBe("");
    expect(second.saveTab).toBe(first.saveTab);
    expect(Number.isInteger(first.saveNumber)).toBe(true);
    expect(second.saveNumber).toBe(first.saveNumber + 1);
  });

  it("gives up on a save the server never answers after 2 minutes, and sends the next", async () => {
    // A PUT left waiting forever would hold every save behind it. This one
    // goes through the real API client, down to fetch.
    jest.useFakeTimers();
    const actual = jest.requireActual("../../api/projectsApi");
    (projectsApi.update as jest.Mock).mockImplementation(
      (id: string, body: unknown) => actual.projectsApi.update(id, body),
    );
    const realFetch = global.fetch;
    const sent: RequestInit[] = [];
    global.fetch = jest.fn((_url: string, opts: RequestInit = {}) => {
      sent.push(opts);
      if (sent.length === 1) {
        // The first PUT is never answered.
        return new Promise((_resolve, reject) => {
          opts.signal?.addEventListener("abort", () => {
            reject(new DOMException("The operation was aborted.", "AbortError"));
          });
        });
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => SAVED });
    }) as unknown as typeof fetch;
    try {
      const deps = makeDeps();
      const { result } = renderHook(() => useWorkflowOperations(deps));
      await loadedProject(result);

      let first!: Promise<unknown>;
      let second!: Promise<unknown>;
      act(() => {
        first = result.current.requestProjectSave();
        second = result.current.requestProjectSave();
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

      // The queue moved on: the next save went out and was answered.
      await act(async () => {
        await expect(second).resolves.toEqual(SAVED);
      });
      expect(sent).toHaveLength(2);
      // From the same tab and numbered after the first, so the server can
      // refuse the first if it still lands.
      const [firstBody, secondBody] = sent.map((opts) => JSON.parse(String(opts.body)));
      expect(typeof firstBody.saveTab).toBe("string");
      expect(firstBody.saveTab).not.toBe("");
      expect(secondBody.saveTab).toBe(firstBody.saveTab);
      expect(secondBody.saveNumber).toBe(firstBody.saveNumber + 1);
    } finally {
      global.fetch = realFetch;
      (projectsApi.update as jest.Mock).mockResolvedValue(SAVED);
    }
  });
});

/**
 * An edited dataflow whose next save hangs: a Save the server has not
 * answered. Fake timers are on, so the 30 second autosave comes due only when
 * a test moves the clock.
 */
async function hungSaveWithAutosaveArmed() {
  jest.useFakeTimers();
  const deps = makeDeps();
  const { result } = renderHook(() => useWorkflowOperations(deps));
  await loadedProject(result);
  // An edit, so the autosave is armed.
  act(() => {
    result.current.renameDataflow("Edited");
  });
  const answerHung = holdNextUpdate();
  let hung!: Promise<unknown>;
  act(() => {
    hung = result.current.requestProjectSave();
  });
  return { result, answerHung, hung };
}

/** Let `count` 30 second autosaves come due, one after another. */
function autosavesComeDue(count: number) {
  for (let tick = 0; tick < count; tick += 1) {
    act(() => {
      jest.advanceTimersByTime(30_000);
    });
  }
}

/** Answer the hung save, then let every save waiting behind it go out. */
async function answerAndDrain(answerHung: () => void, hung: Promise<unknown>) {
  jest.useRealTimers();
  await act(async () => {
    answerHung();
    await hung;
  });
  // The saves behind it are answered at once, so the whole queue has gone
  // out by the next macrotask.
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

describe("autosaves that come due while a save hangs", () => {
  it("send one autosave once the hung save is answered", async () => {
    // A save waits up to 2 minutes for its answer: four autosaves come due.
    const { answerHung, hung } = await hungSaveWithAutosaveArmed();
    autosavesComeDue(4);
    expect(projectsApi.update).toHaveBeenCalledTimes(1);

    await answerAndDrain(answerHung, hung);
    // The hung save, then one autosave.
    expect(projectsApi.update).toHaveBeenCalledTimes(2);
  });

  it("leave a Save clicked during the hang in its place, after the autosave waiting before it", async () => {
    const { result, answerHung, hung } = await hungSaveWithAutosaveArmed();
    autosavesComeDue(1);
    let save!: Promise<unknown>;
    act(() => {
      save = result.current.requestProjectSave();
    });
    let putsWhenSaveAnswered = -1;
    save.then(
      () => {
        putsWhenSaveAnswered = (projectsApi.update as jest.Mock).mock.calls.length;
      },
      () => undefined,
    );
    autosavesComeDue(3);
    expect(projectsApi.update).toHaveBeenCalledTimes(1);

    await answerAndDrain(answerHung, hung);
    await act(async () => {
      await expect(save).resolves.toEqual(SAVED);
    });
    // The hung save, the autosave that was waiting, then the Save; the
    // autosaves that came due after the click joined the one before it.
    expect(putsWhenSaveAnswered).toBe(3);
    expect(projectsApi.update).toHaveBeenCalledTimes(3);
  });

  it("send the canvas as it is when the autosave goes, numbered right after the hung save", async () => {
    (TrillGenerator.generateTrill as jest.Mock).mockImplementation(
      (nodes: unknown) => ({ dataflow: { datasets: [], nodes } }),
    );
    try {
      const { result, answerHung, hung } = await hungSaveWithAutosaveArmed();
      autosavesComeDue(4);
      // A node added after the last autosave came due.
      mockCanvasNodes = [{ id: "added-during-the-hang" }];
      act(() => {
        result.current.markDirty();
      });

      await answerAndDrain(answerHung, hung);
      const [hungBody, autosaveBody] = (projectsApi.update as jest.Mock).mock.calls.map(
        (call) => call[1],
      );
      expect(hungBody.spec.dataflow.nodes).toEqual([]);
      expect(autosaveBody.spec.dataflow.nodes).toEqual([{ id: "added-during-the-hang" }]);
      expect(autosaveBody.saveTab).toBe(hungBody.saveTab);
      expect(autosaveBody.saveNumber).toBe(hungBody.saveNumber + 1);
    } finally {
      (TrillGenerator.generateTrill as jest.Mock).mockImplementation(() => ({
        dataflow: { datasets: [] },
      }));
    }
  });
});
