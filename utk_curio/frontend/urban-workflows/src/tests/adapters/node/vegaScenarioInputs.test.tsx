/**
 * A Vega-Lite chart whose spec reads `inputs` (#662) names its rows by the
 * scenario boxes its inputs come from, stacked in circle order. It draws
 * exactly its spec: the boxes' colors and order are where its scenario chips
 * write them, `[!! scenario colors !!]` and `[!! scenario order !!]`, which its
 * editor resolves before a run (utils/references/codeReferences), and a spec
 * without them draws in Vega-Lite's own colors and order, or the ones it
 * writes. A box renamed or recolored draws it again when what it draws moves,
 * through its chips or the names its rows carry, with no version in its
 * provenance and nothing handed downstream; not during a run, which draws it
 * itself, and not before the chart is first drawn. A spec that does not read
 * `inputs` stacks nothing.
 *
 * The behavior and useVega are real here; vega and vega-lite are the mocks
 * below, which keep the spec each view is built from. A chart's chips are
 * resolved as its editor resolves them (NodeEditor), which hands the behavior
 * the written spec with how to write it again for other labels (`redrawOf`).
 */
import { act, renderHook, waitFor } from "@testing-library/react";

jest.mock("vega", () => {
  const { datasetsRead, unrecognizedDataset } = require("../../_support/vegaViewDatasets");
  const views: any[] = [];
  const changeset = () => {
    const cs: any = { remove: () => cs, insert: () => cs, modify: () => cs };
    return cs;
  };
  class View {
    spec: any;
    constructor(spec: any) { this.spec = spec; views.push(this); }
    logLevel() { return this; }
    renderer() { return this; }
    initialize() { return this; }
    hover() { return this; }
    width() { return this; }
    height() { return this; }
    resize() { return this; }
    runAsync() { return Promise.resolve(this); }
    scenegraph() { return { root: { marktype: "rect", items: [{}, {}] } }; }
    getState() { return { signals: {}, data: {} }; }
    addSignalListener() { throw new Error("no signal"); }
    // As vega's, a view holds only the datasets its spec reads.
    change(name: string) {
      if (!datasetsRead(this.spec).has(name)) throw unrecognizedDataset(name);
      return this;
    }
  }
  return { changeset, View, parse: (spec: any) => spec, Warn: 2, __views: views };
}, { virtual: true });
jest.mock("vega-lite", () => ({ compile: (spec: any) => ({ spec }) }), { virtual: true });

// The flow the chart reads its inputs' boxes from; set per test, read on every render.
let mockFlow: Record<string, unknown> = {};
const mockProvenance = jest.fn();
jest.mock("../../../providers/FlowProvider", () => ({ useFlowContext: () => mockFlow }));
jest.mock("../../../providers/ProvenanceProvider", () => ({
  useProvenanceContext: () => ({ nodeExecProv: mockProvenance }),
}));
jest.mock("../../../providers/ToastProvider", () => ({ useToastContext: () => ({ showToast: jest.fn() }) }));
jest.mock("../../../services/api", () => ({ fetchData: jest.fn(), fetchPreviewData: jest.fn() }));

import { useVegaBehavior } from "../../../adapters/node/vegaBehavior";
import { resolveReferences, type InputScope } from "../../../utils/references/codeReferences";
import { inputScenarios } from "../../../utils/scenarios/inputScenarios";

const views = (): any[] => (jest.requireMock("vega") as any).__views;

const node = (id: string, nodeType: string, extra: Record<string, unknown> = {}) => ({
  id,
  type: "__curioUniversalNode",
  data: { nodeId: id, nodeType, ...extra },
});
const edge = (source: string, target: string, targetHandle = "in") => ({
  id: `${source}->${target}:${targetHandle}`,
  source,
  target,
  sourceHandle: "out",
  targetHandle,
});

const BASE = { id: "s-base", name: "Baseline", color: "#2a9d8f", nodes: ["base"] };
const TALL = { id: "s-tall", name: "Twice as tall", color: "#e76f51", nodes: ["tall"] };
const NODES = [
  node("base", "curio.builtin/computation-analysis@1", { title: "Shade" }),
  node("tall", "curio.builtin/computation-analysis@1", { title: "Shade" }),
  node("chart", "curio.builtin/vis-vega@1"),
];
const EDGES = [edge("base", "chart", "in"), edge("tall", "chart", "in_1")];

