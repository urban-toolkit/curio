import fs from "fs";
import path from "path";

/**
 * The selected-card border on every catalog browse page (issue 188).
 *
 * The colour comes from a COMPOUND selector, `.cardActive.card_<key>`, and CSS
 * modules hash each class per file - so both halves must be emitted from the
 * same stylesheet or the rule never matches. The shared skeleton in
 * `pages/catalog/CatalogBrowseLayout.module.css` gives `.card` a
 * `1.5px solid transparent` border and `.cardActive` only a raised shadow; the
 * border colour lives in each card's own module, beside the category keys.
 *
 * The Data card is fine without help because its `card_<format>` classes live in
 * the shared module too. The Package card applies BOTH modules' `cardActive` and
 * says why in a comment. The Agent card applied only the shared one, so its
 * compound rules were dead and a selected agent kept a transparent border.
 *
 * Read from disk, not rendered: `identity-obj-proxy` collapses every module's
 * `cardActive` to the literal string "cardActive", so a rendered assertion
 * cannot tell the two stylesheets apart - which is precisely the distinction
 * this bug turned on. Same approach as datasetFormatStyles.test.ts.
 */

const SRC = path.resolve(__dirname, "../..");
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), "utf8");

/** Card modules that declare their own `.cardActive.card_<key>` rules. */
const LOCAL_COMPOUND_CARDS = [
  {
    label: "agent",
    component: "pages/agents/AgentCatalogBrowseCard.tsx",
    stylesheet: "pages/agents/AgentCatalogBrowseCard.module.css",
    localImport: "cardStyles",
    keys: ["node", "canvas", "data", "evaluate", "package"],
  },
  {
    label: "package",
    component: "pages/catalog/PackageBrowseCard.tsx",
    stylesheet: "pages/catalog/PackageBrowseCard.module.css",
    localImport: "styles",
    keys: ["data", "computation", "vis", "package"],
  },
];

describe.each(LOCAL_COMPOUND_CARDS)(
  "$label browse card selection border",
  ({ component, stylesheet, localImport, keys }) => {
    it("declares a bare .cardActive so its compound rules can match", () => {
      const css = read(stylesheet);
      expect(css).toMatch(/^\.cardActive\s*\{/m);
    });

    it("declares a border colour for every category key", () => {
      const css = read(stylesheet);
      for (const key of keys) {
        expect(css).toContain(`.cardActive.card_${key}`);
      }
    });

    it("applies its OWN module's cardActive, not just the shared one", () => {
      // Without this the compound selector above is dead code and the card
      // keeps `border: 1.5px solid transparent` while selected.
      const tsx = read(component);
      expect(tsx).toContain(`selected ? ${localImport}.cardActive : ""`);
    });
  },
);

describe("the shared skeleton still supplies what the compounds build on", () => {
  const SHARED = "pages/catalog/CatalogBrowseLayout.module.css";

  it("reserves the border width on .card, so selecting shifts no layout", () => {
    expect(read(SHARED)).toMatch(/\.card\s*\{[^}]*border:\s*1\.5px solid transparent/);
  });

  it("keeps a shared .cardActive for the raised shadow", () => {
    expect(read(SHARED)).toMatch(/^\.cardActive\s*\{/m);
  });
});
