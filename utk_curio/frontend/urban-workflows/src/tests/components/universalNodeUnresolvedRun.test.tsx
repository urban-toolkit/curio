/**
 * A node whose type no installed package provides, when a run triggers it.
 *
 * Run All triggers every node of a level and waits for each to report. A node
 * no package provides (a saved Compare Scenarios node, or one of a package that
 * is not installed) renders its card instead of a body, and the card never
 * reported: the level waited for it until the stall watchdog gave up, ten
 * minutes later, and the nodes it fed were then triggered with no input.
 *
 * It reports at once that its run failed, naming its type as its card's title
 * does, so the run moves on and skips what it feeds. Its card stays. A trigger
 * that comes while the registry may still deliver the type is answered once the
 * registry has settled without it, and a trigger from before the node opened is
 * not answered, as a node with a body does not run one.
 */
import React from "react";
import { act, render } from "@testing-library/react";

const mockSignalNodeExecDone = jest.fn();
let mockRegistryReady = true;
const mockReadyListeners = new Set<() => void>();

jest.mock("reactflow", () => ({
  __esModule: true,
  Handle: ({ id, type }: any) => <div className="react-flow__handle" data-handleid={id} data-handletype={type} />,
  Position: { Left: "left", Right: "right", Top: "top", Bottom: "bottom" },
  useEdges: () => [],
  useNodes: () => [],
  useUpdateNodeInternals: () => () => undefined,
}));
jest.mock("../../components/styles", () => ({
  NodeContainer: ({ children }: any) => <div>{children}</div>,
}));
jest.mock("../../components/editing/NodeEditor", () => ({ __esModule: true, default: () => null }));
jest.mock("../../components/DescriptionModal", () => ({ __esModule: true, default: () => null }));
jest.mock("../../components/edges/OutputIcon", () => ({ OutputIcon: () => null }));
jest.mock("../../components/edges/InputIcon", () => ({ InputIcon: () => null }));
jest.mock("../../components/agents/attach/NodeAgentBadges", () => ({ NodeAgentBadges: () => null }));
jest.mock("../../components/nodes/NodeOutcomeStrip", () => ({ NodeOutcomeStrip: () => null }));
jest.mock("../../providers/packages/NodeCatalogDrawerProvider", () => ({
  useNodeCatalogDrawer: () => ({
    openNodeCatalogDrawer: jest.fn(),
    closeNodeCatalogDrawer: jest.fn(),
    isNodeCatalogDrawerOpen: false,
  }),
}));
// No installed package provides any type here.
jest.mock("../../registry/nodeRegistry", () => ({
  getNodeDescriptor: (nodeType: string) => {
    throw new Error(`no descriptor for ${nodeType}`);
  },
  tryGetNodeDescriptor: () => undefined,
  subscribeToRegistry: () => () => {},
}));
jest.mock("../../registry/registryReadiness", () => ({
  isRegistryReady: () => mockRegistryReady,
  subscribeToRegistryReady: (listener: () => void) => {
    mockReadyListeners.add(listener);
    return () => mockReadyListeners.delete(listener);
  },
}));
jest.mock("../../hook/useNodeState", () => ({ useNodeState: () => ({}) }));
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    signalNodeExecDone: mockSignalNodeExecDone,
    dashboardOn: false,
    edges: [],
    nodes: [],
    isRunActive: true,
    serverRunActive: false,
  }),
}));
jest.mock("../../providers/CollaborationProvider", () => ({
  useCollab: () => ({ enabled: false, lockedNodes: {}, currentUserId: null }),
}));

import UniversalNode from "../../components/UniversalNode";

/** The type a saved Compare Scenarios node carries, which no package provides any more. */
const COMPARE = "curio.builtin/compare-scenarios";

function data(extra: Record<string, unknown> = {}) {
  return { nodeId: "n1", nodeType: COMPARE, input: "", ...extra };
}

async function mount(nodeData: any) {
  let utils: ReturnType<typeof render>;
  await act(async () => {
    utils = render(<UniversalNode data={nodeData} isConnectable />);
  });
  return utils!;
}

async function trigger(utils: ReturnType<typeof render>, nodeData: any) {
  await act(async () => {
    utils.rerender(<UniversalNode data={nodeData} isConnectable />);
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  mockRegistryReady = true;
  mockReadyListeners.clear();
});

describe("a node whose type no installed package provides, when a run triggers it", () => {
  test("reports at once that its run failed, naming its type as its card does, and keeps its card", async () => {
    const utils = await mount(data());
    expect(mockSignalNodeExecDone).not.toHaveBeenCalled();

    await trigger(utils, data({ triggerExec: 1 }));

    expect(mockSignalNodeExecDone).toHaveBeenCalledTimes(1);
    expect(mockSignalNodeExecDone).toHaveBeenCalledWith("n1", {
      failed: true,
      message: `No installed package provides ${COMPARE}`,
    });
    const card = utils.getByTestId("unresolved-node");
    expect(card).toHaveAttribute("title", `No installed package provides ${COMPARE}`);
    expect(card).toHaveTextContent("Missing node package");
  });

  test("answers each trigger once", async () => {
    const utils = await mount(data());

    await trigger(utils, data({ triggerExec: 1 }));
    // A change that is no new trigger, as when the run marks a node below it.
    await trigger(utils, data({ triggerExec: 1, skipExec: 1 }));
    expect(mockSignalNodeExecDone).toHaveBeenCalledTimes(1);

    await trigger(utils, data({ triggerExec: 2, skipExec: 1 }));
    expect(mockSignalNodeExecDone).toHaveBeenCalledTimes(2);
    expect(mockSignalNodeExecDone).toHaveBeenLastCalledWith("n1", {
      failed: true,
      message: `No installed package provides ${COMPARE}`,
    });
  });

  test("does not answer a trigger from before it opened", async () => {
    await mount(data({ triggerExec: 4 }));
    expect(mockSignalNodeExecDone).not.toHaveBeenCalled();
  });

  test("a type that names no package reports as its card names it", async () => {
    const utils = await mount(data({ nodeType: "DATA_LOADING" }));

    await trigger(utils, data({ nodeType: "DATA_LOADING", triggerExec: 1 }));

    expect(mockSignalNodeExecDone).toHaveBeenCalledWith("n1", {
      failed: true,
      message: "Unrecognized node type: DATA_LOADING",
    });
    expect(utils.getByTestId("unrecognized-node")).toHaveAttribute("title", "Unrecognized node type: DATA_LOADING");
  });

  test("waits while the registry may still deliver its type, and reports once it has settled without it", async () => {
    mockRegistryReady = false;
    const utils = await mount(data());

    await trigger(utils, data({ triggerExec: 1 }));
    expect(utils.getByText("Loading node…")).toBeInTheDocument();
    expect(mockSignalNodeExecDone).not.toHaveBeenCalled();

    await act(async () => {
      mockRegistryReady = true;
      mockReadyListeners.forEach((listener) => listener());
    });

    expect(mockSignalNodeExecDone).toHaveBeenCalledTimes(1);
    expect(mockSignalNodeExecDone).toHaveBeenCalledWith("n1", {
      failed: true,
      message: `No installed package provides ${COMPARE}`,
    });
    expect(utils.getByTestId("unresolved-node")).toBeInTheDocument();
  });
});
