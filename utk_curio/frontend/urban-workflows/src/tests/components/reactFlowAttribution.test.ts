import { CANVAS_FILES, reactFlowCanvases } from "../_support/reactFlowCanvases";

/**
 * No canvas draws React Flow's attribution (#509).
 *
 * The main canvas left it on, in the bottom-right corner the version badge is
 * fixed to, so the two strings overlapped on every canvas screen. Read from
 * the source, so a new canvas has to say the same, and is named below.
 */
const canvases = reactFlowCanvases();

test("finds every canvas: the main one and the dashboard's", () => {
  // The provenance drawer draws a dataflow's versions and a node's runs
  // without React Flow.
  expect(canvases.map(({ file }) => file).sort()).toEqual([...CANVAS_FILES].sort());
});

test.each(canvases.map(({ file, tags }) => [file, tags] as const))(
  "%s hides the attribution",
  (_file, tags) => {
    for (const tag of tags) {
      expect(tag).toMatch(/proOptions=\{\{\s*hideAttribution:\s*true\s*\}\}/);
    }
  },
);
