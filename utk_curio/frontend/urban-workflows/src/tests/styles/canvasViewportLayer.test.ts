import fs from "fs";
import path from "path";
import { VIEWPORT_MOVING_CLASS } from "../../hook/useViewportMotionHint";

/**
 * The dataflow canvas takes a compositor layer only while it is moved (#533).
 *
 * With a viewport on a layer of its own, Chrome stopped painting thin edges at
 * some zoom levels (#504): the boxes stayed and the lines between them went.
 * `MainCanvas.css` is imported once for the whole app, so its `will-change`
 * rule is scoped to a canvas the user is panning or zooming.
 *
 * Source-read, as in bundlePreviewScroll.test.ts: jest maps CSS modules to
 * `identity-obj-proxy`, so a rendered assertion cannot see which rules apply.
 */
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

describe("canvas viewport layer", () => {
  test("the dataflow canvas takes its own layer only while it is moved", () => {
    // No bare rule: the hint is scoped to the class useViewportMotionHint sets
    // on a flow's wrapper during a pan or zoom (#533).
    expect(CANVAS).not.toMatch(/^\.react-flow__viewport\s*\{/m);
    expect(ruleBody(CANVAS, MOVING_VIEWPORT)).toMatch(/will-change:\s*transform;/);
  });
});
