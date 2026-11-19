/**
 * A selection tag that names a view of an Autark node of several views
 * ("Node · heights"): it reads that view's selection alone, over that view's
 * table, as a tag on the node reads the node's newest selection. The tag keeps
 * the view's id (`view`) beside the node's (`node`), in the dataflow as it is
 * saved (`normalizeSelections`, the twin of the backend's
 * `normalize_selections`), and a new selection in the node writes each of its
 * tags by what the tag reads: its view, and its column.
 */
// The views' list reads the flow's nodes, handed to it here.
jest.mock("../../providers/FlowProvider", () => ({ useFlowContext: () => ({}) }));

import { CURIO_UNIVERSAL_NODE_TYPE, NodeType, VisInteractionType } from "../../constants";
import { objectRows } from "../../utils/selectionMatch";
import { normalizeSelections, type SelectionTag } from "../../utils/references/selectionTags";
import { provideViewRows, readSelectionRows, recordViewSelection, resetViewSelections, selectionStateOf } from "../../utils/references/viewSelections";
import { selectionViewsOf } from "../../hook/useSelectionViews";
import { tagReadKey, viewStates, withViewStates } from "../../providers/flow/useSelectionTags";

const AUTARK = "curio.builtin/autk-grammar@1";
/** The map's table, `buildings`, and the plot's, `parks`. */
const ROWS: Record<string, Array<Record<string, unknown>>> = {
  buildings: [{ osm_id: 101 }, { osm_id: 102 }, { osm_id: 103 }],
  parks: [{ osm_id: 201 }, { osm_id: 202 }],
};
const pick = (layerRef: string, data: number[], priority: number) => ({
  type: VisInteractionType.POINT, data, priority, source: NodeType.AUTK_GRAMMAR, layerRef,
});
/** What a node of a map `city` and a plot `greens` sends after a pick on the map, then a brush on the plot. */
const SENT = { "autk_selection@city": pick("buildings", [2], 0), "autk_selection@greens": pick("parks", [0, 1], 1) };

beforeEach(() => {
  resetViewSelections();
  provideViewRows("views", (layer) => {
    const rows = ROWS[layer ?? "buildings"];
    return rows ? { rows: objectRows(rows), columns: ["osm_id"] } : null;
  });
});

describe("a tag naming a view, as the dataflow keeps it", () => {
  test("keeps the view's id beside the node's", () => {
    const raw = [
      { name: "greens", node: "views", view: "greens", column: "osm_id", ids: [201] },
      { name: "all", node: "views", column: "osm_id", ids: [] },
      { name: "blank", node: "views", view: "", column: "osm_id", ids: [] },
      { name: "odd", node: "views", view: 3, column: "osm_id", ids: [] },
    ];
    expect(normalizeSelections(raw)).toEqual([
      { name: "greens", node: "views", view: "greens", column: "osm_id", ids: [201] },
      { name: "all", node: "views", column: "osm_id", ids: [] },
      { name: "blank", node: "views", column: "osm_id", ids: [] },
      { name: "odd", node: "views", column: "osm_id", ids: [] },
    ]);
  });
});

describe("what a tag naming a view reads", () => {
  test("that view's select alone, over the view's table, though another view's is newer", async () => {
    expect(await selectionStateOf("views", "osm_id", SENT, "city")).toEqual({ ids: [103] });
    expect(await selectionStateOf("views", "osm_id", SENT, "greens")).toEqual({ ids: [201, 202] });
    // A tag on the node reads its newest selection, as before.
    expect(await selectionStateOf("views", "osm_id", SENT)).toEqual({ ids: [201, 202] });
  });

  test("nothing selected, while that view holds no select", async () => {
    expect(await selectionStateOf("views", "osm_id", { "autk_selection@greens": SENT["autk_selection@greens"] }, "city"))
      .toEqual({ ids: [] });
  });

  test("its chip's preview, the rows of the view's table the tag holds", async () => {
    recordViewSelection("views", SENT);
    const tag: SelectionTag = { name: "city", node: "views", view: "city", column: "osm_id", ids: [103] };
    expect(await readSelectionRows(tag)).toEqual({ columns: ["osm_id"], rows: [{ osm_id: 103 }] });
  });
});

describe("the views a tag can name", () => {
  test("a node of several views is offered whole, then each of its views with an id, named after it", () => {
    const code = JSON.stringify({
      map: [{ id: "city", layerRefs: [{ dataRef: "buildings", isPick: true }] }, { layerRefs: [{ dataRef: "roads" }] }],
      plot: { id: "greens", dataRef: "parks", mark: "bar" },
    });
    const views = selectionViewsOf([
      { id: "views", type: CURIO_UNIVERSAL_NODE_TYPE, data: { nodeType: AUTARK, defaultCode: code } },
      { id: "T", type: CURIO_UNIVERSAL_NODE_TYPE, data: { nodeType: "curio.builtin/python-computation@1" } },
    ], "T");

    expect(views.map((v) => [v.id, v.view ?? null, v.layer ?? null])).toEqual([
      ["views", null, null],
      ["views", "city", "buildings"],
      ["views", "greens", "parks"],
    ]);
    expect(views[1].label).toBe(`${views[0].label} · city`);
    expect(views[2].label).toBe(`${views[0].label} · greens`);
  });

  test("a node of one view is offered whole alone", () => {
    const code = JSON.stringify({ map: { id: "city", layerRefs: [{ dataRef: "buildings" }] } });
    const views = selectionViewsOf([{ id: "views", type: CURIO_UNIVERSAL_NODE_TYPE, data: { nodeType: AUTARK, defaultCode: code } }], "T");
    expect(views.map((v) => [v.id, v.view ?? null])).toEqual([["views", null]]);
  });
});

describe("a new selection in the node writes each tag by what it reads", () => {
  const tags = [
    { name: "all", node: "views", column: "osm_id", ids: [] },
    { name: "city", node: "views", view: "city", column: "osm_id", ids: [] },
    { name: "greens", node: "views", view: "greens", column: "osm_id", ids: [] },
  ];

  test("the node's tag its newest selection, and each view's tag its view's", async () => {
    const states = await viewStates([{ id: "T", data: { selections: tags } }], "views", SENT);
    expect(states.get(tagReadKey(undefined, "osm_id"))).toEqual({ ids: [201, 202] });
    expect(states.get(tagReadKey("city", "osm_id"))).toEqual({ ids: [103] });
    expect(states.get(tagReadKey("greens", "osm_id"))).toEqual({ ids: [201, 202] });

    expect(withViewStates(tags, "views", states)).toEqual([
      { name: "all", node: "views", column: "osm_id", ids: [201, 202] },
      { name: "city", node: "views", view: "city", column: "osm_id", ids: [103] },
      { name: "greens", node: "views", view: "greens", column: "osm_id", ids: [201, 202] },
    ]);
  });
});
