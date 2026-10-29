/**
 * New rows draw a Vega-Lite chart again as a Play does: compiled, recorded in
 * its provenance and handed on, even when its view has drawn them already.
 *
 * New rows reach a chart on two paths at once. useVega swaps them into the
 * view the chart holds and says what it drew. UniversalNode draws the chart
 * again: it sets the node running and calls `sendCode`, and the spec reaches
 * GrammarEditor through the widgets pass, which compiles only a node that is
 * still running. A browser runs other work between those steps, so the swap
 * could say the chart was drawn before the spec got there. GrammarEditor then
 * found a node already done and compiled nothing: the chart showed the new
 * rows, but it handed nothing on, so the nodes it feeds kept the rows it gave
 * them before, and its provenance recorded no draw. Seen in 4 of 8 runs of the
 * dashboard pick test (CI run 40337748122).
 *
 * The node, its editor (NodeEditor, WidgetsEditor and GrammarEditor), the
 * Vega-Lite behavior and useVega are real here; vega and vega-lite are the
 * mocks below. React runs on its mock scheduler, and the test lets promises
 * settle after each commit, as a browser runs other work between React's
 * tasks. So the swap's report lands where it landed in the browser: after the
 * node was set running, before its spec reached GrammarEditor. The chart here
 * is on the canvas, where new rows reach it outside a run whenever a Data Pool
 * above it fetches, or a run that left it out ends.
 */
import React from "react";
import { act, render } from "@testing-library/react";

// React's own test scheduler: work React schedules outside act waits until the
// test runs it (`landsLikeInABrowser`).
jest.mock("scheduler", () => require("scheduler/unstable_mock"));

// What useVega calls on the library. A view keeps the spec it was built from
// and the datasets new rows were swapped into, and draws one mark.
jest.mock("vega", () => {
  const views: any[] = [];
  const changeset = () => {
    const cs: any = { remove: () => cs, insert: () => cs, modify: () => cs };
    return cs;
  };
  class View {
    spec: any;
    swapped: string[] = [];
    constructor(spec: any) {
      this.spec = spec;
      views.push(this);
    }
    logLevel() { return this; }
    renderer() { return this; }
    initialize() { return this; }
    tooltip() { return this; }
    hover() { return this; }
    addEventListener() { return this; }
    width() { return this; }
    height() { return this; }
    resize() { return this; }
    runAsync() { return Promise.resolve(this); }
    change(name: string) {
      this.swapped.push(name);
      return this;
    }
    scenegraph() {
      return { root: { marktype: "rect", items: [{ datum: { _vgsid_: 1, __row_index__: 0 } }] } };
    }
    getState() { return { signals: {}, data: {} }; }
    addSignalListener() {}
  }
  return { changeset, View, parse: (spec: any) => spec, Warn: 2, __views: views };
}, { virtual: true });
jest.mock("vega-lite", () => ({ compile: (spec: any) => ({ spec }) }), { virtual: true });