const setFlow = (scenarios: unknown[], extra: Record<string, unknown> = {}) => {
  mockFlow = {
    nodes: NODES,
    edges: EDGES,
    scenarios,
    nodeExecStatus: {},
    isRunActive: false,
    workflowNameRef: { current: "wf" },
    dashboardOn: false,
    ...extra,
  };
};

const frame = (sunlight: number[]) => ({
  dataType: "dataframe",
  data: { segment: sunlight.map((_, i) => `r${i + 1}`), sunlight },
});
/** What the chart's two circles hold: Baseline's rows, then Twice as tall's. */
const INPUT = { dataType: "outputs", data: [frame([5, 6]), frame([3])] };

/** Mean sunlight per scenario, colored by scenario, its colors written by hand. */
const BARS = JSON.stringify({
  data: { name: "inputs" },
  mark: "bar",
  encoding: {
    x: { field: "scenario_name", type: "nominal" },
    y: { field: "sunlight", type: "quantitative", aggregate: "mean" },
    color: {
      field: "scenario_name",
      type: "nominal",
      scale: { domain: ["Twice as tall", "Baseline"], range: ["#000000", "#999999"] },
    },
  },
});

/** Mean sunlight per scenario, in the boxes' colors and order, through chips. */
const CHIP_BARS = '{"data": {"name": "inputs"}, "mark": "bar", "encoding": {'
  + '"x": {"field": "scenario_name", "type": "nominal", "sort": [!! scenario order !!]}, '
  + '"y": {"field": "sunlight", "type": "quantitative", "aggregate": "mean"}, '
  + '"color": {"field": "scenario_name", "type": "nominal", "scale": [!! scenario colors !!]}}}';

/** The chart node over the two boxes' rows, drawn once by a Play of *spec*, handed in as written. */
async function playedChart(spec = BARS) {
  const data: any = {
    nodeId: "chart",
    input: INPUT,
    outputCallback: jest.fn(),
    interactionsCallback: jest.fn(),
  };
  const nodeState: any = { code: spec, setOutput: jest.fn(), templateData: { code: spec } };
  let hook: any;
  await act(async () => {
    hook = renderHook(() => useVegaBehavior(data, nodeState));
  });
  const before = views().length;
  await act(async () => {
    await hook.result.current.applyGrammar(spec);
  });
  expect(views()).toHaveLength(before + 1);
  return { hook, data, nodeState };
}

/** Each circle's label, as the editor's scope holds it (hook/useInputScope): its box's, ranked by the dataflow's list, else its node's. */
const labelsOf = (scenarios: any[]) => new Map(
  inputScenarios("chart", (mockFlow.nodes as any[]) ?? NODES, (mockFlow.edges as any[]) ?? EDGES, scenarios).map((input) => [
    input.slot,
    input.scenario ? { ...input.label, rank: scenarios.findIndex((s) => s.id === input.scenario!.id) } : input.label,
  ]),
);
const scopeOf = (labels: Map<number, any>) => ({
  widgets: [],
  shared: [],
  inputs: [0, 1].map((slot): InputScope => ({ slot, dataType: "dataframe", columns: ["segment", "sunlight"], scenario: labels.get(slot) })),
});
/** What the editor writes for *raw* with *labels*, or null when a chip does not resolve. */
const writeWith = (raw: string, labels: Map<number, any>) => {
  const { code, problems } = resolveReferences(raw, scopeOf(labels), "json", "vega-lite");
  return problems.length > 0 ? null : code;
};
const redrawOf = (raw: string) => (labels: ReadonlyMap<number, any>) => writeWith(raw, new Map(labels));

