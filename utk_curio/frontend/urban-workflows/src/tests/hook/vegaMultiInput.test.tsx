/**
 * A Vega-Lite node with several input circles (#662): each input reaches the
 * spec as the dataset `input_0`, `input_1`, ..., a spec that names none draws
 * the first, and a selection is sent on only as rows of the first input.
 */
import { act, renderHook, waitFor } from "@testing-library/react";

// Only what useVega calls on the library. A view records the spec it was built
// from, the changesets it is handed and its signal listeners; its scenegraph
// and its top-level signals are whatever the test sets. As in vega, a listener
// is added only to a top-level signal.
jest.mock("vega", () => {
  const views: any[] = [];
  const changeset = () => {
    const ops: any[] = [];
    const cs: any = {
      ops,
      remove: (test: any) => { ops.push({ op: "remove", test }); return cs; },
      insert: (values: any) => { ops.push({ op: "insert", values }); return cs; },
      modify: (test: any, field: string, value: any) => { ops.push({ op: "modify", test, field, value }); return cs; },
    };
    return cs;
  };
  class View {
    spec: any;
    changes: Array<{ name: string; ops: any[] }> = [];
    listeners: Record<string, (name: string, value: any) => void> = {};
    static scene: any = { items: [] };
    static signals: string[] = [];
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
    getState() { return { signals: Object.fromEntries(View.signals.map((name) => [name, null])) }; }
    addSignalListener(name: string, fn: any) {
      if (!View.signals.includes(name)) throw new Error(`Unrecognized signal name: "${name}"`);
      this.listeners[name] = fn;
    }
    change(name: string, cs: any) { this.changes.push({ name, ops: cs.ops }); return this; }
  }
  return { changeset, View, parse: (spec: any) => spec, Warn: 2, __views: views };
}, { virtual: true });
// The spec as vega-lite is handed it, so the test reads what was injected.
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
import { markSelectionEcho } from "../../utils/selectionEcho";
import { objectRows, selectIndices } from "../../utils/selectionMatch";

const vegaMock = () => jest.requireMock("vega") as any;

const BARS = JSON.stringify({
  mark: "bar",
  encoding: { x: { field: "label", type: "nominal" }, y: { field: "value", type: "quantitative" } },
});
const LAYERED = JSON.stringify({
  layer: [
    { mark: "bar", encoding: { x: { field: "label", type: "nominal" }, y: { field: "value", type: "quantitative" } } },
    { data: { name: "input_1" }, mark: "point", encoding: { x: { field: "label", type: "nominal" }, y: { field: "income", type: "quantitative" } } },
  ],
});

const frame = (columns: Record<string, unknown[]>) => ({ dataType: "dataframe", data: columns });
const POP = frame({ label: ["a", "b"], value: [1, 2] });
const INCOME = frame({ label: ["a", "b"], income: [10, 20] });
const both = (first: any, second: any) => ({ dataType: "outputs", data: [first, second] });

async function drawn(input: any, spec: string) {
  document.body.innerHTML = '<div id="vegan1"></div>';
  const interactionsCallback = jest.fn();
  const base = { nodeId: "n1", interactionsCallback, outputCallback: jest.fn() };
  const hook = renderHook(
    ({ input: current }: { input: any }) => useVega({ data: { ...base, input: current }, code: spec }),
    { initialProps: { input } },
  );
  await act(async () => {
    await hook.result.current.handleCompileGrammar(spec);
  });
  const views = vegaMock().__views;
  return { hook, view: views[views.length - 1], interactionsCallback };
}

beforeAll(() => {
  (globalThis as any).ResizeObserver ??= class { observe() {} disconnect() {} };
});

beforeEach(() => {
  vegaMock().View.scene = { items: [] };
  vegaMock().View.signals = ["pick", "pick_modify"];
});

/** The interactions the node reported last. */
const lastReported = (interactionsCallback: jest.Mock) =>
  interactionsCallback.mock.calls[interactionsCallback.mock.calls.length - 1][0];

/** BARS declaring *params*. */
const barsWith = (params: any[]) => JSON.stringify({ ...JSON.parse(BARS), params });

test("one input is the spec's own data, named input_0", async () => {
  const { view } = await drawn(POP, BARS);
  expect(view.spec.data.name).toBe("input_0");
  expect(view.spec.data.values.map((row: any) => row.label)).toEqual(["a", "b"]);
  expect(view.spec.datasets).toBeUndefined();
});

test("two inputs are the datasets input_0 and input_1, and the spec reads input_0 unless it names another", async () => {
  const { view } = await drawn(both(POP, INCOME), LAYERED);
  expect(Object.keys(view.spec.datasets)).toEqual(["input_0", "input_1"]);
  expect(view.spec.datasets.input_0.map((row: any) => row.value)).toEqual([1, 2]);
  expect(view.spec.datasets.input_1.map((row: any) => row.income)).toEqual([10, 20]);
  expect(view.spec.data).toEqual({ name: "input_0" });
  expect(view.spec.layer[1].data).toEqual({ name: "input_1" });
});

test("a new input to a two-input chart builds the view again", async () => {
  const { hook, view } = await drawn(both(POP, INCOME), LAYERED);
  const views = vegaMock().__views;
  const before = views.length;
  await act(async () => {
    hook.rerender({ input: both(POP, frame({ label: ["a", "b"], income: [30, 40] })) });
  });
  await waitFor(() => expect(views.length).toBe(before + 1));
  expect(view.changes).toEqual([]);
  expect(views[views.length - 1].spec.datasets.input_1.map((row: any) => row.income)).toEqual([30, 40]);
});

