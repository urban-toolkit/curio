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
  test("every project offers the same four actions", () => {
    // No Archive, and no state parameter that could reintroduce a divergence
    // between the drawer and the context menu.
    expect(ids()).toEqual(["open", "rename", "duplicate", "delete"]);
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

  test("the way out comes last", () => {
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
