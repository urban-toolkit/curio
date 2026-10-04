/**
 * Charts draw from a restored input without anyone pressing Play.
 *
 * A grammar node only ever drew when a Play called its `applyGrammar`. That is
 * why a reloaded dataflow showed empty chart boxes, and it is fatal on the
 * dashboard, which has no play button at all. `UniversalNode` now compiles a
 * chart the same way Play does (through `sendCode`, so widget markers are still
 * resolved first) when an input arrives.
 *
 * The rules are narrow on purpose, and each case below is one of them:
 *
 *  - A Vega chart and an Autark map (a document that draws a map or a plot)
 *    follow one rule, and the table below runs every case for both: draw
 *    whenever an input and a document are there, on either route, once per
 *    input. A selection, coming back through a Data Pool or across a direct
 *    interaction edge, is not a new input: the node highlights the matched
 *    rows in the view it has.
 *  - Only an Autark node: it needs WebGPU; a data or compute step never draws
 *    on its own (on the dashboard their layers come from the Data Catalog);
 *    a pinned tile with no input draws once on the dashboard.
 *  - Code nodes: never. Their pane shows a run's stdout, which nothing restores,
 *    and running one would execute the user's code because a page was opened.
 */
import React from "react";
import { act, render } from "@testing-library/react";

const mockSendCode = jest.fn();
const mockSetOutput = jest.fn();
let mockDashboardOn = false;
let mockFlowEdges: any[] = [];
let mockIsRunActive = false;
let mockWebGpuSupported = true;
jest.mock("../../utils/webgpuSupport", () => ({
  detectWebGpuSupport: () => Promise.resolve({ supported: mockWebGpuSupported }),
}));

jest.mock("reactflow", () => ({
  Handle: () => null,
  useEdges: () => [],
  useUpdateNodeInternals: () => () => undefined,
}));
jest.mock("../../components/styles", () => ({
  NodeContainer: ({ children }: any) => <div>{children}</div>,
}));
jest.mock("../../components/editing/NodeEditor", () => {
  const React = require("react");
  return {
    __esModule: true,
    // Registers the play entry point on mount, exactly as the real editor does.
    default: ({ setSendCodeCallback }: any) => {
      React.useEffect(() => { setSendCodeCallback(mockSendCode); }, []);
      return null;
    },
  };
});
jest.mock("../../components/DescriptionModal", () => ({ __esModule: true, default: () => null }));
jest.mock("../../components/edges/OutputIcon", () => ({ OutputIcon: () => null }));
jest.mock("../../components/edges/InputIcon", () => ({ InputIcon: () => null }));
jest.mock("../../components/UnresolvedNode", () => ({ UnresolvedNode: () => null }));
jest.mock("../../components/agents/attach/NodeAgentBadges", () => ({ NodeAgentBadges: () => null }));
jest.mock("../../registry/nodeRegistry", () => {
  const descriptor = (id: string, grammar: boolean) => ({
    id,
    hasCode: !grammar,
    hasGrammar: grammar,
    hasWidgets: true,
    adapter: {
      handles: [],
      editor: {},
      container: {},
      useNodeBehavior: () => ({}),
    },
  });
  const byType: Record<string, any> = {
    "curio.builtin/vis-vega": descriptor("curio.builtin/vis-vega", true),
    "curio.builtin/autk-grammar": descriptor("curio.builtin/autk-grammar", true),
    "curio.builtin/computation-analysis": descriptor("curio.builtin/computation-analysis", false),
  };
  return {
    getNodeDescriptor: (type: string) => byType[type],
    tryGetNodeDescriptor: (type: string) => byType[type],
    subscribeToRegistry: () => () => {},
  };
});
jest.mock("../../registry/registryReadiness", () => ({
  isRegistryReady: () => true,
  subscribeToRegistryReady: () => () => {},
}));
jest.mock("../../hook/useNodeState", () => {
  const React = require("react");
  return {
    useNodeState: (data: any) => {
      const [sendCode, setSendCode] = React.useState(undefined);
      return {
        // ``data.output`` lets a test start the node mid-compile, the state the
        // runner leaves it in.
        output: data.output ?? { code: "", content: "" },
        setOutput: mockSetOutput,
        code: data.code ?? "",
        setCode: () => {},
        sendCode,
        setSendCodeCallback: (fn: any) => setSendCode(() => fn),
        templateData: {},
        user: null,
        promptDescription: () => {},
        closeDescription: () => {},
        showDescriptionModal: false,
      };
    },
  };
});
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    signalNodeExecDone: () => {},
    dashboardOn: mockDashboardOn,
    edges: mockFlowEdges,
    isRunActive: mockIsRunActive,
  }),
}));
jest.mock("../../providers/CollaborationProvider", () => ({
  useCollab: () => ({ enabled: false, lockedNodes: {}, currentUserId: null }),
}));

