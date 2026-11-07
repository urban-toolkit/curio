/**
 * A Simple View that a run asks while it reads its input counts as done only
 * once it has handed its rows on.
 *
 * Example 10's Run All e2e (`test_run_all_draws_every_chart_without_an_empty_render`)
 * failed on CI run 42328180392: route two's Spatial Join said "The Spatial
 * Join has no input_0 to join", while the Simple View feeding it read Done.
 * The run on the server ended with route two's Image Segmentation, and the
 * page applied its output and asked the nodes only a browser runs in the same
 * task, so the Simple View got its new input and the run's ask in one render.
 * It hands its rows on only once it has read them (a fetch of the artifact),
 * but it has no Play, so UniversalNode counted it done the moment the run
 * asked, and the run asked the join before the rows landed.
 *
 * The node, its Simple View behavior and its state are real here. The read
 * (`fetchData`) waits until the test lets it end.
 */
import React from "react";
import { act, render } from "@testing-library/react";

const mockFetchData = jest.fn();

jest.mock("reactflow", () => ({
  Handle: () => null,
  Position: { Left: "left", Right: "right", Top: "top", Bottom: "bottom" },
  useEdges: () => [{ id: "seg->view", source: "seg", target: "view", sourceHandle: "out", targetHandle: "in" }],
  useUpdateNodeInternals: () => () => undefined,
}));
jest.mock("../../components/styles", () => ({
  NodeContainer: ({ children }: any) => <div>{children}</div>,
}));
jest.mock("../../components/editing/NodeEditor", () => ({ __esModule: true, default: () => null }));
jest.mock("../../components/DescriptionModal", () => ({ __esModule: true, default: () => null }));
jest.mock("../../components/edges/OutputIcon", () => ({ OutputIcon: () => null }));
jest.mock("../../components/edges/InputIcon", () => ({ InputIcon: () => null }));
jest.mock("../../components/UnresolvedNode", () => ({ UnresolvedNode: () => null }));
jest.mock("../../components/agents/attach/NodeAgentBadges", () => ({ NodeAgentBadges: () => null }));
jest.mock("../../components/nodes/NodeOutcomeStrip", () => ({ NodeOutcomeStrip: () => null }));
jest.mock("../../registry/nodeRegistry", () => {
  // The built-in Simple View, drawn by its own behavior.
  const view = {
    id: "curio.builtin/vis-simple",
    hasCode: false,
    hasGrammar: false,
    hasWidgets: false,
    adapter: {
      handles: [],
      editor: {},
      container: {},
      useNodeBehavior: (data: any, nodeState: any) =>
        require("../../adapters/node/simpleVisBehavior").useSimpleVisBehavior(data, nodeState),
    },
  };
  const byType = (type: string) => (type === view.id ? view : undefined);
  return {
    getNodeDescriptor: byType,
    tryGetNodeDescriptor: byType,
    subscribeToRegistry: () => () => undefined,
  };
});
jest.mock("../../registry/registryReadiness", () => ({
  isRegistryReady: () => true,
  subscribeToRegistryReady: () => () => undefined,
}));
jest.mock("../../hook/useNodeState", () => {
  const React = require("react");
  return {
    useNodeState: (data: any) => {
      const [output, setOutput] = React.useState(data.output ?? { code: "", content: "" });
      const [sendCode, setSendCode] = React.useState(undefined);
      return {
        output,
        setOutput,
        code: data.code ?? "",
        setCode: () => undefined,
        sendCode,
        setSendCodeCallback: (fn: any) => setSendCode(() => fn),
        templateData: {},
        user: null,
        promptDescription: () => undefined,
        closeDescription: () => undefined,
        showDescriptionModal: false,
      };
    },
  };
});
// The flow around the view, set per test and read on every render.
let mockFlow: Record<string, unknown> = {};
jest.mock("../../providers/FlowProvider", () => ({ useFlowContext: () => mockFlow }));
jest.mock("../../providers/ProvenanceProvider", () => ({
  useProvenanceContext: () => ({ nodeExecProv: () => undefined }),
}));
jest.mock("../../providers/ToastProvider", () => ({ useToastContext: () => ({ showToast: () => undefined }) }));
jest.mock("../../providers/CollaborationProvider", () => ({
  useCollab: () => ({
    connected: false,
    users: [],
    lockedNodes: {},
    onRemote: () => () => undefined,
  }),
}));
jest.mock("../../services/api", () => ({ fetchData: (...args: unknown[]) => mockFetchData(...args) }));
jest.mock("../../utils/backendUrl", () => ({ backendUrl: () => "http://backend.test" }));
jest.mock("../../utils/authApi", () => ({ getToken: () => "tok-123" }));

import UniversalNode from "../../components/UniversalNode";

const VIEW = "view";
/** What route two's Image Segmentation hands the view: its artifact, to read. */
const SEGMENTED = { path: "seg-artifact", dataType: "dataframe" };
/** What the read of that artifact answers. */
const ROWS = { dataType: "dataframe", data: { dominant_class: ["road", "building"], dominant_pct: [24.13, 45.16] } };
/** An input that carries its rows, which the view reads with no fetch. */
const CARRIED = { dataType: "dataframe", data: { dominant_class: ["road"] } };

/** What reached the nodes the view feeds, and each time a run was told it was done, in order. */
const happened: string[] = [];
const DONE = `done ${VIEW}`;

