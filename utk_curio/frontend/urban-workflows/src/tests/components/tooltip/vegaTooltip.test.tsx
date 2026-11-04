/**
 * A chart's data tooltip in the one Curio tooltip. Vega's own tooltip handler
 * writes the hovered mark's tooltip into the chart element as a native
 * `title`; Curio's (components/tooltip/vegaTooltip.ts) writes the same text,
 * at the same moments, as the element's `data-tooltip`, and asks for it at the
 * pointer (`data-tooltip-side="pointer"`). The layer shows it and follows it
 * as the pointer crosses marks (TooltipLayer.test.tsx).
 *
 * "The same text" is checked against Vega itself: its own handler, from the
 * build the app bundles, run on the same values. Then each place that builds a
 * Vega view installs Curio's handler, and the nearest mark's tooltip
 * (`reachVegaTooltips`): the Vega-Lite node (useVega), the grammar adapter,
 * and the monitor page's charts. There the library is a fake that records what
 * each view was given, as in vegaPointerEvents.test.tsx.
 *
 * Last, the nearest mark's tooltip on a view of a scenegraph written here: a
 * pointer near a line, between its points, where Vega gives no tooltip, gets
 * the nearer point's; Vega's own stands; a pointer leaving the chart takes it
 * away. Where the nearest mark lies in a scenegraph Vega built from Vega-Lite
 * is vegaNearestTooltip.test.ts.
 */
import * as path from "path";
import React from "react";
import { act, render, renderHook } from "@testing-library/react";

// Only what the three places call on the library. A view keeps the handler it
// is given, through `view.tooltip(handler)` or its options, and the events it
// is asked to listen to, and draws into a canvas it puts in its container, as
// vega's canvas renderer does. `point` maps a pointer to an element's pixels
// as vega's does, at a CSS scale of 1.
jest.mock(
  "vega",
  () => {
    class View {
      static made: View[] = [];
      options: Record<string, unknown>;
      handler: unknown = undefined;
      listens: string[] = [];
      constructor(_spec: unknown, options?: Record<string, unknown>) {
        this.options = options ?? {};
        View.made.push(this);
      }
      tooltip(handler?: unknown) {
        if (handler === undefined) return this.handler ?? this.options.tooltip;
        this.handler = handler;
        return this;
      }
      logLevel() { return this; }
      renderer() { return this; }
      initialize(target: string | Element) {
        const page = globalThis.document;
        const el = typeof target === "string" ? page.querySelector(target) : target;
        el?.appendChild(page.createElement("canvas"));
        return this;
      }
      hover() { return this; }
      width() { return this; }
      height() { return this; }
      resize() { return this; }
      runAsync() { return Promise.resolve(this); }
      scenegraph() { return { root: { marktype: "rect", items: [{}, {}, {}] } }; }
      getState() { return { signals: {} }; }
      addSignalListener() {}
      addEventListener(type: string) {
        this.listens.push(type);
        return this;
      }
      change() { return this; }
      finalize() {}
    }
    const point = (event: MouseEvent, el: Element) => {
      const box = el.getBoundingClientRect();
      return [event.clientX - box.left, event.clientY - box.top];
    };
    return { View, parse: (spec: unknown) => spec, Warn: 2, changeset: () => ({}), point };
  },
  { virtual: true },
);
jest.mock("vega-lite", () => ({ compile: (spec: unknown) => ({ spec }) }), { virtual: true });

