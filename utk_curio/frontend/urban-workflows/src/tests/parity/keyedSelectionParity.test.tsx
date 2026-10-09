/**
 * A pick on an Autark map that names its rows by key (`selectFields`) sends
 * what a Vega-Lite point select over the same fields sends (#847): the values
 * of the units picked. So a Data Pool, or any chart linked to either, marks
 * the same rows for both, wherever it holds them. What differs is by nature:
 * the select's name, its source, and the layer an Autark pick names.
 *
 * The units and readings are _support/keyedSelections' fixture.
 */
import { act, renderHook } from "@testing-library/react";

// Only what useVega calls on the library, as in hook/vegaMultiInput.test.tsx.
jest.mock("vega", () => {
  const views: any[] = [];
  const changeset = () => {
    const cs: any = { remove: () => cs, insert: () => cs, modify: () => cs };
    return cs;
  };
  class View {
    spec: any;
    listeners: Record<string, (name: string, value: any) => void> = {};
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
    scenegraph() { return { root: { items: [] } }; }
    getState() { return { signals: Object.fromEntries(View.signals.map((name) => [name, null])) }; }
    addSignalListener(name: string, fn: any) {
      if (!View.signals.includes(name)) throw new Error(`Unrecognized signal name: "${name}"`);
      this.listeners[name] = fn;
    }
    change() { return this; }
  }
  return { changeset, View, parse: (spec: any) => spec, Warn: 2, __views: views };
}, { virtual: true });
jest.mock("vega-lite", () => ({ compile: (spec: any) => ({ spec }) }), { virtual: true });

jest.mock("../../providers/FlowProvider", () => require("../_support/autkNodeMocks").flowProviderModule);
jest.mock("../../providers/ToastProvider", () => require("../_support/autkNodeMocks").toastProviderModule);
jest.mock("../../providers/ProvenanceProvider", () => ({
  useProvenanceContext: () => ({ nodeExecProv: jest.fn() }),
}));
jest.mock("../../services/api", () => require("../_support/autkNodeMocks").apiModule);
jest.mock("../../JavaScriptInterpreter", () => ({ JavaScriptInterpreter: class { } }));
jest.mock(
  "@urban-toolkit/autk-grammar",
  () => require("../_support/autkNodeMocks").autkGrammarModule,
  { virtual: true },
);
jest.mock("@urban-toolkit/autk-compute", () => ({ ComputeGpgpu: jest.fn() }), { virtual: true });

import { useVega } from "../../hook/useVega";
import { columnRows, matchSelections } from "../../utils/selectionMatch";
import { grammarRuns, resetAutkNodeMocks } from "../_support/autkNodeMocks";
import { lastSelection, mountAutkNode, stubWebGpu, unstubWebGpu } from "../_support/autkNode";
import {
  UNIT_ROW,
  atPositions,
  drawnAt,
  expectDiscriminates,
  inHeightRange,
  looselyHolding,
  readingColumns,
  readingsOf,
  unitsCollection,
  unitsFrame,
} from "../_support/keyedSelections";

const vegaMock = () => jest.requireMock("vega") as any;

/** A bar per unit, picked by a point select over unit_id. */
const PICK_UNITS = JSON.stringify({
  params: [{ name: "pick", select: { type: "point", fields: ["unit_id"] } }],
  mark: "bar",
  encoding: { x: { field: "unit_id", type: "ordinal" }, y: { field: "height", type: "quantitative" } },
});
/** The units on an Autark map, picked by their unit_id. */
const PICK_SQUARES = {
  map: { layerRefs: [{ dataRef: "input_0", getFnv: "height", isPick: true, selectFields: ["unit_id"] }] },
};

/** The readings a Data Pool linked to the view marks for its *select*. */
const marked = (select: any) =>
  matchSelections([{ details: { select }, priority: 1 }], columnRows(readingColumns()));

beforeAll(() => {
  (globalThis as any).ResizeObserver ??= class { observe() {} disconnect() {} };
});

beforeEach(() => {
  resetAutkNodeMocks();
  stubWebGpu();
  vegaMock().View.signals = ["pick", "pick_modify"];
});

afterEach(unstubWebGpu);

test("repro: the same picks on a Vega-Lite chart and on an Autark map send the same values, and a Data Pool marks the same readings", async () => {
  // The chart first: it draws into the page's one container.
  document.body.innerHTML = '<div id="vegachart"></div>';
  const fromChart = jest.fn();
  const data = { nodeId: "chart", input: unitsFrame(), interactionsCallback: fromChart, outputCallback: jest.fn() };
  const hook = renderHook(() => useVega({ data, code: PICK_UNITS }));
  await act(async () => {
    await hook.result.current.handleCompileGrammar(PICK_UNITS);
  });
  const views = vegaMock().__views;
  const view = views[views.length - 1];
  const map = mountAutkNode("map", unitsCollection());
  await map.run(PICK_SQUARES);
  const chartSent = () => fromChart.mock.calls[fromChart.mock.calls.length - 1][0].pick;

  // Unit 103.
  await act(async () => {
    view.listeners.pick("pick", { unit_id: [103] });
  });
  act(() => grammarRuns[0].pick([drawnAt(UNIT_ROW[103])]));

  expect(lastSelection(map).data).toEqual(chartSent().data);
  expect(lastSelection(map)).toMatchObject({ type: chartSent().type, priority: chartSent().priority });
  expect(marked(lastSelection(map))).toEqual(marked(chartSent()));
  expect(marked(chartSent())).toEqual(readingsOf(103));
  expectDiscriminates(readingsOf(103), {
    positions: atPositions([UNIT_ROW[103]]),
    range: inHeightRange([103]),
    looseEquality: looselyHolding([103]),
  });

  // Units 103 and 105, as vega lists two points.
  await act(async () => {
    view.listeners.pick("pick", { unit_id: [103, 105], vlPoint: { or: [{ unit_id: 103 }, { unit_id: 105 }] } });
  });
  act(() => grammarRuns[0].pick([drawnAt(UNIT_ROW[103]), drawnAt(UNIT_ROW[105])]));

  expect(lastSelection(map).data).toEqual(chartSent().data);
  expect(marked(lastSelection(map))).toEqual(marked(chartSent()));
  expect(marked(chartSent())).toEqual(readingsOf(103, 105));
  expectDiscriminates(readingsOf(103, 105), {
    positions: atPositions([UNIT_ROW[103], UNIT_ROW[105]]),
    range: inHeightRange([103, 105]),
    looseEquality: looselyHolding([103, 105]),
  });
});
