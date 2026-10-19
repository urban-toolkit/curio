/**
 * A scenario recolored draws a Vega-Lite chart after a Compare Scenarios node
 * again as the Compare node's Chart tab draws its own chart
 * (components/compare/CompareChart): through useVega, with no version recorded
 * in the chart's provenance and nothing handed downstream. A selection made in
 * the chart is kept: the new view gets it back on the same rows, and the flow
 * goes on holding it, however fast the recolors come.
 *
 * The behavior and useVega are real here. vega and vega-lite are the mocks
 * below, which keep what each view is handed and the state vega keeps for it.
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { VisInteractionType } from "../../../constants";

// What useVega calls on the library. A view keeps vega's view state (each
// signal's value, each data set's rows), and a select's listener hears its
// signal after each run that changed it, the first included, as vega's does.
// The rows a view draws carry the ids `View.ids` holds when it is built
// (vega's `_vgsid_`), and a select's signal is read off its store on a
// restore, as vega-lite's is.
jest.mock("vega", () => {
  const views: any[] = [];
  const changeset = () => {
    const cs: any = { remove: () => cs, insert: () => cs, modify: () => cs };
    return cs;
  };
  class View {
    static ids: number[] = [1, 2, 3];
    spec: any;
    ids: number[];
    signals: Record<string, any> = { width: 300, pick: {}, pick_tuple: null, pick_toggle: false, pick_modify: 0 };
    data: Record<string, any[]> = { pick_store: [] };
    restored: any[] = [];
    listeners: Record<string, (name: string, value: any) => void> = {};
    heard: Record<string, any> = {};
    constructor(spec: any) {
      this.spec = spec;
      this.ids = View.ids;
      views.push(this);
    }
    logLevel() { return this; }
    renderer() { return this; }
    initialize() { return this; }
    hover() { return this; }
    width() { return this; }
    height() { return this; }
    resize() { return this; }
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
    scenegraph() {
      return {
        root: { marktype: "rect", items: this.ids.map((id, row) => ({ datum: { _vgsid_: id, __row_index__: row } })) },
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
      if (state.data?.pick_store) {
        this.signals.pick = { _vgsid_: state.data.pick_store.map((tuple: any) => tuple._vgsid_) };
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
jest.mock("vega-lite", () => ({ compile: (spec: any) => ({ spec }) }), { virtual: true });

// The flow the chart reads its upstream from; set per test, read on every render.
let mockFlow: Record<string, unknown> = {};
const mockProvenance = jest.fn();
jest.mock("../../../providers/FlowProvider", () => ({ useFlowContext: () => mockFlow }));
jest.mock("../../../providers/ProvenanceProvider", () => ({
  useProvenanceContext: () => ({ nodeExecProv: mockProvenance }),
}));
jest.mock("../../../providers/ToastProvider", () => ({ useToastContext: () => ({ showToast: jest.fn() }) }));
jest.mock("../../../services/api", () => ({ fetchData: jest.fn(), fetchPreviewData: jest.fn() }));

import { useVegaBehavior } from "../../../adapters/node/vegaBehavior";

const vegaMock = () => jest.requireMock("vega") as any;
const views = (): any[] => vegaMock().__views;

const TALL = { scenario: "s-tall", name: "Twice as tall", color: "#e76f51" };
const BASELINE = { scenario: "s-base", name: "Baseline", color: "#2a9d8f" };
const NEW_COLOR = "#7b3294";

const node = (id: string, nodeType: string, extra: Record<string, unknown> = {}) => ({
  id,
  type: "__curioUniversalNode",
  data: { nodeId: id, nodeType, ...extra },
});
const compare = (labels: typeof TALL[]) =>
  node("cmp", "curio.builtin/compare-scenarios@1", { compareScenarios: { inputs: labels } });
const chart = node("chart", "curio.builtin/vis-vega@1");
const EDGES = [{ id: "cmp->chart", source: "cmp", target: "chart", sourceHandle: "out", targetHandle: "in" }];

const setFlow = (labels: typeof TALL[]) => {
  mockFlow = {
    nodes: [compare(labels), chart],
    edges: EDGES,
    scenarios: [],
    nodeExecStatus: {},
    isRunActive: false,
    workflowNameRef: { current: "wf" },
    dashboardOn: false,
  };
};

/** The Compare node's stacked table, as the chart reads it. */
const STACKED = {
  dataType: "dataframe",
  data: { scenario_name: ["Twice as tall", "Baseline", "Baseline"], sunlight: [5, 3, 4] },
};

/** Bars per scenario in their colors, any bar picked by a point select over no fields. */
const PICKED_BARS = JSON.stringify({
  params: [{ name: "pick", select: "point" }],
  mark: "bar",
  encoding: {
    x: { field: "scenario_name", type: "nominal" },
    y: { field: "sunlight", type: "quantitative" },
    color: { field: "scenario_name", type: "nominal" },
  },
});

/** The chart node over the Compare node's table, drawn once by a Play. */
async function playedChart() {
  setFlow([TALL, BASELINE]);
  const data: any = {
    nodeId: "chart",
    input: STACKED,
    outputCallback: jest.fn(),
    interactionsCallback: jest.fn(),
  };
  const nodeState: any = { code: PICKED_BARS, setOutput: jest.fn(), templateData: { code: PICKED_BARS } };
  let hook: any;
  await act(async () => {
    hook = renderHook(() => useVegaBehavior(data, nodeState));
  });
  await act(async () => {
    await hook.result.current.applyGrammar(PICKED_BARS);
  });
  expect(views()).toHaveLength(1);
  expect(mockProvenance).toHaveBeenCalledTimes(1);
  expect(data.outputCallback).toHaveBeenCalledTimes(1);
  return { hook, data, nodeState, view: views()[0] };
}

