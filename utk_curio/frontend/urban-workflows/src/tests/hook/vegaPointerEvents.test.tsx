/**
 * A Vega-Lite chart on the canvas takes a pointer where it is, at any zoom.
 *
 * React Flow scales the canvas with a CSS transform, so a chart's canvas shows
 * smaller or larger than its own pixels. vega maps a pointer through that
 * scale itself: it divides the pointer's distance from the canvas's on-screen
 * box by the box's scale (`point`, from vega-scenegraph). The first test pins
 * that on the vega Curio installs. The Vega-Lite node hands the chart's
 * pointer events to vega as the browser sent them: turned into the canvas's
 * own pixels first, they would be scaled a second time, and at any zoom but 1
 * a hover or a brush would land on another mark.
 */
import * as path from "path";
import { act, renderHook } from "@testing-library/react";

// Only what useVega calls on the library. The view draws into a canvas it
// puts in the node's container, as vega's canvas renderer does.
jest.mock("vega", () => {
  class View {
    logLevel() { return this; }
    renderer() { return this; }
    initialize(selector: string) {
      const page = globalThis.document;
      page.querySelector(selector)?.appendChild(page.createElement("canvas"));
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
    change() { return this; }
  }
  return { View, parse: (spec: any) => spec, Warn: 2, changeset: () => ({}) };
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

const SPEC = JSON.stringify({
  mark: "bar",
  encoding: {
    x: { field: "label", type: "nominal" },
    y: { field: "value", type: "quantitative" },
  },
});

beforeAll(() => {
  (globalThis as any).ResizeObserver ??= class { observe() {} disconnect() {} };
});

describe("vega's pointer mapping", () => {
  test("a pointer on a canvas a CSS transform scales maps to the canvas's own pixels", () => {
    // The vega build the app bundles, as CommonJS: its own `point`, which its
    // canvas handler maps every pointer event through.
    const vega = require(path.resolve(__dirname, "../../../node_modules/vega/build/vega.js"));
    const canvas = document.createElement("canvas");
    // Laid out 400 by 200, shown at half that size, as a node at zoom 0.5.
    Object.defineProperty(canvas, "offsetWidth", { get: () => 400 });
    Object.defineProperty(canvas, "offsetHeight", { get: () => 200 });
    canvas.getBoundingClientRect = () =>
      ({ left: 100, top: 50, width: 200, height: 100, right: 300, bottom: 150, x: 100, y: 50 }) as DOMRect;

    const at = vega.point(new MouseEvent("pointermove", { clientX: 150, clientY: 75 }), canvas);
    expect(at).toEqual([100, 50]);
  });
});

describe("the Vega-Lite node", () => {
  test("hands the chart's pointer events to vega as the browser sent them", async () => {
    document.body.innerHTML = '<div id="vegan1"></div>';
    const base = { nodeId: "n1", interactionsCallback: jest.fn(), outputCallback: jest.fn() };
    const input = { dataType: "dataframe", data: { label: ["a", "b"], value: [1, 2] } };
    const hook = renderHook(() => useVega({ data: { ...base, input }, code: SPEC }));
    await act(async () => {
      await hook.result.current.handleCompileGrammar(SPEC);
    });

    const canvas = document.querySelector("#vegan1 canvas") as HTMLCanvasElement;
    expect(canvas).not.toBeNull();
    // Where vega listens: on the canvas, after whatever the node put there.
    const reached: MouseEvent[] = [];
    for (const type of ["pointermove", "pointerover", "mousemove", "mousedown"]) {
      canvas.addEventListener(type, (event) => reached.push(event as MouseEvent));
    }

    const sent = ["pointermove", "pointerover", "mousemove", "mousedown"].map((type) => {
      const event = new MouseEvent(type, { clientX: 150, clientY: 75, bubbles: true, cancelable: true });
      canvas.dispatchEvent(event);
      return event;
    });
    // The very events sent, not copies made in the canvas's pixels.
    expect(reached.map((event) => [event.type, sent.includes(event), event.clientX, event.clientY])).toEqual(
      sent.map((event) => [event.type, true, 150, 75]),
    );
  });
});
