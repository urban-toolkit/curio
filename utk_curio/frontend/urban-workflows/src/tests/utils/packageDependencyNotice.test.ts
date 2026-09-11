/**
 * The one sentence seven install surfaces say when a package's libraries did
 * not end up working.
 *
 * pip counts matching metadata as satisfaction, so a wheel whose native
 * extension cannot load records a perfectly good version and installs without
 * complaint. Each surface is the last place that failure is still attached to
 * the package that brought it in, and each one used to write its own wording -
 * or, on three of them, none at all.
 */
import {
  brokenLibraryClause,
  dependencyFailureNotice,
} from "../../utils/packageDependencyNotice";

describe("brokenLibraryClause", () => {
  it("names the library AND the reason", () => {
    const clause = brokenLibraryClause({
      rasterio: "ImportError: DLL load failed while importing _base",
    });
    expect(clause).toContain("rasterio");
    expect(clause).toContain("DLL load failed while importing _base");
  });

  it("joins several so none is dropped", () => {
    const clause = brokenLibraryClause({ rasterio: "boom", rasterstats: "bang" });
    expect(clause).toContain("rasterio");
    expect(clause).toContain("rasterstats");
  });

  it("is null when every library works, so success stays quiet", () => {
    expect(brokenLibraryClause({})).toBeNull();
    expect(brokenLibraryClause(undefined)).toBeNull();
    expect(brokenLibraryClause(null)).toBeNull();
  });
});

describe("dependencyFailureNotice", () => {
  it("leads with what the surface just did, then what is wrong", () => {
    const notice = dependencyFailureNotice("Added Weather", {
      importErrors: { rasterio: "ImportError: DLL load failed" },
    });
    expect(notice).toMatch(/^Added Weather, but rasterio cannot be imported/);
    expect(notice).toContain("ImportError: DLL load failed");
    // A user who reads only this has to know what to expect next.
    expect(notice).toContain("will fail until it is repaired");
  });

  it("distinguishes pip failing from a library that installed and does not work", () => {
    const notice = dependencyFailureNotice("Saved Demo", {
      dependencyError: "ERROR: No matching distribution found for nope",
    });
    expect(notice).toContain("could not be installed");
    expect(notice).toContain("No matching distribution found");
    expect(notice).not.toContain("cannot be imported");
  });

  it("leads with pip's own failure when both are present", () => {
    // The probe still runs after a failed pip, and reports every dep pip did
    // not install as "not installed" - true, and a restatement of the failure
    // rather than a second problem. Leading with the import wording said a
    // library was broken when nothing had been installed at all.
    const notice = dependencyFailureNotice("Imported Pack", {
      importErrors: { rasterstats: "rasterstats is not installed" },
      dependencyError: "ERROR: Could not find a version",
    });
    expect(notice).toContain("could not be installed");
    expect(notice).toContain("Could not find a version");
    expect(notice).not.toContain("cannot be imported");
  });

  it("is null when there is nothing to say", () => {
    expect(dependencyFailureNotice("Added Weather", {})).toBeNull();
    expect(dependencyFailureNotice("Added Weather", null)).toBeNull();
    expect(dependencyFailureNotice("Added Weather", undefined)).toBeNull();
    expect(
      dependencyFailureNotice("Added Weather", { importErrors: {} }),
    ).toBeNull();
  });
});