// The flow around the chart, set per test and read on every render.
let mockFlow: Record<string, unknown> = {};
jest.mock("../../providers/FlowProvider", () => ({ useFlowContext: () => mockFlow }));
const mockProvenance = jest.fn();
jest.mock("../../providers/ProvenanceProvider", () => ({
  useProvenanceContext: () => ({ nodeExecProv: mockProvenance }),
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
jest.mock("@monaco-editor/react", () => ({ __esModule: true, default: () => null }));

jest.mock("reactflow", () => ({
  Handle: () => null,
  Position: { Left: "left", Right: "right", Top: "top", Bottom: "bottom" },
  useEdges: () => [],
  useUpdateNodeInternals: () => () => undefined,
}));
jest.mock("../../components/styles", () => ({
  NodeContainer: ({ children }: any) => <div>{children}</div>,
}));
jest.mock("../../components/DescriptionModal", () => ({ __esModule: true, default: () => null }));
jest.mock("../../components/edges/OutputIcon", () => ({ OutputIcon: () => null }));
jest.mock("../../components/edges/InputIcon", () => ({ InputIcon: () => null }));
jest.mock("../../components/UnresolvedNode", () => ({ UnresolvedNode: () => null }));
jest.mock("../../components/agents/attach/NodeAgentBadges", () => ({ NodeAgentBadges: () => null }));
jest.mock("../../components/nodes/NodeOutcomeStrip", () => ({ NodeOutcomeStrip: () => null }));
jest.mock("../../registry/nodeRegistry", () => {
  // The built-in chart, drawn by the Vega-Lite behavior: the same hook on
  // every render, as the registry hands it.
  const chart = {
    id: "curio.builtin/vis-vega",
    hasCode: false,
    hasGrammar: true,
    hasWidgets: true,
    adapter: {
      handles: [],
      editor: {},
      container: {},
      useNodeBehavior: (data: any, nodeState: any) =>
        require("../../adapters/node/vegaBehavior").useVegaBehavior(data, nodeState),
    },
  };
  const byType = (type: string) => (type === chart.id ? chart : undefined);
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
// The node's state as useNodeState holds it, with each outcome it is given.
const mockOutcomes: string[] = [];
jest.mock("../../hook/useNodeState", () => {
  const React = require("react");
  return {
    useNodeState: (data: any) => {
      const [output, setOutputState] = React.useState(data.output ?? { code: "", content: "" });
      const [code, setCode] = React.useState(data.code ?? "");
      const [sendCode, setSendCode] = React.useState(undefined);
      const setOutput = React.useCallback((next: any) => {
        mockOutcomes.push(next?.code);
        setOutputState(next);
      }, []);
      return {
        output,
        setOutput,
        code,
        setCode,
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

import UniversalNode from "../../components/UniversalNode";

type MockScheduler = {
  unstable_flushUntilNextPaint: () => void;
  unstable_flushAllWithoutAsserting: () => boolean;
  unstable_getFirstCallbackNode: () => unknown;
};
const Scheduler = jest.requireMock("scheduler") as MockScheduler;
const views = (): any[] => (jest.requireMock("vega") as { __views: any[] }).__views;

const CHART = "chart";
const VEGA = "curio.builtin/vis-vega";
const SPEC = JSON.stringify({
  mark: "bar",
  width: 300,
  height: 200,
  encoding: {
    x: { field: "category", type: "nominal" },
    y: { field: "count", type: "quantitative" },
  },
});
/** The rows the chart opens with, and the rows that reach it next, each one
 * object, as the flow hands them. */
const THREE = { dataType: "dataframe", data: { category: ["a", "b", "c"], count: [3, 7, 5] } };
const FIVE = {
  dataType: "dataframe",
  data: { category: ["a", "b", "c", "d", "e"], count: [3, 7, 5, 9, 4] },
};

/** What the chart hands the nodes it feeds (the flow's `outputCallback`). */
const handedOn = jest.fn();
let deliver: (input: unknown) => void = () => undefined;

/** The chart on the canvas, its rows set from outside as the flow sets them. */
function Canvas() {
  const [input, setInput] = React.useState<unknown>(THREE);
  deliver = setInput;
  const data = React.useMemo(
    () => ({
      nodeId: CHART,
      nodeType: VEGA,
      code: SPEC,
      defaultCode: SPEC,
      input,
      outputCallback: handedOn,
      interactionsCallback: () => undefined,
      propagationCallback: () => undefined,
    }),
    [input],
  );
  return <UniversalNode data={data} isConnectable />;
}

/** The chart opened on its rows, as a reload draws it, and settled. */
async function opened() {
  await act(async () => {
    render(<Canvas />);
  });
  await act(async () => undefined);
}

const nextTask = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

/**
 * Hands the chart *input* outside act, then runs what React scheduled one
 * commit at a time, letting promises settle after each, as a browser runs
 * other work between React's tasks.
 */
async function landsLikeInABrowser(input: unknown) {
  const env = globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean };
  const actEnvironment = env.IS_REACT_ACT_ENVIRONMENT;
  env.IS_REACT_ACT_ENVIRONMENT = false;
  try {
    deliver(input);
    for (let commits = 0; commits < 100; commits++) {
      if (Scheduler.unstable_getFirstCallbackNode() === null) {
        await nextTask();
        if (Scheduler.unstable_getFirstCallbackNode() === null) return;
      }
      Scheduler.unstable_flushUntilNextPaint();
      await nextTask();
    }
    throw new Error("the page was still busy after 100 commits");
  } finally {
    Scheduler.unstable_flushAllWithoutAsserting();
    env.IS_REACT_ACT_ENVIRONMENT = actEnvironment;
  }
}

beforeAll(() => {
  (globalThis as any).ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

beforeEach(() => {
  views().length = 0;
  handedOn.mockClear();
  mockProvenance.mockClear();
  mockOutcomes.length = 0;
  // A node upstream wired into the chart, nothing running.
  mockFlow = {
    nodes: [
      { id: "up", type: "__curioUniversalNode", data: { nodeId: "up", nodeType: "curio.builtin/computation-analysis" } },
      { id: CHART, type: "__curioUniversalNode", data: { nodeId: CHART, nodeType: VEGA } },
    ],
    edges: [{ id: "up->chart", source: "up", target: CHART, sourceHandle: "out", targetHandle: "in" }],
    scenarios: [],
    nodeExecStatus: {},
    dashboardOn: false,
    dashboardStopped: null,
    projectId: "p1",
    isRunActive: false,
    serverRunActive: false,
    workflowNameRef: { current: "wf" },
    signalNodeExecDone: () => undefined,
    playNodesUpTo: () => undefined,
    markDirty: () => undefined,
    markNodeStale: () => undefined,
    markNodeErrored: () => undefined,
    requestAutoRun: () => undefined,
    clearSelectionTagsOf: () => undefined,
  };
});

test("a chart opened on its rows compiles them and hands them on", async () => {
  await opened();

  expect(views().length).toBeGreaterThan(0);
  expect(mockProvenance).toHaveBeenCalled();
  expect(handedOn).toHaveBeenLastCalledWith(CHART, THREE);
  expect(mockOutcomes[mockOutcomes.length - 1]).toBe("success");
});

test("new rows draw the chart again, compiled and handed on, though its view drew them first", async () => {
  await opened();
  const viewsBefore = views().length;
  const outcomesBefore = mockOutcomes.length;
  const recordsBefore = mockProvenance.mock.calls.length;
  const shown = views()[viewsBefore - 1];

  await landsLikeInABrowser(FIVE);

  // Both paths ran: the rows went into the view the chart held,
  expect(shown.swapped).toEqual(["input_0"]);
  // and the chart was set running, then said it was done.
  expect(mockOutcomes.slice(outcomesBefore)).toEqual(["exec", "success"]);
  // Done means compiled: a view built from the new rows,
  expect(views()).toHaveLength(viewsBefore + 1);
  // the draw recorded in the chart's provenance,
  expect(mockProvenance).toHaveBeenCalledTimes(recordsBefore + 1);
  // and the new rows handed on to the nodes the chart feeds.
  expect(handedOn).toHaveBeenLastCalledWith(CHART, FIVE);
});
