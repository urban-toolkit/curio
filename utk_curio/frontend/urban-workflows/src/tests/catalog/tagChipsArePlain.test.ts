/**
 * Every catalog chip is plain grey, on every surface (#193).
 *
 * There were four policies at once. The Data card tinted the **last** chip by
 * file format - positional rather than semantic, so a `2023` chip turned green
 * because the file happened to be GeoJSON. The Agent card tinted the last chip
 * by category. The Package card tinted **every** chip. The detail drawer tinted
 * none. The same tag therefore had a different colour depending on which card
 * you were looking at, and on where it happened to sit in the row.
 *
 * No information is lost by dropping them: the coloured card strip and the
 * tinted avatar already carry the format and the category.
 *
 * Read from disk rather than rendered, because `identity-obj-proxy` collapses
 * every CSS-module key to its own name under jest - a render assertion cannot
 * tell a tinted chip from a plain one.
 */
import fs from "fs";
import path from "path";

const SRC = path.resolve(__dirname, "../..");
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), "utf8");

/** The three cards that used to tint, and the drawer body that never did. */
const CARDS = [
  "pages/dataHub/DataCatalogBrowseCard.tsx",
  "pages/agents/AgentCatalogBrowseCard.tsx",
  "pages/catalog/PackageBrowseCard.tsx",
  "pages/catalog/CatalogBrowseDrawerBody.tsx",
];

/** The stylesheets whose `tagAccent_*` rules the cards used to look up. */
const STYLESHEETS = [
  "pages/catalog/CatalogBrowseLayout.module.css",
  "pages/agents/AgentCatalogBrowseCard.module.css",
  "pages/catalog/PackageBrowseCard.module.css",
];

describe("catalog tag chips carry no tint (#193)", () => {
  test.each(CARDS)("%s applies no tagAccent class", (file) => {
    const src = read(file);
    // Covers both the literal `styles.tagAccent_x` and the templated
    // `styles[\`tagAccent_${key}\`]` / `stripClass(..., "tagAccent", ...)` forms
    // the three cards each used a different one of.
    expect(src).not.toContain("tagAccent");
  });

  test.each(CARDS)("%s keeps no positional index for the chip row", (file) => {
    // `lastTagIdx` is what made the tint positional. Its presence would mean
    // the row has started treating one chip differently again.
    expect(read(file)).not.toContain("lastTagIdx");
  });

  test.each(STYLESHEETS)("%s declares no tagAccent rule", (file) => {
    const css = read(file);
    // Comments may still mention the removed lookup by name; a *rule* may not
    // exist, or a card could quietly start resolving one again.
    expect(css).not.toMatch(/^\s*\.tagAccent_/m);
  });

  test("the shared .tag rule survives, so chips are still styled", () => {
    // Dropping the tints must not have taken the chip styling with them.
    expect(read("pages/catalog/CatalogBrowseLayout.module.css")).toMatch(
      /^\.tag\s*\{/m,
    );
  });
});
