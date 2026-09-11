import fs from "fs";
import path from "path";

/**
 * A selected filter chip must stay readable under the cursor.
 *
 * `.chipActive` paints a dark fill with light text (`--curio-text-on-dark`).
 * `.chip:hover` sets only the background, and at (0,2,0) it outranks
 * `.chipActive` at (0,1,0) — so hovering a chip you had already selected
 * replaced #1E1F23 with #f0f0f0 and left the text at #fbfcf6. That is roughly
 * 1.03:1 against its background: the chip reads as blank while you point at it.
 *
 * Source-read rather than rendered: jest maps CSS modules to
 * `identity-obj-proxy`, so a render assertion cannot see a specificity conflict
 * at all — `styles.chip` is just a string either way.
 */
const CSS = fs.readFileSync(
  path.resolve(__dirname, "../../pages/catalog/CatalogBrowseLayout.module.css"),
  "utf8",
);

/**
 * The declarations inside the rule whose selector is exactly `selector`.
 *
 * Plain string scanning rather than a built regex: the selectors here carry
 * `.`, `:` and `()`, and escaping them into a pattern is more ceremony than the
 * lookup deserves. Anchored on a newline so `.chip:hover` cannot match inside
 * `.chip:hover:not(...)`, which is the exact distinction under test.
 */
function ruleBody(selector: string): string | null {
  const at = CSS.indexOf("\n" + selector + " {");
  if (at === -1) return null;
  const open = CSS.indexOf("{", at);
  const close = CSS.indexOf("}", open);
  return close === -1 ? null : CSS.slice(open + 1, close);
}

describe("catalog filter chips", () => {
  it("does not restyle a chip that is already selected on hover", () => {
    // The fix, and the thing to keep: the hover rule must exclude the active
    // state rather than merely re-declaring the dark background after it.
    expect(ruleBody(".chip:hover:not(.chipActive)")).not.toBeNull();
    expect(ruleBody(".chip:hover")).toBeNull();
  });

  it("still gives an unselected chip hover feedback", () => {
    // Removing the conflict must not remove the affordance.
    expect(ruleBody(".chip:hover:not(.chipActive)")).toContain("background");
  });

  it("keeps the selected chip's dark fill and light text together", () => {
    // If either half of this pair is ever dropped the contrast argument above
    // stops holding, so pin both.
    const active = ruleBody(".chipActive") ?? "";
    expect(active).toContain("--curio-top-bar-bg");
    expect(active).toContain("--curio-text-on-dark");
  });
});
