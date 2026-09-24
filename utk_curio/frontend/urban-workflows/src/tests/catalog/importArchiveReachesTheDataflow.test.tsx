/**
 * An imported archive reaches the dataflow that was saved to receive it.
 *
 * Importing is two calls: the upload writes the account store, then
 * ``installToProject`` writes the open dataflow's lockfile, and only the second
 * one puts the package on the palette (the palette is dataflow-scoped).
 *
 * The second call is conditional on a project id, and the drawer used to let
 * the hook read the id it had captured when it rendered. For an unsaved
 * dataflow that value is null: ``onPickArchive`` auto-saves on the way in, but
 * no render happens between that save and the call, so the closure still held
 * null and the install was skipped outright. The package landed in the account
 * store, never in the lockfile, and never on the palette -- the flake behind
 * #340, which under CI load showed up as an e2e waiting out its full timeout
 * for an install request that was never going to be sent.
 *
 * ``performInstall`` in the same file always re-read the id at call time. This
 * path was the odd one out.
 */
import fs from "fs";
import path from "path";
import React from "react";
import { render, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";

import { usePackageArchiveImport } from "../../components/packages/publishing/usePackageArchiveImport";

const SRC = path.resolve(__dirname, "../..");
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), "utf8");

const mockUploadArchive = jest.fn();
const mockInstallToProject = jest.fn();

jest.mock("../../api/packagesApi", () => ({
  packagesApi: {
    uploadArchive: (...args: unknown[]) => mockUploadArchive(...args),
    installToProject: (...args: unknown[]) => mockInstallToProject(...args),
  },
  refreshPackageRegistry: jest.fn().mockResolvedValue(undefined),
}));

