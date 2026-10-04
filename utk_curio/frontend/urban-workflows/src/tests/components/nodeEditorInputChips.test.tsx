/**
 * Input chips on a run (#662). A node without a Widgets tab (JS Computation,
 * Data Summary) used to forward its code untouched; it now resolves its
 * references with the same table as every other node, so `[!! input 1 !!]`
 * reaches the sandbox as `arg[1]`. A node with several inputs waits until each
 * one holds a value.
 *
 * CodeEditor is stubbed to show the code it would run.
 */
import React from "react";
import { act, render, screen } from "@testing-library/react";

const mockFlow: { nodes: any[]; edges: any[] } = { nodes: [], edges: [] };
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ dashboardOn: false, markDirty: jest.fn(), markNodeStale: jest.fn(), ...mockFlow }),
}));

jest.mock("../../components/editing/CodeEditor", () => ({
  __esModule: true,
  default: ({ replacedCode, stripInputs }: any) => (
    <div>
      <pre data-testid="replaced">{replacedCode}</pre>
      <span data-testid="strip-inputs">{(stripInputs ?? []).map((i: any) => `${i.slot}:${i.label}`).join(",")}</span>
    </div>
  ),
}));

jest.mock("../../components/editing/NodeProvenance", () => ({
  __esModule: true,
  default: () => null,
}));

import NodeEditor from "../../components/editing/NodeEditor";

function setFlow() {
  mockFlow.nodes = [
    { id: "roads", data: { nodeType: "x", packageTemplateLabel: "Roads" } },
    { id: "parcels", data: { nodeType: "x", packageTemplateLabel: "Parcels" } },
  ];
  mockFlow.edges = [
    { id: "e0", source: "roads", target: "t", sourceHandle: "out", targetHandle: "in" },
    { id: "e1", source: "parcels", target: "t", sourceHandle: "out", targetHandle: "in_1" },
  ];
}

function renderJsNode(inputSlots: unknown[], setOutputCallback = jest.fn()) {
  let play: ((code: string) => void) | undefined;
  render(
    <NodeEditor
      {...({
        setSendCodeCallback: (cb: any) => { play = cb; },
        setOutputCallback,
        data: { nodeId: "t", inputSlots, outputCallback: jest.fn() },
        output: { code: "", content: "" },
        nodeType: "curio.builtin/js-computation",
        readOnly: false,
        code: true,
        grammar: false,
        widgets: false,
        defaultValue: "",
      } as any)}
    />,
  );
  return { play: (code: string) => act(() => play!(code)), setOutputCallback };
}

/** Python Computation: it has a Widgets tab, so a run resolves there (the real
 *  WidgetsEditor), not in NodeEditor itself. */
function renderPythonNode(inputSlots: unknown[], setOutputCallback = jest.fn()) {
  let play: ((code: string) => void) | undefined;
  render(
    <NodeEditor
      {...({
        setSendCodeCallback: (cb: any) => { play = cb; },
        setOutputCallback,
        data: { nodeId: "t", inputSlots, outputCallback: jest.fn() },
        output: { code: "", content: "" },
        nodeType: "curio.builtin/computation-analysis",
        readOnly: false,
        code: true,
        grammar: false,
        widgets: true,
        defaultValue: "",
      } as any)}
    />,
  );
  return { play: (code: string) => act(() => play!(code)), setOutputCallback };
}

beforeEach(() => setFlow());

test("a node without a Widgets tab runs its input chips as arg indexed", () => {
  const { play } = renderJsNode([{ path: "a" }, { path: "b" }]);
  play("return [!! input 1 !!].length;");
  expect(screen.getByTestId("replaced").textContent).toBe("return arg[1].length;");
});

test("the strip above JavaScript code offers the inputs, named after their nodes", () => {
  renderJsNode([{ path: "a" }, { path: "b" }]);
  expect(screen.getByTestId("strip-inputs").textContent).toBe("0:Roads,1:Parcels");
});

test("a chip for an input with no edge ends the run with the problem", () => {
  const { play, setOutputCallback } = renderJsNode([{ path: "a" }, { path: "b" }]);
  play("return [!! input 4 !!];");
  expect(setOutputCallback).toHaveBeenCalledWith({
    code: "error",
    content: expect.stringContaining("input 4 has no edge"),
  });
  expect(screen.getByTestId("replaced").textContent).toBe("");
});

test("a node with several inputs waits until each holds a value", () => {
  const { play, setOutputCallback } = renderJsNode([{ path: "a" }, undefined]);
  play("return [!! input 0 !!];");
  expect(setOutputCallback).toHaveBeenCalledWith({
    code: "error",
    content: "Input 1 (from Parcels) has no value yet. Run the node that feeds it.",
  });
});

test("a Python node with an empty wired circle runs nothing and names the input it waits for", () => {
  // Circle 0 empty, circle 1 filled: the run must not go ahead with input 1
  // alone, and must say which input is missing.
  const { play, setOutputCallback } = renderPythonNode([undefined, { path: "b" }]);
  play("return [!! input 1 !!]");
  expect(setOutputCallback).toHaveBeenCalledTimes(1);
  expect(setOutputCallback).toHaveBeenCalledWith({
    code: "error",
    content: "Input 0 (from Roads) has no value yet. Run the node that feeds it.",
  });
  expect(screen.getByTestId("replaced").textContent).toBe("");
});