jest.mock("../../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ workflowNameRef: { current: "wf" } }),
}));
jest.mock("../../../providers/ProvenanceProvider", () => ({
  useProvenanceContext: () => ({ nodeExecProv: jest.fn() }),
}));
jest.mock("../../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));
jest.mock("../../../services/api", () => ({ fetchData: jest.fn(), fetchPreviewData: jest.fn() }));

import {
  reachVegaTooltips,
  vegaTooltipHandler,
  type TooltipView,
  type VegaSceneMark,
} from "../../../components/tooltip/vegaTooltip";
import { useVega } from "../../../hook/useVega";
import { vegaLiteAdapter } from "../../../adapters/vegaLiteAdapter";
import { DurationHistogram } from "../../../pages/monitor/MonitorCharts";

/** A Vega tooltip handler: what a view calls with its scenegraph handler, the event, the item and its tooltip. */
type Handler = (handler: { element(): Element | null }, event: unknown, item: unknown, value: unknown) => void;

const curio = vegaTooltipHandler as unknown as Handler;

/** Vega's own handler: the one a view keeps when it is given none. */
function vegasOwn(): Handler {
  const vega = require(path.resolve(__dirname, "../../../../node_modules/vega/build/vega.js"));
  return new vega.View(vega.parse({}), { renderer: "none" }).tooltip();
}

/** What *handler* leaves on a fresh chart element for a mark whose tooltip is *value*. */
function written(handler: Handler, value: unknown) {
  const el = document.createElement("div");
  handler({ element: () => el }, new MouseEvent("pointermove"), {}, value);
  return {
    title: el.getAttribute("title"),
    tooltip: el.getAttribute("data-tooltip"),
    side: el.getAttribute("data-tooltip-side"),
  };
}

/** The values a tooltip encoding gives Vega: a field's text, a number, the fields of a mark, a list. */
const VALUES: unknown[] = [
  "Bronx",
  42,
  { zip: "60614", VEGETATED_SQFT: 1200 },
  { bin: "≤ 1s", count: 3 },
  [1, 2, 3],
  { a: [1, [2]], b: { c: 1 }, d: null },
];

describe("Curio's Vega tooltip handler", () => {
  test("writes the mark's tooltip as data-tooltip, never as a title, and asks for it at the pointer", () => {
    expect(written(curio, { zip: "60614", VEGETATED_SQFT: 1200 })).toEqual({
      title: null,
      tooltip: "zip: 60614\nVEGETATED_SQFT: 1200",
      side: "pointer",
    });
  });

  test("writes every value as Vega's own handler writes it", () => {
    const own = vegasOwn();
    for (const value of VALUES) {
      expect({ value, text: written(curio, value).tooltip }).toEqual({ value, text: written(own, value).title });
    }
  });

  test("clears it where Vega's own handler clears its title", () => {
    const el = document.createElement("div");
    const handler = { element: () => el };
    curio(handler, new MouseEvent("pointermove"), {}, { zip: "60614" });
    expect(el.getAttribute("data-tooltip")).toBe("zip: 60614");
    // Off every mark Vega passes no value, and its own handler empties the title.
    curio(handler, new MouseEvent("pointermove"), {}, null);
    expect(el.getAttribute("data-tooltip") ?? "").toBe("");
    curio(handler, new MouseEvent("pointermove"), {}, { zip: "60601" });
    curio(handler, new MouseEvent("pointermove"), {}, undefined);
    expect(el.getAttribute("data-tooltip") ?? "").toBe("");
    expect(el.hasAttribute("title")).toBe(false);
  });

  test("does nothing before the view has an element", () => {
    expect(() => curio({ element: () => null }, new MouseEvent("pointermove"), {}, { zip: "60614" })).not.toThrow();
  });
});

describe("every Vega view Curio builds uses it", () => {
  const views = () => (jest.requireMock("vega") as { View: { made: any[] } }).View.made;

  /**
   * The last view made was given a handler, and it is Curio's: data-tooltip
   * at the pointer, no title. And it listens to the pointer's moves and its
   * leaving, for the nearest mark's tooltip.
   */
  function expectCuriosHandler(where: string) {
    const view = views()[views().length - 1];
    expect({ where, made: view !== undefined }).toEqual({ where, made: true });
    const handler = view.handler ?? view.options.tooltip;
    expect({ where, handler: typeof handler }).toEqual({ where, handler: "function" });
    expect({ where, written: written(handler as Handler, { label: "a", value: 1 }) }).toEqual({
      where,
      written: { title: null, tooltip: "label: a\nvalue: 1", side: "pointer" },
    });
    expect({ where, listens: [...view.listens].sort() }).toEqual({ where, listens: ["pointermove", "pointerout"] });
  }

  const SPEC = {
    mark: "bar",
    encoding: {
      x: { field: "label", type: "nominal" },
      y: { field: "value", type: "quantitative" },
      tooltip: [{ field: "label" }, { field: "value" }],
    },
  };
  const INPUT = { dataType: "dataframe", data: { label: ["a", "b"], value: [1, 2] } };

  beforeAll(() => {
    (globalThis as any).ResizeObserver ??= class {
      observe() {}
      disconnect() {}
    };
  });

  beforeEach(() => {
    views().length = 0;
  });

  test("the Vega-Lite node's chart (useVega)", async () => {
    document.body.innerHTML = '<div id="vegan1"></div>';
    const code = JSON.stringify(SPEC);
    const base = { nodeId: "n1", interactionsCallback: jest.fn(), outputCallback: jest.fn() };
    const hook = renderHook(() => useVega({ data: { ...base, input: INPUT }, code }));
    await act(async () => {
      await hook.result.current.handleCompileGrammar(code);
    });
    expectCuriosHandler("useVega");
  });

  test("the grammar adapter's chart (vegaLiteAdapter)", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    await vegaLiteAdapter.render(container, SPEC, INPUT);
    expectCuriosHandler("vegaLiteAdapter");
    container.remove();
  });

  test("the monitor page's histograms (MonitorCharts)", () => {
    render(
      <DurationHistogram
        buckets={[
          { leMs: 100, count: 2 },
          { leMs: null, count: 1 },
        ]}
      />,
    );
    expectCuriosHandler("MonitorCharts");
  });
});

