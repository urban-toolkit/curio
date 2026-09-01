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
      // `DatasetDetailPanel` used to be on this list. It no longer publishes:
      // it is the DETAILS view, and it carried a second, ungated publish
      // control beside the drawer's gated one - which is how an unpublishable
      // dataset ended up offering Unpublish. One decision, one place.
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

describe("add/remove toasts are shared across all three catalogs (#198)", () => {
  // Only the Data catalog reported an add or a remove; the Node and Agent
  // catalogs completed in silence, which reads as "nothing happened" on a slow
  // install. useDatasetCatalogDrawer's wording is the canonical one, so the
  // other two adopt it verbatim rather than inventing a third phrasing.
  const SOURCES: [string, string][] = [
    ["data", "components/datasets/catalog/useDatasetCatalogDrawer.ts"],
    ["node", "components/packages/publishing/NodeCatalogDrawer.tsx"],
    ["agent", "components/agents/catalog/useAgentCatalogDrawer.ts"],
  ];

  test.each(SOURCES)("the %s catalog toasts both an add and a remove", (_kind, file) => {
    const src = read(file);
    // The interpolated expression differs per catalog (dataset.title, pkg.name,
    // card.name), so match the template around it rather than the whole line.
    expect(src).toMatch(/Added \$\{[^}]+\} to this dataflow\./);
    expect(src).toMatch(/Removed \$\{[^}]+\} from this dataflow\./);
  });

  // showToast defaults to **error** (ToastProvider.tsx), so an omitted variant
  // paints a successful add red. The three catalogs reach showToast by
  // different routes, so the variant is asserted where each one applies it:
  // Data and Agent behaviourally (useDatasetCatalogDrawer.import.test.ts,
  // useAgentCatalogDrawer.test.ts), Node from source — it has no render
  // harness, for the reasons NodeCatalogDrawerReload.test.tsx sets out.
  test("the node catalog passes the success variant at the call site", () => {
    const src = read("components/packages/publishing/NodeCatalogDrawer.tsx");
    // The add is one sentence and still matches the shared template exactly.
    expect(src).toMatch(
      new RegExp(`showToast\\(\\s*\`Added \\$\\{[^}]+\\} to this dataflow\\.\`,\\s*"success"`),
    );
    // The remove branches now: removing a package can also delete it from the
    // account and pip-uninstall its libraries from the shared interpreter, so
    // the toast reports which of those actually happened. Both branches carry
    // the same sentence stem.
    expect(src).toMatch(/`Removed \$\{[^}]+\} from this dataflow \$\{extra\}\.`/);
    expect(src).toMatch(/`Removed \$\{[^}]+\} from this dataflow\.`/);
    // Whichever branch is taken, the variant is explicit — showToast defaults
    // to "error", so an omitted one paints a successful removal red.
    const at = src.indexOf("const extra =");
    expect(at).toBeGreaterThan(-1);
    expect(src.slice(at, at + 700)).toContain('"success"');
  });
});
