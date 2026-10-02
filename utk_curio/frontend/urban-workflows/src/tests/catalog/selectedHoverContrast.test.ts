import fs from "fs";
import path from "path";

/**
 * A selected control must stay readable under the cursor.
 *
 * This was the catalog filter chips' bug. `.chipActive` painted a dark fill with
 * light text, `.chip:hover` set only the background, and at (0,2,0) it
 * outranked `.chipActive` at (0,1,0). So hovering a chip you had already
 * selected replaced #1E1F23 with #f0f0f0 and left the text at #fbfcf6, about
 * 1.03:1: the chip read as blank while you pointed at it.
 *
 * The chip row is gone, but two selectable controls on the same pages carry the
 * same shape: the rail's rows and the Projects page's Grid/List switch, whose
 * selected state is the same dark fill with light text. Both keep the idiom
 * that fixed it: hover styles only what is NOT selected.
 *
 * Source-read rather than rendered: jest maps CSS modules to
 * `identity-obj-proxy`, so a render assertion cannot see a specificity conflict
 * at all.
 */
const read = (rel: string) =>
  fs.readFileSync(path.resolve(__dirname, "../..", rel), "utf8");

const BROWSE = read("pages/catalog/CatalogBrowseLayout.module.css");
const PROJECTS = read("pages/projects/ProjectsBrowseLayout.module.css");

/**
 * The declarations inside the rule whose selector is exactly `selector`.
 *
 * Plain string scanning rather than a built regex: the selectors here carry
 * `.`, `:` and `()`, and escaping them into a pattern is more ceremony than the
 * lookup deserves. Anchored on a newline so `.x:hover` cannot match inside
 * `.x:hover:not(...)`, which is the exact distinction under test.
 */
function ruleBody(css: string, selector: string): string | null {
  const at = css.indexOf("\n" + selector + " {");
  if (at === -1) return null;
  const open = css.indexOf("{", at);
  const close = css.indexOf("}", open);
  return close === -1 ? null : css.slice(open + 1, close);
}

describe("the Projects Grid/List switch", () => {
  it("does not restyle the selected view on hover", () => {
    expect(ruleBody(PROJECTS, ".viewButton:hover:not(.viewButtonActive)")).not.toBeNull();
    expect(ruleBody(PROJECTS, ".viewButton:hover")).toBeNull();
  });

  it("still gives the other view hover feedback", () => {
    expect(ruleBody(PROJECTS, ".viewButton:hover:not(.viewButtonActive)")).toContain("background");
  });

  it("keeps the selected view's dark fill and light text together", () => {
    // If either half of this pair is ever dropped the contrast argument above
    // stops holding, so pin both.
    const active = ruleBody(PROJECTS, ".viewButtonActive") ?? "";
    expect(active).toContain("--curio-top-bar-bg");
    expect(active).toContain("--curio-card-bg");
  });
});

describe("the rail's rows", () => {
  it("does not restyle the selected row on hover", () => {
    // The selected row's fill is what marks it; a hover over it must not
    // replace that fill with the hover tint.
    const rule = BROWSE.match(/\n(\.railButton:hover[^{]*)\{([^}]*)\}/);
    expect(rule).not.toBeNull();
    expect((rule as RegExpMatchArray)[1].trim()).toBe(
      ".railButton:hover:not(.railButtonActive)",
    );
    expect((rule as RegExpMatchArray)[2]).toContain("background");
  });

  it("marks the selected row with its fill", () => {
    expect(ruleBody(BROWSE, ".railButtonActive")).toContain("background");
  });
});
