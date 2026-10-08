/**
 * The Compare Scenarios node (#662) on the canvas. Its labels and the code
 * written from them follow the graph: a new input or a renamed scenario writes
 * them again, and a project load, which adds the nodes before their edges,
 * writes nothing. Its body warns about context, lists what differs, and draws
 * its own output through the Vega-Lite node's code.
 */
import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { NodeBehaviorData, UseNodeStateReturn } from "../../../registry/types";

// The flow reaches the node through a React context, as FlowProvider's does,
// so a new flow re-renders every part of the node that reads it.
let mockFlow: Record<string, any> = {};
const mockFlowContext = React.createContext<Record<string, any>>({});
const mockUpdateDataNode = jest.fn();
const mockMarkNodeStale = jest.fn();
jest.mock("../../../providers/FlowProvider", () => ({
  useFlowContext: () => require("react").useContext(mockFlowContext),
}));

jest.mock("../../../utils/palettePackageFactoryDraft", () => ({
  resolveNodeDisplayLabel: (data: any) => data.title ?? data.nodeId,
}));

const mockCompile = jest.fn().mockResolvedValue({ rowsIn: 4, drawn: 4 });
const mockUseVega = jest.fn((_options: any) => ({ handleCompileGrammar: mockCompile }));
jest.mock("../../../hook/useVega", () => ({
  useVega: (options: any) => mockUseVega(options),
}));
jest.mock("vega", () => ({}), { virtual: true });
jest.mock("vega-lite", () => ({}), { virtual: true });

jest.mock("../../../utils/grammarInput", () => ({
  readGrammarInput: jest.fn().mockResolvedValue({
    frames: [
      {
        dataType: "dataframe",
        payload: { scenario: { 0: "s-base" }, scenario_name: { 0: "Baseline" }, segment: { 0: "r1" }, sunlight: { 0: 5 } },
        schema: { scenario: "object", scenario_name: "object", segment: "object", sunlight: "float64" },
        geometryName: null,
      },
    ],
  }),
}));

import { failureLine, savedFile, useCompareScenariosBehavior } from "../../../adapters/node/compareScenariosBehavior";
import { stackCode } from "../../../utils/compare/compareCode";

const COMPARE = "cmp";
const node = (id: string, data: Record<string, unknown> = {}) => ({
  id,
  type: "__curioUniversalNode",
  data: { nodeId: id, nodeType: "curio.builtin/computation-analysis@1", code: "return arg", ...data },
});
const edge = (source: string, target: string, targetHandle = "in") => ({
  id: `${source}-${target}-${targetHandle}`, source, target, sourceHandle: "out", targetHandle,
});

const BASE = { scenario: "s-base", name: "Baseline", color: "#2a9d8f" };
const TALL = { scenario: "s-tall", name: "Twice as tall", color: "#e76f51" };

function graph(compareData: Record<string, unknown> = {}) {
  const nodes = [
    node("load", { title: "Loader" }),
    node("a", { title: "Scale", widgets: [{ name: "factor", type: "number", default: 1, value: 1 }] }),
    node("b", { title: "Scale", copiedFrom: ["a"], widgets: [{ name: "factor", type: "number", default: 1, value: 2 }] }),
    node(COMPARE, { nodeType: "curio.builtin/compare-scenarios@1", title: "Compare", ...compareData }),
  ];
  const edges = [edge("load", "a"), edge("load", "b"), edge("a", COMPARE, "in"), edge("b", COMPARE, "in_1")];
  const scenarios = [
    { id: "s-base", name: "Baseline", color: "#2a9d8f", nodes: ["a"] },
    { id: "s-tall", name: "Twice as tall", color: "#e76f51", nodes: ["b"] },
  ];
  return { nodes, edges, scenarios };
}

function flowOf(g: ReturnType<typeof graph>, extra: Record<string, unknown> = {}) {
  return {
    ...g,
    outputs: [],
    updateDataNode: mockUpdateDataNode,
    markNodeStale: mockMarkNodeStale,
    markDirty: jest.fn(),
    dashboardOn: false,
    viewerMode: "owner",
    ...extra,
  };
}

function nodeState(output: { code: string; content?: string } = { code: "" }) {
  return { setCode: jest.fn(), output } as unknown as UseNodeStateReturn;
}

