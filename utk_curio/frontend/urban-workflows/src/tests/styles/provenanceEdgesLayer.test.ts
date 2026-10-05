import fs from "fs";
import path from "path";
import { VIEWPORT_MOVING_CLASS } from "../../hook/useViewportMotionHint";

/**
 * The provenance graph's viewport stays off its own compositor layer (#504).
 *
 * With that viewport on a layer of its own, Chrome stopped painting the graph's
 * 2px edges at some zoom levels: the version cards stayed and the lines between
 * them went. The DOM keeps correct boxes either way, so only a screenshot shows
 * it; the provenance-graph baselines do. `MainCanvas.css` is imported once for
 * the whole app, and its `will-change` rule is scoped to a moving canvas (#533);
 * the window's own rule keeps its viewport off a layer whatever that rule says.
 *
 * Source-read, as in bundlePreviewScroll.test.ts: jest maps CSS modules to
 * `identity-obj-proxy`, so a rendered assertion cannot see which rules apply.
 */
const WINDOW = fs.readFileSync(
  path.resolve(__dirname, "../../components/menus/provenance/TrillProvenanceWindow.module.css"),
  "utf8",
);
const CANVAS = fs.readFileSync(
  path.resolve(__dirname, "../../components/MainCanvas.css"),
  "utf8",
);
const MOVING_VIEWPORT =
  `.react-flow.${VIEWPORT_MOVING_CLASS} > .react-flow__renderer > .react-flow__pane > .react-flow__viewport`;

function ruleBody(css: string, selector: string): string | null {
  const at = css.indexOf(selector + " {");
  if (at === -1) return null;
  const open = css.indexOf("{", at);
  return css.slice(open + 1, css.indexOf("}", open));
}

describe("provenance graph viewport layer", () => {
  test("the Provenance window's viewport opts out of will-change", () => {
    const body = ruleBody(WINDOW, ".graphDiv :global(.react-flow__viewport)");
    expect(body).not.toBeNull();
    expect(body).toMatch(/will-change:\s*auto;/);
  });

  test("the dataflow canvas takes its own layer only while it is moved", () => {
    // No bare rule: the hint is scoped to the class useViewportMotionHint sets
    // on a flow's wrapper during a pan or zoom (#533).
    expect(CANVAS).not.toMatch(/^\.react-flow__viewport\s*\{/m);
    expect(ruleBody(CANVAS, MOVING_VIEWPORT)).toMatch(/will-change:\s*transform;/);
  });
});
