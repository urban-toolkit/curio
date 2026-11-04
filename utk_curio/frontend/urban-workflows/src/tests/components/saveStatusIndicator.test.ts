import fs from "fs";
import path from "path";

/**
 * The save indicator is always on screen for someone who can save (issue found
 * while reviewing the agent-catalog recordings: the disk was simply absent).
 *
 * It used to render only when `saving || projectDirty || projectSavedAt`, so a
 * brand-new dataflow showed nothing: the one moment the state is most worth
 * stating, because nothing is on disk at all. Absence then had to be read as
 * either "saved" or "nothing to save", and it meant neither.
 *
 * The rule now: present whenever the viewer owns the dataflow. On a dataflow
 * bound to its doc it reads Saved once the server has every change, and
 * Saving... or Offline while changes wait; a canvas bound to no doc reads
 * Unsaved unless what you see is on the server. "Saved" means that and only
 * that, and the bar says it in a word as well as a colour.
 *
 * Source-read for the rules that hold whatever the provider stack; the states
 * as the bar renders them are in upMenuSave.test.tsx, and the live behaviour
 * in the `agent-catalog-adding-to-an-unsaved-dataflow` walkthrough, which
 * starts on `/dataflow/new` and reads the rendered state.
 */

const SRC = path.resolve(__dirname, "../..");
const read = (file: string) => fs.readFileSync(path.join(SRC, file), "utf8");
const UP_MENU = read("components/menus/top/UpMenu.tsx");
const SAVE_STATUS = read("components/menus/top/SaveStatus.tsx");
const SAVE_STATE = read("providers/flow/useSaveState.ts");
const STYLES = read("components/menus/top/UpMenu.module.css");
const TOKENS = read("styles/curioTokens.css");

/** The status's JSX: its button, from the opening tag to the closing one. */
function saveBlock(): string {
  const at = SAVE_STATUS.indexOf("<button");
  expect(at).toBeGreaterThan(-1);
  const end = SAVE_STATUS.indexOf("</button>", at);
  expect(end).toBeGreaterThan(at);
  return SAVE_STATUS.slice(at, end);
}

/** What the bar says for each state, as SaveStatus names them. */
function labels(): Record<string, string> {
  const table = SAVE_STATUS.match(/const LABEL: Record<SaveState, string> = \{([\s\S]*?)\};/);
  expect(table).not.toBeNull();
  return Object.fromEntries(
    [...table![1].matchAll(/(\w+): "([^"]*)"/g)].map(([, state, label]) => [state, label]),
  );
}

describe("the save status indicator", () => {
  it("is not gated on the dataflow having been saved before", () => {
    // The exact regression: `projectSavedAt` in the render guard hid the disk
    // on every dataflow that had never been written to disk.
    expect(UP_MENU).not.toMatch(/\{\(saving \|\| projectDirty \|\| projectSavedAt\) &&/);
    expect(UP_MENU).not.toMatch(/projectSavedAt\)? &&\s*<SaveStatus/);
    // Nor does the status itself render nothing in any state.
    expect(SAVE_STATUS).not.toMatch(/return null/);
  });

  it("is shown to anyone who can save", () => {
    // The owner's tab: another account's dataflow, a watcher's or an
    // editor's, is saved by its owner's tab.
    expect(UP_MENU).toContain("{savesHere && <SaveStatus saving={saving} onSave={handleSave} />}");
    expect(UP_MENU).toContain('const savesHere = viewerMode !== "shared";');
  });

  it("treats a never-saved dataflow as unsaved", () => {
    // A canvas bound to no doc: a dataflow never saved has nothing on the
    // server, whatever it holds.
    expect(SAVE_STATE).toMatch(
      /if \(!provider\) \{[\s\S]{0,80}state: projectDirty \|\| !projectSavedAt \? "unsaved" : "saved"/,
    );
    expect(saveBlock()).toMatch(/done \? styles\.savedIcon : styles\.unsavedIcon/);
    expect(SAVE_STATUS).toContain('const done = shown === "saved";');
  });

  it("names its state for anything that needs to read it", () => {
    // The walkthroughs assert on these rather than on a hashed CSS class.
    const block = saveBlock();
    expect(block).toContain("data-curio-save-state={shown}");
    expect(block).toContain('data-curio-changes-pending={pending ? "true" : "false"}');
    expect(SAVE_STATE).toContain('export type SaveState = "saved" | "saving" | "offline" | "unsaved";');
    expect(Object.keys(labels()).sort()).toEqual(["offline", "saved", "saving", "unsaved"]);
  });

  it("says which state it is in, in words", () => {
    expect(SAVE_STATUS).toContain("Not saved yet - click to save");
    // On the bar itself, not only in the tooltip: the colour alone is not
    // something every reader can tell apart.
    expect(saveBlock()).toMatch(/<span>\{LABEL\[shown\]\}<\/span>/);
    expect(labels()).toEqual({
      saved: "Saved",
      saving: "Saving...",
      offline: "Offline",
      unsaved: "Unsaved",
    });
  });

  it("keeps one colour for unsaved and another for saved, from the tokens", () => {
    expect(STYLES).toMatch(/\.unsavedIcon \{\s*color: var\(--curio-top-bar-unsaved\)/);
    expect(STYLES).toMatch(/\.savedIcon \{\s*color: var\(--curio-top-bar-saved\)/);
    const value = (name: string) => TOKENS.match(new RegExp(`--${name}:\\s*([^;]+);`))?.[1];
    expect(value("curio-top-bar-unsaved")).toBeTruthy();
    expect(value("curio-top-bar-saved")).toBeTruthy();
    expect(value("curio-top-bar-unsaved")).not.toBe(value("curio-top-bar-saved"));
  });
});