/** One scenario's box recolored: the chart drawn again in its new color, and that view. */
async function recolored(played: Awaited<ReturnType<typeof playedChart>>) {
  setFlow([{ ...TALL, color: NEW_COLOR }, BASELINE]);
  await act(async () => {
    played.hook.rerender();
  });
  // Done once it says what it drew, as the Play did.
  await waitFor(() => expect(played.nodeState.setOutput).toHaveBeenCalledTimes(2));
  expect(views()).toHaveLength(2);
  const view = views()[1];
  expect(view.spec.encoding.color.scale).toEqual({ domain: [TALL.name, BASELINE.name], range: [NEW_COLOR, BASELINE.color] });
  expect(played.nodeState.setOutput).toHaveBeenLastCalledWith({ code: "success", content: "", outputType: "" });
  return view;
}

/** What the chart last told the flow its select holds. */
const lastSent = (data: any) => data.interactionsCallback.mock.calls.at(-1)[0].pick;

beforeAll(() => {
  (globalThis as any).ResizeObserver ??= class { observe() {} disconnect() {} };
});

beforeEach(() => {
  document.body.innerHTML = '<div id="vegachart"></div>';
  views().length = 0;
  vegaMock().View.ids = [1, 2, 3];
  mockProvenance.mockClear();
});

describe("a recolor draws the chart after a Compare node again, as its Chart tab draws", () => {
  test("in the new color, with no version recorded in the chart's provenance", async () => {
    const played = await playedChart();
    await recolored(played);
    expect(mockProvenance).toHaveBeenCalledTimes(1);
  });

  test("in the new color, handing nothing downstream", async () => {
    const played = await playedChart();
    await recolored(played);
    expect(played.data.outputCallback).toHaveBeenCalledTimes(1);
  });

  test("in the new color, with a selection made in the chart kept, on the same rows", async () => {
    // New rows reached the drawn chart before the pick, so vega numbered them
    // after the rows it held: the view built again numbers them from 1.
    vegaMock().View.ids = [4, 5, 6];
    const played = await playedChart();
    vegaMock().View.ids = [1, 2, 3];

    // The second bar picked, row 1.
    await act(async () => {
      played.view.data.pick_store = [{ unit: "", _vgsid_: 5 }];
      played.view.signals.pick = { _vgsid_: [5], vlPoint: { or: [{ _vgsid_: 5 }] } };
      await played.view.runAsync();
    });
    expect(lastSent(played.data)).toEqual(expect.objectContaining({ type: VisInteractionType.POINT, data: [1] }));
    const sentBefore = played.data.interactionsCallback.mock.calls.length;
    played.view.signals.width = 520;

    const view = await recolored(played);

    // The new view holds the pick on row 1, under its own id for that row, and
    // keeps its own size.
    expect(view.restored).toHaveLength(1);
    expect(view.restored[0].data).toEqual({ pick_store: [{ unit: "", _vgsid_: 2 }] });
    expect(view.signals.width).toBe(300);
    // The flow is never told the select emptied: it goes on holding row 1.
    for (const [sent] of played.data.interactionsCallback.mock.calls.slice(sentBefore)) {
      expect(sent.pick).toEqual(expect.objectContaining({ type: VisInteractionType.POINT, data: [1] }));
    }
    expect(lastSent(played.data)).toEqual(expect.objectContaining({ type: VisInteractionType.POINT, data: [1] }));

    // A pick in the new view reaches the flow, by the new view's ids.
    await act(async () => {
      view.signals.pick = { _vgsid_: [3], vlPoint: { or: [{ _vgsid_: 3 }] } };
      await view.runAsync();
    });
    expect(lastSent(played.data)).toEqual(expect.objectContaining({ type: VisInteractionType.POINT, data: [2] }));
  });

  test("recolored again before its redraw is done, it ends in the last color with the selection kept", async () => {
    const played = await playedChart();
    // The second bar picked, row 1.
    await act(async () => {
      played.view.data.pick_store = [{ unit: "", _vgsid_: 2 }];
      played.view.signals.pick = { _vgsid_: [2], vlPoint: { or: [{ _vgsid_: 2 }] } };
      await played.view.runAsync();
    });
    const sentBefore = played.data.interactionsCallback.mock.calls.length;

    // A color dragged through the picker is written at each step it passes:
    // the second step lands while the redraw for the first is still drawing.
    // Each render is its own act, so the two are not batched into one.
    setFlow([{ ...TALL, color: "#9e9ac8" }, BASELINE]);
    played.hook.rerender();
    setFlow([{ ...TALL, color: NEW_COLOR }, BASELINE]);
    played.hook.rerender();
    // Drawn once by the Play and once for each step.
    await waitFor(() => expect(played.nodeState.setOutput).toHaveBeenCalledTimes(3));

    const last = views()[views().length - 1];
    expect(last.spec.encoding.color.scale.range).toEqual([NEW_COLOR, BASELINE.color]);
    expect(last.restored[last.restored.length - 1]?.data).toEqual({ pick_store: [{ unit: "", _vgsid_: 2 }] });
    for (const [sent] of played.data.interactionsCallback.mock.calls.slice(sentBefore)) {
      expect(sent.pick).toEqual(expect.objectContaining({ type: VisInteractionType.POINT, data: [1] }));
    }
  });
});
