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
 *  - Vega: whenever it has an input and a spec, on either route, once per input.
 *    It is a client-side recompile, so the canvas benefits too.
 *  - Autark: only a PINNED tile, only on the dashboard, only a render spec, and
 *    only once. It needs WebGPU; it is real work. Upstream data/compute nodes
 *    are never run: their layers come from the Data Catalog.
 *  - Code nodes: never. Their pane shows a run's stdout, which nothing restores,
 *    and running one would execute the user's code because a page was opened.
 */
import React from "react";
import { act, render } from "@testing-library/react";

const mockSendCode = jest.fn();
const mockSetOutput = jest.fn();
let mockDashboardOn = false;
let mockFlowEdges: any[] = [];

jest.mock("reactflow", () => ({
  Handle: () => null,
  useEdges: () => [],
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
jest.mock("../../registry/packageRegistryBootstrap", () => ({
  isRegistryReady: () => true,
  subscribeToRegistryReady: () => () => {},
}));
jest.mock("../../hook/useNodeState", () => {
  const React = require("react");
  return {
    useNodeState: (data: any) => {
      const [sendCode, setSendCode] = React.useState(undefined);
      return {
        output: { code: "", content: "" },
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
  }),
}));
jest.mock("../../providers/CollaborationProvider", () => ({
  useCollab: () => ({ enabled: false, lockedNodes: {}, currentUserId: null }),
}));

import UniversalNode from "../../components/UniversalNode";

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
});

describe("a Vega chart", () => {
  test("compiles from a restored input on the canvas, like a Play would", async () => {
    await mount(data(VEGA, { code: VEGA_SPEC, input: INPUT_A }));

    expect(mockSetOutput).toHaveBeenCalledWith({ code: "exec", content: "" });
    expect(mockSendCode).toHaveBeenCalledTimes(1);
    expect(mockSendCode).toHaveBeenCalledWith(VEGA_SPEC);
  });

  test("and on the dashboard", async () => {
    mockDashboardOn = true;

    await mount(data(VEGA, { code: VEGA_SPEC, input: INPUT_A, dashboardPinned: true }));

    expect(mockSendCode).toHaveBeenCalledTimes(1);
  });

  test("the same input is never compiled twice", async () => {
    const utils = await mount(data(VEGA, { code: VEGA_SPEC, input: INPUT_A }));

    await rerenderWith(utils, data(VEGA, { code: VEGA_SPEC, input: INPUT_A }));

    expect(mockSendCode).toHaveBeenCalledTimes(1);
  });

  test("a new input compiles again", async () => {
    // A chart behind a Data Pool gets its rows when the pool's fetch lands.
    const utils = await mount(data(VEGA, { code: VEGA_SPEC, input: INPUT_A }));

    await rerenderWith(utils, data(VEGA, { code: VEGA_SPEC, input: INPUT_B }));

    expect(mockSendCode).toHaveBeenCalledTimes(2);
  });

  test("nothing to draw from, nothing compiled", async () => {
    // Compiling against no rows would replace the "connect something" message
    // with an empty set of axes and mark the node done.
    await mount(data(VEGA, { code: VEGA_SPEC, input: "" }));

    expect(mockSendCode).not.toHaveBeenCalled();
  });

  test("no spec, nothing compiled", async () => {
    // The starter spec arrives a beat later; compiling "" would throw on parse.
    await mount(data(VEGA, { code: "", input: INPUT_A }));

    expect(mockSendCode).not.toHaveBeenCalled();
  });
});

describe("an Autark tile", () => {
  test("draws once, pinned, on the dashboard", async () => {
    mockDashboardOn = true;

    await mount(data(AUTARK, { code: MAP_SPEC, dashboardPinned: true }));

    expect(mockSendCode).toHaveBeenCalledTimes(1);
    expect(mockSendCode).toHaveBeenCalledWith(MAP_SPEC);
  });

  test("never on the canvas", async () => {
    await mount(data(AUTARK, { code: MAP_SPEC, dashboardPinned: true, input: INPUT_A }));

    expect(mockSendCode).not.toHaveBeenCalled();
  });

  test("never when it is not the tile", async () => {
    mockDashboardOn = true;

    await mount(data(AUTARK, { code: MAP_SPEC, input: INPUT_A }));

    expect(mockSendCode).not.toHaveBeenCalled();
  });

  test("never for a data or compute step", async () => {
    // Those make layers. On the dashboard the layers come from the Data Catalog,
    // so running this would re-execute the data load for no reason.
    mockDashboardOn = true;

    await mount(data(AUTARK, { code: DATA_SPEC, dashboardPinned: true }));

    expect(mockSendCode).not.toHaveBeenCalled();
  });

  test("a wired tile waits for its input, then draws once", async () => {
    mockDashboardOn = true;
    mockFlowEdges = [{ id: "e", source: "pool", target: "n1" }];
    const utils = await mount(data(AUTARK, { code: MAP_SPEC, dashboardPinned: true }));

    expect(mockSendCode).not.toHaveBeenCalled();

    await rerenderWith(utils, data(AUTARK, { code: MAP_SPEC, dashboardPinned: true, input: INPUT_A }));
    expect(mockSendCode).toHaveBeenCalledTimes(1);

    // A Data Pool re-emits on every brush; the map syncs highlights itself.
    await rerenderWith(utils, data(AUTARK, { code: MAP_SPEC, dashboardPinned: true, input: INPUT_B }));
    expect(mockSendCode).toHaveBeenCalledTimes(1);
  });
});

describe("a code node", () => {
  test("is never run by opening a page", async () => {
    mockDashboardOn = true;

    await mount(data(PYTHON, { code: "return 1", input: INPUT_A, dashboardPinned: true }));

    expect(mockSendCode).not.toHaveBeenCalled();
  });
});
