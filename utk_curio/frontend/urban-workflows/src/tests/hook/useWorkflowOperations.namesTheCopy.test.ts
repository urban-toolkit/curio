/**
 * The canvas's load of a dataflow names the id the page names it by from then
 * on (`utils/requestHeaders.ts`): for a hosted guest on an example, the
 * guest's own copy of it, which the load's answer gives (`copy_id`), else the
 * dataflow itself. The server keeps each copy on the backend process its own
 * id names, so the guests of one example spread over the processes.
 *
 * The load names it as its answer comes, before `loadProject` hands that
 * answer to ProjectLoader, which builds the canvas from it: the room's socket,
 * which waits for the name, and every request a node or a panel sends after
 * name the copy. A load from the dataflow's link names the dataflow itself.
 * The guest's dashboard of the example loads it with the same `loadProject`,
 * and names the copy the same way: its viewer's runs are the copy's process's.
 *
 * The helper is loaded in each test, so a checkout without it fails each test
 * on its own.
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
const mockGet = jest.fn();
const mockGetShared = jest.fn();
jest.mock("../../api/projectsApi", () => ({
  projectsApi: {
    create: jest.fn(),
    update: jest.fn(),
    get: (...args: unknown[]) => mockGet(...args),
    getShared: (...args: unknown[]) => mockGetShared(...args),
  },
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

const HEADER = "X-Curio-Dataflow";
/** The example the canvas opens, and a hosted guest's own copy of it. */
const EXAMPLE = "11111111-2222-4333-8444-555555555555";
const COPY = "99999999-8888-5777-a666-555555555555";

/** The helper, loaded when a test asks for it. */
const names = (): any => require("../../utils/requestHeaders");

/** The load's answer, with the copy it names when *copy* is given. */
function answer(copy?: string | null) {
  return {
    project: { id: EXAMPLE, name: "Example", updated_at: null, categories: {} },
    spec: { dataflow: { nodes: [], edges: [] } },
    outputs: [],
    ...(copy === undefined ? {} : { copy_id: copy }),
  };
}

function renderOperations() {
  const deps = {
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
  } as any;
  return renderHook(() => useWorkflowOperations(deps));
}

beforeEach(() => {
  mockGet.mockReset();
  mockGetShared.mockReset();
  // The canvas of the example, whose load ProjectLoader has started.
  window.history.replaceState(null, "", `/dataflow/${EXAMPLE}`);
  names().awaitDataflowName(EXAMPLE);
});

afterEach(() => {
  window.history.replaceState(null, "", "/");
  names().resetDataflowNames?.();
});

test("a hosted guest's load names its own copy by the time it hands its answer on", async () => {
  mockGet.mockResolvedValue(answer(COPY));
  const { result } = renderOperations();

  let named: Record<string, string> | undefined;
  await act(async () => {
    await result.current.loadProject(EXAMPLE, { lastResults: true });
    named = { header: names().requestHeaders("tok")[HEADER], ...names().socketQuery(EXAMPLE) };
  });

  expect(named).toEqual({ header: COPY, dataflow: COPY });
  expect(names().dataflowNameKnown(EXAMPLE)).toBe(true);
  // A request that names the example itself names the copy too.
  expect(names().requestHeaders("tok", {}, EXAMPLE)[HEADER]).toBe(COPY);
});

test("a hosted guest's dashboard load names its own copy by the time it hands its answer on", async () => {
  // The dashboard of the example, whose load ProjectLoader has started with
  // the saved outputs, not the results a canvas was left with.
  window.history.replaceState(null, "", `/dashboard/${EXAMPLE}`);
  mockGet.mockResolvedValue(answer(COPY));
  const { result } = renderOperations();

  let named: string | undefined;
  await act(async () => {
    await result.current.loadProject(EXAMPLE);
    named = names().requestHeaders("tok")[HEADER];
  });

  expect(named).toBe(COPY);
  // A request that names the example itself, a viewer's run of it, names the copy too.
  expect(names().requestHeaders("tok", {}, EXAMPLE)[HEADER]).toBe(COPY);
});

test.each([
  ["an account's load, which names no copy", null],
  ["an answer that says nothing of a copy", undefined],
])("%s names the dataflow itself", async (_what, copy) => {
  mockGet.mockResolvedValue(answer(copy));
  const { result } = renderOperations();

  await act(async () => {
    await result.current.loadProject(EXAMPLE);
  });

  expect(names().dataflowNameKnown(EXAMPLE)).toBe(true);
  expect(names().requestHeaders("tok")[HEADER]).toBe(EXAMPLE);
  expect(names().socketQuery(EXAMPLE)).toEqual({ dataflow: EXAMPLE });
});

test("a load from the dataflow's link names the dataflow itself", async () => {
  mockGetShared.mockResolvedValue(answer());
  const { result } = renderOperations();

  await act(async () => {
    await result.current.loadSharedProject(EXAMPLE);
  });

  expect(names().dataflowNameKnown(EXAMPLE)).toBe(true);
  expect(names().socketQuery(EXAMPLE)).toEqual({ dataflow: EXAMPLE });
});

test("a load the page left names nothing", async () => {
  const left = new AbortController();
  mockGet.mockImplementation(async () => {
    left.abort();
    return answer(COPY);
  });
  const { result } = renderOperations();

  await act(async () => {
    await expect(result.current.loadProject(EXAMPLE, { signal: left.signal })).rejects.toThrow();
  });

  expect(names().requestHeaders("tok")[HEADER]).toBe(EXAMPLE);
  // ProjectLoader lets the socket go on when the page leaves the load.
  expect(names().dataflowNameKnown(EXAMPLE)).toBe(false);
});
