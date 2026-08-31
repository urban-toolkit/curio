import fs from "fs";
import path from "path";

/**
 * The save indicator is always on screen for someone who can save (issue found
 * while reviewing the agent-catalog recordings: the disk was simply absent).
 *
 * It used to render only when `saving || projectDirty || projectSavedAt`, so a
 * brand-new dataflow showed nothing — the one moment the state is most worth
 * stating, because nothing is on disk at all. Absence then had to be read as
 * either "saved" or "nothing to save", and it meant neither.
 *
 * The rule now: present whenever the viewer owns the dataflow; orange unless
 * what you see is on disk. Green means that and only that.
 *
 * Source-read because UpMenu needs the whole provider stack to render; the live
 * behaviour is asserted in the `agent-catalog-adding-to-an-unsaved-dataflow`
 * walkthrough, which starts on `/dataflow/new` and reads the rendered state.
 */

const SRC = path.resolve(__dirname, "../..");
const UP_MENU = fs.readFileSync(
  path.join(SRC, "components/menus/top/UpMenu.tsx"),
  "utf8",
);
const STYLES = fs.readFileSync(
  path.join(SRC, "components/menus/top/UpMenu.module.css"),
  "utf8",
);

/** The JSX from the save-status comment to the end of its button. */
function saveBlock(): string {
  const at = UP_MENU.indexOf("Save status indicator");
  expect(at).toBeGreaterThan(-1);
  return UP_MENU.slice(at, UP_MENU.indexOf("<UserMenu />", at));
}

describe("the save status indicator", () => {
  it("is not gated on the dataflow having been saved before", () => {
    // The exact regression: `projectSavedAt` in the render guard hid the disk
    // on every dataflow that had never been written to disk.
    expect(saveBlock()).not.toMatch(/\{\(saving \|\| projectDirty \|\| projectSavedAt\) &&/);
  });

  it("is shown to anyone who can save", () => {
    expect(saveBlock()).toContain("{!isSharedView && (");
  });

  it("treats a never-saved dataflow as unsaved", () => {
    const block = saveBlock();
    expect(block).toContain("!projectSavedAt");
    expect(block).toMatch(/projectDirty \|\| !projectSavedAt[\s\S]{0,60}unsavedIcon/);
  });

  it("names its state for anything that needs to read it", () => {
    // The walkthrough asserts on this rather than on a hashed CSS class.
    const block = saveBlock();
    expect(block).toContain('data-curio-save-state');
    for (const state of ["saving", "unsaved", "saved"]) {
      expect(block).toContain(`"${state}"`);
    }
  });

  it("says which state it is in, in words", () => {
    expect(saveBlock()).toContain("Not saved yet - click to save");
  });

  it("keeps orange for unsaved and green for saved", () => {
    expect(STYLES).toMatch(/\.unsavedIcon \{\s*color: rgb\(251, 170, 105\)/);
    expect(STYLES).toMatch(/\.savedIcon \{\s*color: #5cb85c/);
  });
});
