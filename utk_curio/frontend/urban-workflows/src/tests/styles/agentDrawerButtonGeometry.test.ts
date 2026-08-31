import fs from "fs";
import path from "path";

/**
 * The Agent Catalog drawer's action column is pinned at 140px (issue 191).
 *
 * `article.agentCard` sets `grid-template-columns: 72px 1fr 140px` deliberately,
 * so the body column cannot collapse when a label is long. That makes the
 * BUTTONS responsible for fitting: the shared `.btnSecondary` in
 * `PackageCard.module.css` is a fixed `height: 30px` with `font: inherit` (which
 * resets line-height) and no wrap handling, so "Remove from my account" at 12px
 * wrapped to two lines inside a box nailed to one and spilled out of it.
 *
 * The fix brings the type down rather than letting the button grow, so the card
 * rows stay a uniform height. Asserted from disk because `identity-obj-proxy`
 * erases the stylesheet under jest; the live geometry is measured in the
 * walkthrough baselines, which fail if the label ever wraps again.
 */

const SRC = path.resolve(__dirname, "../..");
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), "utf8");

const DRAWER_CSS = "components/agents/catalog/AgentCatalogDrawer.module.css";
const DRAWER_TSX = "components/agents/catalog/AgentCatalogDrawer.tsx";

/** The body of one CSS rule, or "" when the selector is absent.
 *
 * Plain string scanning rather than a built regex: the selectors here contain
 * `.` and `{`, and escaping them into a pattern is more code than the search.
 */
function rule(css: string, selector: string): string {
  const at = css.indexOf(selector + " {");
  if (at < 0) return "";
  const open = css.indexOf("{", at);
  const close = css.indexOf("}", open);
  return close < 0 ? "" : css.slice(open + 1, close);
}

describe("agent drawer action buttons fit their pinned column", () => {
  it("keeps the column pinned - the buttons adapt, not the grid", () => {
    expect(rule(read(DRAWER_CSS), "article.agentCard")).toMatch(
      /grid-template-columns:\s*72px 1fr 140px/,
    );
  });

  it("shrinks the secondary label rather than growing the button", () => {
    const secondary = rule(read(DRAWER_CSS), "button.secondaryBtn");
    expect(secondary).toMatch(/font-size:\s*10px/);
    // Growing the row was the other option, and was rejected: it would make the
    // card heights ragged across a list.
    expect(secondary).not.toMatch(/height:\s*auto/);
  });

  it("makes an overflow visible instead of silent", () => {
    // If a longer label ever lands here it ellipsizes, which is reviewable.
    // Wrapping was what hid the original overflow until someone screenshotted it.
    const secondary = rule(read(DRAWER_CSS), "button.secondaryBtn");
    expect(secondary).toMatch(/white-space:\s*nowrap/);
    expect(secondary).toMatch(/text-overflow:\s*ellipsis/);
  });

  it("applies the override to every secondary button on the card", () => {
    // Three of them share the column: Remove from dataflow, Remove from my
    // account, Import. The original fix reached only the primary button.
    const tsx = read(DRAWER_TSX);
    const bare = tsx.match(/className=\{cardStyles\.btnSecondary\}/g) ?? [];
    expect(bare).toHaveLength(0);
    const overridden = tsx.match(/cardStyles\.btnSecondary\} \$\{styles\.secondaryBtn\}/g) ?? [];
    expect(overridden.length).toBeGreaterThanOrEqual(3);
  });

  it("still grows the primary button, whose label may legitimately wrap", () => {
    // "Add to dataflow" / "Update" / "Installed" vary in length and the primary
    // control is allowed two lines; only the secondaries are pinned.
    expect(rule(read(DRAWER_CSS), "button.installBtn")).toMatch(/height:\s*auto/);
  });
});
