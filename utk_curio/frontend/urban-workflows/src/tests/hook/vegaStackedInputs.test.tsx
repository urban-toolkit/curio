/**
 * A Vega-Lite spec that reads `inputs` (#662) is drawn from every input's rows
 * stacked, each named by its scenario's box, and judged on them: what arrived
 * is every input's rows, not the first input's alone. A new input stacks them
 * again under the names the chart has then.
 */
import { act, renderHook, waitFor } from "@testing-library/react";

// Only what useVega calls on the library: a view keeps the spec it was built
// from, and its scenegraph is whatever the test sets.
jest.mock("vega", () => {
  const views: any[] = [];
  const changeset = () => {
    const cs: any = { remove: () => cs, insert: () => cs, modify: () => cs };
    return cs;
  };
  class View {
    spec: any;
    static scene: any = { items: [] };
    constructor(spec: any) { this.spec = spec; views.push(this); }
    logLevel() { return this; }
    renderer() { return this; }
    initialize() { return this; }
    hover() { return this; }
    width() { return this; }
    height() { return this; }
    resize() { return this; }
    runAsync() { return Promise.resolve(this); }
    scenegraph() { return { root: View.scene }; }
    getState() { return { signals: {} }; }
    addSignalListener() { throw new Error("no signal"); }
    change() { return this; }
  }
  return { changeset, View, parse: (spec: any) => spec, Warn: 2, __views: views };
}, { virtual: true });
jest.mock("vega-lite", () => ({ compile: (spec: any) => ({ spec }) }), { virtual: true });

jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ workflowNameRef: { current: "wf" } }),
}));
jest.mock("../../providers/ProvenanceProvider", () => ({
  useProvenanceContext: () => ({ nodeExecProv: jest.fn() }),
}));
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));
jest.mock("../../services/api", () => ({ fetchData: jest.fn(), fetchPreviewData: jest.fn() }));

import { useVega } from "../../hook/useVega";
import { renderOutcome } from "../../utils/renderOutcome";

const vegaMock = () => jest.requireMock("vega") as any;
const views = (): any[] => vegaMock().__views;

const BASE = { scenario: "s-base", name: "Baseline", color: "#2a9d8f" };
const TALL = { scenario: "s-tall", name: "Twice as tall", color: "#e76f51" };

/** Mean sunlight per scenario, read from the stacked rows. */
const BARS = JSON.stringify({
  data: { name: "inputs" },
  mark: "bar",
  encoding: {
    x: { field: "scenario_name", type: "nominal" },
    y: { field: "sunlight", type: "quantitative", aggregate: "mean" },
  },
});

const frame = (columns: Record<string, unknown[]>) => ({ dataType: "dataframe", data: columns });
const both = (first: any, second: any) => ({ dataType: "outputs", data: [first, second] });

async function drawn(input: any, labels: typeof BASE[]) {
  document.body.innerHTML = '<div id="vegan1"></div>';
  const base = { nodeId: "n1", interactionsCallback: jest.fn(), outputCallback: jest.fn() };
  const hook = renderHook(
    ({ input: current, labels: names }: { input: any; labels: typeof BASE[] }) =>
      useVega({ data: { ...base, input: current }, code: BARS, inputLabels: names }),
    { initialProps: { input, labels } },
  );
  let counts: any;
  await act(async () => {
    counts = await hook.result.current.handleCompileGrammar(BARS);
  });
  return { hook, counts, view: views()[views().length - 1] };
}

beforeAll(() => {
  (globalThis as any).ResizeObserver ??= class { observe() {} disconnect() {} };
});

beforeEach(() => {
  views().length = 0;
  // Three bars drawn.
  vegaMock().View.scene = { marktype: "rect", items: [{}, {}, {}] };
});

describe("a chart reading inputs is judged on every input's rows", () => {
  test("the first input's column is empty and the second's is not: it drew, and says so", async () => {
    const { counts, view } = await drawn(
      both(frame({ sunlight: [null, null] }), frame({ sunlight: [3] })),
      [BASE, TALL],
    );
    expect(view.spec.datasets.inputs.map((row: any) => [row.scenario_name, row.sunlight])).toEqual([
      ["Baseline", null],
      ["Baseline", null],
      ["Twice as tall", 3],
    ]);
    // Every stacked row holds its scenario's name, which the chart plots.
    expect(counts).toMatchObject({ rowsIn: 3, usableRows: 3, usableFields: ["scenario_name", "sunlight"] });
    expect(renderOutcome(counts).empty).toBe(false);
  });

  test("the first input has no rows and the second has some: rows arrived", async () => {
    const { counts } = await drawn(both(frame({ sunlight: [] }), frame({ sunlight: [3, 4] })), [BASE, TALL]);
    expect(counts).toMatchObject({ rowsIn: 2, usableRows: 2 });
    expect(renderOutcome(counts).empty).toBe(false);
  });

  test("the scenarios' names are a column it plots, which every stacked row holds", async () => {
    const spec = JSON.stringify({
      data: { name: "inputs" },
      mark: "point",
      encoding: { x: { field: "scenario_name", type: "nominal" }, color: { field: "__input__", type: "nominal" } },
    });
    document.body.innerHTML = '<div id="vegan1"></div>';
    const base = { nodeId: "n1", interactionsCallback: jest.fn(), outputCallback: jest.fn() };
    const hook = renderHook(() =>
      useVega({ data: { ...base, input: both(frame({ a: [1] }), frame({ a: [2] })) }, code: spec, inputLabels: [BASE, TALL] }),
    );
    let counts: any;
    await act(async () => {
      counts = await hook.result.current.handleCompileGrammar(spec);
    });
    expect(counts.usableFields).toEqual(["scenario_name", "__input__"]);
    expect(counts).toMatchObject({ rowsIn: 2, usableRows: 2 });
  });

  test("inputs that cannot be stacked draw nothing, and say why the upstream must change", async () => {
    const clash = frame({ scenario_name: ["mine"], sunlight: [1] });
    const { counts } = await drawn(both(frame({ sunlight: [3] }), clash), [BASE, TALL]);
    expect(counts.drawn).toBe(0);
    const outcome = renderOutcome(counts);
    expect(outcome.empty).toBe(true);
    expect(outcome.message).toContain('The dataset "inputs": input_1 (Twice as tall) already has a column named scenario_name.');
    expect(outcome.message).toContain("The upstream node that feeds it is what must change");
    expect(document.getElementById("vegan1")!.textContent).toContain("already has a column named scenario_name");
  });
});

describe("a new input stacks the rows again", () => {
  test("under the names the chart has when it arrives", async () => {
    const { hook } = await drawn(both(frame({ sunlight: [5] }), frame({ sunlight: [3] })), [BASE, TALL]);
    const before = views().length;
    const renamed = [{ ...BASE, name: "Today" }, TALL];
    await act(async () => {
      hook.rerender({ input: both(frame({ sunlight: [6] }), frame({ sunlight: [3] })), labels: renamed });
    });
    await waitFor(() => expect(views().length).toBe(before + 1));
    const rows = views()[views().length - 1].spec.datasets.inputs;
    expect(rows.map((row: any) => [row.scenario, row.scenario_name, row.sunlight])).toEqual([
      ["s-base", "Today", 6],
      ["s-tall", "Twice as tall", 3],
    ]);
  });
});