/** Each render's body, to tell when its identity changes. */
const bodies: unknown[] = [];

function Node({ data, state }: { data: any; state: UseNodeStateReturn }) {
  const behavior = useCompareScenariosBehavior(data as NodeBehaviorData, state);
  bodies.push(behavior.contentComponent);
  return (
    <>
      <span data-testid="override">{behavior.defaultValueOverride ?? ""}</span>
      {behavior.contentComponent}
    </>
  );
}

/** The node, under the flow `mockFlow` holds when it renders. */
function Harness({ data, state }: { data: any; state: UseNodeStateReturn }) {
  return (
    <mockFlowContext.Provider value={mockFlow}>
      <Node data={data} state={state} />
    </mockFlowContext.Provider>
  );
}

beforeEach(() => {
  mockUpdateDataNode.mockReset();
  mockMarkNodeStale.mockReset();
  mockCompile.mockClear();
  mockUseVega.mockClear();
  bodies.length = 0;
});

describe("its labels and code follow the graph", () => {
  const written = stackCode([
    { slot: 0, label: BASE },
    { slot: 1, label: TALL },
  ]);

  test("a project load, which adds the nodes before the edges, writes nothing", async () => {
    const g = graph({ compareScenarios: { inputs: [BASE, TALL] }, defaultCode: written, code: written });
    const compare = g.nodes.find((n) => n.id === COMPARE)!;
    const state = nodeState({ code: "success" });
    // The nodes are on the canvas; the edges come a render later.
    mockFlow = flowOf({ ...g, edges: [] });
    const view = render(<Harness data={compare.data} state={state} />);
    mockFlow = flowOf(g);
    view.rerender(<Harness data={compare.data} state={state} />);
    await act(async () => {});
    expect(mockUpdateDataNode).not.toHaveBeenCalled();
    expect(mockMarkNodeStale).not.toHaveBeenCalled();
    expect(state.setCode).not.toHaveBeenCalled();
  });

  test("a new input writes the labels, and the code that reads it through its chip", () => {
    const one = stackCode([{ slot: 0, label: BASE }]);
    const g = graph({ compareScenarios: { inputs: [BASE], chart: { preset: "pie" } }, defaultCode: one, code: one });
    const compare = g.nodes.find((n) => n.id === COMPARE)!;
    const state = nodeState({ code: "success" });
    mockFlow = flowOf(g);
    render(<Harness data={compare.data} state={state} />);
    expect(state.setCode).toHaveBeenCalledWith(written);
    expect(mockUpdateDataNode).toHaveBeenCalledWith(
      COMPARE,
      expect.objectContaining({
        compareScenarios: { inputs: [BASE, TALL], chart: { preset: "pie" } },
        defaultCode: written,
        code: written,
      }),
    );
    expect(written).toContain('("s-tall", "Twice as tall", [!! input_1 !!]),');
    // It had run, so its output is now stale.
    expect(mockMarkNodeStale).toHaveBeenCalledWith(COMPARE);
  });

  test("a renamed scenario writes them again", () => {
    const g = graph({ compareScenarios: { inputs: [BASE, TALL] }, defaultCode: written, code: written });
    g.scenarios[1] = { ...g.scenarios[1], name: "Tall" };
    const compare = g.nodes.find((n) => n.id === COMPARE)!;
    mockFlow = flowOf(g);
    render(<Harness data={compare.data} state={nodeState()} />);
    expect(mockUpdateDataNode).toHaveBeenCalledWith(
      COMPARE,
      expect.objectContaining({ compareScenarios: { inputs: [BASE, { ...TALL, name: "Tall" }] } }),
    );
    expect(mockMarkNodeStale).not.toHaveBeenCalled();
  });

  test("the dashboard and a shared view write nothing", () => {
    const g = graph({ compareScenarios: { inputs: [BASE] } });
    const compare = g.nodes.find((n) => n.id === COMPARE)!;
    mockFlow = flowOf(g, { dashboardOn: true });
    render(<Harness data={compare.data} state={nodeState()} />);
    mockFlow = flowOf(g, { viewerMode: "shared" });
    render(<Harness data={compare.data} state={nodeState()} />);
    expect(mockUpdateDataNode).not.toHaveBeenCalled();
  });

  test("a node just dropped offers the code for its inputs", () => {
    const g = graph();
    const compare = g.nodes.find((n) => n.id === COMPARE)!;
    mockFlow = flowOf({ ...g, edges: [] });
    render(<Harness data={compare.data} state={nodeState()} />);
    expect(screen.getByTestId("override").textContent).toBe(stackCode([]));
  });
});

