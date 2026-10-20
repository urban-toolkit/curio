/**
 * A Vega-Lite chart drawn again shows the selection its tags hold, or empties
 * them (#884). A tag keeps the ids of the last selection made in its chart,
 * saved with the dataflow, and a view built again starts on no selection. So a
 * chart whose point select can hold those rows puts them back, as clicks on
 * them would have; a chart whose selection was a brush, which cannot be drawn
 * again from ids, empties its tags instead.
 *
 * useVega is real here, and in the last cases so is useSelectionTags. vega and
 * vega-lite are the mocks below: vega-lite gives each select the signals
 * vega-lite 6 compiles it into (their own output is pinned in
 * utils/selectionTagRestore.test.ts), and a view keeps vega's view state and
 * reads a select's signal off its store, as vega-lite's does.
 */
import React from "react";
import { act, render, renderHook } from "@testing-library/react";
import { VisInteractionType } from "../../constants";

jest.mock("vega", () => {
  const views: any[] = [];
  const changeset = () => {
    const cs: any = { remove: () => cs, insert: () => cs, modify: () => cs };
    return cs;
  };
  // A select's signal as vega-lite resolves it from its store.
  const resolved = (tuples: any[]) => {
    if (tuples.length === 0) return {};
    if (!tuples[0].fields) {
      return {
        _vgsid_: new Set(tuples.map((tuple) => tuple._vgsid_)),
        vlPoint: { or: tuples.map((tuple) => ({ _vgsid_: tuple._vgsid_ })) },
      };
    }
    const fields: string[] = tuples[0].fields.map((field: any) => field.field);
    const points = tuples.map((tuple) => Object.fromEntries(fields.map((field, i) => [field, tuple.values[i]])));
    return { ...Object.fromEntries(fields.map((field) => [field, points.map((point) => point[field])])), vlPoint: { or: points } };
  };
  class View {
    /** The `_vgsid_` a view gives rows 0, 1 and 2 of the chart's input. */
    static ids: number[] = [11, 12, 13];
    spec: any;
    ids: number[];
    signals: Record<string, any> = { width: 300 };
    data: Record<string, any[]> = {};
    restored: any[] = [];
    listeners: Record<string, (name: string, value: any) => void> = {};
    heard: Record<string, any> = {};
    constructor(spec: any) {
      this.spec = spec;
      this.ids = View.ids;
      // Each select's selection starts empty in a view built anew.
      for (const signal of spec.signals ?? []) {
        if (!signal.name.includes("_tuple")) this.signals[signal.name] = {};
      }
      views.push(this);
    }
    logLevel() { return this; }
    renderer() { return this; }
    initialize() { return this; }
    hover() { return this; }
    width() { return this; }
    height() { return this; }
    resize() { return this; }
    // A listener hears its signal after each run that changed it, the first included.
    runAsync() {
      return Promise.resolve().then(() => {
        for (const [name, listener] of Object.entries(this.listeners)) {
          if (name in this.heard && this.heard[name] === this.signals[name]) continue;
          this.heard[name] = this.signals[name];
          listener(name, this.signals[name]);
        }
        return this;
      });
    }
    signal(name: string) { return this.signals[name]; }
    scenegraph() {
      return {
        root: { marktype: "symbol", items: this.ids.map((id, row) => ({ datum: { _vgsid_: id, __row_index__: row } })) },
      };
    }
    getState(options?: any) {
      const keep = (all: Record<string, any>, test: any) =>
        Object.fromEntries(Object.entries(all).filter(([name, value]) => !options || (!!test && test(name, value))));
      return { signals: keep(this.signals, options?.signals), data: keep(this.data, options?.data) };
    }
    setState(state: any) {
      this.restored.push(state);
      this.signals = { ...this.signals, ...state.signals };
      this.data = { ...this.data, ...state.data };
      for (const [name, tuples] of Object.entries(state.data ?? {})) {
        if (name.endsWith("_store")) this.signals[name.slice(0, -"_store".length)] = resolved(tuples as any[]);
      }
      return this;
    }
    addSignalListener(name: string, listener: any) {
      if (!(name in this.signals)) throw new Error(`Unrecognized signal name: "${name}"`);
      this.listeners[name] = listener;
    }
    change() { return this; }
  }
  return { changeset, View, parse: (spec: any) => spec, Warn: 2, __views: views };
}, { virtual: true });