/** The chart played over the flow's boxes, its chips resolved as the editor resolves them. */
async function playedWithChips(raw: string) {
  const written = writeWith(raw, labelsOf(mockFlow.scenarios as any[]));
  expect(written).not.toBeNull();
  const data: any = { nodeId: "chart", input: INPUT, outputCallback: jest.fn(), interactionsCallback: jest.fn() };
  const nodeState: any = { code: raw, setOutput: jest.fn(), templateData: { code: raw } };
  let hook: any;
  await act(async () => {
    hook = renderHook(() => useVegaBehavior(data, nodeState));
  });
  await act(async () => {
    await (hook.result.current.applyGrammar as any)(written, redrawOf(raw));
  });
  expect(views()).toHaveLength(1);
  return { hook, data, nodeState, written: written as string };
}

/** The flow changed: the chart renders again, and is drawn *count* times in all. */
async function changed(played: { hook: any }, scenarios: unknown[], count: number, extra: Record<string, unknown> = {}) {
  setFlow(scenarios, extra);
  await act(async () => {
    played.hook.rerender();
  });
  await waitFor(() => expect(views()).toHaveLength(count));
}

/** The rows the last view stacked, as [id, name, sunlight]. */
const stackedRows = () =>
  views()[views().length - 1].spec.datasets.inputs.map((row: any) => [row.scenario, row.scenario_name, row.sunlight]);
const lastSpec = () => views()[views().length - 1].spec;

/**
 * The chart renders again over the flow as it is now, and is not drawn again:
 * given the time a redraw takes to start and land (as `changed` waits for
 * one), no view comes past *count*.
 */
async function drawsNothingNew(hook: { rerender: () => void }, count: number) {
  await act(async () => {
    hook.rerender();
  });
  await expect(waitFor(() => expect(views()).toHaveLength(count + 1), { timeout: 1000 })).rejects.toThrow();
  expect(views()).toHaveLength(count);
}

/** The flow changed: the chart renders again, and is drawn again once. */
async function redrawn(played: Awaited<ReturnType<typeof playedChart>>, scenarios: unknown[]) {
  setFlow(scenarios);
  await act(async () => {
    played.hook.rerender();
  });
  await waitFor(() => expect(views()).toHaveLength(2));
  await waitFor(() => expect(played.nodeState.setOutput).toHaveBeenCalledTimes(2));
}

beforeAll(() => {
  (globalThis as any).ResizeObserver ??= class { observe() {} disconnect() {} };
});

beforeEach(() => {
  document.body.innerHTML = '<div id="vegachart"></div>';
  views().length = 0;
  mockProvenance.mockClear();
  setFlow([BASE, TALL]);
});

describe("a chart reading inputs names its rows by its inputs' boxes", () => {
  test("each row under its box's id and name, in circle order", async () => {
    const { nodeState } = await playedChart();
    expect(stackedRows()).toEqual([
      ["s-base", "Baseline", 5],
      ["s-base", "Baseline", 6],
      ["s-tall", "Twice as tall", 3],
    ]);
    expect(nodeState.setOutput).toHaveBeenLastCalledWith({ code: "success", content: "", outputType: "" });
  });

  test("the rows stay in circle order, whatever order the dataflow lists its boxes in", async () => {
    // Listed Twice as tall first, wired Baseline first.
    setFlow([TALL, BASE]);
    await playedChart();
    expect(stackedRows().map((row: any[]) => row[1])).toEqual(["Baseline", "Baseline", "Twice as tall"]);
  });

  test("a spec whose text holds a bare chip reads inputs once its chips are resolved, as the editor hands it on", async () => {
    // The y field is a column chip, written bare: the text is no JSON until it resolves.
    const raw = '{"data": {"name": "inputs"}, "mark": "bar", "encoding": {'
      + '"x": {"field": "scenario_name", "type": "nominal"}, "y": {"field": [!! input_0.sunlight !!], "type": "quantitative"}}}';
    expect(() => JSON.parse(raw)).toThrow();
    const scope = { widgets: [], shared: [], inputs: [0, 1].map((slot) => ({ slot, columns: ["segment", "sunlight"] })) };
    const { code, problems } = resolveReferences(raw, scope, "json");
    expect(problems).toEqual([]);
    await playedChart(code);
    expect(lastSpec().encoding.y.field).toBe("sunlight");
    expect(stackedRows()).toEqual([
      ["s-base", "Baseline", 5],
      ["s-base", "Baseline", 6],
      ["s-tall", "Twice as tall", 3],
    ]);
  });

  test("an input whose node is in no box is named by its node, in a neutral color through the chips", async () => {
    setFlow([BASE]);
    await playedWithChips(CHIP_BARS);
    expect(stackedRows()[2]).toEqual([null, "Shade", 3]);
    expect(lastSpec().encoding.color.scale).toEqual({ domain: ["Baseline", "Shade"], range: ["#2a9d8f", "#8a8f98"] });
  });

  test("only a spec that reads inputs: the same spec without it stacks nothing and is drawn as written", async () => {
    await playedChart();
    expect(Object.keys(lastSpec().datasets)).toEqual(["input_0", "input_1", "inputs"]);

    const plain = JSON.stringify({ ...JSON.parse(BARS), data: undefined });
    await playedChart(plain);
    expect(Object.keys(lastSpec().datasets)).toEqual(["input_0", "input_1"]);
    expect(lastSpec().encoding.color.scale).toEqual({ domain: ["Twice as tall", "Baseline"], range: ["#000000", "#999999"] });
  });
});

