/**
 * One definition of what can be done to a project (#221).
 *
 * The projects page had two surfaces rendering hand-written lists, and only one
 * consulted ``archived_at``: the detail drawer offered Archive OR Delete
 * forever depending on state, while the right-click menu hardcoded five items
 * and offered both to everything. The same project was told two different
 * things about what could be done to it.
 */
import { projectActions } from "../../pages/projects/projectActions";

const ids = (archived: boolean) => projectActions({ archived }).map((a) => a.id);

describe("projectActions", () => {
  test("an active project can be archived or deleted", () => {
    // The change #221 asked for: deletion is no longer hidden behind archiving.
    expect(ids(false)).toEqual(["open", "rename", "duplicate", "archive", "delete"]);
  });

  test("an archived project is not offered archiving again", () => {
    // The half the context menu got wrong — it offered Archive to everything.
    expect(ids(true)).toEqual(["open", "rename", "duplicate", "delete"]);
  });

  test("delete is marked destructive in both states", () => {
    // Drives the confirm dialog and the danger styling on both surfaces, so a
    // surface cannot render it as an ordinary button.
    for (const archived of [true, false]) {
      const del = projectActions({ archived }).find((a) => a.id === "delete");
      expect(del?.destructive).toBe(true);
    }
  });

  test("nothing else is destructive", () => {
    // Archive is recoverable in principle and must not be styled as the way out.
    const others = projectActions({ archived: false }).filter((a) => a.id !== "delete");
    expect(others.every((a) => !a.destructive)).toBe(true);
  });

  test("the way out comes last", () => {
    // The order the catalogs already use: every way on is offered before the
    // way out.
    for (const archived of [true, false]) {
      const list = projectActions({ archived });
      expect(list[list.length - 1].id).toBe("delete");
    }
  });

  test("every action has a label", () => {
    for (const archived of [true, false]) {
      for (const action of projectActions({ archived })) {
        expect(action.label.trim()).not.toBe("");
      }
    }
  });
});
