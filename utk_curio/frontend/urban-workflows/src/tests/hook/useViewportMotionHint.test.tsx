/**
 * The canvas viewport is a GPU layer only while the user moves it (#533).
 *
 * Chrome keeps a `will-change: transform` layer painted at the zoom it was
 * rasterized at, so a canvas that kept the hint at rest showed its nodes as a
 * scaled bitmap after a fit. `useViewportMotionHint` puts a class on the flow's
 * wrapper for the length of a gesture, and `MainCanvas.css` gives the viewport
 * the hint under that class only.
 *
 * A real React Flow renders here, with a second flow inside one of its nodes as
 * `NodeProvenance` draws one, so the stylesheet's own selector is matched
 * against the DOM React Flow builds: the outer viewport takes the rule while
 * moving, and the nested one never does.
 */
import fs from "fs";
import path from "path";
import React from "react";
import { act, render } from "@testing-library/react";
import ReactFlow, { Node, ReactFlowProvider } from "reactflow";
import {
  VIEWPORT_MOVING_CLASS,
  VIEWPORT_SETTLE_MS,
  useViewportMotionHint,
} from "../../hook/useViewportMotionHint";

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(global as any).ResizeObserver = ResizeObserverStub;
if (!(global as any).DOMMatrixReadOnly) {
  (global as any).DOMMatrixReadOnly = class { m22 = 1; constructor() {} };
}

const CANVAS = fs
  .readFileSync(path.resolve(__dirname, "../../components/MainCanvas.css"), "utf8")
  .replace(/\/\*[\s\S]*?\*\//g, "");

/** The selectors of the MainCanvas.css rules that give an element `will-change: transform`. */
function hintSelectors(css: string): string[] {
  const selectors: string[] = [];
  for (const rule of css.matchAll(/([^{}]+)\{([^}]*)\}/g)) {
    if (/will-change:\s*transform/.test(rule[2])) selectors.push(rule[1].trim());
  }
  return selectors;
}

const InnerFlow: React.FC = () => (
  <ReactFlowProvider>
    <div style={{ width: 200, height: 100 }}>
      <ReactFlow nodes={[]} edges={[]} proOptions={{ hideAttribution: true }} />
    </div>
  </ReactFlowProvider>
);

const nodeTypes = { inner: InnerFlow };
const NODES: Node[] = [{ id: "n", type: "inner", position: { x: 0, y: 0 }, data: {} }];

let hint: ReturnType<typeof useViewportMotionHint>;

const Canvas: React.FC = () => {
  hint = useViewportMotionHint();
  return (
    <div style={{ width: 800, height: 600 }}>
      <ReactFlow
        nodes={NODES}
        edges={[]}
        nodeTypes={nodeTypes}
        onMoveStart={hint.onMoveStart}
        onMove={hint.onMove}
        onMoveEnd={hint.onMoveEnd}
        proOptions={{ hideAttribution: true }}
      />
    </div>
  );
};

const VIEWPORT = { x: 0, y: 0, zoom: 1 };
const gesture = () => new MouseEvent("mousemove");

function renderCanvas() {
  const view = render(
    <ReactFlowProvider>
      <Canvas />
    </ReactFlowProvider>,
  );
  const [outer, inner] = Array.from(view.container.querySelectorAll<HTMLElement>(".react-flow"));
  return {
    view,
    outer,
    outerViewport: outer.querySelector<HTMLElement>(".react-flow__viewport")!,
    innerViewport: inner.querySelector<HTMLElement>(".react-flow__viewport")!,
    moving: () => outer.classList.contains(VIEWPORT_MOVING_CLASS),
  };
}

afterEach(() => {
  jest.useRealTimers();
});

describe("useViewportMotionHint", () => {
  test("MainCanvas.css gives a viewport the hint only under the moving class", () => {
    const selectors = hintSelectors(CANVAS);
    expect(selectors.length).toBeGreaterThan(0);
    for (const selector of selectors) {
      expect(selector).toContain(`.${VIEWPORT_MOVING_CLASS}`);
    }
  });

  test("a gesture gives the canvas's own viewport the hint, and not a flow inside a node", () => {
    const { outer, outerViewport, innerViewport } = renderCanvas();
    expect(innerViewport).not.toBe(outerViewport);
    expect(outer.contains(innerViewport)).toBe(true);
    const selectors = hintSelectors(CANVAS);

    for (const selector of selectors) expect(outerViewport.matches(selector)).toBe(false);
    act(() => hint.onMoveStart(gesture(), VIEWPORT));
    for (const selector of selectors) {
      expect(outerViewport.matches(selector)).toBe(true);
      expect(innerViewport.matches(selector)).toBe(false);
    }
  });

  test("the hint goes when the gesture ends", () => {
    const { moving } = renderCanvas();
    act(() => hint.onMoveStart(gesture(), VIEWPORT));
    expect(moving()).toBe(true);
    act(() => hint.onMoveEnd(gesture(), VIEWPORT));
    expect(moving()).toBe(false);
  });

  test("a programmatic move never takes the hint, and drops one a gesture left", () => {
    const { moving } = renderCanvas();
    act(() => hint.onMove(null, VIEWPORT));
    expect(moving()).toBe(false);
    act(() => hint.onMoveStart(gesture(), VIEWPORT));
    act(() => hint.onMove(null, VIEWPORT));
    expect(moving()).toBe(false);
  });

  test("a press that moves nothing drops the hint once it settles", () => {
    jest.useFakeTimers();
    const { moving } = renderCanvas();
    act(() => hint.onMoveStart(gesture(), VIEWPORT));
    act(() => jest.advanceTimersByTime(VIEWPORT_SETTLE_MS - 1));
    expect(moving()).toBe(true);
    act(() => jest.advanceTimersByTime(1));
    expect(moving()).toBe(false);
  });

  test("moves keep the hint for as long as the gesture goes on", () => {
    jest.useFakeTimers();
    const { moving } = renderCanvas();
    act(() => hint.onMoveStart(gesture(), VIEWPORT));
    for (let step = 0; step < 10; step++) {
      act(() => jest.advanceTimersByTime(VIEWPORT_SETTLE_MS / 2));
      act(() => hint.onMove(gesture(), VIEWPORT));
      expect(moving()).toBe(true);
    }
    act(() => jest.advanceTimersByTime(VIEWPORT_SETTLE_MS));
    expect(moving()).toBe(false);
  });

  test("unmounting drops the hint and its timer", () => {
    jest.useFakeTimers();
    const { view, outer } = renderCanvas();
    act(() => hint.onMoveStart(gesture(), VIEWPORT));
    view.unmount();
    expect(outer.classList.contains(VIEWPORT_MOVING_CLASS)).toBe(false);
    expect(jest.getTimerCount()).toBe(0);
  });
});