describe("its body", () => {
  test("says there is nothing to compare until an input is connected, then until it runs", () => {
    const g = graph();
    const compare = g.nodes.find((n) => n.id === COMPARE)!;
    mockFlow = flowOf({ ...g, edges: [] });
    const view = render(<Harness data={compare.data} state={nodeState()} />);
    expect(view.container.querySelector('[data-curio-node-empty="disconnected"]')).not.toBeNull();
    mockFlow = flowOf(g);
    view.rerender(<Harness data={compare.data} state={nodeState()} />);
    expect(view.container.querySelector('[data-curio-node-empty="not-run"]')).not.toBeNull();
    expect(mockUseVega).not.toHaveBeenCalled();
  });

  test("draws its own output through useVega, without forwarding it or recording a version", async () => {
    const g = graph({ compareScenarios: { inputs: [BASE, TALL] } });
    const compare = g.nodes.find((n) => n.id === COMPARE)!;
    mockFlow = flowOf(g, { outputs: [{ nodeId: COMPARE, output: { path: "stacked-1", dataType: "dataframe" } }] });
    render(<Harness data={compare.data} state={nodeState({ code: "success" })} />);
    // Bars of the first number column, once the stacked table's columns are read.
    await waitFor(() => expect(JSON.parse(mockCompile.mock.calls.at(-1)![0]).encoding?.y?.field).toBe("sunlight"));
    const options = mockUseVega.mock.calls.at(-1)![0];
    expect(options.recordsProvenance).toBe(false);
    expect(options.forwardsInput).toBe(false);
    expect(options.data.input).toEqual({ path: "stacked-1", dataType: "dataframe" });
    const spec = JSON.parse(mockCompile.mock.calls.at(-1)![0]);
    expect(spec.mark).toEqual({ type: "bar", tooltip: true });
    expect(spec.encoding.color.scale).toEqual({ domain: ["Baseline", "Twice as tall"], range: ["#2a9d8f", "#e76f51"] });
    expect(document.getElementById("vega" + COMPARE)).not.toBeNull();
  });

  test("lists what differs, and warns when the scenarios read different context", () => {
    const g = graph({ compareScenarios: { inputs: [BASE, TALL] } });
    g.nodes.push(node("load-2", { title: "Loader 2020" }));
    g.edges = g.edges.map((e) => (e.source === "load" && e.target === "b" ? edge("load-2", "b") : e));
    const compare = g.nodes.find((n) => n.id === COMPARE)!;
    mockFlow = flowOf(g);
    const view = render(<Harness data={compare.data} state={nodeState()} />);
    expect(screen.getByText(/read different context/).textContent).toBe(
      "input_1 (Twice as tall) and input_0 (Baseline) read different context: only input_1 reads Loader 2020; only input_0 reads Loader.",
    );
    fireEvent.click(screen.getByRole("tab", { name: "What differs" }));
    const row = view.container.querySelector('[data-compare-widget="factor"]')!;
    expect(row.textContent).toContain("Baseline: 1");
    expect(row.textContent).toContain("Twice as tall: 2");
  });
});

