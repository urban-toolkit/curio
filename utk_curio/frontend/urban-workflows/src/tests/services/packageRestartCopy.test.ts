/**
 * The restart sentence, and the surfaces that owe it.
 *
 * pip installing a library into the interpreter the server is already running
 * leaves every module it already imported on the old version until Curio
 * restarts. The drawer's install has always said so. The file-first routes
 * (/upload, /factory/install) did not run pip at all until they started
 * honouring declared dependencies - so they can now cause exactly the same
 * thing, and were the ones staying quiet about it.
 */
import fs from "fs";
import path from "path";

import {
  restartNotice,
  withRestartNotice,
} from "../../services/packageRestartCopy";

const SRC = path.resolve(__dirname, "../..");
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), "utf8");

describe("withRestartNotice", () => {
  it("appends the restart sentence to whatever the surface already said", () => {
    const out = withRestartNotice("Imported Weather.", { libs: ["shapely"] });
    expect(out).toContain("Imported Weather.");
    expect(out).toContain(restartNotice({ libs: ["shapely"] }));
  });

  it("adds nothing when pip changed nothing", () => {
    // A skipped install is the common case - the whole point of the field is
    // that it fires ONLY when a shared library actually moved.
    expect(withRestartNotice("Imported Weather.", { libs: [] }))
      .toBe("Imported Weather.");
    expect(withRestartNotice("Imported Weather.", null)).toBe("Imported Weather.");
    expect(withRestartNotice("Imported Weather.", undefined))
      .toBe("Imported Weather.");
  });

  it("composes with the broken-library sentence rather than replacing it", () => {
    // Both can be true of one install: a library that moved AND a library that
    // will not import. Neither may swallow the other.
    const out = withRestartNotice(
      "Imported Weather, but rasterio cannot be imported (ImportError: boom).",
      { libs: ["shapely"] },
    );
    expect(out).toContain("rasterio cannot be imported");
    expect(out).toContain("Restart Curio");
  });

  it("names every library that moved", () => {
    const out = withRestartNotice("Imported X.", { libs: ["shapely", "pyproj"] });
    expect(out).toContain("shapely");
    expect(out).toContain("pyproj");
  });
});

describe("every install surface that can be handed restartRecommended reads it", () => {
  // The backend returns the field from provision_declared_deps on /upload and
  // /factory/install, and from install_to_project on the drawer path. A surface
  // that receives it and drops it leaves the user with stale imports and no
  // way to know.
  test.each([
    ["archive sideload", "components/packages/publishing/usePackageArchiveImport.ts"],
    ["Node Catalog page import", "pages/catalog/useNodeCatalogBrowse.ts"],
    ["Node Catalog drawer import", "components/packages/publishing/NodeCatalogDrawer.tsx"],
    ["Save As, save and install", "components/packages/editing/NodeSaveAsModal.tsx"],
  ])("%s", (_label, file) => {
    expect(read(file)).toMatch(/withRestartNotice|restartRecommended/);
  });
});
