import fs from "fs";
import path from "path";

/**
 * Guards against decorative catalog controls coming back.
 *
 * A batch of chrome was removed because it lied to the user: a **Columns**
 * button that opened nothing, grid/list **view toggles** that changed nothing,
 * a **Popular** filter chip with no backing sort, a **✓ Verified** badge no
 * check ever produced, and a "Published by verified author" trust note under
 * every dataset regardless of provenance. A hardcoded `CC BY 4.0` license
 * fallback went with them, since asserting a permissive licence for a dataset
 * that declares none is the same class of mistake.
 *
 * These are absences, and the components have no render tests, so nothing else
 * would notice them being reinstated. Following the precedent in
 * `datasetFormatStyles.test.ts`, the sources are read from disk: CSS modules go
 * through `identity-obj-proxy` in jest, so an import-based assertion cannot see
 * whether a rule exists.
 */

const SRC = path.resolve(__dirname, "../..");
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), "utf8");

describe("removed catalog chrome stays removed", () => {
  test("the dataset preview has no non-functional Columns button", () => {
    const tsx = read("components/datasets/catalog/DatasetTablePreview.tsx");
    expect(tsx).not.toMatch(/>\s*Columns\s*</);
    const css = read("components/datasets/catalog/DatasetTablePreview.module.css");
    expect(css).not.toContain(".columnsButton");
  });

  test("the browse pages have no grid/list view toggles", () => {
    const css = read("pages/catalog/CatalogBrowseLayout.module.css");
    for (const cls of [".viewToggles", ".viewToggleActive", ".viewToggleInactive"]) {
      expect(css).not.toContain(cls);
    }
    for (const page of [
      "pages/catalog/NodeCatalogBrowse.tsx",
      "pages/dataHub/DataCatalogBrowse.tsx",
      "pages/agents/AgentCatalogBrowse.tsx",
    ]) {
      expect(read(page)).not.toMatch(/viewToggle/);
    }
  });

  test("the data browse page has no Popular chip", () => {
    expect(read("pages/dataHub/DataCatalogBrowse.tsx")).not.toMatch(/>\s*Popular\s*</);
  });

  test("no Verified badge or trust note on the dataset drawer", () => {
    const tsx = read("pages/dataHub/DataCatalogBrowseDrawer.tsx");
    expect(tsx).not.toMatch(/Verified/);
    expect(tsx).not.toMatch(/Published by verified author/);

    const css = read("pages/catalog/CatalogBrowseLayout.module.css");
    for (const cls of [".verifiedBadge", ".verifiedCircle", ".trustNote"]) {
      expect(css).not.toContain(cls);
    }
  });

  test("an unspecified license reads Unknown, not an invented CC BY 4.0", () => {
    const tsx = read("pages/dataHub/DataCatalogBrowseDrawer.tsx");
    expect(tsx).not.toContain("CC BY 4.0");
    expect(tsx).toMatch(/license\s*\|\|\s*"Unknown"/);
  });
});
