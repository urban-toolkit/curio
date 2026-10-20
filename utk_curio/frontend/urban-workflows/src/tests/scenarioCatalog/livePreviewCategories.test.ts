/**
 * A preview built in the browser gives each node the category of its
 * registered descriptor, as the server gives a saved project's preview the
 * category its template declares: the Scenario Catalog drawer's In project tab
 * draws the canvas's own nodes (`liveGraphPreview`), and each version of a
 * dataflow is drawn from the preview recorded with it (`TrillGenerator`). A
 * node whose type nothing registered provides gets none, and is drawn grey.
 */
import { CURIO_UNIVERSAL_NODE_TYPE } from "../../constants";
import { liveGraphPreview } from "../../components/scenarios/catalog/inProjectRows";
import { TrillGenerator } from "../../TrillGenerator";
import { clearCategoryDescriptors, registerCategoryDescriptor } from "../_support/categoryDescriptors";

beforeAll(() => {
  registerCategoryDescriptor("acme.hydro/gauge@1", "data");
  registerCategoryDescriptor("acme.hydro/gauge@2", "vis_simple");
  registerCategoryDescriptor("curio.scout/donuts@1", "vis_grammar");
  registerCategoryDescriptor("acme.tools/route@1", "flow");
});

afterAll(() => clearCategoryDescriptors());

/** A node as the canvas holds it: React Flow's type is the one universal
 *  kind, and the node's own type is `data.nodeType`. */
const canvasNode = (id: string, nodeType: string | undefined, x = 0) => ({
  id,
  type: CURIO_UNIVERSAL_NODE_TYPE,
  position: { x, y: 10 },
  width: 320,
  height: 200,
  data: { nodeId: id, ...(nodeType !== undefined ? { nodeType } : {}) },
});

const CANVAS = [
  canvasNode("gauge", "acme.hydro/gauge@1"),
  // No major: the highest one registered, as the canvas resolves the node.
  canvasNode("latest", "acme.hydro/gauge", 300),
  canvasNode("donuts", "curio.scout/donuts@1", 600),
  canvasNode("route", "acme.tools/route@1", 900),
  canvasNode("gone", "acme.gone/gauge@1", 1200),
  canvasNode("legacy", "VIS_VEGA", 1500),
];

const EXPECTED = [
  ["gauge", "data"],
  ["latest", "vis_simple"],
  ["donuts", "vis_grammar"],
  ["route", "flow"],
  ["gone", null],
  ["legacy", null],
];

const categories = (preview: { nodes: Array<{ id: string; category?: string | null }> }) =>
  preview.nodes.map((n) => [n.id, n.category]);

describe("the In project tab's preview", () => {
  test("gives each canvas node its registered descriptor's category", () => {
    const preview = liveGraphPreview(CANVAS, [{ source: "gauge", target: "donuts" }]);

    expect(categories(preview)).toEqual(EXPECTED);
    expect(preview.edges).toEqual([{ source: "gauge", target: "donuts" }]);
  });

  test("keeps each node's type and box", () => {
    const [first] = liveGraphPreview(CANVAS, []).nodes;

    expect(first).toEqual({
      id: "gauge", type: "acme.hydro/gauge@1", category: "data", x: 0, y: 10, w: 320, h: 200,
    });
  });

  test("gives a node with no type of its own none", () => {
    const preview = liveGraphPreview([canvasNode("bare", undefined)], []);

    expect(preview.nodes).toEqual([
      { id: "bare", type: CURIO_UNIVERSAL_NODE_TYPE, category: null, x: 0, y: 10, w: 320, h: 200 },
    ]);
  });
});

describe("a dataflow version's preview", () => {
  beforeEach(() => TrillGenerator.reset());

  test("gives each node its registered descriptor's category", () => {
    TrillGenerator.addNewVersionProvenance(CANVAS, [], "Gauges", "", "Node added");

    const version = TrillGenerator.provenanceJSON.nodes.at(-1);
    expect(categories(version.preview)).toEqual(EXPECTED);
  });

  test("is recorded with the version, so a saved dataflow keeps it", () => {
    TrillGenerator.addNewVersionProvenance(CANVAS.slice(0, 1), [], "Gauges", "", "Node added");

    const saved = TrillGenerator.getSerializableDataflowProvenance();
    expect(saved.graph.nodes.at(-1).preview.nodes).toEqual([
      { id: "gauge", type: "acme.hydro/gauge@1", category: "data", x: 0, y: 10, w: null, h: null },
    ]);
  });
});
