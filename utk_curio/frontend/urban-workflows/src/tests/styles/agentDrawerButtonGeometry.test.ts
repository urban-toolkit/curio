import fs from "fs";
import path from "path";

/**
 * The Agent Catalog drawer's action column is pinned at 140px (issue 191).
 *
 * `article.agentCard` sets `grid-template-columns: 72px 1fr 140px` deliberately,
 * so the body column cannot collapse when a label is long. That makes the
 * BUTTONS responsible for fitting: the shared `.btnSecondary` in
 * `PackageCard.module.css` is a fixed `height: 30px` with `font: inherit` (which
 * resets line-height) and no wrap handling, so "Remove from all projects" at 12px
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
    // 150px, widened from 140px: the extra ten fit "Remove from project" at the
    // SHARED type size, which is what let the local shrink below be deleted.
    expect(rule(read(DRAWER_CSS), "article.agentCard")).toMatch(
      /grid-template-columns:\s*72px 1fr 150px/,
    );
  });

  it("no longer shrinks the secondary label", () => {
    // This asserted `font-size: 10px`. The shrink was for a card carrying four
    // secondary controls, the longest being "Remove from my account"; three of
    // them have left, and the column was widened for the one that remains. All
    // it still did was render this drawer's "Remove from project" visibly
    // smaller than the identical button on the Data and Node cards.
    const secondary = rule(read(DRAWER_CSS), "button.secondaryBtn");
    expect(secondary).not.toMatch(/font-size:/);
    expect(secondary).not.toMatch(/padding:/);
    // Growing the row was the other option, and is still rejected: it would
    // make the card heights ragged across a list.
    expect(secondary).not.toMatch(/height:\s*auto/);
  });

  it("makes an overflow visible instead of silent", () => {
    // If a longer label ever lands here it ellipsizes, which is reviewable.
    // Wrapping was what hid the original overflow until someone screenshotted it.
    const secondary = rule(read(DRAWER_CSS), "button.secondaryBtn");
    expect(secondary).toMatch(/white-space:\s*nowrap/);
    expect(secondary).toMatch(/text-overflow:\s*ellipsis/);
  });

  it("leaves no unpinned secondary button behind on the card", () => {
    // The card used to carry four of these at once - Remove from project,
    // Unpublish, Remove from all projects, Add to all projects - and the
    // original geometry fix reached only the primary button. Three of those
    // four have since left: publishing and the account-level add/remove are
    // decisions about an item, not about this project, so they live on the
    // Agent Catalog page's detail drawer. What remains must still be pinned.
    const tsx = read(DRAWER_TSX);
    const bare = tsx.match(/className=\{cardStyles\.btnSecondary\}/g) ?? [];
    expect(bare).toHaveLength(0);
    // Down to zero: all four of those controls have now left the card. Three
    // were account-level (publish, unpublish, the all-projects pair) and belong
    // on the Agent Catalog page's detail drawer; the fourth, "Remove from
    // project", went because an agent reaches a dataflow by being in the
    // account and is seeded into every one, so removing it from a single
    // dataflow contradicted the catalog's own "In all projects".
    //
    // The rule that matters survives either way: any secondary button that
    // comes back must carry the override, which the bare-class check above
    // enforces at zero just as well as at four.
  });

  it("still grows the primary button, whose label may legitimately wrap", () => {
    // "Add to project" / "Update" / "Installed" vary in length and the primary
    // control is allowed two lines; only the secondaries are pinned.
    expect(rule(read(DRAWER_CSS), "button.installBtn")).toMatch(/height:\s*auto/);
  });
});
