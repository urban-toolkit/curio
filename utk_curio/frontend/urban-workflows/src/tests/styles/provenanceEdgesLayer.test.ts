import fs from "fs";
import path from "path";

/**
 * The provenance graph's viewport stays off its own compositor layer (#504).
 *
 * `MainCanvas.css` is imported once for the whole app and sets
 * `.react-flow__viewport { will-change: transform; }` unscoped, so it reached
 * the React Flow inside the Provenance window too. With the viewport on its own
 * layer, Chrome stopped painting that graph's 2px edges at some zoom levels:
 * the version cards stayed and the lines between them went. The DOM keeps
 * correct boxes either way, so only a screenshot shows it; the
 * provenance-graph baselines do.
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

  test("the dataflow canvas keeps its own layer", () => {
    // The global rule is there for panning the main canvas in Firefox.
    expect(ruleBody(CANVAS, ".react-flow__viewport")).toMatch(/will-change:\s*transform;/);
  });
});
