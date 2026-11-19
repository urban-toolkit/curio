/**
 * A node whose behavior adds handles of its own (`dynamicHandles`), as an
 * Autark node of several views adds a dot per view: React Flow is told when
 * they change (`useUpdateNodeInternals`), so an edge on a dot that came with a
 * new view of the document has a handle to attach to, and is told nothing
 * while they stay the same.
 * Harness as in universalNodeNotebookCell.test.tsx.
 */
import React from "react";
import { act, render, screen } from "@testing-library/react";

const mockDots: { current: any[] | undefined } = { current: undefined };
const mockUpdateInternals = jest.fn();

jest.mock("reactflow", () => ({
  Handle: ({ id, position }: any) => <div data-testid={`handle-${id}`} data-position={position} />,
  Position: { Left: "left", Right: "right", Top: "top", Bottom: "bottom" },
  useEdges: () => [],
  useUpdateNodeInternals: () => mockUpdateInternals,
}));
jest.mock("../../components/styles", () => ({
  NodeContainer: (props: any) => <div>{props.children}</div>,
}));
jest.mock("../../components/editing/NodeEditor", () => ({ __esModule: true, default: () => <div data-testid="editor" /> }));
jest.mock("../../components/DescriptionModal", () => ({ __esModule: true, default: () => null }));
jest.mock("../../components/edges/OutputIcon", () => ({ OutputIcon: () => null }));
jest.mock("../../components/edges/InputIcon", () => ({ InputIcon: () => null }));
jest.mock("../../components/UnresolvedNode", () => ({ UnresolvedNode: () => null }));
jest.mock("../../components/agents/attach/NodeAgentBadges", () => ({ NodeAgentBadges: () => null }));
jest.mock("../../components/nodes/NodeOutcomeStrip", () => ({ NodeOutcomeStrip: () => null }));
jest.mock("../../registry/nodeRegistry", () => {
  const descriptor = {
    id: "curio.builtin/autk-grammar",
    hasCode: false,
    hasGrammar: true,
    hasWidgets: false,
    adapter: {
      handles: [
        { id: "in", type: "target", position: "left" },
        { id: "out", type: "source", position: "right" },
        { id: "in/out", type: "source", position: "top" },
      ],
      editor: {},
      container: { nodeWidth: 525, nodeHeight: 350 },
      useNodeBehavior: () => ({ dynamicHandles: mockDots.current }),
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
jest.mock("../../hook/useNodeState", () => ({
  useNodeState: (data: any) => ({
    output: data.output ?? { code: "", content: "" },
    setOutput: () => {},
    code: data.code ?? "",
    setCode: () => {},
    sendCode: undefined,
    setSendCodeCallback: () => {},
    templateData: {},
    user: null,
    promptDescription: () => {},
    closeDescription: () => {},
    showDescriptionModal: false,
  }),
}));
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ signalNodeExecDone: () => {}, dashboardOn: false, edges: [], isRunActive: false, nodes: [] }),
}));
jest.mock("../../providers/CollaborationProvider", () => ({
  useCollab: () => ({ lockedNodes: {} }),
}));

import UniversalNode from "../../components/UniversalNode";

const data = { nodeId: "n1", nodeType: "curio.builtin/autk-grammar", input: "", code: "{}" };

beforeEach(() => {
  mockDots.current = undefined;
  mockUpdateInternals.mockClear();
});

test("React Flow is told when a node's own handles change, and not while they stay the same", async () => {
  let view: ReturnType<typeof render> | undefined;
  await act(async () => {
    view = render(<UniversalNode data={{ ...data }} isConnectable />);
  });
  expect(mockUpdateInternals).not.toHaveBeenCalled();

  // The document gains two views with ids: a dot each.
  mockDots.current = [
    { id: "in/out@north", type: "source", position: "top" },
    { id: "in/out@heights", type: "source", position: "top" },
  ];
  await act(async () => {
    view!.rerender(<UniversalNode data={{ ...data, code: "{\"map\": []}" }} isConnectable />);
  });
  expect(screen.getByTestId("handle-in/out@north")).toHaveAttribute("data-position", "top");
  expect(screen.getByTestId("handle-in/out@heights")).toHaveAttribute("data-position", "top");
  expect(mockUpdateInternals).toHaveBeenCalledWith("n1");

  // Drawn again with the same dots: nothing to tell.
  mockUpdateInternals.mockClear();
  mockDots.current = mockDots.current.map((dot) => ({ ...dot }));
  await act(async () => {
    view!.rerender(<UniversalNode data={{ ...data, code: "{\"map\": [], \"plot\": []}" }} isConnectable />);
  });
  expect(mockUpdateInternals).not.toHaveBeenCalled();

  // A view leaves: its dot goes, and React Flow is told.
  mockDots.current = [{ id: "in/out@north", type: "source", position: "top" }];
  await act(async () => {
    view!.rerender(<UniversalNode data={{ ...data, code: "{}" }} isConnectable />);
  });
  expect(screen.queryByTestId("handle-in/out@heights")).toBeNull();
  expect(mockUpdateInternals).toHaveBeenCalledWith("n1");
});