import UniversalNode from "../../components/UniversalNode";
import { markSelectionEcho } from "../../utils/selectionEcho";

const VEGA = "curio.builtin/vis-vega";
const AUTARK = "curio.builtin/autk-grammar";
const PYTHON = "curio.builtin/computation-analysis";
const VEGA_SPEC = JSON.stringify({ mark: "bar" });
const MAP_SPEC = JSON.stringify({ map: { layerRefs: [] } });
const DATA_SPEC = JSON.stringify({ data: [{ type: "osm" }] });
const INPUT_A = { path: "art_a", dataType: "dataframe" };
const INPUT_B = { path: "art_b", dataType: "dataframe" };

function data(nodeType: string, extra: Record<string, unknown> = {}) {
  return { nodeId: "n1", nodeType, input: "", ...extra };
}

async function mount(nodeData: any) {
  let utils: ReturnType<typeof render>;
  await act(async () => {
    utils = render(<UniversalNode data={nodeData} isConnectable />);
  });
  return utils!;
}

async function rerenderWith(utils: ReturnType<typeof render>, nodeData: any) {
  await act(async () => {
    utils.rerender(<UniversalNode data={nodeData} isConnectable />);
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  mockDashboardOn = false;
  mockFlowEdges = [];
  mockIsRunActive = false;
  mockWebGpuSupported = true;
});

// The redraw rule, one table: every case runs for a Vega chart and for an
// Autark map. What only an Autark node does follows the table.
describe.each([
  ["a Vega chart", VEGA, VEGA_SPEC, "spec"],
  ["an Autark map", AUTARK, MAP_SPEC, "document"],
])("%s", (_name, type, spec, docWord) => {
  const node = (extra: Record<string, unknown> = {}) => data(type, { code: spec, ...extra });
  // An Autark draw waits for its WebGPU probe, which answers asynchronously.
  const settle = () => act(async () => {});
  const open = async (nodeData: any) => {
    const utils = await mount(nodeData);
    await settle();
    return utils;
  };
  const next = async (utils: ReturnType<typeof render>, nodeData: any) => {
    await rerenderWith(utils, nodeData);
    await settle();
  };
  const wire = () => { mockFlowEdges = [{ id: "e", source: "up", target: "n1" }]; };

  test("draws from a restored input on the canvas, like a Play would", async () => {
    await open(node({ input: INPUT_A }));

    expect(mockSetOutput).toHaveBeenCalledWith({ code: "exec", content: "" });
    expect(mockSendCode).toHaveBeenCalledTimes(1);
    expect(mockSendCode).toHaveBeenCalledWith(spec);
  });

  test("and as a tile on the dashboard", async () => {
    mockDashboardOn = true;
    wire();

    await open(node({ input: INPUT_A, dashboardPinned: true }));

    expect(mockSendCode).toHaveBeenCalledTimes(1);
  });

  test("a wired tile draws when its input lands", async () => {
    mockDashboardOn = true;
    wire();
    const utils = await open(node({ dashboardPinned: true }));
    expect(mockSendCode).not.toHaveBeenCalled();

    await next(utils, node({ dashboardPinned: true, input: INPUT_A }));

    expect(mockSendCode).toHaveBeenCalledTimes(1);
  });

  test("the same input is never drawn twice", async () => {
    const utils = await open(node({ input: INPUT_A }));

    await next(utils, node({ input: INPUT_A }));

    expect(mockSendCode).toHaveBeenCalledTimes(1);
  });

  test("a new input draws again", async () => {
    // A node behind a Data Pool gets its rows when the pool's fetch lands.
    const utils = await open(node({ input: INPUT_A }));

    await next(utils, node({ input: INPUT_B }));

    expect(mockSendCode).toHaveBeenCalledTimes(2);
  });

  test("a selection coming back through a Data Pool highlights; it does not redraw", async () => {
    // Same rows, new `interacted` flags, highlighted in the view the node has.
    // Rebuilding it would throw its own selection away.
    const utils = await open(node({ input: INPUT_A }));

    await next(utils, node({ input: markSelectionEcho({ dataType: "dataframe", data: { a: [1] } }) }));

    expect(mockSendCode).toHaveBeenCalledTimes(1);
  });

  test("new data after a selection still draws", async () => {
    const utils = await open(node({ input: INPUT_A }));
    await next(utils, node({ input: markSelectionEcho({ dataType: "dataframe", data: { a: [1] } }) }));

    await next(utils, node({ input: INPUT_B }));

    expect(mockSendCode).toHaveBeenCalledTimes(2);
  });

  test("a selection across a direct interaction edge highlights; it does not redraw", async () => {
    const utils = await open(node({ input: INPUT_A }));

    await next(utils, node({
      input: INPUT_A,
      interactions: [{ nodeId: "bars", type: "POINT", data: { selected: [0] }, source: "bars" }],
    }));

    expect(mockSendCode).toHaveBeenCalledTimes(1);
  });

  test("nothing to draw from, nothing drawn", async () => {
    // Drawing against no rows would replace the "connect something" message
    // with an empty frame and mark the node done.
    await open(node({ input: "" }));

    expect(mockSendCode).not.toHaveBeenCalled();
  });

  test(`no ${docWord}, nothing drawn`, async () => {
    // The starter arrives a beat later; drawing "" would throw on parse.
    await open(node({ code: "", input: INPUT_A }));

    expect(mockSendCode).not.toHaveBeenCalled();
  });

  test(`the ${docWord} the starter fill guessed is not drawn on its own`, async () => {
    // Wiring a fresh node to one that has already run: the input lands on an
    // empty buffer, the behavior writes a starter guessed from its columns,
    // and that arrives as a second render. Drawing it would run the node on
    // connect and pull the editor to its output pane while the author is
    // still typing the real one into it.
    const utils = await open(node({ code: "", input: INPUT_A }));

    await next(utils, node({ input: INPUT_A }));

    expect(mockSendCode).not.toHaveBeenCalled();
  });

  test(`but the next input draws, because the author has a ${docWord} by then`, async () => {
    const utils = await open(node({ code: "", input: INPUT_A }));
    await next(utils, node({ input: INPUT_A }));

    await next(utils, node({ input: INPUT_B }));

    expect(mockSendCode).toHaveBeenCalledTimes(1);
    expect(mockSendCode).toHaveBeenCalledWith(spec);
  });

  test(`a reopened node is not held back that way, though its input lands before its ${docWord} (#711)`, async () => {
    // On a reopen the editor mounts on `{}` and floats it into the buffer
    // until Monaco loads and applies the saved document, and the restored
    // input lands in that window. The node was written with its document, so
    // nobody is wiring an empty node: it draws once the document is back.
    const utils = await open(node({ code: "{}", defaultCode: spec, input: INPUT_A }));
    expect(mockSendCode).not.toHaveBeenCalled();

    await next(utils, node({ defaultCode: spec, input: INPUT_A }));

    expect(mockSendCode).toHaveBeenCalledTimes(1);
    expect(mockSendCode).toHaveBeenCalledWith(spec);
  });

  test(`a tile is never held back that way; it opens with its ${docWord} loaded`, async () => {
    // The dashboard has no author to interrupt, and a pinned tile's document
    // comes back from the save before its data does.
    mockDashboardOn = true;
    wire();
    const utils = await open(node({ code: "", input: INPUT_A, dashboardPinned: true }));

    await next(utils, node({ input: INPUT_A, dashboardPinned: true }));

    expect(mockSendCode).toHaveBeenCalledTimes(1);
  });

  test("a run in flight is left to draw the node itself", async () => {
    // The runner triggers the node it is running. Doing it here as well puts two
    // `sendCode` calls in one tick, and each toggles the widgets pass: two
    // toggles in a batch cancel, the marker round trip never happens, and the
    // node sits at "exec" until its watchdog. Found by the end-to-end run.
    mockIsRunActive = true;

    await open(node({ input: INPUT_A }));

    expect(mockSendCode).not.toHaveBeenCalled();
  });

  test("a node already drawing is not asked again", async () => {
    await open({ ...node({ input: INPUT_A }), output: { code: "exec" } });

    expect(mockSendCode).not.toHaveBeenCalled();
  });

  test("once the run ends, a restored input still draws", async () => {
    mockIsRunActive = true;
    const utils = await open(node({ input: INPUT_A }));
    expect(mockSendCode).not.toHaveBeenCalled();

    mockIsRunActive = false;
    await next(utils, node({ input: INPUT_A }));

    expect(mockSendCode).toHaveBeenCalledTimes(1);
  });

  test("but a node the run drew is not drawn again when it ends", async () => {
    // The run's own trigger records which input it drew, so the end of a Run
    // All does not redraw every node it just drew.
    mockIsRunActive = true;
    const utils = await open(node({ input: INPUT_A, triggerExec: 0 }));

    await next(utils, node({ input: INPUT_A, triggerExec: 1 }));
    expect(mockSendCode).toHaveBeenCalledTimes(1);

    mockIsRunActive = false;
    await next(utils, node({ input: INPUT_A, triggerExec: 1 }));

    expect(mockSendCode).toHaveBeenCalledTimes(1);
  });
});

describe("only an Autark node", () => {
  const settle = () => act(async () => {});

  test("needs WebGPU: without it nothing is drawn on its own", async () => {
    mockWebGpuSupported = false;

    await mount(data(AUTARK, { code: MAP_SPEC, input: INPUT_A }));
    await settle();

    expect(mockSendCode).not.toHaveBeenCalled();
  });

  test("a data or compute step is never run by an input or a page", async () => {
    // Those make layers. On the dashboard the layers come from the Data Catalog,
    // so running this would re-execute the data load for no reason.
    await mount(data(AUTARK, { code: DATA_SPEC, input: INPUT_A }));
    mockDashboardOn = true;
    await mount(data(AUTARK, { code: DATA_SPEC, dashboardPinned: true }));
    await settle();

    expect(mockSendCode).not.toHaveBeenCalled();
  });

  test("an unwired pinned tile draws once on the dashboard", async () => {
    // Its document loads everything it draws, so no input will ever arrive.
    mockDashboardOn = true;

    await mount(data(AUTARK, { code: MAP_SPEC, dashboardPinned: true }));
    await settle();

    expect(mockSendCode).toHaveBeenCalledTimes(1);
    expect(mockSendCode).toHaveBeenCalledWith(MAP_SPEC);
  });

  test("but not while a run is in flight", async () => {
    mockDashboardOn = true;
    mockIsRunActive = true;

    await mount(data(AUTARK, { code: MAP_SPEC, dashboardPinned: true }));

    expect(mockSendCode).not.toHaveBeenCalled();
  });
});

describe("a code node", () => {
  test("is never run by opening a page", async () => {
    mockDashboardOn = true;

    await mount(data(PYTHON, { code: "return 1", input: INPUT_A, dashboardPinned: true }));

    expect(mockSendCode).not.toHaveBeenCalled();
  });
});