function viewData(extra: Record<string, unknown> = {}) {
  return {
    nodeId: VIEW,
    nodeType: "curio.builtin/vis-simple",
    input: "",
    outputCallback: (_nodeId: string, output: any) => happened.push(`handed on ${output?.path ?? "rows"}`),
    interactionsCallback: () => undefined,
    ...extra,
  };
}

async function mount(nodeData: any) {
  let utils: ReturnType<typeof render>;
  await act(async () => {
    utils = render(<UniversalNode data={nodeData} isConnectable />);
  });
  return utils!;
}

/** Lets the promises and timers the node started run. */
async function settle() {
  for (let i = 0; i < 5; i++) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }
}

/** The view's reads, each held until the test ends it. */
function holdReads() {
  const reads: Array<{ end: (rows: unknown) => void; fail: (err: Error) => void }> = [];
  mockFetchData.mockImplementation(() => new Promise((resolve, reject) => {
    reads.push({ end: resolve, fail: reject });
  }));
  return reads;
}

beforeAll(() => {
  (globalThis as any).ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

beforeEach(() => {
  happened.length = 0;
  mockFetchData.mockReset();
  // A segmentation wired into the view, and a run going on.
  mockFlow = {
    nodes: [
      { id: "seg", type: "__curioUniversalNode", data: { nodeId: "seg", nodeType: "model.curio.ddrnet23-slim/image-segmentation" } },
      { id: VIEW, type: "__curioUniversalNode", data: { nodeId: VIEW, nodeType: "curio.builtin/vis-simple" } },
    ],
    edges: [{ id: "seg->view", source: "seg", target: VIEW, sourceHandle: "out", targetHandle: "in" }],
    scenarios: [],
    nodeExecStatus: {},
    dashboardOn: false,
    dashboardStopped: null,
    projectId: "p1",
    isRunActive: true,
    serverRunActive: false,
    workflowNameRef: { current: "wf" },
    updateDataNode: () => undefined,
    signalNodeExecDone: (nodeId: string) => happened.push(`done ${nodeId}`),
    playNodesUpTo: () => undefined,
    markDirty: () => undefined,
    markNodeStale: () => undefined,
    markNodeErrored: () => undefined,
    requestAutoRun: () => undefined,
    clearSelectionTagsOf: () => undefined,
  };
});

describe("a Simple View a run asks in the render that brings its input", () => {
  test("is done once its rows have gone on, not while it reads them", async () => {
    // CI run 42328180392: the segmentation's output and the run's ask in one render.
    const reads = holdReads();
    const utils = await mount(viewData());

    await act(async () => {
      utils.rerender(<UniversalNode data={viewData({ input: SEGMENTED, triggerExec: 1 })} isConnectable />);
    });
    await settle();

    // Still reading: the run must not move on to the node it feeds.
    expect(happened).toEqual([]);

    await act(async () => {
      reads[0].end(ROWS);
    });
    await settle();

    expect(happened[0]).toBe("handed on seg-artifact");
    expect(happened.slice(1)).toContain(DONE);
  });

  test("whose read fails is done once the read has failed, not while it reads", async () => {
    const reads = holdReads();
    const utils = await mount(viewData());

    await act(async () => {
      utils.rerender(<UniversalNode data={viewData({ input: SEGMENTED, triggerExec: 1 })} isConnectable />);
    });
    await settle();

    expect(happened).toEqual([]);

    await act(async () => {
      reads[0].fail(new Error("HTTP 504"));
    });
    await settle();

    // Nothing to hand on; the run is told the view is done, and moves on.
    expect(happened).toContain(DONE);
    expect(happened.filter((line) => line.startsWith("handed on"))).toEqual([]);
  });

  test("whose input carries its rows hands them on, then is done", async () => {
    const utils = await mount(viewData());

    await act(async () => {
      utils.rerender(<UniversalNode data={viewData({ input: CARRIED, triggerExec: 1 })} isConnectable />);
    });
    await settle();

    expect(mockFetchData).not.toHaveBeenCalled();
    expect(happened[0]).toBe("handed on rows");
    expect(happened.slice(1)).toContain(DONE);
  });
});

describe("a Simple View a run asks with nothing being read", () => {
  test("with no input, is done as the run asks", async () => {
    const utils = await mount(viewData());

    await act(async () => {
      utils.rerender(<UniversalNode data={viewData({ triggerExec: 1 })} isConnectable />);
    });
    await settle();

    expect(happened).toEqual([DONE]);
  });

  test("asked again with the input it handed on, is done and hands nothing on again", async () => {
    mockFetchData.mockResolvedValue(ROWS);
    const utils = await mount(viewData());
    await act(async () => {
      utils.rerender(<UniversalNode data={viewData({ input: SEGMENTED })} isConnectable />);
    });
    await settle();
    expect(happened.filter((line) => line.startsWith("handed on"))).toEqual(["handed on seg-artifact"]);
    const before = happened.length;

    await act(async () => {
      utils.rerender(<UniversalNode data={viewData({ input: SEGMENTED, triggerExec: 1 })} isConnectable />);
    });
    await settle();

    expect(happened.slice(before)).toEqual([DONE]);
    expect(mockFetchData).toHaveBeenCalledTimes(1);
  });
});
