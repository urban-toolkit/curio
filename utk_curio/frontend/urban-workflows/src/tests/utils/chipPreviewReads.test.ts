/**
 * What a selection chip's and a Parameter chip's previews read: the rows a
 * selection tag's ids pick in its view (viewRowsOf, rowsHeldBy), once the view
 * has drawn, and the Parameter node a shared tag names, with how many nodes
 * read it.
 */
import { parameterPreviewOf } from "../../utils/references/sharedParameters";
import { provideViewRows, readSelectionRows, resetViewSelections } from "../../utils/references/viewSelections";

const ROWS = [
  { zip: "60601", count: 12 },
  { zip: "60602", count: 7 },
  { zip: "60610", count: 1 },
  { zip: "60603", count: 3 },
  { zip: "60604", count: 9 },
];

const held = () => ({
  rows: { count: ROWS.length, value: (index: number, column: string) => (ROWS[index] as any)[column] },
  columns: ["zip", "count"],
});

describe("readSelectionRows", () => {
  afterEach(resetViewSelections);

  test("the first 3 rows the tag's ids pick, in the view's row order, with its columns", async () => {
    provideViewRows("zip-bars", held);
    const tag = { name: "picked", node: "zip-bars", column: "zip", ids: ["60603", "60601", "60602", "60604"] };
    expect(await readSelectionRows(tag)).toEqual({
      columns: ["zip", "count"],
      rows: [ROWS[0], ROWS[1], ROWS[3]],
    });
  });

  test("a view that answers later is waited for", async () => {
    provideViewRows("zip-bars", async () => held());
    const tag = { name: "picked", node: "zip-bars", column: "zip", ids: ["60610"] };
    expect(await readSelectionRows(tag)).toEqual({ columns: ["zip", "count"], rows: [ROWS[2]] });
  });

  test("null while the view has not drawn", async () => {
    expect(await readSelectionRows({ name: "picked", node: "zip-bars", column: "zip", ids: ["60601"] })).toBeNull();
  });

  test("a tag that holds a count in place of its ids picks no row", async () => {
    provideViewRows("zip-bars", held);
    expect(await readSelectionRows({ name: "picked", node: "zip-bars", column: "zip", count: 12000 })).toEqual({
      columns: ["zip", "count"],
      rows: [],
    });
  });
});

describe("parameterPreviewOf", () => {
  // Chicago Loop's Season, read by both shadow models.
  const nodes = [
    {
      id: "season",
      type: "curio.builtin/parameter",
      data: { title: "Season", widgets: [{ name: "season", type: "choice", default: "summer", options: { choices: ["spring", "summer", "winter"] } }] },
    },
    { id: "existing-shadow", type: "model.scout.deep-umbra/accumulated-shadow", data: { code: "accumulated_shadow(input_0, season=[!! @season !!])" } },
    { id: "towers-shadow", type: "model.scout.deep-umbra/accumulated-shadow", data: { code: "accumulated_shadow(input_0, season=[!! @season !!])" } },
    { id: "chart", type: "curio.scout/bars", data: { code: "{}" } },
  ];

  test("its node's title, and how many nodes read it", () => {
    expect(parameterPreviewOf(nodes, "season")).toEqual({ node: "Season", readers: 2 });
  });

  test("a name no Parameter node holds has none", () => {
    expect(parameterPreviewOf(nodes, "hour")).toBeNull();
  });
});