jest.mock("vega-lite", () => {
  const clicked = "datum && item().mark.marktype !== 'group' && indexof(item().mark.role, 'legend') < 0 ? ";
  // The signals vega-lite 6 compiles a select of a single view into.
  const signalsOf = (param: any) => {
    const select = typeof param.select === "string" ? { type: param.select } : param.select;
    const name = param.name;
    if (select.type === "interval") return [{ name }, { name: `${name}_x` }];
    if (!select.fields) {
      return [
        { name },
        { name: `${name}_tuple`, on: [{ update: `${clicked}{unit: "", _vgsid_: (item().isVoronoi ? datum.datum : datum)["_vgsid_"]} : null` }] },
      ];
    }
    return [
      { name },
      {
        name: `${name}_tuple`,
        on: [{ update: `${clicked}{unit: "", fields: ${name}_tuple_fields, values: [(item().isVoronoi ? datum.datum : datum)["${select.fields[0]}"]]} : null` }],
      },
      { name: `${name}_tuple_fields`, value: select.fields.map((field: string) => ({ type: "E", field })) },
    ];
  };
  return {
    compile: (spec: any) => ({
      spec: { ...spec, signals: (spec.params ?? []).filter((param: any) => param.select).flatMap(signalsOf) },
    }),
  };
}, { virtual: true });

// The flow the chart reads its tags from; set per test, read on every render.
let mockFlow: Record<string, unknown> = {};
jest.mock("../../providers/FlowProvider", () => ({ useFlowContext: () => mockFlow }));
jest.mock("../../providers/ProvenanceProvider", () => ({
  useProvenanceContext: () => ({ nodeExecProv: jest.fn() }),
}));
jest.mock("../../providers/ToastProvider", () => ({ useToastContext: () => ({ showToast: jest.fn() }) }));
jest.mock("../../services/api", () => ({ fetchData: jest.fn(), fetchPreviewData: jest.fn() }));

import { useVega } from "../../hook/useVega";
import { useSelectionTags } from "../../providers/flow/useSelectionTags";
import { resetViewSelections, selectionStateOf } from "../../utils/references/viewSelections";
import type { SelectionTag } from "../../utils/references/selectionTags";

const vegaMock = () => jest.requireMock("vega") as any;
const views = (): any[] => vegaMock().__views;

/** Three units: Charlie (row 2) is the one clicked before. */
const UNITS = {
  dataType: "dataframe",
  data: { osm_id: [1001, 1002, 1003], label: ["Alice", "Bob", "Charlie"], value: [30, 10, 50] },
};
const chartWith = (params: any[]) =>
  JSON.stringify({
    params,
    mark: { type: "point", filled: true },
    encoding: { x: { field: "value", type: "quantitative" } },
  });
const PICK = chartWith([{ name: "pick", select: "point" }]);
const PICK_BY_ID = chartWith([{ name: "pick", select: { type: "point", fields: ["osm_id"] } }]);
const BRUSH = chartWith([{ name: "brush", select: "interval" }]);
const PICK_AND_BRUSH = chartWith([
  { name: "pick", select: "point" },
  { name: "brush", select: "interval" },
]);

const tagHolding = (ids: SelectionTag["ids"]): SelectionTag => ({ name: "picked", node: "chart", column: "osm_id", ids });
const flowNodes = (tag: SelectionTag) => [
  { id: "chart", data: { nodeId: "chart" } },
  { id: "counter", data: { nodeId: "counter", selections: [tag] } },
];

const mockClear = jest.fn();

/** The chart drawn by a compile of *spec*, with the counting node's tag *tag*. */
async function drawn(spec: string, tag: SelectionTag) {
  mockFlow = { workflowNameRef: { current: "wf" }, dashboardOn: false, nodes: flowNodes(tag), clearSelectionTagsOf: mockClear };
  const interactionsCallback = jest.fn();
  const data = { nodeId: "chart", input: UNITS, interactionsCallback, outputCallback: jest.fn() };
  const hook = renderHook(() => useVega({ data, code: spec }));
  await act(async () => {
    await hook.result.current.handleCompileGrammar(spec);
  });
  // The selection put back is told once it is back.
  await act(async () => {});
  return { hook, view: views()[views().length - 1], interactionsCallback };
}

