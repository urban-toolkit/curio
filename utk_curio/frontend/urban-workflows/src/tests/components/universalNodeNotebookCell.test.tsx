/**
 * A node shown as a notebook cell (UniversalNode under the notebook view).
 *
 * The cell is the column's fixed size, its dots sit on its right edge where the
 * bar draws the connections, each input dot carries the number its
 * `[!! input k !!]` chips use and names what feeds it, and the cardinality
 * markers at the box's edges are gone. On the canvas nothing of this applies.
 * Harness as in universalNodeSkipped.test.tsx.
 */
import React from "react";
import { act, render, screen } from "@testing-library/react";

const mockContainerProps: any[] = [];

jest.mock("reactflow", () => ({
  Handle: ({ id, position, style, title, children }: any) => (
    <div
      data-testid={`handle-${id}`}
      data-position={position}
      data-top={style?.top === undefined ? "" : String(style.top)}
      title={title}
    >
      {children}
    </div>
  ),
  Position: { Left: "left", Right: "right", Top: "top", Bottom: "bottom" },
  useEdges: () => [
    { id: "e0", source: "load", target: "n1", sourceHandle: "out", targetHandle: "in" },
  ],
  useUpdateNodeInternals: () => () => undefined,
}));
jest.mock("../../components/styles", () => ({
  NodeContainer: (props: any) => {
    mockContainerProps.push(props);
    return <div>{props.children}</div>;
  },
}));
jest.mock("../../components/editing/NodeEditor", () => ({
  __esModule: true,
  default: (props: any) => (
    <div data-testid="editor" data-input-marker={String(props.inputMarker)} data-output-marker={String(props.outputMarker)} />
  ),
}));
jest.mock("../../components/DescriptionModal", () => ({ __esModule: true, default: () => null }));
jest.mock("../../components/edges/OutputIcon", () => ({ OutputIcon: () => <span data-testid="output-marker" /> }));
jest.mock("../../components/edges/InputIcon", () => ({ InputIcon: () => <span data-testid="input-marker" /> }));
jest.mock("../../components/UnresolvedNode", () => ({ UnresolvedNode: () => null }));
jest.mock("../../components/agents/attach/NodeAgentBadges", () => ({ NodeAgentBadges: () => null }));
jest.mock("../../components/nodes/NodeOutcomeStrip", () => ({ NodeOutcomeStrip: () => null }));
jest.mock("../../registry/nodeRegistry", () => {
  const descriptor = {
    id: "curio.builtin/vis-vega",
    hasCode: false,
    hasGrammar: true,
    hasWidgets: false,
    adapter: {
      handles: [
        { id: "in", type: "target", position: "left" },
        { id: "in_1", type: "target", position: "left", style: { top: "66%" } },
        { id: "out", type: "source", position: "right" },
        { id: "in/out", type: "source", position: "top" },
      ],
      editor: {},
      container: { nodeWidth: 525, nodeHeight: 350 },
      inputIconType: "1",
      outputIconType: "1",
      useNodeBehavior: () => ({}),
    },
  };
  return {
    getNodeDescriptor: () => descriptor,
    tryGetNodeDescriptor: () => descriptor,
    subscribeToRegistry: () => () => {},
  };
});
jest.mock("../../registry/packageRegistryBootstrap", () => ({
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
  useFlowContext: () => ({
    signalNodeExecDone: () => {},
    dashboardOn: false,
    edges: [],
    isRunActive: false,
    // A package node's own label: how resolveNodeDisplayLabel names a node
    // without consulting the registry (a numeric type id).
    nodes: [{ id: "load", data: { nodeId: "load", nodeType: "1024", packageTemplateLabel: "Load roads" } }],
  }),
}));
jest.mock("../../providers/CollaborationProvider", () => ({
  useCollab: () => ({ enabled: false, lockedNodes: {}, currentUserId: null }),
}));

import UniversalNode from "../../components/UniversalNode";
import { NotebookViewContext } from "../../providers/flow/notebookViewContext";
import { NOTEBOOK_CELL_HEIGHT, NOTEBOOK_CELL_WIDTH } from "../../utils/notebookLayout";

const data = { nodeId: "n1", nodeType: "curio.builtin/vis-vega", input: "", code: "{}" };

async function mount(on: boolean) {
  mockContainerProps.length = 0;
  await act(async () => {
    render(
      <NotebookViewContext.Provider
        value={{ on, laneX: new Map(), heights: new Map([["n1", NOTEBOOK_CELL_HEIGHT]]), reveal: () => on }}
      >
        <UniversalNode data={data} isConnectable />
      </NotebookViewContext.Provider>,
    );
  });
}

const lastContainer = () => mockContainerProps[mockContainerProps.length - 1];

describe("a node shown as a notebook cell", () => {
  test("has the column's fixed size, not its canvas size", async () => {
    await mount(true);
    expect(lastContainer().nodeWidth).toBe(NOTEBOOK_CELL_WIDTH);
    expect(lastContainer().nodeHeight).toBe(NOTEBOOK_CELL_HEIGHT);
  });

  test("puts every dot on its right edge: inputs from the top, the output at the bottom", async () => {
    await mount(true);
    for (const id of ["in", "in_1", "out", "in/out"]) {
      expect(screen.getByTestId(`handle-${id}`)).toHaveAttribute("data-position", "right");
    }
    const top = (id: string) => Number(screen.getByTestId(`handle-${id}`).getAttribute("data-top"));
    expect(top("in")).toBeLessThan(top("in_1"));
    expect(top("in_1")).toBeLessThan(top("in/out"));
    expect(top("in/out")).toBeLessThan(top("out"));
  });

  test("numbers each input dot as its chips do and names what feeds it", async () => {
    await mount(true);
    expect(screen.getByTestId("handle-in")).toHaveTextContent("0");
    expect(screen.getByTestId("handle-in_1")).toHaveTextContent("1");
    expect(screen.getByTestId("handle-in")).toHaveAttribute("title", "input 0 · Load roads");
    expect(screen.getByTestId("handle-in_1")).toHaveAttribute("title", "input 1");
    expect(screen.getByTestId("handle-out")).toHaveAttribute("title", "output");
  });

  test("drops the cardinality markers at the box's edges", async () => {
    await mount(true);
    expect(screen.queryByTestId("input-marker")).toBeNull();
    expect(screen.queryByTestId("output-marker")).toBeNull();
    expect(screen.getByTestId("editor")).toHaveAttribute("data-input-marker", "false");
    expect(screen.getByTestId("editor")).toHaveAttribute("data-output-marker", "false");
  });
});

describe("the same node on the canvas", () => {
  test("keeps its canvas size, its handles' sides and its markers", async () => {
    await mount(false);
    expect(lastContainer().nodeWidth).toBe(525);
    expect(lastContainer().nodeHeight).toBe(350);
    expect(screen.getByTestId("handle-in")).toHaveAttribute("data-position", "left");
    expect(screen.getByTestId("handle-in_1")).toHaveAttribute("data-top", "66%");
    expect(screen.getByTestId("handle-in/out")).toHaveAttribute("data-position", "top");
    expect(screen.getByTestId("handle-in")).not.toHaveAttribute("title");
    expect(screen.getByTestId("input-marker")).toBeInTheDocument();
    expect(screen.getByTestId("editor")).toHaveAttribute("data-input-marker", "true");
  });
});
