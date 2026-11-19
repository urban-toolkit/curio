/**
 * The selects an Autark node sends (utils/autkSelects): a node of one view
 * under `autk_selection`, a node of several one per view, under
 * `autk_selection@<id>`, else `autk_selection#<place>`, as a Vega-Lite chart
 * sends one per param. Every reader reads them through the module: the layer
 * a selection names is its newest select's, and a source's selects are told
 * apart by the table each was made on. The module is loaded in each test, so
 * a checkout without it fails each test on its own.
 */
import { VisInteractionType } from "../../constants";
import { selectionLayer } from "../../utils/references/selectionTags";
import { selectedIdsIn } from "../../utils/editFeatures/mapEditSelection";

const selects = () =>
  require("../../utils/autkSelects") as {
    AUTK_SELECTION: string;
    autkSelectionKey: (view?: string | number | null) => string;
    isAutkSelectionKey: (key: string) => boolean;
    autkSelectionView: (key: string) => string | null;
    autkSelects: (details: unknown) => Array<{ key: string; view: string | null; select: any }>;
    newestAutkSelect: (details: unknown) => any;
    selectsOnLayer: <T>(details: T, layer: string | undefined) => T;
    byAutkLayer: (selections: any[]) => Array<{ layer: string | undefined; selection: any }>;
    selectsOfView: (details: unknown, view: string) => Record<string, any>;
  };

const pick = (layerRef: string, data: unknown[], priority: number) =>
  ({ type: VisInteractionType.POINT, data, priority, source: "AUTK_GRAMMAR", layerRef });

/** What a node of a map, `city`, and a plot without an id sends after a brush on the plot. */
const SEVERAL = {
  "autk_selection@city": pick("buildings", [0, 2], 0),
  "autk_selection#1": pick("parks", [1], 1),
};

describe("the key each view's select is sent under", () => {
  test("a node's one view keeps autk_selection; a view of several adds its id or its place", () => {
    expect(selects().AUTK_SELECTION).toBe("autk_selection");
    expect(selects().autkSelectionKey()).toBe("autk_selection");
    expect(selects().autkSelectionKey(null)).toBe("autk_selection");
    expect(selects().autkSelectionKey("heights")).toBe("autk_selection@heights");
    expect(selects().autkSelectionKey(1)).toBe("autk_selection#1");
  });

  test("a view whose id reads as a place and the view without an id at that place have two keys", () => {
    expect(selects().autkSelectionKey("1")).toBe("autk_selection@1");
    expect(selects().autkSelectionKey(1)).toBe("autk_selection#1");
    expect(selects().autkSelectionView("autk_selection@1")).toBe("1");
    expect(selects().autkSelectionView("autk_selection#1")).toBeNull();
  });

  test("a key names the view it was sent for, and no other key is an Autark select's", () => {
    expect(selects().autkSelectionView("autk_selection")).toBeNull();
    expect(selects().autkSelectionView("autk_selection@heights")).toBe("heights");
    // A view without an id is named by no id.
    expect(selects().autkSelectionView("autk_selection#0")).toBeNull();
    for (const key of ["autk_selection", "autk_selection@heights", "autk_selection@0", "autk_selection#0", "autk_selection#12"]) {
      expect(selects().isAutkSelectionKey(key)).toBe(true);
    }
    for (const key of ["autk_selection@", "autk_selection#", "autk_selection#x", "autk_selection#1a", "autk_selectionX", "brush", "pick"]) {
      expect(selects().isAutkSelectionKey(key)).toBe(false);
    }
  });
});

