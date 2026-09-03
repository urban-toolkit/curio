import fs from "fs";
import path from "path";

/**
 * The canvas title's rename has to reach the PROJECT ROW, not just the canvas.
 *
 * #230: committing the title only called `setIsEditing(false)`, so the new name
 * lived in `workflowName` alone. `saveCurrentProject` sends `projectName` — set
 * only by `loadProject` — so the save re-sent the name the dataflow was opened
 * under and the Projects card never moved. `renameDataflow` writes both stores
 * and marks the dataflow dirty; committing must go through it.
 *
 * Source-read, following `saveStatusIndicator.test.ts` on this same component:
 * UpMenu needs the whole provider stack to render, and nothing in the suite
 * mounts it. The behaviour itself is asserted where it can be — against the real
 * app — by the `renaming-a-dataflow-renames-it-everywhere` walkthrough and by
 * `test_project_save_load.py`, and the hook contract by
 * `useWorkflowOperations.rename.test.ts`.
 */

const SRC = path.resolve(__dirname, "../..");
const UP_MENU = fs.readFileSync(
  path.join(SRC, "components/menus/top/UpMenu.tsx"),
  "utf8",
);

describe("the canvas title's rename", () => {
  it("pulls renameDataflow out of the flow context", () => {
    expect(UP_MENU).toMatch(/^\s*renameDataflow,$/m);
  });

  it("commits through renameDataflow on both blur and Enter", () => {
    // Both, or the bug survives on whichever path was missed.
    const commit = UP_MENU.slice(
      UP_MENU.indexOf("const commitName"),
      UP_MENU.indexOf("const openTutorial"),
    );
    expect(commit).toContain("renameDataflow(workflowName)");
    expect(commit).toMatch(/handleNameBlur[\s\S]*commitName\(\)/);
    expect(commit).toMatch(/e\.key === "Enter"[\s\S]*commitName\(\)/);
  });

  it("restores a real name rather than leaving the title blank", () => {
    // `renameDataflow` returns false for a blank entry; the caller has to put
    // something back or the dataflow is left visibly nameless.
    const commit = UP_MENU.slice(
      UP_MENU.indexOf("const commitName"),
      UP_MENU.indexOf("const openTutorial"),
    );
    expect(commit).toMatch(/if \(!renameDataflow\(workflowName\)\)/);
    expect(commit).toContain("setWorkflowName(");
    expect(commit).toContain("projectName");
  });

  it("still updates the visible title on every keystroke", () => {
    // The fix moves what *committing* means; typing must stay live, or the
    // field stops echoing what the user types.
    const onChange = UP_MENU.slice(
      UP_MENU.indexOf("const handleNameChange"),
      UP_MENU.indexOf("const commitName"),
    );
    expect(onChange).toContain("setWorkflowName(e.target.value)");
  });
});