describe("a chart reading inputs with no box among its inputs", () => {
  /** The spec's own color scale. */
  const OWN_SCALE = { domain: ["Twice as tall", "Baseline"], range: ["#000000", "#999999"] };

  test("draws its own colors and order", async () => {
    setFlow([]);
    await playedChart();
    expect(lastSpec().encoding.color.scale).toEqual(OWN_SCALE);
    expect(lastSpec().encoding.x.sort).toBeUndefined();
    // Both feeders are titled Shade: their rows carry one name.
    expect(stackedRows()).toEqual([
      [null, "Shade", 5],
      [null, "Shade", 6],
      [null, "Shade", 3],
    ]);
  });

  test("a box drawn around a feeder afterwards: the chart draws again, in the boxes' colors through its chips", async () => {
    setFlow([]);
    const played = await playedWithChips(CHIP_BARS);
    // Both from no box, both named Shade: one name, written alone, which
    // Vega-Lite's own palette colors.
    expect(lastSpec().encoding.color.scale).toEqual({ domain: ["Shade"] });

    await changed(played, [BASE], 2);
    expect(lastSpec().encoding.color.scale).toEqual({ domain: ["Baseline", "Shade"], range: ["#2a9d8f", "#8a8f98"] });
    expect(lastSpec().encoding.x.sort).toEqual(["Baseline", "Shade"]);
    expect(stackedRows().map((row: any[]) => row[1])).toEqual(["Baseline", "Baseline", "Shade"]);
  });

  test("guard: two boxes of one name draw as one name, in the first box's color", async () => {
    setFlow([BASE, { ...TALL, name: "Baseline" }]);
    await playedWithChips(CHIP_BARS);
    expect(stackedRows().map((row: any[]) => row[1])).toEqual(["Baseline", "Baseline", "Baseline"]);
    expect(lastSpec().encoding.color.scale).toEqual({ domain: ["Baseline"], range: ["#2a9d8f"] });
  });

  test("untitled nodes of one type, in no box, give their rows one name, in the spec's own colors", async () => {
    setFlow([], {
      nodes: [
        node("base", "curio.builtin/computation-analysis@1"),
        node("tall", "curio.builtin/computation-analysis@1"),
        node("chart", "curio.builtin/vis-vega@1"),
      ],
    });
    await playedChart();
    const names = stackedRows().map((row: any[]) => row[1]);
    expect(new Set(names).size).toBe(1);
    expect(lastSpec().encoding.color.scale).toEqual(OWN_SCALE);
  });
});

