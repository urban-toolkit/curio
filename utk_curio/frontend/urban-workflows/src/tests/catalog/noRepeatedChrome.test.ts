/**
 * The three catalog drawers do not repeat themselves.
 *
 * The user's stated principle: **the default should be no repetition.** Two
 * things violated it, and in both cases the Agent drawer was the one that had
 * it right, so the other two were brought into line rather than the reverse.
 *
 * 1. The Data and Node drawers printed the ACTIVE TAB'S OWN LABEL again, as a
 *    section heading directly beneath the tab strip - so "Browse all" appeared
 *    twice, a few pixels apart, one of them already highlighted as the selected
 *    tab. The heading carried no information the tab strip was not already
 *    showing.
 *
 * 2. All three showed an "This dataflow isn't saved yet; adding will save it
 *    first" banner while `projectId` was null. It is gone: the add now states
 *    what it will do in its confirmation dialog, and the save indicator shows
 *    that it happened, so the banner was a third telling of the same thing -
 *    and one that appeared on some screens and not others depending on whether
 *    the dataflow happened to be saved.
 *
 * Read from disk, the established pattern for this kind of claim: CSS modules
 * resolve through `identity-obj-proxy` under jest, so a render assertion cannot
 * distinguish a heading that is present from one that is not styled.
 */
import fs from "fs";
import path from "path";

const SRC = path.resolve(__dirname, "../..");
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), "utf8");

const DRAWERS: [string, string][] = [
  ["data", "components/datasets/catalog/DatasetCatalogDrawer.tsx"],
  ["node", "components/packages/publishing/NodeCatalogDrawer.tsx"],
  ["agent", "components/agents/catalog/AgentCatalogDrawer.tsx"],
];

describe("no catalog repeats its own tab label as a heading", () => {
  test.each(DRAWERS)("the %s drawer prints no tab-label heading", (_kind, file) => {
    const src = read(file);
    // The two shapes it took: `shell.sectionLabel` with the label table piped
    // straight into it.
    expect(src).not.toMatch(/sectionLabel\}>\{TAB_LABEL\[/);
    expect(src).not.toMatch(/sectionLabel\}>\{tabLabel\[/);
    // And no drawer should reach for the shared shell's section-heading style
    // at all — the only headings left are the per-list ones ("Your datasets ·
    // 3 in dataflow"), which say something the tab strip does not.
    expect(src).not.toContain("shell.sectionLabel");
  });

  test("the shared drawer shell no longer ships the dead heading style", () => {
    const css = read("components/packages/publishing/CatalogDrawerShell.module.css");
    expect(css).not.toMatch(/^\.sectionLabel \{/m);
  });

  test("the per-list headings survive — they carry a count, not a repeat", () => {
    // "Your datasets · N in dataflow" is not a restatement of the tab; it adds
    // the count. Removing the tab-label headings must not have taken it too.
    expect(read("components/datasets/catalog/InstalledDatasetsList.tsx")).toContain(
      "in dataflow",
    );
    expect(read("components/packages/publishing/MyPackagesList.tsx")).toContain(
      "in dataflow",
    );
  });
});

describe("the unsaved-dataflow banner is gone from every catalog", () => {
  test.each(DRAWERS)("the %s drawer shows no unsaved notice", (_kind, file) => {
    const src = read(file);
    expect(src).not.toContain("UNSAVED_DATAFLOW_NOTICE");
    expect(src).not.toMatch(/isn.{0,6}t saved yet/i);
    // The banner element it lived in, too — no drawer should reintroduce one
    // through the shared shell.
    expect(src).not.toContain("shell.noticeBanner");
  });

  test("the shared copy constant is deleted, not merely unused", () => {
    // Left in place it would invite a fourth surface to import it back.
    expect(fs.existsSync(path.join(SRC, "constants/catalogCopy.ts"))).toBe(false);
  });

  test("the shared shell's notice surface is gone too", () => {
    const css = read("components/packages/publishing/CatalogDrawerShell.module.css");
    expect(css).not.toMatch(/^\.noticeBanner \{/m);
    expect(css).not.toMatch(/^\.noticeBannerText \{/m);
  });

  test("the Node drawer keeps its OWN restart notice, which is unrelated", () => {
    // `NodeCatalogDrawer.module.css` has a separate `.noticeBanner` for the
    // "restart recommended after a shared-library install" line. That one says
    // something real and must survive.
    const src = read("components/packages/publishing/NodeCatalogDrawer.tsx");
    expect(src).toContain("styles.noticeBanner");
    expect(read("components/packages/publishing/NodeCatalogDrawer.module.css")).toMatch(
      /^\.noticeBanner \{/m,
    );
  });
});
