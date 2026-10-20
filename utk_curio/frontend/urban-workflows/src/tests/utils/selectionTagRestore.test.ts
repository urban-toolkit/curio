/**
 * What a chart drawn again puts back from its selection tags (#884): the rows
 * whose ids the tags hold, and the store of its point select set to them, in
 * the form vega-lite gives a click's own tuples. The compiled signals below are
 * vega-lite 6's own output for each spec (`lite.compile(spec).spec`), trimmed
 * to the signals read here.
 */
import { objectRows } from "../../utils/selectionMatch";
import { rowsHeldBy, tagsOnView, type SelectionTag } from "../../utils/references/selectionTags";
import { pointStoreOf, pointStoreTuples } from "../../utils/vegaSelects";

/** What vega-lite builds for a click on a mark, before the unit and the rest. */
const CLICKED = "datum && item().mark.marktype !== 'group' && indexof(item().mark.role, 'legend') < 0 ? ";

/** A click's tuple over `_vgsid_`, in the unit *unit* (an expression, quoted). */
const byId = (unit: string) =>
  `${CLICKED}{unit: ${unit}, _vgsid_: (item().isVoronoi ? datum.datum : datum)["_vgsid_"]} : null`;

/** The tuple signal of the select `pick`, as vega-lite writes it. */
const tupleSignal = (update: string) => ({ name: "pick_tuple", on: [{ update }, { update: "null" }] });

/** `{"params": [{"name": "pick", "select": "point"}], "mark": "point", ...}` */
const SINGLE = { signals: [{ name: "pick" }, tupleSignal(byId('""'))] };
/** The same select in the first view of a layer. */
const LAYER = { signals: [{ name: "pick" }, tupleSignal(byId('"layer_0"'))] };
/** The same select in the first view of an hconcat: its tuple in the view's own scope. */
const CONCAT = { signals: [{ name: "pick" }], marks: [{ signals: [tupleSignal(byId('"concat_0"'))] }] };
/** The same select in a facet's cells, whose unit names each cell. */
const FACET = {
  signals: [{ name: "pick" }],
  marks: [{ signals: [tupleSignal(byId(`"child" + '__facet_column_' + (facet["g"])`))] }],
};
/** `{"select": {"type": "point", "fields": ["osm_id"]}}` */
const FIELDS = {
  signals: [
    { name: "pick" },
    tupleSignal(`${CLICKED}{unit: "", fields: pick_tuple_fields, values: [(item().isVoronoi ? datum.datum : datum)["osm_id"]]} : null`),
    { name: "pick_tuple_fields", value: [{ type: "E", field: "osm_id" }] },
  ],
};
/** `{"select": {"type": "point", "encodings": ["x"]}}` over `x: {"field": "value"}` */
const ENCODINGS = {
  signals: [
    { name: "pick" },
    tupleSignal(`${CLICKED}{unit: "", fields: pick_tuple_fields, values: [(item().isVoronoi ? datum.datum : datum)["value"]]} : null`),
    { name: "pick_tuple_fields", value: [{ field: "value", channel: "x", type: "E" }] },
  ],
};
/** `{"select": {"type": "point", "encodings": ["x"]}}` over a binned `x`. */
const BINNED = {
  signals: [
    { name: "pick" },
    tupleSignal(
      `${CLICKED}{unit: "", fields: pick_tuple_fields, values: [[(item().isVoronoi ? datum.datum : datum)["bin_maxbins_10_value"], `
        + `(item().isVoronoi ? datum.datum : datum)["bin_maxbins_10_value_end"]]]} : null`,
    ),
    { name: "pick_tuple_fields", value: [{ field: "value", channel: "x", type: "R-RE" }] },
  ],
};

const ROWS = [
  { osm_id: 1001, label: "Alice", zip: "60614" },
  { osm_id: 1002, label: "Bob", zip: "60657" },
  { osm_id: 1003, label: "Charlie", zip: "60614" },
];
const tag = (extra: Partial<SelectionTag>): SelectionTag => ({ name: "picked", node: "chart", column: "osm_id", ...extra });

