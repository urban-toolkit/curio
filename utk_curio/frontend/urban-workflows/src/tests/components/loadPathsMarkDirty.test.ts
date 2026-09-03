import fs from "fs";
import path from "path";

/**
 * The other half of #229, and the half a reviewer is most likely to drop as
 * unrelated.
 *
 * Suppressing `markDirty` during `loadParsedTrill`'s edge replay fixes opening a
 * saved dataflow — but the SAME replay is how File -> Load and a provenance
 * revert put their content on the canvas, and both of those genuinely do diverge
 * from what is on disk. Left alone they would read as already-saved, which
 * trades a cosmetic false positive for a silent loss of work. Each caller says
 * so itself now, because only the caller knows the intent.
 *
 * Source-read for the same reason `saveStatusIndicator.test.ts` is: neither
 * component can be mounted without the whole provider stack. `dirtyOnLoad.test.ts`
 * covers the suppression itself against the live hook.
 */

const SRC = path.resolve(__dirname, "../..");
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), "utf8");

describe("load paths that DO diverge from disk still mark dirty", () => {
  const UP_MENU = read("components/menus/top/UpMenu.tsx");
  const USE_CODE = read("hook/useCode.ts");

  it("File -> Load marks the dataflow dirty after importing", () => {
    // Also strictly more correct than before the fix: an EDGELESS import never
    // marked dirty at all, because the replay was the only thing doing it.
    const upload = UP_MENU.slice(
      UP_MENU.indexOf("const handleFileUpload"),
      UP_MENU.indexOf("const loadTrillFile"),
    );
    expect(upload).toContain("loadTrill(parsed.spec)");
    expect(upload).toContain("markDirty()");
    expect(upload.indexOf("loadTrill(parsed.spec)")).toBeLessThan(
      upload.indexOf("markDirty()"),
    );
  });

  it("UpMenu takes markDirty off the flow context", () => {
    expect(UP_MENU).toMatch(/^\s*markDirty,$/m);
  });

  it("reverting to a previous version marks the dataflow dirty", () => {
    // Marked in `useCode.loadTrill`'s `fromProvenance` branch rather than in
    // TrillProvenanceWindow: that branch is the last point where a revert is
    // still distinguishable from opening a project (below it both reach
    // loadParsedTrill identically), and the window's own suite mocks `useCode`
    // precisely to keep FlowProvider's module graph - vega included - out of a
    // presentational test. Importing the context there breaks it.
    const branch = USE_CODE.slice(
      USE_CODE.indexOf("if (fromProvenance)"),
      USE_CODE.indexOf("} else if(suggestionType == undefined)"),
    );
    expect(branch).toContain("loadParsedTrill(");
    expect(branch).toContain("markDirty()");
  });

  it("useCode pulls markDirty from the flow context", () => {
    expect(USE_CODE).toMatch(/^\s*markDirty,$/m);
  });

  it("does NOT mark dirty on the project-open branch", () => {
    // The bug itself: opening a saved project must stay clean. The two branches
    // sit next to each other, so this pins that the fix went in the right one.
    const openBranch = USE_CODE.slice(
      USE_CODE.indexOf("} else if(suggestionType == undefined)"),
      USE_CODE.indexOf("const generateCodeNode"),
    );
    expect(openBranch).not.toContain("markDirty()");
  });
});
