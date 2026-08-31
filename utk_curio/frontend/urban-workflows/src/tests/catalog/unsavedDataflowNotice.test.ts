import fs from "fs";
import path from "path";

import { UNSAVED_DATAFLOW_NOTICE } from "../../constants/catalogCopy";

/**
 * All three catalog drawers say the same thing about an unsaved dataflow.
 *
 * Each of them adds to the open dataflow, and each creates and saves it first
 * when it has never been persisted - the Data and Agent drawers through
 * `ensureProjectId`, the Node drawer by calling `saveCurrentProject` itself. So
 * all three owe the user the same disclosure before the click.
 *
 * They did not have it. The Node and Agent drawers carried two spellings of one
 * sentence (one with `&apos;`), and the Data drawer performed the same save
 * while saying nothing. Read from disk because the claim is about the source -
 * that no drawer re-states the sentence instead of importing it.
 */

const SRC = path.resolve(__dirname, "../..");
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), "utf8");

const DRAWERS = [
  ["data", "components/datasets/catalog/DatasetCatalogDrawer.tsx"],
  ["node", "components/packages/publishing/NodeCatalogDrawer.tsx"],
  ["agent", "components/agents/catalog/AgentCatalogDrawer.tsx"],
] as const;

describe("the unsaved-dataflow notice", () => {
  it("says the add will save first, and says which way round", () => {
    expect(UNSAVED_DATAFLOW_NOTICE).toMatch(/saved/i);
    expect(UNSAVED_DATAFLOW_NOTICE).toMatch(/save it first/i);
  });

  it.each(DRAWERS)("is shown by the %s drawer", (_label, file) => {
    const src = read(file);
    expect(src).toContain("UNSAVED_DATAFLOW_NOTICE");
    // Gated on there being no dataflow yet; showing it always would be a lie.
    expect(src).toContain("!projectId");
  });

  it.each(DRAWERS)("is not re-stated inline by the %s drawer", (_label, file) => {
    // The two copies had already drifted apart once.
    expect(read(file)).not.toMatch(/isn.{0,6}t saved yet/);
  });

  it.each(DRAWERS)("reads as information, not failure, in the %s drawer", (_label, file) => {
    // `.errorBanner` paints --curio-danger-bg. A red banner for "this will save
    // your work first" reads as something having gone wrong.
    const src = read(file);
    // The LAST mention is the JSX; the first is the import.
    const at = src.lastIndexOf("UNSAVED_DATAFLOW_NOTICE");
    const noticeBlock = src.slice(Math.max(0, at - 400), at + 120);
    expect(noticeBlock).toContain("noticeBanner");
    expect(noticeBlock).not.toContain("errorBanner");
  });

  it("has a neutral surface of its own in the shared drawer shell", () => {
    const css = read("components/packages/publishing/CatalogDrawerShell.module.css");
    expect(css).toMatch(/^\.noticeBanner \{/m);
    expect(css).not.toMatch(/\.noticeBanner \{[^}]*--curio-danger/);
  });
});
