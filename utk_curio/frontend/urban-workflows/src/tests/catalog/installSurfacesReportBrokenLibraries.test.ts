/**
 * Every surface that installs a package says when its libraries do not work.
 *
 * pip counts matching metadata as satisfaction, so a wheel whose native
 * extension cannot load records a perfectly good version, installs without
 * complaint, and only announces itself when a node runs. The backend answers
 * that question at its install seam now, so the remaining way to get it wrong
 * is for a surface to receive the answer and drop it - which is exactly what
 * three of them did.
 *
 * Read from disk in the style of this directory's other source-level claims:
 * the assertion is about which surfaces consult the shared helper at all, and
 * a render test can only speak for the tree it rendered.
 */
import fs from "fs";
import path from "path";

const SRC = path.resolve(__dirname, "../..");
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), "utf8");

/** Every user-facing entry point that installs a package's python deps. */
const INSTALL_SURFACES: [label: string, file: string][] = [
  ["Node Catalog drawer, add to this project",
   "components/packages/publishing/NodeCatalogDrawer.tsx"],
  ["Node Catalog page, add to all projects",
   "pages/catalog/useNodeCatalogBrowse.ts"],
  ["dataflow open, auto-install of declared packages",
   "hook/useEnsureWorkflowDeps.ts"],
  ["archive sideload", "components/packages/publishing/usePackageArchiveImport.ts"],
  ["Save As, save and install", "components/packages/editing/NodeSaveAsModal.tsx"],
];

describe("an install surface that can report a broken library does", () => {
  test.each(INSTALL_SURFACES)("%s", (_label, file) => {
    expect(read(file)).toContain("dependencyFailureNotice");
  });

  test("none of them writes its own wording", () => {
    // Two of them did, and had already drifted apart. The failure should not
    // read as a different problem depending on which button reached it.
    for (const [, file] of INSTALL_SURFACES) {
      expect(read(file)).not.toContain("cannot be imported (");
    }
  });
});