describe("reading the selects", () => {
  test("every Autark select of a selection is listed with its view, and a Vega param is not", () => {
    expect(selects().autkSelects(SEVERAL).map(({ key, view }) => [key, view])).toEqual([
      ["autk_selection@city", "city"],
      ["autk_selection#1", null],
    ]);
    expect(selects().autkSelects({ brush: pick("x", [1], 1) })).toEqual([]);
    expect(selects().autkSelects(null)).toEqual([]);
  });

  test("the selection a reader takes is the newest select's, else the first that holds one", () => {
    expect(selects().newestAutkSelect(SEVERAL)).toBe(SEVERAL["autk_selection#1"]);
    const settled = { "autk_selection@a": pick("roads", [], 0), "autk_selection@b": pick("parks", [3], 0) };
    expect(selects().newestAutkSelect(settled)).toBe(settled["autk_selection@b"]);
    expect(selectionLayer(SEVERAL)).toBe("parks");
    expect(selectionLayer({ autk_selection: pick("roads", [0], 1) })).toBe("roads");
    expect(selectionLayer({ brush: pick("roads", [0], 1) })).toBeUndefined();
  });

  test("the selects made on one table are told apart from the others, the newest of them at priority 1", () => {
    // The map's select is the buildings' selection, though the plot's came after it.
    expect(selects().selectsOnLayer(SEVERAL, "buildings")).toEqual({
      "autk_selection@city": { ...SEVERAL["autk_selection@city"], priority: 1 },
    });
    expect(selects().selectsOnLayer(SEVERAL, "parks")).toEqual({ "autk_selection#1": SEVERAL["autk_selection#1"] });
    // Two views of one table: the one sent at priority 1 is newest, else the last sent.
    const twoOfOne = { "autk_selection@a": pick("roads", [0], 0), "autk_selection@b": pick("roads", [1], 0) };
    expect(selects().selectsOnLayer(twoOfOne, "roads")).toEqual({
      "autk_selection@a": pick("roads", [0], 0),
      "autk_selection@b": pick("roads", [1], 1),
    });
    expect(selects().selectsOnLayer(SEVERAL, "trees")).toEqual({});
    const vega = { brush: pick("x", [1], 1) };
    expect(selects().selectsOnLayer(vega, undefined)).toBe(vega);
  });

  test("a source's selects on two tables are two selections, each with its table; a Vega chart's is one", () => {
    const vega = { nodeId: "chart", details: { brush: pick("x", [1], 1) }, priority: 0 };
    const autark = { nodeId: "views", details: SEVERAL, priority: 1 };
    expect(selects().byAutkLayer([vega, autark])).toEqual([
      { layer: undefined, selection: vega },
      { layer: "buildings", selection: { ...autark, details: { "autk_selection@city": { ...SEVERAL["autk_selection@city"], priority: 1 } } } },
      { layer: "parks", selection: { ...autark, details: { "autk_selection#1": SEVERAL["autk_selection#1"] } } },
    ]);
  });
});

// An interaction edge on a view's dot (`in/out@<id>`) carries that view's
// selection alone (providers/flow/interactionRoutes).
describe("the selects one view sent", () => {
  test("of a node of several views, the view's own select, at priority 1 though another view's is newer", () => {
    expect(selects().selectsOfView(SEVERAL, "city")).toEqual({
      "autk_selection@city": { ...SEVERAL["autk_selection@city"], priority: 1 },
    });
    // Its own select, newest or not, unchanged when it is the newest.
    const newest = { "autk_selection@city": pick("buildings", [2], 1), "autk_selection@roads": pick("roads", [0], 0) };
    expect(selects().selectsOfView(newest, "city")).toEqual({ "autk_selection@city": newest["autk_selection@city"] });
  });

  test("the view whose id reads as a place, its own select, never that of the view without an id at that place", () => {
    const both = { "autk_selection@1": pick("buildings", [0], 0), "autk_selection#1": pick("parks", [1], 1) };
    expect(selects().selectsOfView(both, "1")).toEqual({ "autk_selection@1": { ...both["autk_selection@1"], priority: 1 } });
    expect(selects().selectsOfView({ "autk_selection#1": pick("parks", [1], 1) }, "1")).toEqual({});
  });

  test("none of a view that sent none, nor of another node's selects", () => {
    expect(selects().selectsOfView(SEVERAL, "parks")).toEqual({});
    // Nor of a view the node does not have.
    expect(selects().selectsOfView(SEVERAL, "heights")).toEqual({});
    expect(selects().selectsOfView({ brush: pick("x", [1], 1) }, "city")).toEqual({});
    expect(selects().selectsOfView(undefined, "city")).toEqual({});
  });

  test("a node of one view sends its one view's select, which any view's dot carries", () => {
    const one = { autk_selection: pick("buildings", [1], 1) };
    expect(selects().selectsOfView(one, "city")).toEqual(one);
  });
});

describe("a Map Editor node takes the selects of the layer it edits alone", () => {
  const features = [0, 1, 2].map((n) => ({ id: `b${n}`, properties: { n } }));

  test("of a node of several views, it reads the selects made on its layer, whatever the newest", () => {
    const incoming = [{ nodeId: "views", details: SEVERAL, priority: 1 }];
    // The buildings layer it edits: the map's select of rows 0 and 2.
    expect(selectedIdsIn(incoming, (_node, layer) => layer === "buildings", features)).toEqual(["b0", "b2"]);
    // Of a layer no select names, none.
    expect(selectedIdsIn(incoming, (_node, layer) => layer === "trees", features)).toBeNull();
  });
});