describe("a chart reading inputs whose one wired input carries several tables", () => {
  test("says so and draws nothing, as Python's stack_inputs refuses it", async () => {
    setFlow([BASE], { edges: [edge("base", "chart", "in")] });
    const data: any = {
      nodeId: "chart",
      // A node returning a tuple of two tables, on the chart's one circle.
      input: { dataType: "outputs", data: [frame([5, 6]), frame([3])] },
      outputCallback: jest.fn(),
      interactionsCallback: jest.fn(),
    };
    const nodeState: any = { code: BARS, setOutput: jest.fn(), templateData: { code: BARS } };
    let hook: any;
    await act(async () => {
      hook = renderHook(() => useVegaBehavior(data, nodeState));
    });
    await act(async () => {
      await hook.result.current.applyGrammar(BARS);
    });
    expect(views()).toHaveLength(0);
    const [last] = nodeState.setOutput.mock.calls[nodeState.setOutput.mock.calls.length - 1];
    expect(last.code).toBe("error");
    expect(last.content).toContain(
      'The dataset "inputs": input_0 (Baseline) carries 2 tables. Connect a node that returns one table, '
        + "or pick the table to compare in a node between them.",
    );
  });
});

describe("a box renamed or recolored draws the chart again", () => {
  test("renamed: its rows are stacked again under the new name, with no version and nothing handed on", async () => {
    const played = await playedChart();
    await redrawn(played, [{ ...BASE, name: "Today" }, TALL]);
    expect(stackedRows()).toEqual([
      ["s-base", "Today", 5],
      ["s-base", "Today", 6],
      ["s-tall", "Twice as tall", 3],
    ]);
    // Its own scale, as written.
    expect(lastSpec().encoding.color.scale.domain).toEqual(["Twice as tall", "Baseline"]);
    expect(mockProvenance).toHaveBeenCalledTimes(1);
    expect(played.data.outputCallback).toHaveBeenCalledTimes(1);
  });

  test("recolored: a chart that writes no chip draws nothing new, its rows carry no color", async () => {
    const played = await playedChart();
    setFlow([BASE, { ...TALL, color: "#7b3294" }]);
    await drawsNothingNew(played.hook, 1);
  });

  test("a box whose id alone changed: its rows carry the new id; a change the chart does not draw draws nothing", async () => {
    const played = await playedChart();
    await redrawn(played, [{ ...BASE, id: "s-today" }, TALL]);
    expect(stackedRows()[0]).toEqual(["s-today", "Baseline", 5]);

    setFlow([{ ...BASE, id: "s-today", description: "the city as built" }, TALL]);
    await drawsNothingNew(played.hook, 2);
  });

  test("renamed during a run: the run draws it, then the chart is drawn again once the run ends if the run did not", async () => {
    const played = await playedWithChips(CHIP_BARS);
    const renamed = [{ ...BASE, name: "Today" }, TALL];

    setFlow(renamed, { isRunActive: true });
    await drawsNothingNew(played.hook, 1);

    await changed(played, renamed, 2, { isRunActive: false });
    expect(stackedRows().map((row: any[]) => row[1])).toEqual(["Today", "Today", "Twice as tall"]);
    expect(lastSpec().encoding.x.sort).toEqual(["Today", "Twice as tall"]);
    expect(mockProvenance).toHaveBeenCalledTimes(1);
  });

  test("nothing is drawn before the chart has been drawn once", async () => {
    const data: any = { nodeId: "chart", input: INPUT, outputCallback: jest.fn(), interactionsCallback: jest.fn() };
    const nodeState: any = { code: BARS, setOutput: jest.fn(), templateData: { code: "" } };
    let hook: any;
    await act(async () => {
      hook = renderHook(() => useVegaBehavior(data, nodeState));
    });
    setFlow([BASE, { ...TALL, color: "#7b3294" }]);
    await drawsNothingNew(hook, 0);
  });
});

/**
 * The chips a spec writes its scenarios with: `[!! scenario colors !!]` the
 * scale of the boxes' colors, `[!! scenario order !!]` their names in the order
 * the dataflow lists them, `[!! scenario input_1 !!]` the color of input_1's
 * box. The node's editor resolves them before a run, as it resolves every chip
 * (components/editing/NodeEditor), and hands the behavior the spec it wrote
 * with a way to write it again for other labels: `redrawOf` above does what
 * the editor's does. A chart draws exactly its spec, its chips resolved: a spec
 * without them gets Vega-Lite's own colors and order.
 */
