import fs from "fs";
import path from "path";

/**
 * The canvas's right edge, under the top bar, holds one panel: the
 * collaboration panel, open by default under `--collab`, placed by a dock. The
 * Scenarios panel that shared the dock is gone: a dataflow's scenarios are the
 * Scenario Catalog drawer's In project tab, which opens over the canvas as
 * every catalog drawer does.
 *
 * Source-read: jest maps CSS modules to `identity-obj-proxy` and jsdom has no
 * layout engine, so a rendered assertion could see neither the rule nor the
 * box. The panel is measured in a browser by test_canvas_side_panels_e2e.py.
 */

const SRC = path.resolve(__dirname, "../..");
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), "utf8");

/** The declarations of *selector*'s rule in *css*, or null when it has none. */
function ruleBody(css: string, selector: string): string | null {
  const at = css.indexOf("\n" + selector + " {");
  if (at === -1) return null;
  const open = css.indexOf("{", at);
  const close = css.indexOf("}", open);
  return close === -1 ? null : css.slice(open + 1, close);
}

const DOCK_TAG = "CanvasSidePanels";
const TOP_BAR = "var(--curio-top-bar-height)";

describe("the canvas's right-hand dock", () => {
  it("holds only the collaboration panel", () => {
    const canvas = read("components/MainCanvas.tsx");
    const open = canvas.indexOf(`<${DOCK_TAG}>`);
    const close = canvas.indexOf(`</${DOCK_TAG}>`);
    expect(open).toBeGreaterThan(-1);
    expect(close).toBeGreaterThan(open);
    const dock = canvas.slice(open + `<${DOCK_TAG}>`.length, close).trim();
    expect(dock).toBe("<CollaborationSidePanel />");
    // And nowhere else: one mount.
    expect(canvas.split("<CollaborationSidePanel").length - 1).toBe(1);
  });

  it("has no Scenarios panel left to mount", () => {
    expect(read("components/MainCanvas.tsx")).not.toContain("ScenariosPanel");
    for (const file of ["ScenariosPanel.tsx", "ScenariosPanel.module.css"]) {
      expect([file, fs.existsSync(path.join(SRC, "components/scenarios", file))]).toEqual([file, false]);
    }
  });

  it("leaves the panel's place to the dock: the collaboration panel does not place itself", () => {
    const source = read("components/collab/CollaborationSidePanel.tsx");
    expect(source).not.toMatch(/\bposition\s*:/);
    expect(source).not.toContain(TOP_BAR);
  });

  it("places it under the top bar, scrolling within the window", () => {
    const css = read(`components/layout/${DOCK_TAG}.module.css`);
    const dock = ruleBody(css, ".dock") ?? "";
    expect(dock).toContain("position: absolute;");
    expect(dock).toContain(`top: ${TOP_BAR};`);
    expect(dock).toContain("right: 0;");
    expect(dock).toContain("display: flex;");
    expect(dock).toContain("flex-direction: column;");
    // The panel never runs past the window's bottom.
    expect(dock).toContain(`max-height: calc(100vh - ${TOP_BAR} - 16px);`);
    // Clicks beside the panel reach the canvas.
    expect(dock).toContain("pointer-events: none;");
    const panel = ruleBody(css, ".dock > *") ?? "";
    expect(panel).toContain("pointer-events: auto;");
    // A panel may shrink below its content's height, and then scrolls.
    expect(panel).toContain("min-height: 0;");
    expect(panel).toContain("overflow-y: auto;");
  });
});
