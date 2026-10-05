/**
 * Selection tags (#662): a view's current selection, read by a node's code as
 * `[!! selection name !!]`, the ids of the rows it picks.
 */
import { VisInteractionType } from "../../constants";
import { objectRows } from "../../utils/selectionMatch";
import {
  SELECTION_ID_CAP,
  changesSelection,
  idColumns,
  isNewSelection,
  normalizeSelections,
  selectedIds,
  suggestTagName,
  withState,
  type SelectionTag,
} from "../../utils/references/selectionTags";
import { resolveReferences } from "../../utils/references/codeReferences";
import { runKeyWithShared } from "../../utils/references/sharedParameters";

const BUILDINGS = [
  { osm_id: 101, building_id: 7, height: 10, name: "a" },
  { osm_id: 102, building_id: 7, height: 30, name: "b" },
  { osm_id: 103, building_id: 8, height: 50, name: "c" },
  { osm_id: 104, building_id: 9, height: 20, name: "d" },
];
const columnsOf = (rows: any[]) => Object.keys(rows[0]);

const brush = (bounds: Record<string, unknown>) => ({
  brush: { type: VisInteractionType.INTERVAL, data: bounds, priority: 1 },
});

describe("the columns a tag can identify rows by", () => {
  test("osm_id and building_id come first, though a building's parts share its building_id", () => {
    expect(idColumns(objectRows(BUILDINGS), columnsOf(BUILDINGS))).toEqual(["osm_id", "building_id", "height", "name"]);
  });

  test("another column is offered only when every row holds a different text or number", () => {
    const rows = [
      { code: "x1", group: "a", size: 1, shape: { type: "Point" } },
      { code: "x2", group: "a", size: null, shape: { type: "Point" } },
    ];
    expect(idColumns(objectRows(rows), columnsOf(rows))).toEqual(["code"]);
  });

  test("none, for rows that no column tells apart: the tag is refused", () => {
    const rows = [
      { kind: "tree", count: 1 },
      { kind: "tree", count: 1 },
    ];
    expect(idColumns(objectRows(rows), columnsOf(rows))).toEqual([]);
  });

  test("never a column the view adds to its own rows", () => {
    const rows = [
      { __row_index__: 0, __input__: 0, _vgsid_: 1, interacted: "0", label: "a" },
      { __row_index__: 1, __input__: 0, _vgsid_: 2, interacted: "1", label: "b" },
    ];
    expect(idColumns(objectRows(rows), columnsOf(rows))).toEqual(["label"]);
  });
});

describe("the ids a selection picks", () => {
  test("a brush picks the rows in its range, as a Data Pool reads it, each id once in row order", () => {
    expect(selectedIds(brush({ height: [15, 60] }), objectRows(BUILDINGS), "osm_id")).toEqual({ ids: [102, 103, 104] });
    // Two parts of one building are one id.
    expect(selectedIds(brush({ height: [5, 35] }), objectRows(BUILDINGS), "building_id")).toEqual({ ids: [7, 9] });
  });

  test("a point selection names row positions, never Vega's _vgsid_", () => {
    const point = { pick: { type: VisInteractionType.POINT, data: [3, 0], priority: 1 } };
    expect(selectedIds(point, objectRows(BUILDINGS), "osm_id")).toEqual({ ids: [101, 104] });
  });

  test("the latest select wins, as in a Data Pool's default mode", () => {
    const details = {
      brush: { type: VisInteractionType.INTERVAL, data: { height: [0, 100] }, priority: 0 },
      hover: { type: VisInteractionType.POINT, data: [2], priority: 1 },
    };
    expect(selectedIds(details, objectRows(BUILDINGS), "osm_id")).toEqual({ ids: [103] });
  });

  test("a row with no id in the column is left out, and nothing selected is no ids", () => {
    const rows = [{ osm_id: null, height: 10 }, { osm_id: 5, height: 20 }];
    expect(selectedIds(brush({ height: [0, 30] }), objectRows(rows), "osm_id")).toEqual({ ids: [5] });
    const cleared = { brush: { type: VisInteractionType.INTERVAL, data: {}, priority: 1 } };
    expect(selectedIds(cleared, objectRows(BUILDINGS), "osm_id")).toEqual({ ids: [] });
  });

  test("more ids than a tag takes come back as their count", () => {
    const rows = Array.from({ length: SELECTION_ID_CAP + 5 }, (_, i) => ({ osm_id: i, v: 1 }));
    expect(selectedIds(brush({ v: [0, 2] }), objectRows(rows), "osm_id")).toEqual({ count: SELECTION_ID_CAP + 5 });
    const exactly = rows.slice(0, SELECTION_ID_CAP);
    const state = selectedIds(brush({ v: [0, 2] }), objectRows(exactly), "osm_id");
    expect("ids" in state && state.ids).toHaveLength(SELECTION_ID_CAP);
  });
});