describe("the store a point select is put back with", () => {
  test("over no fields, holds the rows' _vgsid_ in the unit the click names", () => {
    expect(pointStoreOf(SINGLE, "pick")).toEqual({ unit: "" });
    expect(pointStoreOf(LAYER, "pick")).toEqual({ unit: "layer_0" });
  });

  test("of a select in a concatenated view, is read from that view's own scope", () => {
    expect(pointStoreOf(CONCAT, "pick")).toEqual({ unit: "concat_0" });
  });

  test("over fields or encodings, holds their values, under the fields the click's tuple names", () => {
    expect(pointStoreOf(FIELDS, "pick")).toEqual({ unit: "", fields: [{ type: "E", field: "osm_id" }] });
    expect(pointStoreOf(ENCODINGS, "pick")).toEqual({
      unit: "",
      fields: [{ field: "value", channel: "x", type: "E" }],
    });
  });

  test("is not read where a click's tuple cannot be rebuilt from ids: a facet's cells, a bin, another select", () => {
    expect(pointStoreOf(FACET, "pick")).toBeNull();
    expect(pointStoreOf(BINNED, "pick")).toBeNull();
    expect(pointStoreOf(SINGLE, "brush")).toBeNull();
    // A select whose selection is no top-level signal is not heard either.
    expect(pointStoreOf({ signals: [tupleSignal(byId('""'))] }, "pick")).toBeNull();
    expect(pointStoreOf(undefined, "pick")).toBeNull();
  });

  test("over no fields, picks each row by the id the view gives it, sorted as vega keeps them", () => {
    // Rows 2 and 0, drawn with ids 7 and 5; row 1 is not drawn.
    const idOfRow = new Map([[0, 5], [2, 7]]);
    expect(pointStoreTuples({ unit: "" }, [2, 0, 1], ROWS, idOfRow)).toEqual([
      { unit: "", _vgsid_: 5 },
      { unit: "", _vgsid_: 7 },
    ]);
    expect(pointStoreTuples({ unit: "" }, [1], ROWS, idOfRow)).toEqual([]);
  });

  test("over fields, picks each set of the rows' values once", () => {
    const store = { unit: "", fields: [{ type: "E", field: "zip" }] };
    expect(pointStoreTuples(store, [0, 2, 1], ROWS, new Map())).toEqual([
      { unit: "", fields: [{ type: "E", field: "zip" }], values: ["60614"] },
      { unit: "", fields: [{ type: "E", field: "zip" }], values: ["60657"] },
    ]);
    // A row with no value in a field picks nothing.
    expect(pointStoreTuples({ unit: "", fields: [{ type: "E", field: "missing" }] }, [0], ROWS, new Map())).toEqual([]);
  });
});

describe("the rows a view's tags hold", () => {
  test("are the rows holding one of a tag's ids in its column, in row order, each once", () => {
    const rows = objectRows(ROWS);
    expect(rowsHeldBy([tag({ ids: [1003, 1001] })], rows)).toEqual([0, 2]);
    // Two tags on one view, by two columns.
    expect(rowsHeldBy([tag({ ids: [1003] }), tag({ name: "by_label", column: "label", ids: ["Bob", "Charlie"] })], rows)).toEqual([1, 2]);
  });

  test("match an id of the type the column holds", () => {
    expect(rowsHeldBy([tag({ ids: ["1003"] })], objectRows(ROWS))).toEqual([]);
  });

  test("are none for tags that hold no ids, or a count in their place", () => {
    const rows = objectRows(ROWS);
    expect(rowsHeldBy([tag({ ids: [] })], rows)).toEqual([]);
    expect(rowsHeldBy([tag({ count: 20000 })], rows)).toEqual([]);
    expect(rowsHeldBy([tag({ ids: [9999] })], rows)).toEqual([]);
  });

  test("are read from the tags every node holds on that view", () => {
    const nodes = [
      { id: "chart", data: {} },
      { id: "counter", data: { selections: [tag({ ids: [1001] }), tag({ name: "other", node: "map", ids: [5] })] } },
      { id: "reader", data: { selections: [tag({ name: "again", ids: [1002] })] } },
    ];
    expect(tagsOnView(nodes, "chart").map((t) => t.name)).toEqual(["picked", "again"]);
    expect(tagsOnView(nodes, "map").map((t) => t.name)).toEqual(["other"]);
    expect(tagsOnView(nodes, "nowhere")).toEqual([]);
  });
});