/** Every `pick` the chart told the flow. */
const picksSent = (interactionsCallback: jest.Mock) =>
  interactionsCallback.mock.calls.map(([interactions]) => interactions?.pick).filter(Boolean);

beforeAll(() => {
  (globalThis as any).ResizeObserver ??= class { observe() {} disconnect() {} };
});

beforeEach(() => {
  document.body.innerHTML = '<div id="vegachart"></div>';
  views().length = 0;
  vegaMock().View.ids = [11, 12, 13];
  mockClear.mockClear();
  resetViewSelections();
});

describe("a chart drawn again with a tag's ids", () => {
  test("shows those rows selected by its point select, and tells the flow as a click would", async () => {
    // Nothing to put back while the tag holds no ids: drawn as before.
    const before = await drawn(PICK, tagHolding([]));
    expect(before.view.restored).toEqual([]);

    const { view, interactionsCallback } = await drawn(PICK, tagHolding([1003]));

    // Charlie, row 2, under the id this view gives it.
    expect(view.restored).toEqual([{ data: { pick_store: [{ unit: "", _vgsid_: 13 }] } }]);
    expect(picksSent(interactionsCallback).at(-1)).toEqual(
      expect.objectContaining({ type: VisInteractionType.POINT, data: [2], priority: 1 }),
    );
    expect(mockClear).not.toHaveBeenCalled();
  });

  test("never tells the flow the empty selection the new view starts on", async () => {
    // Told, it would empty the tag and mark the counting node stale before the
    // selection came back.
    const { interactionsCallback } = await drawn(PICK, tagHolding([1003]));
    const sent = picksSent(interactionsCallback);
    expect(sent.length).toBeGreaterThan(0);
    for (const pick of sent.filter((p: any) => p.priority === 1)) {
      expect(pick).toEqual(expect.objectContaining({ type: VisInteractionType.POINT, data: [2] }));
    }
  });

  test("of a point select over fields, puts back the values those rows hold", async () => {
    const { view, interactionsCallback } = await drawn(PICK_BY_ID, tagHolding([1003, 1001]));

    expect(view.restored).toEqual([
      {
        data: {
          pick_store: [
            { unit: "", fields: [{ type: "E", field: "osm_id" }], values: [1001] },
            { unit: "", fields: [{ type: "E", field: "osm_id" }], values: [1003] },
          ],
        },
      },
    ]);
    expect(picksSent(interactionsCallback).at(-1)).toEqual(
      expect.objectContaining({ type: VisInteractionType.POINT, data: [{ osm_id: 1001 }, { osm_id: 1003 }], priority: 1 }),
    );
    expect(mockClear).not.toHaveBeenCalled();
  });

  test("redrawn to keep its selection (a recolor), takes the selection from its view, not again from the tags", async () => {
    const { hook, view } = await drawn(PICK, tagHolding([1003]));
    expect(view.restored).toHaveLength(1);

    await act(async () => {
      await hook.result.current.handleCompileGrammar(PICK, {
        recordsProvenance: false, forwardsInput: false, keepsSelection: true,
      });
    });
    await act(async () => {});
    const again = views()[views().length - 1];
    expect(again).not.toBe(view);
    // Only the carried state, the view before's store.
    expect(again.restored).toEqual([{ signals: {}, data: { pick_store: [{ unit: "", _vgsid_: 13 }] } }]);
    expect(mockClear).not.toHaveBeenCalled();
  });
});