test("a second input arriving, then leaving, builds the view from the spec as written each time", async () => {
  const { hook } = await drawn(POP, BARS);
  const views = vegaMock().__views;

  await act(async () => {
    hook.rerender({ input: both(POP, INCOME) });
  });
  await waitFor(() => expect(views[views.length - 1].spec.datasets).toBeDefined());
  const two = views[views.length - 1].spec;
  expect(Object.keys(two.datasets)).toEqual(["input_0", "input_1"]);
  expect(two.data).toEqual({ name: "input_0" });

  const count = views.length;
  await act(async () => {
    hook.rerender({ input: POP });
  });
  await waitFor(() => expect(views.length).toBe(count + 1));
  const one = views[views.length - 1].spec;
  expect(one.datasets).toBeUndefined();
  expect(one.data.name).toBe("input_0");
  expect(one.data.values.map((row: any) => row.value)).toEqual([1, 2]);
});

test("a selection coming back on one input changes that input's flags in the view, not the view (#535)", async () => {
  const flagged = (flags: string[]) => frame({ label: ["a", "b"], value: [1, 2], interacted: flags });
  const { hook, view } = await drawn(both(flagged(["0", "0"]), INCOME), LAYERED);
  const views = vegaMock().__views;
  const count = views.length;

  await act(async () => {
    hook.rerender({ input: both(markSelectionEcho(flagged(["0", "1"])), INCOME) });
  });
  await waitFor(() => expect(view.changes.length).toBeGreaterThan(0));
  expect(views.length).toBe(count);
  const [change] = view.changes;
  expect(change.name).toBe("input_0");
  expect(change.ops.map((o: any) => o.op)).toEqual(["modify"]);
  const held = [0, 1].map((i) => ({ __row_index__: i, interacted: "0" }));
  expect(held.map(change.ops[0].value)).toEqual(["0", "1"]);
});

test("a pick on a mark of the second input is not sent on as a row of the first", async () => {
  // Row 1 of each input is drawn; vega gave them different tuple ids.
  vegaMock().View.scene = {
    items: [
      { datum: { __row_index__: 1, __input__: 0, _vgsid_: 11 } },
      { datum: { __row_index__: 1, __input__: 1, _vgsid_: 21 } },
    ],
  };
  const { view, interactionsCallback } = await drawn(both(POP, INCOME), LAYERED);

  await act(async () => {
    view.listeners.pick("pick", { _vgsid_: [11, 21] });
  });
  const [interactions] = interactionsCallback.mock.calls[interactionsCallback.mock.calls.length - 1];
  expect(interactions.pick.data).toEqual([1]);

  await act(async () => {
    view.listeners.pick("pick", { _vgsid_: [21] });
  });
  const [after] = interactionsCallback.mock.calls[interactionsCallback.mock.calls.length - 1];
  expect(after.pick.data).toEqual([]);
});

test("a select whose name holds an underscore is heard, and reported under its whole name (#846)", async () => {
  vegaMock().View.signals = ["zip_select", "zip_select_modify"];
  const { view, interactionsCallback } = await drawn(
    POP,
    barsWith([{ name: "zip_select", select: { type: "point", fields: ["label"] } }]),
  );
  expect(view.listeners.zip_select).toEqual(expect.any(Function));

  await act(async () => {
    view.listeners.zip_select("zip_select", { label: ["a"] });
  });
  const reported = lastReported(interactionsCallback);
  expect(Object.keys(reported)).toEqual(["zip_select"]);
  expect(reported.zip_select.priority).toBe(1);
});

test("a select inside a concatenated view is heard through its top-level signal (#846)", async () => {
  // vega keeps `brush_modify` in the concatenated view's own scope: only the
  // signal holding the selection, `brush`, is a top-level one.
  vegaMock().View.signals = ["brush"];
  const encoding = { x: { field: "label", type: "nominal" }, y: { field: "value", type: "quantitative" } };
  const spec = JSON.stringify({
    hconcat: [
      { params: [{ name: "brush", select: { type: "interval" } }], mark: "point", encoding },
      { mark: "bar", encoding },
    ],
  });
  const { view, interactionsCallback } = await drawn(POP, spec);
  expect(view.listeners.brush).toEqual(expect.any(Function));

  await act(async () => {
    view.listeners.brush("brush", { value: [1, 2] });
  });
  expect(lastReported(interactionsCallback).brush).toMatchObject({
    type: "INTERVAL",
    data: { value: [1, 2] },
    priority: 1,
  });
});

test("a point select over fields is reported as the values it picked, and matched by value (#847)", async () => {
  const { view, interactionsCallback } = await drawn(
    POP,
    barsWith([{ name: "pick", select: { type: "point", fields: ["value"] } }]),
  );

  // A select over fields reports their values, not vega's tuple ids: value 2,
  // which is not the position of its row.
  await act(async () => {
    view.listeners.pick("pick", { value: [2] });
  });
  expect(lastReported(interactionsCallback).pick).toMatchObject({ type: "POINT", data: [{ value: 2 }], priority: 1 });

  // As vega reports two points: each field's values, and each point under vlPoint.
  await act(async () => {
    view.listeners.pick("pick", { value: [1, 2], vlPoint: { or: [{ value: 1 }, { value: 2 }] } });
  });
  const picked = lastReported(interactionsCallback).pick;
  expect(picked).toMatchObject({ type: "POINT", data: [{ value: 1 }, { value: 2 }], priority: 1 });

  // Whatever table reads it finds the rows holding those values, in its own order.
  expect(selectIndices(picked, objectRows([{ value: 2 }, { value: 3 }, { value: 1 }]))).toEqual([0, 2]);
});
