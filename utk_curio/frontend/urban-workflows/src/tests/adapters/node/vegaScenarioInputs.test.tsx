/**
 * A Vega-Lite chart whose spec reads `inputs` (#662) names its rows by the
 * scenario boxes its inputs come from, stacked in circle order, and draws them
 * in the boxes' colors, in the order the dataflow lists its boxes, whatever the
 * spec writes for `scenario_name`. A box renamed or recolored draws it again,
 * its rows stacked again under the new name, as a recolor draws a chart after
 * a Compare Scenarios node: no version in its provenance, nothing handed
 * downstream. A spec that does not read `inputs` stacks nothing and is drawn as
 * written.
 *
 * The behavior and useVega are real here; vega and vega-lite are the mocks
 * below, which keep the spec each view is built from.
 */
import { act, renderHook, waitFor } from "@testing-library/react";

jest.mock("vega", () => {
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
    change() { return this; }
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
import { resolveReferences } from "../../../utils/references/codeReferences";

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

/** The chart node over the two boxes' rows, drawn once by a Play. */
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

/** The rows the last view stacked, as [id, name, sunlight]. */
const stackedRows = () =>
  views()[views().length - 1].spec.datasets.inputs.map((row: any) => [row.scenario, row.scenario_name, row.sunlight]);
const lastSpec = () => views()[views().length - 1].spec;

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
  test("each row under its box's id and name, drawn in the boxes' colors in circle order", async () => {
    const { nodeState } = await playedChart();
    expect(stackedRows()).toEqual([
      ["s-base", "Baseline", 5],
      ["s-base", "Baseline", 6],
      ["s-tall", "Twice as tall", 3],
    ]);
    expect(lastSpec().encoding.color.scale).toEqual({ domain: ["Baseline", "Twice as tall"], range: ["#2a9d8f", "#e76f51"] });
    expect(lastSpec().encoding.x.sort).toEqual(["Baseline", "Twice as tall"]);
    expect(nodeState.setOutput).toHaveBeenLastCalledWith({ code: "success", content: "", outputType: "" });
  });

  test("the scales take the order the dataflow lists its boxes in; the rows stay in circle order", async () => {
    // Listed Twice as tall first, wired Baseline first.
    setFlow([TALL, BASE]);
    await playedChart();
    expect(lastSpec().encoding.color.scale).toEqual({ domain: ["Twice as tall", "Baseline"], range: ["#e76f51", "#2a9d8f"] });
    expect(lastSpec().encoding.x.sort).toEqual(["Twice as tall", "Baseline"]);
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

  test("an input whose node is in no box is named by its node, in a neutral color", async () => {
    setFlow([BASE]);
    await playedChart();
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

describe("a box renamed or recolored draws the chart again", () => {
  test("renamed: its rows are stacked again under the new name, with no version and nothing handed on", async () => {
    const played = await playedChart();
    await redrawn(played, [{ ...BASE, name: "Today" }, TALL]);
    expect(stackedRows()).toEqual([
      ["s-base", "Today", 5],
      ["s-base", "Today", 6],
      ["s-tall", "Twice as tall", 3],
    ]);
    expect(lastSpec().encoding.color.scale.domain).toEqual(["Today", "Twice as tall"]);
    expect(mockProvenance).toHaveBeenCalledTimes(1);
    expect(played.data.outputCallback).toHaveBeenCalledTimes(1);
  });

  test("recolored: drawn in the new color", async () => {
    const played = await playedChart();
    await redrawn(played, [BASE, { ...TALL, color: "#7b3294" }]);
    expect(lastSpec().encoding.color.scale).toEqual({ domain: ["Baseline", "Twice as tall"], range: ["#2a9d8f", "#7b3294"] });
    expect(stackedRows()[2]).toEqual(["s-tall", "Twice as tall", 3]);
  });

  test("a box whose id alone changed: its rows carry the new id; a change the chart does not draw draws nothing", async () => {
    const played = await playedChart();
    await redrawn(played, [{ ...BASE, id: "s-today" }, TALL]);
    expect(stackedRows()[0]).toEqual(["s-today", "Baseline", 5]);

    setFlow([{ ...BASE, id: "s-today", description: "the city as built" }, TALL]);
    await act(async () => {
      played.hook.rerender();
    });
    expect(views()).toHaveLength(2);
  });
});
