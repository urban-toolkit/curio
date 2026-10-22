/**
 * Undo and Redo over a node's entries (utils/nodeRuns `undoStep`,
 * `redoStep`): Undo puts back the entry before the one in use, or the code a
 * first edit replaced, and Redo the newest entry after it. Entries that hold
 * the code the node holds already, as a run of an edit does, are passed over.
 */
import type { NodeExecRecord } from "../../providers/ProvenanceProvider";
import { redoStep, undoStep } from "../../utils/nodeRuns";

const entry = (id: number, parentId: number | null, code: string, more: Partial<NodeExecRecord> = {}): NodeExecRecord => ({
  id, parentId, code, inputs: [], outputs: [], startTime: "", endTime: "", kind: "edit", label: `edit ${id}`, ...more,
});

describe("undoStep", () => {
  test("puts back the entry before, then the code the node's first edit replaced, then nothing", () => {
    const records = [entry(1, null, "a", { before: "start" }), entry(2, 1, "b")];
    expect(undoStep(records, 2, "b")).toEqual({ code: "a", current: 1 });
    expect(undoStep(records, 1, "a")).toEqual({ code: "start", current: null });
    expect(undoStep(records, null, "start")).toBeNull();
    // A first entry that kept nothing has nothing before it.
    expect(undoStep([entry(1, null, "a")], 1, "a")).toBeNull();
  });

  test("puts back the entry in use first when the node holds other code, and passes over a run of the same code", () => {
    const records = [entry(1, null, "a", { before: "start" }), entry(2, 1, "b"), entry(3, 2, "b", { kind: undefined, label: undefined })];
    expect(undoStep(records, 3, "typed")).toEqual({ code: "b", current: 3 });
    // The run (3) holds the edit's code (2): one Undo goes back past both.
    expect(undoStep(records, 3, "b")).toEqual({ code: "a", current: 1 });
  });

  test("ends on a history whose parents run in a circle", () => {
    const records = [entry(1, 2, "a"), entry(2, 1, "a")];
    expect(undoStep(records, 1, "a")).toBeNull();
  });
});

describe("redoStep", () => {
  test("puts back the newest entry after the one in use, the first ones from before the first entry", () => {
    const records = [entry(1, null, "a", { before: "start" }), entry(2, 1, "b"), entry(3, 1, "c"), entry(4, 3, "d")];
    expect(redoStep(records, null, "start")).toEqual({ code: "a", current: 1 });
    // Two entries branch from 1: the newest is put back.
    expect(redoStep(records, 1, "a")).toEqual({ code: "c", current: 3 });
    expect(redoStep(records, 3, "c")).toEqual({ code: "d", current: 4 });
    expect(redoStep(records, 4, "d")).toBeNull();
    expect(redoStep(records, 2, "b")).toBeNull();
  });

  test("passes over an entry that holds the code the node holds, as a run of an edit does", () => {
    const records = [entry(1, null, "a"), entry(2, 1, "a", { kind: undefined, label: undefined }), entry(3, 2, "b")];
    expect(redoStep(records, 1, "a")).toEqual({ code: "b", current: 3 });
  });

  test("takes an entry whose parent left the history for a first one", () => {
    expect(redoStep([entry(5, 4, "e")], null, "x")).toEqual({ code: "e", current: 5 });
  });
});
