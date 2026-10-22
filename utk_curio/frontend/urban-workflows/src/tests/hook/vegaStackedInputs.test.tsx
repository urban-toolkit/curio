/**
 * A Vega-Lite spec that reads `inputs` (#662), which its editor writes from
 * the chip `[!! inputs !!]` before the chart draws, is drawn from every input's rows
 * stacked, each named by its scenario's box, and judged on them: what arrived
 * is every input's rows, not the first input's alone. A new input stacks them
 * again under the names the chart has then.
 *
 * vega-lite builds only the datasets a spec reads, so a view drawing `inputs`
 * alone holds no `input_0`. A selection that covers the first input's rows, a
 * Data Pool's echo of one or a direct link's, lands on its rows in `inputs`
 * (`__input__` 0), and a change to a dataset the view lacks is skipped: vega
 * throws for one, and so does the stand-in below.
 */
import { act, renderHook, waitFor } from "@testing-library/react";

// Only what useVega calls on the library: a view keeps the spec it was built
// from and the changesets it is handed, and its scenegraph is whatever the
// test sets. As vega's, it throws for a change to a dataset it does not hold.
jest.mock("vega", () => {
  const { datasetsRead, unrecognizedDataset } = require("../_support/vegaViewDatasets");
  const views: any[] = [];
  const changeset = () => {
    const ops: any[] = [];
    const cs: any = {
      ops,
      remove: () => cs,
      insert: () => cs,
      modify: (test: any, field: string, value: any) => { ops.push({ op: "modify", test, field, value }); return cs; },
    };
    return cs;
  };
  class View {
    spec: any;
    changes: Array<{ name: string; ops: any[] }> = [];
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
    change(name: string, cs: any) {
      if (!datasetsRead(this.spec).has(name)) throw unrecognizedDataset(name);
      this.changes.push({ name, ops: cs.ops });
      return this;
    }
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
const mockShowToast = jest.fn();
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));
jest.mock("../../services/api", () => ({ fetchData: jest.fn(), fetchPreviewData: jest.fn() }));

import { useVega } from "../../hook/useVega";
import { resolveReferences } from "../../utils/references/codeReferences";
import { renderOutcome } from "../../utils/renderOutcome";
import { markSelectionEcho } from "../../utils/selectionEcho";

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

/** BARS as Scout's charts write it: its dataset named by its chip. */
const CHIP_BARS = BARS.replace('"name":"inputs"', '"name":"[!! inputs !!]"');

/** *raw* as the node's editor writes it before a run (components/editing/NodeEditor):
 * its chips resolved over the chart's two wired circles, in a Vega-Lite spec. */
function asTheEditorWrites(raw: string): string {
  expect(raw).toContain("[!! inputs !!]");
  const { code, problems } = resolveReferences(
    raw, { widgets: [], inputs: [{ slot: 0 }, { slot: 1 }], shared: [] }, "json", "vega-lite",
  );
  expect(problems).toEqual([]);
  return code;
}

/** The first input's rows as bars, and every input's stacked rows as points over them. */
const OVER_THE_FIRST = JSON.stringify({
  layer: [
    { mark: "bar", encoding: { x: { field: "segment", type: "nominal" }, y: { field: "sunlight", type: "quantitative" } } },
    {
      data: { name: "inputs" },
      mark: "point",
      encoding: { x: { field: "segment", type: "nominal" }, y: { field: "sunlight", type: "quantitative" } },
    },
  ],
});

/** A chart joined to this one by a direct interaction edge has picked the first input's row *row*. */
const picked = (row: number) => [
  { nodeId: "pick", details: { highlight: { type: "POINT", data: [row], priority: 1 } }, priority: 1 },
];

const frame = (columns: Record<string, unknown[]>) => ({ dataType: "dataframe", data: columns });
const both = (first: any, second: any) => ({ dataType: "outputs", data: [first, second] });

type Props = { input: any; labels: typeof BASE[]; interactions?: unknown };

async function drawn(input: any, labels: typeof BASE[], spec = BARS, interactions?: unknown) {
  document.body.innerHTML = '<div id="vegan1"></div>';
  const base = { nodeId: "n1", interactionsCallback: jest.fn(), outputCallback: jest.fn() };
  const hook = renderHook(
    ({ input: current, labels: names, interactions: incoming }: Props) =>
      useVega({ data: { ...base, input: current, interactions: incoming }, code: spec, inputLabels: names }),
    { initialProps: { input, labels, interactions } as Props },
  );
  let counts: any;
  await act(async () => {
    counts = await hook.result.current.handleCompileGrammar(spec);
  });
  return { hook, counts, view: views()[views().length - 1] };
}

/** The flag each of *rows* gets from the change *change* made. */
const flagsOf = (change: { ops: any[] }, rows: any[]) => rows.map((row) => change.ops[0].value(row));

beforeAll(() => {
  (globalThis as any).ResizeObserver ??= class { observe() {} disconnect() {} };
});

beforeEach(() => {
  views().length = 0;
  mockShowToast.mockClear();
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
    // One input object for every render, as a node's data holds it.
    const data = {
      nodeId: "n1",
      interactionsCallback: jest.fn(),
      outputCallback: jest.fn(),
      input: both(frame({ a: [1] }), frame({ a: [2] })),
    };
    const hook = renderHook(() => useVega({ data, code: spec, inputLabels: [BASE, TALL] }));
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

describe("a selection coming back from a Data Pool", () => {
  const flagged = (flags: string[]) => frame({ segment: ["r1", "r2"], sunlight: [5, 6], interacted: flags });
  const tall = frame({ segment: ["r1"], sunlight: [3] });

  test("on a chart that reads inputs alone: that input's rows in inputs change their flags, not the view (#535)", async () => {
    // Its dataset named by its chip, as the editor writes it.
    const { hook, view } = await drawn(both(flagged(["0", "0"]), tall), [BASE, TALL], asTheEditorWrites(CHIP_BARS));
    const count = views().length;
    // The view holds inputs alone, as vega-lite builds it.
    expect(() => view.change("input_0", { ops: [] })).toThrow("Unrecognized data set: input_0");

    await act(async () => {
      hook.rerender({ input: both(markSelectionEcho(flagged(["0", "1"])), tall), labels: [BASE, TALL] });
    });
    await waitFor(() => expect(view.changes.map((change: any) => change.name)).toEqual(["inputs"]));
    expect(views()).toHaveLength(count);
    expect(mockShowToast).not.toHaveBeenCalled();
    // Baseline's second row is picked; Twice as tall's row keeps its flag.
    expect(flagsOf(view.changes[0], [
      { __input__: 0, __row_index__: 0, interacted: "0" },
      { __input__: 0, __row_index__: 1, interacted: "0" },
      { __input__: 1, __row_index__: 0, interacted: "0" },
    ])).toEqual(["0", "1", "0"]);
  });

  test("on a chart that reads the first input and inputs: both change their flags", async () => {
    const { hook, view } = await drawn(both(flagged(["0", "0"]), tall), [BASE, TALL], OVER_THE_FIRST);

    await act(async () => {
      hook.rerender({ input: both(markSelectionEcho(flagged(["1", "0"])), tall), labels: [BASE, TALL] });
    });
    await waitFor(() => expect(view.changes.map((change: any) => change.name)).toEqual(["input_0", "inputs"]));
    expect(flagsOf(view.changes[0], [{ __row_index__: 0, interacted: "0" }, { __row_index__: 1, interacted: "0" }]))
      .toEqual(["1", "0"]);
    expect(flagsOf(view.changes[1], [
      { __input__: 0, __row_index__: 0, interacted: "0" },
      { __input__: 1, __row_index__: 0, interacted: "0" },
    ])).toEqual(["1", "0"]);
  });
});

describe("a selection from a chart joined by a direct interaction edge", () => {
  const rows = [
    { __input__: 0, __row_index__: 0, interacted: "0" },
    { __input__: 0, __row_index__: 1, interacted: "0" },
    { __input__: 1, __row_index__: 1, interacted: "1" },
  ];
  const two = () => both(frame({ segment: ["r1", "r2"], sunlight: [5, 6] }), frame({ segment: ["r1", "r2"], sunlight: [3, 2] }));

  test("lights the first input's rows in inputs on the first draw, and the draw still counts its marks", async () => {
    // Its dataset named by its chip, as the editor writes it.
    const { counts, view } = await drawn(two(), [BASE, TALL], asTheEditorWrites(CHIP_BARS), picked(1));
    expect(counts.drawn).toBe(3);
    expect(view.changes.map((change: any) => change.name)).toEqual(["inputs"]);
    // The first input's second row is picked; another input's row keeps its flag.
    expect(flagsOf(view.changes[0], rows)).toEqual(["0", "1", "1"]);
  });

  test("a selection arriving after the draw lights them too, and nothing throws", async () => {
    // The same input on every render: only the selection changes.
    const input = two();
    const { hook, view } = await drawn(input, [BASE, TALL]);
    expect(view.changes).toEqual([]);

    await act(async () => {
      hook.rerender({ input, labels: [BASE, TALL], interactions: picked(0) });
    });
    await waitFor(() => expect(view.changes.map((change: any) => change.name)).toContain("inputs"));
    const last = view.changes[view.changes.length - 1];
    expect(last.name).toBe("inputs");
    expect(flagsOf(last, rows)).toEqual(["1", "0", "1"]);
    expect(mockShowToast).not.toHaveBeenCalled();
  });

  test("a chart that reads the first input and inputs lights both", async () => {
    const { view } = await drawn(two(), [BASE, TALL], OVER_THE_FIRST, picked(1));
    expect(view.changes.map((change: any) => change.name)).toEqual(["input_0", "inputs"]);
    expect(flagsOf(view.changes[0], [{ __row_index__: 0 }, { __row_index__: 1 }])).toEqual(["0", "1"]);
    expect(flagsOf(view.changes[1], rows)).toEqual(["0", "1", "1"]);
  });

  test("a chart that reads only its second input changes nothing it does not hold, and counts its marks", async () => {
    const second = JSON.stringify({ data: { name: "input_1" }, mark: "bar" });
    const { counts, view } = await drawn(two(), [BASE, TALL], second, picked(1));
    expect(counts.drawn).toBe(3);
    expect(view.changes).toEqual([]);
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
