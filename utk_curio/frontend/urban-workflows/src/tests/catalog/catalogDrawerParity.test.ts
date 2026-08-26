import fs from "fs";
import path from "path";

/**
 * Guards the Node, Data and Agent Catalog drawers against drifting apart again.
 *
 * The two drawers render the same screen from the same stylesheet, but each page
 * used to hand-assemble its own markup. They diverged: the word "Published" was
 * rendered four different ways (a shared pill on cards, a bespoke badges-row
 * chip, a full-width block in the CTA footer, and bare meta text), the package
 * drawer coloured its *category* with a *format* colour, and one side styled a
 * list with inline styles. Both now compose `CatalogBrowseDrawerBody`.
 *
 * These assertions are mostly about absences, and CSS modules resolve through
 * `identity-obj-proxy` in jest, so the sources are read from disk — the same
 * approach as `removedCatalogChrome.test.ts` and `datasetFormatStyles.test.ts`.
 */

const SRC = path.resolve(__dirname, "../..");
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), "utf8");

const DRAWERS = [
  "pages/catalog/PackageBrowseDrawer.tsx",
  "pages/dataHub/DataCatalogBrowseDrawer.tsx",
  "pages/agents/AgentCatalogBrowseDrawer.tsx",
];

describe("catalog drawer parity", () => {
  test("both drawers are built from the shared drawer body", () => {
    for (const drawer of DRAWERS) {
      expect(read(drawer)).toMatch(/<CatalogBrowseDrawerBody\b/);
    }
  });

  test("publication status is only ever the shared pill", () => {
    for (const drawer of DRAWERS) {
      const tsx = read(drawer);
      expect(tsx).toMatch(/<CatalogPublishPill\b/);
      // No drawer-local re-implementation of the status.
      expect(tsx).not.toContain("drawerPublishStatus");
      expect(tsx).not.toContain("drawerPublishedPrimary");
    }
  });

  test("the bespoke status treatments are gone from the stylesheet", () => {
    const css = read("pages/catalog/CatalogBrowseLayout.module.css");
    for (const cls of [
      ".drawerPublishStatusPublished",
      ".drawerPublishStatusUnpublished",
      ".drawerPublishedPrimary",
    ]) {
      expect(css).not.toContain(cls);
    }
  });

  test("both drawers use the shared installed badge, not a format colour", () => {
    for (const drawer of DRAWERS) {
      const tsx = read(drawer);
      expect(tsx).toContain("drawerInstalledBadge");
      // `dfmt_geojson` is GeoJSON's colour; it is not an "installed" colour.
      expect(tsx).not.toContain("dfmt_geojson");
    }
  });

  test("a package category is not rendered in a file-format colour", () => {
    const tsx = read("pages/catalog/PackageBrowseDrawer.tsx");
    expect(tsx).toContain("drawerCategoryBadge");
    expect(tsx).not.toMatch(/dfmt_/);
  });

  test("drawer lists are styled from the stylesheet, not inline styles", () => {
    const css = read("pages/catalog/CatalogBrowseLayout.module.css");
    expect(css).toContain(".drawerList");
    expect(read("pages/catalog/PackageBrowseDrawer.tsx")).not.toMatch(/paddingLeft:/);
  });

  test("neither catalog hardcodes an uppercase badge label", () => {
    // Casing is a CSS concern; authoring SHOUTED strings made the two catalogs
    // disagree about where uppercasing came from.
    for (const card of [
      "pages/catalog/PackageBrowseCard.tsx",
      "pages/dataHub/DataCatalogBrowseCard.tsx",
    ]) {
      expect(read(card)).not.toMatch(/>\s*✓ (DEFAULTS|IN DATAFLOW)\s*</);
    }
  });

  test("the orange NEW chip is gone from the Data Catalog filter bar", () => {
    // It only re-applied the default sort, and the Node Catalog had no twin.
    expect(read("pages/dataHub/DataCatalogBrowse.tsx")).not.toContain("newChip");
    expect(read("pages/catalog/CatalogBrowseLayout.module.css")).not.toContain(".newChip");
  });
});

describe("publish wording is shared across both catalogs", () => {
  test("success and failure copy follow one template", () => {
    const sources = [
      "pages/catalog/useNodeCatalogBrowse.ts",
      "components/packages/publishing/NodeCatalogDrawer.tsx",
      "pages/dataHub/DataCatalogBrowse.tsx",
      "components/datasets/catalog/DatasetDetailPanel.tsx",
    ].map(read);

    // Every publish path reports success the same way.
    for (const src of sources) {
      expect(src).toMatch(/Published \$\{[^}]+\}\./);
    }
    // No leftovers of the older, catalog-specific phrasings.
    for (const src of sources) {
      expect(src).not.toContain("Dataset published to the Data Catalog.");
      expect(src).not.toContain("Could not publish dataset.");
      expect(src).not.toContain("Publish to Catalog");
    }
  });
});
