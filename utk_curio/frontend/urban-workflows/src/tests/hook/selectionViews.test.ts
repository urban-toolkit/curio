/**
 * The views a selection tag can read (`selectionViewsOf`): Vega-Lite charts
 * and Autark nodes. A package chart that draws with the Vega-Lite grammar (a
 * Scout node) draws with the Vega-Lite node's behavior, whose view
 * hands its selection on, so it is one of them too.
 */
jest.mock("../../providers/FlowProvider", () => ({ useFlowContext: () => ({}) }));

import { NodeType } from "../../constants";
import { selectionViewsOf } from "../../hook/useSelectionViews";
import { VEGA_LITE_TEMPLATE, clearVegaLiteTemplate, registerVegaLiteTemplate } from "../_support/vegaLiteTemplate";

function node(id: string, nodeType: string) {
  return { id, type: "__curioUniversalNode", data: { nodeId: id, nodeType } } as any;
}

beforeEach(() => registerVegaLiteTemplate());
afterEach(() => clearVegaLiteTemplate());

test("a package chart that draws with Vega-Lite is a view, as the Vega-Lite node is", () => {
  const nodes = [
    node("tags", NodeType.COMPUTATION_ANALYSIS),
    node("chart", NodeType.VIS_VEGA),
    node("donuts", VEGA_LITE_TEMPLATE),
    node("plain", "curio.scout/donuts"),
    node("map", NodeType.AUTK_GRAMMAR),
    node("heatmap", "acme.tools/heatmap@1"),
  ];

  expect(selectionViewsOf(nodes, "tags").map((view) => view.id)).toEqual(["chart", "donuts", "plain", "map"]);
});
