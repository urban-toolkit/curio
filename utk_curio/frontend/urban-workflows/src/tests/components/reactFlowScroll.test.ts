import { CANVAS_FILES, reactFlowCanvases } from "../_support/reactFlowCanvases";

/**
 * Every canvas keeps what the browser shows on it in sight and React Flow's
 * own element unscrolled (`useFlowInSight`, whose cases are
 * `useFlowInSight.test.tsx`).
 *
 * The browser scrolls `.react-flow`, whose overflow is hidden, to show what Tab
 * reaches past the canvas's edge, and React Flow 11 never scrolls it back: the
 * canvas's dot grid, pane and buttons stayed that far off the window, and every
 * fit drew the nodes that far off where it put them. A node Tab reaches left of
 * the view or above it stayed out of sight. The dashboard's tiles take Tab too.
 * Read from the source, so a new canvas has to say the same, and is named
 * below.
 */
const canvases = reactFlowCanvases();

test("finds every canvas: the main one and the dashboard's", () => {
  expect(canvases.map(({ file }) => file).sort()).toEqual([...CANVAS_FILES].sort());
});

test.each(canvases.map(({ file, text, tags }) => [file, text, tags] as const))(
  "%s spreads the handlers on its React Flow",
  (_file, text, tags) => {
    const handlers = /const (\w+) = useFlowInSight\(/.exec(text)?.[1] ?? null;
    expect({
      handlers,
      spread: tags.map((tag) => handlers !== null && tag.includes(`{...${handlers}}`)),
    }).toEqual({ handlers: expect.any(String), spread: tags.map(() => true) });
  },
);