describe("the nearest mark's tooltip", () => {
  // A line from (0, 100) to (100, 0) in a group drawn at (10, 20): on the page,
  // from (10, 120) to (110, 20). Its two points are far apart, so most of it
  // lies more than its stroke's width from either, where Vega gives no tooltip.
  const SCENE: VegaSceneMark = {
    marktype: "group",
    items: [
      {
        x: 10,
        y: 20,
        items: [
          {
            marktype: "line",
            items: [
              { x: 0, y: 100, tooltip: { day: 1 } },
              { x: 100, y: 0, tooltip: { day: 2 } },
            ],
          },
        ],
      },
    ],
  };

  /**
   * A view of SCENE drawn into a canvas in its container, at a scale of 1 and
   * padding 0. When *vegaSays* is given, Vega's own handler gives that tooltip
   * for each move, before the nearest mark's listener hears it, as Vega's
   * canvas does.
   */
  function chartOf(vegaSays?: unknown) {
    const container = document.createElement("div");
    const chart = document.createElement("canvas");
    container.appendChild(chart);
    document.body.appendChild(container);
    if (vegaSays !== undefined) {
      chart.addEventListener("pointermove", (event) => curio({ element: () => container }, event, {}, vegaSays));
    }
    const heard: Record<string, (event: PointerEvent) => void> = {};
    const view: TooltipView = {
      addEventListener(type, handler) {
        heard[type] = handler;
        chart.addEventListener(type, handler as EventListener);
        return view;
      },
      container: () => container,
      scenegraph: () => ({ root: SCENE }),
      padding: () => ({ left: 0, top: 0 }),
      origin: () => [0, 0],
    };
    reachVegaTooltips(view);
    const move = (x: number, y: number) =>
      chart.dispatchEvent(new MouseEvent("pointermove", { clientX: x, clientY: y, bubbles: true }));
    const said = () => container.getAttribute("data-tooltip") ?? "";
    return { container, chart, heard, move, said };
  }

  afterEach(() => {
    document.body.innerHTML = "";
  });

  test("a pointer near a line, between its points, gets the nearer point's tooltip at the pointer", () => {
    const { container, move, said } = chartOf();
    // 40% of the way from the first point, 2 px off the line.
    move(10 + 40, 20 + 62);
    expect(said()).toBe("day: 1");
    expect(container.getAttribute("data-tooltip-side")).toBe("pointer");
    // 80% of the way: the second point is nearer.
    move(10 + 80, 20 + 20);
    expect(said()).toBe("day: 2");
  });

  test("a pointer out of reach of every mark gets none", () => {
    const { move, said } = chartOf();
    move(10 + 40, 20 + 62);
    expect(said()).toBe("day: 1");
    // 14 px from the line.
    move(10 + 40, 20 + 80);
    expect(said()).toBe("");
  });

  test("the tooltip Vega gives for a move stands", () => {
    const { move, said } = chartOf({ bar: "own" });
    move(10 + 40, 20 + 62);
    expect(said()).toBe("bar: own");
  });

  test("the pointer leaving the chart takes it away, and crossing from one mark to another does not", () => {
    const { chart, heard, move, said } = chartOf();
    move(10 + 40, 20 + 62);
    expect(said()).toBe("day: 1");
    // Vega's canvas calls its pointerout listeners with the move's own event.
    heard.pointerout(new MouseEvent("pointermove") as PointerEvent);
    expect(said()).toBe("day: 1");
    chart.dispatchEvent(new MouseEvent("pointerout", { relatedTarget: document.body }));
    expect(said()).toBe("");
  });
});
