/**
 * One definition of what can be done to a project (#221).
 *
 * The projects page had two surfaces rendering hand-written lists, and only one
 * consulted ``archived_at``: the detail drawer offered Archive OR Delete
 * depending on state, while the right-click menu hardcoded five items and
 * offered both to everything. The same project was told two different things
 * about what could be done to it.
 *
 * Archive itself was then removed (#261), so there is no per-project state left
 * that could make the two surfaces disagree — but the single source is what
 * keeps them honest, and these cases guard it.
 */
import { projectActions } from "../../pages/projects/projectActions";

const ids = () => projectActions().map((a) => a.id);

describe("projectActions", () => {
  test("a project the user made offers four actions", () => {
    // No Archive. The one piece of state left subtracts Delete from a seeded
    // example; nothing adds an action, so the two surfaces still cannot show
    // different sets for the same project.
    expect(ids()).toEqual(["open", "rename", "duplicate", "delete"]);
  });

  test("a seeded example offers no Delete", () => {
    // What Curio put in the list is the user's to open, rename and edit, but
    // not to remove - the rule the Data Catalog has applied to shared-catalog
    // datasets all along. And there is no way back from it: since #270 a
    // deleted example is never seeded again.
    expect(projectActions({ isExample: true }).map((a) => a.id)).toEqual([
      "open",
      "rename",
      "duplicate",
    ]);
  });

  test("an example loses nothing else", () => {
    // Only the way out is withheld. An example is still fully usable.
    const example = projectActions({ isExample: true }).map((a) => a.id);
    for (const id of ["open", "rename", "duplicate"]) {
      expect(example).toContain(id);
    }
  });

  test("an unset flag reads as an ordinary project", () => {
    // Older responses carry no `is_example`, and must not silently lose Delete.
    expect(projectActions({}).map((a) => a.id)).toEqual(ids());
    expect(projectActions({ isExample: undefined }).map((a) => a.id)).toEqual(ids());
  });

  test("delete is marked destructive", () => {
    // Drives the confirm dialog and the danger styling on both surfaces, so a
    // surface cannot render it as an ordinary button.
    expect(projectActions().find((a) => a.id === "delete")?.destructive).toBe(true);
  });

  test("nothing else is destructive", () => {
    const others = projectActions().filter((a) => a.id !== "delete");
    expect(others.every((a) => !a.destructive)).toBe(true);
  });

  test("the way out comes last, when it is offered at all", () => {
    // The order the catalogs already use: every way on is offered before the
    // way out.
    const list = projectActions();
    expect(list[list.length - 1].id).toBe("delete");
  });

  test("delete is labelled plainly", () => {
    // "Delete forever" earned its keep only while Archive sat next to it as the
    // softer-sounding option (#261). The confirm dialog states the permanence.
    expect(projectActions().find((a) => a.id === "delete")?.label).toBe("Delete");
  });

  test("every action has a label", () => {
    for (const action of projectActions()) {
      expect(action.label.trim()).not.toBe("");
    }
  });
});
