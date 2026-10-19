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
 * Chrome, Edge and Safari draw it from its ::-webkit-scrollbar rules, a 6 px
 * bar that shows at rest, on a Mac too. In Chrome and Edge, scrollbar-width or
 * scrollbar-color on the box turns those rules off for the browser's own bar,
 * which on a Mac hides until you scroll. So the two standard properties sit
 * only under `@supports not selector(::-webkit-scrollbar)`, for Firefox.
 *
 * Source-read, as in bundlePreviewScroll.test.ts: jest maps CSS modules to
 * identity-obj-proxy, so a rendered assertion cannot see which rules a class
 * carries. test_widget_panel_scrollbar_e2e.py checks the drawn scrollbar in a
 * browser.
 */
const SRC = path.resolve(__dirname, "../..");
const SHARED = path.join(SRC, "styles", "scrollbars.module.css");
const read = (file: string) => fs.readFileSync(path.join(SRC, file), "utf8");

/** The browsers without ::-webkit-scrollbar (Firefox). */
const NO_WEBKIT_SCROLLBAR = "@supports not selector(::-webkit-scrollbar)";
const STANDARD_PROPERTIES = /scrollbar-(width|color)\s*:/;

/** A style rule: the at-rules it sits in ("" at the top level), its selector, its declarations. */
type Rule = { at: string; selector: string; body: string };

/** Every style rule of a stylesheet, nested ones included. */
function rules(css: string): Rule[] {
  const text = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const open: string[] = []; // the preludes of the blocks around the current one
  const found: Rule[] = [];
  let from = 0;
  for (let at = 0; at < text.length; at += 1) {
    if (text[at] === "{") {
      // The prelude starts after the last statement (`@import ...;`) before it.
      open.push((text.slice(from, at).split(";").pop() ?? "").trim());
      from = at + 1;
    } else if (text[at] === "}") {
      const prelude = open.pop() ?? "";
      if (!prelude.startsWith("@")) {
        found.push({ at: open.join(" "), selector: prelude, body: text.slice(from, at) });
      }
      from = at + 1;
    }
  }
  return found;
}

/** The declarations of each rule whose selector is exactly `selector`, inside `at`. */
function rulesFor(css: string, selector: string, at = ""): string[] {
  return rules(css)
    .filter((rule) => rule.selector === selector && rule.at === at)
    .map((rule) => rule.body);
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
    // The 6 px bar of the ::-webkit-scrollbar rules, at the top level.
    expect(rulesFor(shared, ".thinScrollbar::-webkit-scrollbar")).toEqual([
      expect.stringContaining("width: 6px;"),
    ]);
    expect(rulesFor(shared, ".thinScrollbar::-webkit-scrollbar-thumb")).toEqual([
      expect.stringContaining("background: rgba(30, 31, 35, 0.18);"),
    ]);
    expect(rulesFor(shared, ".thinScrollbar::-webkit-scrollbar-thumb")[0]).toContain(
      "border-radius: 999px;",
    );
    // Firefox's thin bar, in the same colour.
    expect(rulesFor(shared, ".thinScrollbar", NO_WEBKIT_SCROLLBAR)).toEqual([
      expect.stringContaining("scrollbar-width: thin;"),
    ]);
    expect(rulesFor(shared, ".thinScrollbar", NO_WEBKIT_SCROLLBAR)[0]).toContain(
      "scrollbar-color: rgba(30, 31, 35, 0.18) transparent;",
    );
  });

  it("shows at rest in Chrome, Edge and Safari: the standard properties are only for Firefox", () => {
    const shared = rules(fs.readFileSync(SHARED, "utf8"));
    // scrollbar-width and scrollbar-color sit only under the @supports rule, so
    // that Chrome and Edge keep the ::-webkit-scrollbar rules on every system.
    expect(
      shared
        .filter((rule) => STANDARD_PROPERTIES.test(rule.body))
        .map(({ at, selector }) => [at, selector]),
    ).toEqual([[NO_WEBKIT_SCROLLBAR, ".thinScrollbar"]]);
    // The ::-webkit-scrollbar rules hold everywhere: none sits inside an at-rule.
    expect(
      shared
        .filter((rule) => rule.selector.includes("::-webkit-scrollbar"))
        .map(({ at, selector }) => [at, selector]),
    ).toEqual([
      ["", ".thinScrollbar::-webkit-scrollbar"],
      ["", ".thinScrollbar::-webkit-scrollbar-track"],
      ["", ".thinScrollbar::-webkit-scrollbar-thumb"],
      ["", ".thinScrollbar:hover::-webkit-scrollbar-thumb"],
    ]);
  });

  test.each(USERS)("%s %s takes it", (file, selector) => {
    // CSS Modules wants `composes` before the rule's other declarations.
    const from = path
      .relative(path.dirname(path.join(SRC, file)), SHARED)
      .split(path.sep)
      .join("/");
    const takes = `composes: thinScrollbar from "${from}";`;
    expect(rulesFor(read(file), selector).some((body) => body.trim().startsWith(takes))).toBe(true);
    // No rule of the panel sets a standard property, which in Chrome would turn
    // the shared bar off for that panel.
    const panel = new RegExp(`${selector.replace(".", "\\.")}(?![\\w-])`);
    expect(
      rules(read(file))
        .filter((rule) => panel.test(rule.selector) && STANDARD_PROPERTIES.test(rule.body))
        .map((rule) => rule.selector),
    ).toEqual([]);
  });

  it("is defined once", () => {
    // Its colour is in no other stylesheet, so no panel keeps a copy that drifts.
    const copies = stylesheets(SRC).filter(
      (file) => path.join(SRC, file) !== SHARED && read(file).includes("rgba(30, 31, 35, 0.18)"),
    );
    expect(copies).toEqual([]);
  });
});
