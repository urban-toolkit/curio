/**
 * Parity across the three *canvas* catalog drawers.
 *
 * `catalogDrawerParity.test.ts` next door guards the three drawers under
 * `pages/` — the browse-page ones. Nothing guarded the three under
 * `components/`, which are a separate set of files that happen to render the
 * same idea on the canvas, and they drifted: the Node Catalog drawer was the
 * only one of the three with no `aria-hidden={!presented}` on its overlay root,
 * while all three put `aria-modal="true"` on the panel inside. Each drawer stays
 * mounted through its exit slide (`mounted ? <Drawer/> : null` in the provider,
 * unmounted on `onExitComplete`), so for the length of that slide it was
 * advertising a modal dialog that was on its way off screen.
 *
 * The e2e suite paid for the same divergence: `test_frontend/README.md` tells
 * tests to gate a drawer on `aria-hidden="false"`, which silently never becomes
 * true for one of the three.
 *
 * Read from disk rather than rendered, the same approach the sibling parity test
 * uses and for the same reason: CSS modules resolve through `identity-obj-proxy`
 * under jest, and these assertions are mostly about the presence or absence of
 * an attribute in the source.
 */
import fs from "fs";
import path from "path";

const SRC = path.resolve(__dirname, "../..");
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), "utf8");

const CANVAS_DRAWERS = [
  "components/packages/publishing/NodeCatalogDrawer.tsx",
  "components/datasets/catalog/DatasetCatalogDrawer.tsx",
  "components/agents/catalog/AgentCatalogDrawer.tsx",
];

const PROVIDERS = [
  "providers/NodeCatalogDrawerProvider.tsx",
  "providers/datasetCatalog/DatasetCatalogDrawerProvider.tsx",
  "providers/AgentCatalogDrawerProvider.tsx",
];

describe("canvas catalog drawer parity", () => {
  test.each(CANVAS_DRAWERS)(
    "%s hides its root from assistive tech until presented",
    (drawer) => {
      expect(read(drawer)).toContain("aria-hidden={!presented}");
    },
  );

  test.each(CANVAS_DRAWERS)("%s marks its panel as a modal dialog", (drawer) => {
    const source = read(drawer);
    expect(source).toContain('role="dialog"');
    expect(source).toContain('aria-modal="true"');
  });

  test.each(PROVIDERS)(
    "%s unmounts the drawer rather than leaving it in the DOM",
    (provider) => {
      // This is what keeps the aria-hidden gap to the slide rather than making
      // it permanent. If a provider ever stops unmounting, the attribute above
      // becomes the only thing standing between a closed drawer and a screen
      // reader.
      expect(read(provider)).toMatch(/mounted\s*$/m);
      expect(read(provider)).toContain(": null");
    },
  );
});
