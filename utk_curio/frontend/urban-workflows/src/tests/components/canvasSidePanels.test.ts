import fs from "fs";
import path from "path";

/**
 * The canvas's right edge, under the top bar, holds two panels: the
 * collaboration panel, open by default under `--collab`, and the Scenarios
 * panel, opened from View. Each used to place itself at that corner, so the
 * Scenarios panel opened over the collaboration panel. One dock places both
 * now, the collaboration panel first and the Scenarios panel under it, each
 * scrolling within its share of the height.
 *
 * Source-read: jest maps CSS modules to `identity-obj-proxy` and jsdom has no
 * layout engine, so a rendered assertion could see neither the rule nor the
 * boxes. The boxes are measured in a browser by
 * test_canvas_side_panels_e2e.py.
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

/** Whether *body* declares *property* itself (`right`, not `border-right`). */
const declares = (body: string, property: string) => new RegExp(`(^|[\\s;{])${property}\\s*:`).test(body);

const DOCK_TAG = "CanvasSidePanels";
const TOP_BAR = "var(--curio-top-bar-height)";

describe("the canvas's right-hand panels", () => {
  it("leave their place to the dock: the Scenarios panel does not place itself", () => {
    const panel = ruleBody(read("components/scenarios/ScenariosPanel.module.css"), ".panel");
    expect(panel).not.toBeNull();
    for (const property of ["position", "top", "right", "z-index"]) {
      expect([property, declares(panel!, property)]).toEqual([property, false]);
    }
  });

  it("leave their place to the dock: the collaboration panel does not place itself", () => {
    const source = read("components/collab/CollaborationSidePanel.tsx");
    expect(source).not.toMatch(/\bposition\s*:/);
    expect(source).not.toContain(TOP_BAR);
  });

  it("are both mounted by the canvas inside one dock, the collaboration panel first", () => {
    const canvas = read("components/MainCanvas.tsx");
    const open = canvas.indexOf(`<${DOCK_TAG}>`);
    const close = canvas.indexOf(`</${DOCK_TAG}>`);
    expect(open).toBeGreaterThan(-1);
    expect(close).toBeGreaterThan(open);
    const dock = canvas.slice(open, close);
    const collaboration = dock.indexOf("<CollaborationSidePanel />");
    const scenarios = dock.indexOf("<ScenariosPanel />");
    expect(collaboration).toBeGreaterThan(-1);
    expect(scenarios).toBeGreaterThan(collaboration);
    // And nowhere else: one mount of each.
    expect(canvas.split("<CollaborationSidePanel").length - 1).toBe(1);
    expect(canvas.split("<ScenariosPanel").length - 1).toBe(1);
  });

  it("are stacked by the dock in one column under the top bar, each scrolling in its share", () => {
    const css = read(`components/layout/${DOCK_TAG}.module.css`);
    const dock = ruleBody(css, ".dock") ?? "";
    expect(dock).toContain("position: absolute;");
    expect(dock).toContain(`top: ${TOP_BAR};`);
    expect(dock).toContain("right: 0;");
    expect(dock).toContain("display: flex;");
    expect(dock).toContain("flex-direction: column;");
    // The Scenarios panel's own limit before the dock, so alone it opens as it did.
    expect(dock).toContain(`max-height: calc(100vh - ${TOP_BAR} - 16px);`);
    // Clicks between and beside the panels reach the canvas.
    expect(dock).toContain("pointer-events: none;");
    const panel = ruleBody(css, ".dock > *") ?? "";
    expect(panel).toContain("pointer-events: auto;");
    // A panel may shrink below its content's height, and then scrolls.
    expect(panel).toContain("min-height: 0;");
    expect(panel).toContain("overflow-y: auto;");
  });
});