/** Renders the hook and imports one file, exactly as a caller would. */
function importOnce(renderTimeProjectId: string | null, callTimeProjectId?: string | null) {
  const done = jest.fn();

  const Harness: React.FC = () => {
    const { importArchive } = usePackageArchiveImport({
      projectId: renderTimeProjectId,
      reload: async () => {},
      onError: (label, err) => done(`error: ${label} ${String(err)}`),
    });
    React.useEffect(() => {
      const file = new File(["zip"], "pkg.curio.zip");
      // `undefined` means "the caller passed nothing", which is the standalone
      // page; a string is the drawer handing over the id it just saved.
      void (callTimeProjectId === undefined
        ? importArchive(file)
        : importArchive(file, callTimeProjectId)
      ).then(() => done("imported"));
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
    return null;
  };

  render(<Harness />);
  return done;
}

beforeEach(() => {
  jest.clearAllMocks();
  mockUploadArchive.mockResolvedValue({ package: { dirName: "curio.demo.pkg", name: "Demo" } });
  mockInstallToProject.mockResolvedValue({ packages: ["curio.demo.pkg"] });
});

describe("the install that puts an imported package on the palette", () => {
  test("a dataflow saved after the hook rendered still gets the package", async () => {
    // The regression. Render time knows nothing; the id arrives with the call.
    const done = importOnce(null, "project-minted-by-the-autosave");
    await waitFor(() => expect(done).toHaveBeenCalledWith("imported"));

    expect(mockUploadArchive).toHaveBeenCalledTimes(1);
    expect(mockInstallToProject).toHaveBeenCalledWith(
      "project-minted-by-the-autosave",
      "curio.demo.pkg",
    );
  });

  test("an already-saved dataflow needs no hand-over", async () => {
    const done = importOnce("project-already-open");
    await waitFor(() => expect(done).toHaveBeenCalledWith("imported"));
    expect(mockInstallToProject).toHaveBeenCalledWith("project-already-open", "curio.demo.pkg");
  });

  test("the call-time id wins when the two disagree", async () => {
    // The drawer's saved id is the authoritative one: it is what the user's
    // dataflow is, not what the last render happened to know.
    const done = importOnce("stale-from-an-older-render", "the-one-just-saved");
    await waitFor(() => expect(done).toHaveBeenCalledWith("imported"));
    expect(mockInstallToProject).toHaveBeenCalledWith("the-one-just-saved", "curio.demo.pkg");
  });

  test("the standalone page, which has no dataflow, still installs nothing", async () => {
    // The page imports into the account store only. Guarding the fix does not
    // mean every surface suddenly acquires a project.
    //
    // Silenced, not asserted: this path warns now, and the assertion for that
    // belongs to the describe block below. Without the spy the warning is
    // printed on every run of an otherwise quiet suite.
    const warn = jest.spyOn(console, "warn").mockImplementation(() => {});
    try {
      const done = importOnce(null);
      await waitFor(() => expect(done).toHaveBeenCalledWith("imported"));
      expect(mockUploadArchive).toHaveBeenCalledTimes(1);
      expect(mockInstallToProject).not.toHaveBeenCalled();
    } finally {
      warn.mockRestore();
    }
  });
});

describe("the drawer hands over the id it saved", () => {
  // A source-level claim in this directory's style: the behaviour above cannot
  // see which value the drawer passes, only what the hook does with it.
  const DRAWER = "components/packages/publishing/NodeCatalogDrawer.tsx";

  test("importArchive is called with the awaited id, not bare", () => {
    const src = read(DRAWER);
    expect(src).toContain("await importArchive(file, intoProjectId)");
    expect(src).not.toContain("await importArchive(file)");
  });

  test("that id is the one ensureSavedProjectId returned", () => {
    // Re-reading the ref here instead would work today and rot the moment the
    // save stops writing it; the returned value is the save's own answer.
    const src = read(DRAWER);
    expect(src).toMatch(
      /const intoProjectId = await ensureSavedProjectId\([\s\S]{0,120}?\);/,
    );
  });
});

describe("neither silent path stays silent", () => {
  /**
   * Both ways an import can fail to reach the lockfile used to look identical
   * from outside, and identical to success: the upload returns 201, the UI
   * resets, and nothing anywhere says the second call did not happen. On CI
   * that is a 120s timeout in an unrelated assertion, which is how #340 was
   * read as flake three times (#341, `351792bf`, and again on `main`).
   */

  test("a throw after the upload is reported, not swallowed", async () => {
    // The drawer's handler had only a `finally`, so this became an unhandled
    // rejection and the footer button went back to "Import package" as though
    // the import had worked.
    const src = read("components/packages/publishing/NodeCatalogDrawer.tsx");
    const handler = src.slice(src.indexOf("const onPickArchive"));
    const body = handler.slice(0, handler.indexOf("[ensureSavedProjectId"));
    expect(body).toMatch(/catch\s*\([\s\S]{0,40}?\)\s*{[\s\S]{0,1200}?reportActionError/);
  });

  test("reportActionError is a dependency of the handler that now uses it", () => {
    // A stale closure here would report through a function captured before
    // the drawer had its error chrome, which is the quiet way this regresses.
    const src = read("components/packages/publishing/NodeCatalogDrawer.tsx");
    expect(src).toMatch(
      /\[ensureSavedProjectId,\s*importArchive,\s*reportActionError\]/,
    );
  });

  test("skipping the project install says so", async () => {
    // The page path is legitimate and must not toast, so this is a console
    // warning rather than an error - but it must exist, because it is the
    // only thing that distinguishes "no dataflow to install into" from "the
    // dataflow's id failed to arrive".
    const warn = jest.spyOn(console, "warn").mockImplementation(() => {});
    try {
      const done = importOnce(null);
      await waitFor(() => expect(done).toHaveBeenCalledWith("imported"));
      expect(warn).toHaveBeenCalledWith(
        expect.stringContaining("account store only"),
      );
      expect(warn.mock.calls[0][0]).toContain("curio.demo.pkg");
    } finally {
      warn.mockRestore();
    }
  });

  test("an install that did happen warns about nothing", async () => {
    const warn = jest.spyOn(console, "warn").mockImplementation(() => {});
    try {
      const done = importOnce("project-already-open");
      await waitFor(() => expect(done).toHaveBeenCalledWith("imported"));
      expect(warn).not.toHaveBeenCalled();
    } finally {
      warn.mockRestore();
    }
  });
});