describe("a tag over the cap", () => {
  const over: SelectionTag = { name: "picked", node: "chart", column: "osm_id", count: 25000 };

  test("stops the run with a message that says so", () => {
    const { problems } = resolveReferences(
      "x = [!! selection picked !!]",
      { widgets: [], inputs: [], shared: [], selections: [over] },
      "python",
    );
    expect(problems.map((p) => p.message)).toEqual([
      "[!! selection picked !!]: the selection holds 25000 ids, more than the 10000 a selection tag takes. "
        + "Select fewer rows in its view.",
    ]);
  });

  test("a hand-edited list longer than the cap is refused the same way", () => {
    const ids = Array.from({ length: SELECTION_ID_CAP + 1 }, (_, i) => i);
    const { code, problems } = resolveReferences(
      "x = [!! selection picked !!]",
      { widgets: [], inputs: [], shared: [], selections: [{ name: "picked", node: "c", column: "osm_id", ids }] },
      "python",
    );
    expect(code).toBe("x = [!! selection picked !!]");
    expect(problems[0].message).toContain(`holds ${SELECTION_ID_CAP + 1} ids, more than the ${SELECTION_ID_CAP}`);
  });
});

describe("a new selection marks the node stale", () => {
  const tag: SelectionTag = { name: "picked", node: "chart", column: "osm_id", ids: [101] };
  const code = "return arg[arg.osm_id.isin([!! selection picked !!])]";

  test("its run key follows the ids its code names", () => {
    const before = runKeyWithShared(code, [], [], [tag]);
    expect(runKeyWithShared(code, [], [], [withState(tag, { ids: [101, 104] })])).not.toBe(before);
    expect(runKeyWithShared(code, [], [], [withState(tag, { count: 20000 })])).not.toBe(before);
    expect(runKeyWithShared(code, [], [], [{ ...tag }])).toBe(before);
  });

  test("code that names no selection tag keeps the key it had", () => {
    expect(runKeyWithShared("return arg", [], [], [tag])).toBe(runKeyWithShared("return arg", [], []));
  });

  test("only a selection the user made counts, not a chart declaring its selects", () => {
    expect(isNewSelection({ brush: { type: VisInteractionType.UNDETERMINED, data: [] } })).toBe(false);
    expect(isNewSelection({})).toBe(false);
    expect(isNewSelection(brush({ height: [1, 2] }))).toBe(true);
  });

  test("an empty selection counts only when it clears one the view held", () => {
    const empty = { brush: { type: VisInteractionType.UNDETERMINED, data: [], priority: 1 } };
    const declared = { brush: { type: VisInteractionType.UNDETERMINED, data: [] } };
    expect(changesSelection(declared, empty)).toBe(false);
    expect(changesSelection(undefined, empty)).toBe(false);
    expect(changesSelection(brush({ height: [1, 2] }), empty)).toBe(true);
    expect(changesSelection(declared, brush({ height: [1, 2] }))).toBe(true);
  });
});

describe("saved tags", () => {
  test("keep their ids or their count, and drop what is not a tag", () => {
    const raw = [
      { name: "picked", node: "chart", column: "osm_id", ids: [1, "w2"] },
      { name: "many", node: "chart", column: "osm_id", count: 20000 },
      { name: "picked", node: "other", column: "osm_id", ids: [] },
      { name: "no column", node: "chart", ids: [] },
      { name: "nothing", node: "chart", column: "osm_id" },
      "a string",
    ];
    expect(normalizeSelections(raw)).toEqual([
      { name: "picked", node: "chart", column: "osm_id", ids: [1, "w2"] },
      { name: "many", node: "chart", column: "osm_id", count: 20000 },
    ]);
  });

  test("a new tag is named after its view, unlike the node's other tags", () => {
    expect(suggestTagName("Buildings (Vega-Lite)", [])).toBe("buildings_vega_lite");
    expect(suggestTagName("2D plot", [])).toBe("_2d_plot");
    expect(suggestTagName("", ["selection"])).toBe("selection_2");
  });
});