describe("a chart drawn again that cannot show its tag's ids empties its tags", () => {
  test("a brush, which cannot be drawn again from ids", async () => {
    const { view } = await drawn(BRUSH, tagHolding([1002, 1003]));
    expect(mockClear).toHaveBeenCalledWith("chart");
    expect(view.restored).toEqual([]);
  });

  test("a chart that declares a brush beside its point select: the tag does not say which made its ids", async () => {
    const { view } = await drawn(PICK_AND_BRUSH, tagHolding([1003]));
    expect(mockClear).toHaveBeenCalledWith("chart");
    expect(view.restored).toEqual([]);
  });

  test("ids no row of the chart holds", async () => {
    const { view } = await drawn(PICK, tagHolding([9999]));
    expect(mockClear).toHaveBeenCalledWith("chart");
    expect(view.restored).toEqual([]);
  });

  test("ids of rows the chart draws no mark for, as a filter leaves them out", async () => {
    // Charlie's row is in the input, but the view draws rows 0 and 1 only.
    vegaMock().View.ids = [11, 12];
    const { view, interactionsCallback } = await drawn(PICK_BY_ID, tagHolding([1003]));
    expect(view.restored).toEqual([]);
    expect(mockClear).toHaveBeenCalledWith("chart");
    // The flow is told the select holds nothing, as the view's first run says.
    expect(picksSent(interactionsCallback).at(-1)).toEqual(
      expect.objectContaining({ data: [], priority: 1 }),
    );
  });

  test("but not once the chart has left the page", async () => {
    await drawn(BRUSH, tagHolding([1003]));
    expect(mockClear).toHaveBeenCalledTimes(1);

    mockFlow = { workflowNameRef: { current: "wf" }, dashboardOn: false, nodes: flowNodes(tagHolding([1003])), clearSelectionTagsOf: mockClear };
    const data = { nodeId: "chart", input: UNITS, interactionsCallback: jest.fn(), outputCallback: jest.fn() };
    const hook = renderHook(() => useVega({ data, code: BRUSH }));
    let compiling: Promise<unknown> = Promise.resolve();
    act(() => {
      compiling = hook.result.current.handleCompileGrammar(BRUSH);
    });
    hook.unmount();
    await act(async () => {
      await compiling;
    });
    expect(mockClear).toHaveBeenCalledTimes(1);
  });
});

describe("with the flow's own selection tags", () => {
  // useSelectionTags over the nodes below, fed what the chart tells it as the
  // flow feeds it: the chart's latest selection, the newest.
  let nodes: any[] = [];
  const stale = jest.fn();
  const dirty = jest.fn();
  const setNodes = jest.fn((update: any) => {
    nodes = typeof update === "function" ? update(nodes) : update;
  });
  let chart: ReturnType<typeof useVega> | null = null;

  function Flow({ spec }: { spec: string }) {
    const [interactions, setInteractions] = React.useState<any[]>([]);
    const tags = useSelectionTags({
      interactions,
      reactFlow: { getNodes: () => nodes } as any,
      setNodes: setNodes as any,
      markNodeStaleRef: { current: stale },
      markDirtyRef: { current: dirty },
    }) as { clearViewTags?: (viewId: string) => void } | undefined;
    mockFlow = { workflowNameRef: { current: "wf" }, dashboardOn: false, nodes, clearSelectionTagsOf: tags?.clearViewTags };
    const data = React.useMemo(
      () => ({
        nodeId: "chart",
        input: UNITS,
        outputCallback: jest.fn(),
        interactionsCallback: (details: any, nodeId: string) => setInteractions([{ nodeId, details, priority: 1 }]),
      }),
      [],
    );
    chart = useVega({ data, code: spec });
    return null;
  }

  async function drawnInFlow(spec: string, tag: SelectionTag) {
    nodes = flowNodes(tag);
    render(<Flow spec={spec} />);
    await act(async () => {
      await chart!.handleCompileGrammar(spec);
    });
    await act(async () => {});
    await act(async () => {});
  }

  const counterTag = () => nodes.find((node) => node.id === "counter").data.selections[0];

  beforeEach(() => {
    stale.mockClear();
    dirty.mockClear();
    setNodes.mockClear();
  });

  test("a point put back with the ids its tag held changes no tag and marks no node stale", async () => {
    await drawnInFlow(PICK, tagHolding([1003]));

    expect(counterTag().ids).toEqual([1003]);
    expect(setNodes).not.toHaveBeenCalled();
    expect(stale).not.toHaveBeenCalled();
    // A tag added now starts from what the chart shows.
    expect(await selectionStateOf("chart", "osm_id")).toEqual({ ids: [1003] });
  });

  test("a brush's tag is emptied, and the node holding it goes stale", async () => {
    await drawnInFlow(BRUSH, tagHolding([1002, 1003]));

    expect(counterTag().ids).toEqual([]);
    expect(stale).toHaveBeenCalledWith("counter");
    expect(dirty).toHaveBeenCalled();
    expect(await selectionStateOf("chart", "osm_id")).toEqual({ ids: [] });
  });
});