describe("a chart writes its scenarios through chips", () => {
  test("a chart with the chips draws exactly its spec, in the boxes' colors and in the order the dataflow lists them", async () => {
    // Listed Twice as tall first, wired Baseline first.
    setFlow([TALL, BASE]);
    const { written, nodeState } = await playedWithChips(CHIP_BARS);
    expect(lastSpec().encoding).toEqual(JSON.parse(written).encoding);
    expect(lastSpec().encoding.color.scale).toEqual({ domain: ["Twice as tall", "Baseline"], range: ["#e76f51", "#2a9d8f"] });
    expect(lastSpec().encoding.x.sort).toEqual(["Twice as tall", "Baseline"]);
    // The rows stay in circle order.
    expect(stackedRows().map((row: any[]) => row[1])).toEqual(["Baseline", "Baseline", "Twice as tall"]);
    expect(nodeState.setOutput).toHaveBeenLastCalledWith({ code: "success", content: "", outputType: "" });
  });

  test("a chart reading inputs without the chips draws Vega-Lite's own colors and order, or the ones it writes", async () => {
    const plain = JSON.stringify({
      data: { name: "inputs" },
      mark: "bar",
      encoding: {
        x: { field: "scenario_name", type: "nominal" },
        y: { field: "sunlight", type: "quantitative", aggregate: "mean" },
        color: { field: "scenario_name", type: "nominal" },
      },
    });
    await playedChart(plain);
    expect(lastSpec().encoding.color.scale).toBeUndefined();
    expect(lastSpec().encoding.x.sort).toBeUndefined();
    // Its rows still carry their boxes' names.
    expect(stackedRows().map((row: any[]) => row[1])).toEqual(["Baseline", "Baseline", "Twice as tall"]);

    // A scale the spec writes for scenario_name is the one drawn.
    await playedChart(BARS);
    expect(lastSpec().encoding.color.scale).toEqual({ domain: ["Twice as tall", "Baseline"], range: ["#000000", "#999999"] });
    expect(lastSpec().encoding.x.sort).toBeUndefined();
  });

  test("renamed, then recolored: drawn again through its chips each time, with no version and nothing handed on", async () => {
    const played = await playedWithChips(CHIP_BARS);
    await changed(played, [{ ...BASE, name: "Today" }, TALL], 2);
    expect(lastSpec().encoding.color.scale).toEqual({ domain: ["Today", "Twice as tall"], range: ["#2a9d8f", "#e76f51"] });
    expect(lastSpec().encoding.x.sort).toEqual(["Today", "Twice as tall"]);
    expect(stackedRows().map((row: any[]) => row[1])).toEqual(["Today", "Today", "Twice as tall"]);

    await changed(played, [{ ...BASE, name: "Today" }, { ...TALL, color: "#7b3294" }], 3);
    expect(lastSpec().encoding.color.scale).toEqual({ domain: ["Today", "Twice as tall"], range: ["#2a9d8f", "#7b3294"] });
    expect(mockProvenance).toHaveBeenCalledTimes(1);
    expect(played.data.outputCallback).toHaveBeenCalledTimes(1);
  });

  test("a chart that does not read inputs is drawn again when the box its chip names is recolored", async () => {
    // Twice as tall's own rows, its bars in its box's color.
    const raw = '{"data": {"name": "input_1"}, "mark": {"type": "bar", "color": [!! scenario input_1 !!]}, '
      + '"encoding": {"x": {"field": "segment", "type": "nominal"}, "y": {"field": "sunlight", "type": "quantitative"}}}';
    const played = await playedWithChips(raw);
    expect(lastSpec().mark.color).toBe("#e76f51");
    expect(lastSpec().datasets.inputs).toBeUndefined();

    await changed(played, [BASE, { ...TALL, color: "#7b3294" }], 2);
    expect(lastSpec().mark.color).toBe("#7b3294");

    // Baseline's recolor writes nothing this chart draws: no new view.
    setFlow([{ ...BASE, color: "#111111" }, { ...TALL, color: "#7b3294" }]);
    await drawsNothingNew(played.hook, 2);
  });
});
