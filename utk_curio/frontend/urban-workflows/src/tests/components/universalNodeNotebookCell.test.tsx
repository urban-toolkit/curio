/**
 * A node shown as a notebook cell (UniversalNode under the notebook view).
 *
 * The cell is the page's cell width and as tall as its content, at least tall
 * enough for its dots, passed apart from the node's own size, which stays its
 * canvas size so the node keeps it when the canvas comes back. Its dots sit on
 * its right edge where the bar draws the connections: inputs at fixed offsets
 * from the top, the interaction dot halfway, the output anchored to the bottom,
 * so they follow the cell as it grows. Each input dot carries the number its
 * `[!! input k !!]` chips use and names what feeds it, the cardinality markers
 * at the box's edges are gone, and the outcome strip sits in the cell's flow.
 * On the canvas nothing of this applies.
 * Harness as in universalNodeSkipped.test.tsx.
 */
import React from "react";
import { act, render, screen } from "@testing-library/react";

const mockContainerProps: any[] = [];
const mockStripProps: any[] = [];
const mockEditorless = { on: false };

jest.mock("reactflow", () => ({
  Handle: ({ id, position, style, title, children }: any) => (
    <div
      data-testid={`handle-${id}`}
      data-position={position}
      data-top={style?.top === undefined ? "" : String(style.top)}
      data-bottom={style?.bottom === undefined ? "" : String(style.bottom)}
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
    <div data-testid="editor" />
  ),
}));
jest.mock("../../components/DescriptionModal", () => ({ __esModule: true, default: () => null }));
jest.mock("../../components/edges/OutputIcon", () => ({ OutputIcon: () => <span data-testid="output-marker" /> }));
jest.mock("../../components/edges/InputIcon", () => ({ InputIcon: () => <span data-testid="input-marker" /> }));
jest.mock("../../components/UnresolvedNode", () => ({ UnresolvedNode: () => null }));
jest.mock("../../components/agents/attach/NodeAgentBadges", () => ({ NodeAgentBadges: () => null }));
jest.mock("../../components/nodes/NodeOutcomeStrip", () => ({
  NodeOutcomeStrip: (props: any) => {
    mockStripProps.push(props);
    return null;
  },
}));
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
  // A kind with no editor (Data Pool, Simple View, Parameter...) draws its
  // body straight from its behavior.
  const React = require("react");
  const editorless = {
    ...descriptor,
    id: "curio.builtin/data-pool",
    adapter: {
      ...descriptor.adapter,
      editor: null,
      useNodeBehavior: () => ({ contentComponent: React.createElement("div", { "data-testid": "body" }) }),
    },
  };
  const pick = () => (mockEditorless.on ? editorless : descriptor);
  return {
    getNodeDescriptor: pick,
    tryGetNodeDescriptor: pick,
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
import { notebookCellMinHeight } from "../../utils/notebookLayout";

/** The page's cell width the view hands its cells. */
const CELL_WIDTH = 1065;

const data = { nodeId: "n1", nodeType: "curio.builtin/vis-vega", input: "", code: "{}" };

async function mount(on: boolean) {
  mockContainerProps.length = 0;
  mockStripProps.length = 0;
  await act(async () => {
    render(
      <NotebookViewContext.Provider value={{ on, laneX: new Map(), cellWidth: CELL_WIDTH, reveal: () => on }}>
        <UniversalNode data={data} isConnectable />
      </NotebookViewContext.Provider>,
    );
  });
}

const lastContainer = () => mockContainerProps[mockContainerProps.length - 1];
const lastStrip = () => mockStripProps[mockStripProps.length - 1];

describe("a node shown as a notebook cell", () => {
  test("is the page's cell width and at least tall enough for its dots; its own size stays its canvas size", async () => {
    await mount(true);
    const handles = [
      { id: "in", type: "target" as const },
      { id: "in_1", type: "target" as const },
      { id: "out", type: "source" as const },
      { id: "in/out", type: "source" as const },
    ];
    // No fixed height: the cell grows with its code and output.
    expect(lastContainer().cellBox).toEqual({ width: CELL_WIDTH, minHeight: notebookCellMinHeight(handles) });
    // The size props feed the node's own size state, which is what the canvas
    // shows when it comes back: the cell's size must never reach them.
    expect(lastContainer().nodeWidth).toBe(525);
    expect(lastContainer().nodeHeight).toBe(350);
  });

  test("puts every dot on its right edge: inputs from the top, the interaction halfway, the output from the bottom", async () => {
    await mount(true);
    for (const id of ["in", "in_1", "out", "in/out"]) {
      expect(screen.getByTestId(`handle-${id}`)).toHaveAttribute("data-position", "right");
    }
    const top = (id: string) => screen.getByTestId(`handle-${id}`).getAttribute("data-top");
    expect(Number(top("in"))).toBeLessThan(Number(top("in_1")));
    expect(top("in/out")).toBe("50%");
    // `top: auto` inline beats React Flow's right-handle `top: 50%`, so the
    // output keeps its place above the cell's bottom edge as the cell grows.
    expect(top("out")).toBe("auto");
    expect(Number(screen.getByTestId("handle-out").getAttribute("data-bottom"))).toBeGreaterThanOrEqual(0);
  });

  test("puts the outcome strip in the cell's flow, under the output", async () => {
    await mount(true);
    expect(lastStrip().inCell).toBe(true);
  });

  test("lets a kind with no editor take its own height up to 360px, scrolling inside past it", async () => {
    mockEditorless.on = true;
    try {
      await mount(true);
      const box = screen.getByTestId("body").parentElement as HTMLElement;
      expect(box.style.maxHeight).toBe("360px");
      expect(box.style.overflow).toBe("auto");
    } finally {
      mockEditorless.on = false;
    }
  });

  test("numbers each input dot as its chips do and names what feeds it", async () => {
    await mount(true);
    expect(screen.getByTestId("handle-in")).toHaveTextContent("0");
    expect(screen.getByTestId("handle-in_1")).toHaveTextContent("1");
    expect(screen.getByTestId("handle-in")).toHaveAttribute("title", "input_0 · Load roads");
    expect(screen.getByTestId("handle-in_1")).toHaveAttribute("title", "input_1");
    expect(screen.getByTestId("handle-out")).toHaveAttribute("title", "output");
  });

  test("drops the cardinality markers at the box's edges", async () => {
    await mount(true);
    expect(screen.queryByTestId("input-marker")).toBeNull();
    expect(screen.queryByTestId("output-marker")).toBeNull();
  });
});

describe("the same node on the canvas", () => {
  test("keeps its canvas size, its handles' sides and its markers", async () => {
    await mount(false);
    expect(lastContainer().nodeWidth).toBe(525);
    expect(lastContainer().nodeHeight).toBe(350);
    expect(lastContainer().cellBox).toBeUndefined();
    expect(screen.getByTestId("handle-in")).toHaveAttribute("data-position", "left");
    expect(screen.getByTestId("handle-in_1")).toHaveAttribute("data-top", "66%");
    expect(screen.getByTestId("handle-in/out")).toHaveAttribute("data-position", "top");
    expect(screen.getByTestId("handle-in")).not.toHaveAttribute("title");
    expect(screen.getByTestId("input-marker")).toBeInTheDocument();
    expect(screen.getByTestId("output-marker")).toBeInTheDocument();
    expect(lastStrip().inCell).toBeFalsy();
  });

  test("draws a kind with no editor straight in its body, as before", async () => {
    mockEditorless.on = true;
    try {
      await mount(false);
      const box = screen.getByTestId("body").parentElement as HTMLElement;
      expect(box.style.maxHeight).toBe("");
    } finally {
      mockEditorless.on = false;
    }
  });
});
