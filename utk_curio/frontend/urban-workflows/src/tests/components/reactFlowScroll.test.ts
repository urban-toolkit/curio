import { CANVAS_FILES, reactFlowCanvases } from "../_support/reactFlowCanvases";

/**
 * Every canvas turns a scroll of React Flow's own element into a pan
 * (`useFlowScrollAsPan`, whose cases are `useFlowScrollAsPan.test.tsx`).
 *
 * The browser scrolls `.react-flow`, whose overflow is hidden, to show what Tab
 * reaches past the canvas's edge, and React Flow 11 never scrolls it back: the
 * canvas's dot grid, pane and buttons stayed that far off the window, and every
 * fit drew the nodes that far off where it put them. The dashboard's tiles take
 * Tab too. Read from the source, so a new canvas has to say the same, and is
 * named below.
 */
const canvases = reactFlowCanvases();

test("finds every canvas: the main one and the dashboard's", () => {
  expect(canvases.map(({ file }) => file).sort()).toEqual([...CANVAS_FILES].sort());
});

test.each(canvases.map(({ file, text, tags }) => [file, text, tags] as const))(
  "%s passes its React Flow the handler",
  (_file, text, tags) => {
    const handler = /const (\w+) = useFlowScrollAsPan\(/.exec(text)?.[1] ?? null;
    expect({
      handler,
      passed: tags.map((tag) => handler !== null && tag.includes(`onScroll={${handler}}`)),
    }).toEqual({ handler: expect.any(String), passed: tags.map(() => true) });
  },
);
