/**
 * A selection a Data Pool sends back re-flags the rows a Vega-Lite view
 * already holds, rather than replacing them (#535).
 *
 * A point selection remembers the `_vgsid_` of the marks it picked, and vega
 * gives every row it is handed a new one. Swapping in the echo's rows left the
 * chart's own hover selection pointing at rows that were gone, so every bar
 * dimmed, the hovered one too. New data still replaces the rows.
 */
import { act, renderHook, waitFor } from "@testing-library/react";

// Only what useVega calls on the library: a changeset records its operations,
// and a view records the changesets it is handed.
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
    changes: Array<{ name: string; ops: any[] }> = [];
    constructor() { views.push(this); }
    logLevel() { return this; }
    renderer() { return this; }
    initialize() { return this; }
    hover() { return this; }
    width() { return this; }
    height() { return this; }
    resize() { return this; }
    runAsync() { return Promise.resolve(this); }
    scenegraph() { return { root: { marktype: "rect", items: [{}, {}, {}] } }; }
    getState() { return { signals: {} }; }
    addSignalListener() {}
    change(name: string, cs: any) { this.changes.push({ name, ops: cs.ops }); return this; }
  }
  return { changeset, View, parse: (spec: any) => spec, Warn: 2, __views: views };
}, { virtual: true });
jest.mock("vega-lite", () => ({ compile: () => ({ spec: {} }) }), { virtual: true });

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

const SPEC = JSON.stringify({
  mark: "bar",
  encoding: {
    x: { field: "label", type: "nominal" },
    y: { field: "value", type: "quantitative" },
  },
});

/** A pool's output: the rows, with the flags it sets in `interacted`. */
function frame(flags: string[], labels = ["a", "b", "c"].slice(0, flags.length)) {
  return {
    dataType: "dataframe",
    data: {
      label: labels,
      value: labels.map((_, i) => i + 1),
      interacted: Object.fromEntries(flags.map((flag, i) => [String(i), flag])),
    },
  };
}

async function drawnChart() {
  document.body.innerHTML = '<div id="vegan1"></div>';
  const base = { nodeId: "n1", interactionsCallback: jest.fn(), outputCallback: jest.fn() };
  const hook = renderHook(
    ({ input }: { input: any }) => useVega({ data: { ...base, input }, code: SPEC }),
    { initialProps: { input: frame(["0", "0", "0"]) as any } },
  );
  await act(async () => {
    await hook.result.current.handleCompileGrammar(SPEC);
  });
  const views = (jest.requireMock("vega") as any).__views;
  const view = views[views.length - 1];
  expect(view.changes).toEqual([]);
  return {
    view,
    async receive(input: any) {
      await act(async () => {
        hook.rerender({ input });
      });
      await waitFor(() => expect(view.changes.length).toBeGreaterThan(0));
      return view.changes[0];
    },
  };
}

beforeAll(() => {
  (globalThis as any).ResizeObserver ??= class { observe() {} disconnect() {} };
});

test("a selection echo changes the flags on the rows the view holds", async () => {
  const chart = await drawnChart();
  const change = await chart.receive(markSelectionEcho(frame(["0", "1", "0"])));

  expect(change.name).toBe("input_0");
  expect(change.ops.map((o: any) => o.op)).toEqual(["modify"]);
  const [{ test, field, value }] = change.ops;
  expect(field).toBe("interacted");
  // The view's own rows, as vega holds them: same positions, old flags.
  const held = [0, 1, 2].map((i) => ({ __row_index__: i, interacted: "0", _vgsid_: 10 + i }));
  expect(held.filter(test).map(value)).toEqual(["0", "1", "0"]);
});

test("new data replaces the rows", async () => {
  const chart = await drawnChart();
  const change = await chart.receive(frame(["0", "0", "0"], ["x", "y", "z"]));

  expect(change.ops.map((o: any) => o.op)).toEqual(["remove", "insert"]);
  expect(change.ops[1].values.map((row: any) => row.label)).toEqual(["x", "y", "z"]);
});

test("an echo that no longer has the view's rows replaces them", async () => {
  // An upstream run can land between a selection and its echo.
  const chart = await drawnChart();
  const change = await chart.receive(markSelectionEcho(frame(["1", "0"])));

  expect(change.ops.map((o: any) => o.op)).toEqual(["remove", "insert"]);
  expect(change.ops[1].values).toHaveLength(2);
});
