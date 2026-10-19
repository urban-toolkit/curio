import fs from "fs";
import path from "path";

/**
 * One thin scrollbar for the Data Catalog's panels and every widget panel
 * (#1003), defined once in styles/scrollbars.module.css.
 *
 * A Parameter node's "Used by" list can run past the node's bottom edge, and
 * its panel scrolls. The widget panels take the Data Catalog's scrollbar
 * through the same code: each panel composes the shared class, and no
 * stylesheet keeps a copy of its rules, so the look is defined in one place.
 *
 * Source-read, as in bundlePreviewScroll.test.ts: jest maps CSS modules to
 * identity-obj-proxy, so a rendered assertion cannot see which rules a class
 * carries. test_widget_panel_scrollbar_e2e.py checks the computed scrollbar in
 * a browser.
 */
const SRC = path.resolve(__dirname, "../..");
const SHARED = path.join(SRC, "styles", "scrollbars.module.css");
const read = (file: string) => fs.readFileSync(path.join(SRC, file), "utf8");

/** The declarations of each top-level rule whose selector is exactly `selector`. */
function rulesFor(css: string, selector: string): string[] {
  return css
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("}")
    .flatMap((chunk) => {
      const open = chunk.indexOf("{");
      return open !== -1 && chunk.slice(0, open).trim() === selector ? [chunk.slice(open + 1)] : [];
    });
}

/** Every stylesheet under src, relative to src. */
function stylesheets(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return stylesheets(full);
    return entry.name.endsWith(".css") ? [path.relative(SRC, full)] : [];
  });
}

/** The panels that scroll with it: the Data Catalog's, then the widget panel. */
const USERS: Array<[file: string, selector: string]> = [
  ["components/datasets/catalog/DatasetDetailPanel.module.css", ".centerColumn"],
  ["components/datasets/catalog/DatasetDetailPanel.module.css", ".infoColumn"],
  ["components/datasets/catalog/DatasetSchemaPanel.module.css", ".tableWrap"],
  ["components/datasets/catalog/DatasetTablePreview.module.css", ".tableWrap"],
  ["components/datasets/catalog/DatasetBundlePreview.module.css", ".tableWrap"],
  ["components/editing/widgets/WidgetTags.module.css", ".panel"],
];

describe("the thin scrollbar of the Data Catalog's panels and the widget panels", () => {
  it("is the Data Catalog's thin scrollbar", () => {
    const shared = fs.readFileSync(SHARED, "utf8");
    expect(rulesFor(shared, ".thinScrollbar")).toEqual([
      expect.stringContaining("scrollbar-width: thin;"),
    ]);
    expect(rulesFor(shared, ".thinScrollbar")[0]).toContain(
      "scrollbar-color: rgba(30, 31, 35, 0.18) transparent;",
    );
    expect(rulesFor(shared, ".thinScrollbar::-webkit-scrollbar")[0]).toContain("width: 6px;");
    expect(rulesFor(shared, ".thinScrollbar::-webkit-scrollbar-thumb")[0]).toContain(
      "background: rgba(30, 31, 35, 0.18);",
    );
  });

  test.each(USERS)("%s %s takes it", (file, selector) => {
    // CSS Modules wants `composes` before the rule's other declarations.
    const from = path
      .relative(path.dirname(path.join(SRC, file)), SHARED)
      .split(path.sep)
      .join("/");
    const takes = `composes: thinScrollbar from "${from}";`;
    expect(rulesFor(read(file), selector).some((body) => body.trim().startsWith(takes))).toBe(true);
  });

  it("is defined once", () => {
    // Its colour is in no other stylesheet, so no panel keeps a copy that drifts.
    const copies = stylesheets(SRC).filter(
      (file) => path.join(SRC, file) !== SHARED && read(file).includes("rgba(30, 31, 35, 0.18)"),
    );
    expect(copies).toEqual([]);
  });
});
