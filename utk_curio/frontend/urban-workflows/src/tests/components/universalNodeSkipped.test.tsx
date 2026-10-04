/**
 * A node the run did not run, because a node feeding it failed, says so (#603).
 *
 * The runner stops below a failed node and never triggers the nodes after it.
 * Without more, those nodes kept whatever they showed before: a green "Done"
 * and the output of an earlier run, as if they had just run. The runner hands
 * each one the reason instead (`skipExec`, `skipReason`), and the node shows it
 * as its outcome. It is never run for it.
 *
 * Also pinned here: the node's terminal output tells the runner whether it
 * failed, which is what lets the runner stop below a chart or a map as well as
 * below a code node.
 */
import React from "react";
import { act, render } from "@testing-library/react";

const mockSendCode = jest.fn();
const mockSetOutput = jest.fn();
const mockSignalNodeExecDone = jest.fn();

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
jest.mock("../../components/nodes/NodeOutcomeStrip", () => ({ NodeOutcomeStrip: () => null }));
jest.mock("../../registry/nodeRegistry", () => {
  const descriptor = {
    id: "curio.builtin/computation-analysis",
    hasCode: true,
    hasGrammar: false,
    hasWidgets: true,
    adapter: {
      handles: [],
      editor: {},
      container: {},
      useNodeBehavior: () => ({}),
    },
  };
  return {
    getNodeDescriptor: () => descriptor,
    tryGetNodeDescriptor: () => descriptor,
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
    signalNodeExecDone: mockSignalNodeExecDone,
    dashboardOn: false,
    edges: [],
    isRunActive: true,
  }),
}));
jest.mock("../../providers/CollaborationProvider", () => ({
  useCollab: () => ({ enabled: false, lockedNodes: {}, currentUserId: null }),
}));

import UniversalNode from "../../components/UniversalNode";

const PYTHON = "curio.builtin/computation-analysis";
const REASON = 'No data yet: The node feeding this one, "Load parcels", failed. Open it to see the error.';

function data(extra: Record<string, unknown> = {}) {
  return {
    nodeId: "n1",
    nodeType: PYTHON,
    input: "",
    code: "return arg['sp_units']",
    // What an earlier, successful run left behind.
    output: { code: "success", content: "Saved to file: old" },
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

beforeEach(() => {
  jest.clearAllMocks();
});

describe("a node the run did not run (#603)", () => {
  test("shows the reason in place of its last output", async () => {
    const utils = await mount(data());
    expect(mockSetOutput).not.toHaveBeenCalled();

    await act(async () => {
      utils.rerender(<UniversalNode data={data({ skipExec: 1, skipReason: REASON })} isConnectable />);
    });

    expect(mockSetOutput).toHaveBeenCalledWith({ code: "error", content: REASON });
  });

  test("is not run for it", async () => {
    const utils = await mount(data());

    await act(async () => {
      utils.rerender(<UniversalNode data={data({ skipExec: 1, skipReason: REASON })} isConnectable />);
    });

    expect(mockSendCode).not.toHaveBeenCalled();
  });
});

describe("a node's terminal output tells the runner how it went", () => {
  test("an error reports a failure", async () => {
    await mount(data({ output: { code: "error", content: "RuntimeError: boom" } }));
    expect(mockSignalNodeExecDone).toHaveBeenCalledWith("n1", { failed: true });
  });

  test("a success reports no failure", async () => {
    await mount(data());
    expect(mockSignalNodeExecDone).toHaveBeenCalledWith("n1", { failed: false });
  });
});
