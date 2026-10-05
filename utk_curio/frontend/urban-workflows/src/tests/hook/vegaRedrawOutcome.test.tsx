/**
 * A chart judges every redraw, not only its first draw.
 *
 * The report: after a Run All on example 10, a chart said "rendered nothing: 0
 * rows arrived at this node" while it was on screen with its bars. Its first
 * compile had zero rows; when the rows arrived, `useVega` hot-swapped them
 * into the compiled view, which drew them, but that path never reported what
 * it drew, so the verdict from zero rows stayed on the node.
 */
import { act, renderHook, waitFor } from "@testing-library/react";

// Only what useVega calls on the library: a changeset records its operations,
// and a view records the changesets it is handed and draws three bars.
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

function frame(labels: string[]) {
  return {
    dataType: "dataframe",
    data: {
      label: labels,
      value: labels.map((_, i) => i + 1),
      interacted: Object.fromEntries(labels.map((_, i) => [String(i), "0"])),
    },
  };
}

beforeAll(() => {
  (globalThis as any).ResizeObserver ??= class { observe() {} disconnect() {} };
});

async function chartFirstDrawnOver(input: any) {
  document.body.innerHTML = '<div id="vegan1"></div>';
  const onRedraw = jest.fn();
  const base = { nodeId: "n1", interactionsCallback: jest.fn(), outputCallback: jest.fn() };
  const hook = renderHook(
    ({ input }: { input: any }) => useVega({ data: { ...base, input }, code: SPEC, onRedraw }),
    { initialProps: { input } },
  );
  let first: any;
  await act(async () => {
    first = await hook.result.current.handleCompileGrammar(SPEC);
  });
  return { hook, onRedraw, first };
}

test("rows arriving after a zero-row draw are reported with what the view drew", async () => {
  const { hook, onRedraw, first } = await chartFirstDrawnOver(frame([]));
  expect(first.rowsIn).toBe(0);

  await act(async () => {
    hook.rerender({ input: frame(["a", "b", "c"]) });
  });
  await waitFor(() => expect(onRedraw).toHaveBeenCalled());
  const counts = onRedraw.mock.calls[onRedraw.mock.calls.length - 1][0];
  expect(counts.rowsIn).toBe(3);
  expect(counts.drawn).toBe(3);
});

test("rows emptied by a later run are reported as zero rows", async () => {
  const { hook, onRedraw } = await chartFirstDrawnOver(frame(["a", "b"]));

  await act(async () => {
    hook.rerender({ input: frame([]) });
  });
  await waitFor(() => expect(onRedraw).toHaveBeenCalled());
  expect(onRedraw.mock.calls[onRedraw.mock.calls.length - 1][0].rowsIn).toBe(0);
});

test("a selection echo is not a redraw: the rows are the same ones", async () => {
  const { hook, onRedraw } = await chartFirstDrawnOver(frame(["a", "b", "c"]));

  await act(async () => {
    hook.rerender({ input: markSelectionEcho(frame(["a", "b", "c"])) });
  });
  // The echo path re-flags rows and returns; give it the same ticks a redraw takes.
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 20));
  });
  expect(onRedraw).not.toHaveBeenCalled();
});
