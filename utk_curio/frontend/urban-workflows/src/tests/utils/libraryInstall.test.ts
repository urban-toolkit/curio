/**
 * Reading an install response (#299).
 *
 * Shared by the Installed-libraries modal and the node error panel, so these
 * are the cases that must mean the same thing on both.
 */
import {
  MIN_PROGRESS_MS,
  readInstallResponse,
} from "../../utils/libraryInstall";

describe("readInstallResponse", () => {
  it("reports a fresh install", () => {
    expect(readInstallResponse({ installed: ["scikit-learn"], skipped: [] }))
      .toEqual({ kind: "installed" });
  });

  it("reports pip's skip path as already installed", () => {
    expect(readInstallResponse({ installed: [], skipped: ["scikit-learn"] }))
      .toEqual({ kind: "already-installed" });
  });

  it("lets importError override BOTH lists", () => {
    // The load-bearing case. pip is satisfied, so `skipped` reads as success,
    // and the library still raises the moment a node touches it. Saying
    // "already installed" over that message contradicts the message.
    expect(
      readInstallResponse({
        installed: [],
        skipped: ["rasterio"],
        importError: "ImportError: libgdal.so.30: cannot open shared object file",
      }),
    ).toEqual({
      kind: "cannot-import",
      reason: "ImportError: libgdal.so.30: cannot open shared object file",
    });
  });

  it("lets importError override a reported install too", () => {
    expect(
      readInstallResponse({
        installed: ["rasterio"], skipped: [], importError: "boom",
      }),
    ).toEqual({ kind: "cannot-import", reason: "boom" });
  });

  it("treats an empty answer as installed rather than already-installed", () => {
    // Nothing skipped means pip was not asked to skip anything.
    expect(readInstallResponse({})).toEqual({ kind: "installed" });
  });

  it("keeps a progress floor long enough to see", () => {
    expect(MIN_PROGRESS_MS).toBeGreaterThanOrEqual(500);
  });
});