describe("a run's outcome", () => {
  const ran = { code: "success", content: "Saved to file: stacked-1" };

  test("gives the body a new identity, which opens the Output tab, however the node ran", () => {
    // A step of a run on the server reaches the node as its outcome alone, so
    // the outcome is what opens the tab, not the play button.
    const g = graph({ compareScenarios: { inputs: [BASE, TALL] } });
    const compare = g.nodes.find((n) => n.id === COMPARE)!;
    mockFlow = flowOf(g);
    const view = render(<Harness data={compare.data} state={nodeState()} />);
    const fresh = bodies[bodies.length - 1];
    view.rerender(<Harness data={compare.data} state={nodeState()} />);
    expect(bodies[bodies.length - 1]).toBe(fresh);
    view.rerender(<Harness data={compare.data} state={nodeState(ran)} />);
    const done = bodies[bodies.length - 1];
    expect(done).not.toBe(fresh);
    view.rerender(<Harness data={compare.data} state={nodeState({ ...ran })} />);
    expect(bodies[bodies.length - 1]).toBe(done);
  });

  test("that failed says why, where the chart goes", () => {
    const g = graph({ compareScenarios: { inputs: [BASE, TALL] } });
    const compare = g.nodes.find((n) => n.id === COMPARE)!;
    mockFlow = flowOf(g, { outputs: [{ nodeId: COMPARE, output: { path: "stacked-1", dataType: "dataframe" } }] });
    const failed = {
      code: "error",
      content:
        "Traceback (most recent call last):\n  File \"<string>\", line 4, in userCode\n" +
        "ValueError: Compare Scenarios stacks inputs of one kind, and these differ: input_0 (Baseline) is a table, input_1 (Twice as tall) is a value. Connect outcomes of the same kind.",
    };
    const view = render(<Harness data={compare.data} state={nodeState(failed)} />);
    expect(view.container.querySelector("[data-compare-run-error]")!.textContent).toBe(
      "Compare Scenarios stacks inputs of one kind, and these differ: input_0 (Baseline) is a table, input_1 (Twice as tall) is a value. Connect outcomes of the same kind.",
    );
    expect(mockUseVega).not.toHaveBeenCalled();
  });

  test("restored by a load, it draws the saved output it names, though the flow lists no outputs yet", async () => {
    // A load restores each node with its saved output's outcome, and the
    // flow's outputs list starts empty: the dashboard and a reopened canvas.
    const g = graph({ compareScenarios: { inputs: [BASE, TALL] } });
    const compare = g.nodes.find((n) => n.id === COMPARE)!;
    mockFlow = flowOf(g);
    render(<Harness data={compare.data} state={nodeState({ code: "success", content: "Saved to file: computed.p1.cmp.parquet" })} />);
    await waitFor(() => expect(mockUseVega).toHaveBeenCalled());
    expect(mockUseVega.mock.calls.at(-1)![0].data.input.path).toBe("computed.p1.cmp.parquet");
  });

  test("the chart says when its compile settled, and what stopped it", async () => {
    const g = graph({ compareScenarios: { inputs: [BASE, TALL] } });
    const compare = g.nodes.find((n) => n.id === COMPARE)!;
    mockFlow = flowOf(g);
    const restored = nodeState({ code: "success", content: "Saved to file: computed.p1.cmp.parquet" });
    const view = render(<Harness data={compare.data} state={restored} />);
    const chartState = () => view.container.querySelector("[data-compare-chart-state]")?.getAttribute("data-compare-chart-state");
    await waitFor(() => expect(chartState()).toBe("drawn"));
    // The reference the chart reads carries the type its read found.
    expect(mockUseVega.mock.calls.at(-1)![0].data.input).toEqual({ path: "computed.p1.cmp.parquet", dataType: "dataframe" });
    expect(view.container.querySelector("[data-compare-chart-problem]")).toBeNull();

    mockCompile.mockRejectedValueOnce(new Error("undefined is not iterable"));
    view.unmount();
    const again = render(<Harness data={compare.data} state={restored} />);
    await waitFor(() =>
      expect(again.container.querySelector("[data-compare-chart-state]")?.getAttribute("data-compare-chart-state")).toBe("problem"),
    );
    expect(again.container.querySelector("[data-compare-chart-problem]")!.textContent).toBe("undefined is not iterable");
  });

  test("the file a run saved is its outcome's last such line", () => {
    expect(savedFile("stdout:\nSaved to file: printed-by-the-code\nSaved to file: 1791158683119_cf030fd5")).toBe(
      "1791158683119_cf030fd5",
    );
    expect(savedFile("No output yet")).toBeNull();
  });

  test("a message that is no traceback is shown as it is", () => {
    expect(failureLine("input_1 (from Scale) has no value yet. Run the node that feeds it.")).toBe(
      "input_1 (from Scale) has no value yet. Run the node that feeds it.",
    );
  });
});
