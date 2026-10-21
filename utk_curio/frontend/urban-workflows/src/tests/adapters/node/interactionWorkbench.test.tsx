/**
 * The Interaction node's Edit view (#662, `LayerWorkbench`): the layers it
 * finds on its input, by geometry; a new layer and its properties; a
 * property added to a layer; and an edit on a layer other than the node's,
 * which names that layer and its id column.
 */
import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { NodeBehaviorData, UseNodeStateReturn } from "../../../registry/types";

const mockFlowContext = React.createContext<Record<string, any>>({});
jest.mock("../../../providers/FlowProvider", () => ({
  useFlowContext: () => require("react").useContext(mockFlowContext),
}));
jest.mock("../../../adapters/node/compareScenariosBehavior", () => ({
  failureLine: (content: unknown) => String(content ?? ""),
}));
let mockSources: any[] = [];
jest.mock("../../../utils/autkInput", () => ({
  readAutkInput: jest.fn(() => Promise.resolve({ frames: mockSources.map((s: any) => ({ name: s.named ? s.outputTableName : null })) })),
  autkSourcesFrom: jest.fn(() => ({ sources: mockSources })),
}));
jest.mock("../../../adapters/node/autkGrammarBehavior", () => ({
  useAutkGrammarBehavior: () => ({ applyGrammar: jest.fn().mockResolvedValue(undefined), contentComponent: <div data-testid="autark-map" /> }),
}));

import { useEditFeaturesBehavior } from "../../../adapters/node/editFeaturesBehavior";
import { editFeaturesCode } from "../../../utils/editFeatures/editFeatures";

const NODE = "edit-1";
const INPUT = { path: "art_layers", dataType: "dict" };
const square = { type: "Polygon", coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] };
const BUILDINGS = {
  outputTableName: "table_osm_buildings",
  named: true,
  layerType: "buildings",
  geojsonObject: {
    type: "FeatureCollection",
    features: [
      { type: "Feature", geometry: square, properties: { building_id: 119, height: 240 } },
      { type: "Feature", geometry: square, properties: { building_id: 136, height: 60 } },
    ],
  },
};
const ROADS = {
  outputTableName: "table_osm_roads",
  named: true,
  layerType: "roads",
  geojsonObject: {
    type: "FeatureCollection",
    features: [
      { type: "Feature", geometry: { type: "LineString", coordinates: [[0, 2], [4, 2]] }, properties: { osm_id: 7, highway: "primary" } },
      { type: "Feature", geometry: { type: "LineString", coordinates: [[0, 3], [4, 3]] }, properties: { osm_id: 8, highway: "primary" } },
    ],
  },
};

function nodeState(): UseNodeStateReturn {
  return { output: { code: "", content: "" }, setOutput: jest.fn(), code: "", setCode: jest.fn() } as unknown as UseNodeStateReturn;
}

/** The node on a canvas that keeps what it writes. */
function mountLive(editFeatures: unknown) {
  const updateDataNode = jest.fn();
  const first = { nodeId: NODE, input: INPUT, editFeatures, defaultCode: editFeaturesCode(undefined), code: editFeaturesCode(undefined) };
  function Canvas({ children }: { children: React.ReactNode }) {
    const [live, setLive] = React.useState<any>(first);
    const flow = {
      nodes: [{ id: NODE, data: live }],
      edges: [],
      markNodeStale: jest.fn(),
      updateDataNode: (id: string, data: any) => {
        updateDataNode(id, data);
        setLive(data);
      },
    };
    return <mockFlowContext.Provider value={flow}>{children}</mockFlowContext.Provider>;
  }
  const state = nodeState();
  function Host() {
    const live = React.useContext(mockFlowContext).nodes[0].data;
    const behavior = useEditFeaturesBehavior(live as unknown as NodeBehaviorData, state);
    return <>{behavior.contentComponent}</>;
  }
  render(
    <Canvas>
      <Host />
    </Canvas>,
  );
  const settings = () => updateDataNode.mock.calls[updateDataNode.mock.calls.length - 1]?.[1]?.editFeatures;
  return { updateDataNode, settings, state };
}

beforeEach(() => {
  mockSources = [ROADS, BUILDINGS];
});

test("the Edit view lists the input's layers by the geometry of their features", async () => {
  mountLive(undefined);
  const list = await screen.findByTestId("interaction-layers");
  expect(list).toHaveTextContent("Found 2 layers in 2 geometry types. Pick a layer to work on:");
  expect(within(list).getByText("Lines · LineString")).toBeInTheDocument();
  expect(within(list).getByText("Areas · Polygon")).toBeInTheDocument();
  expect(screen.getByTestId("interaction-layer-table_osm_roads")).toHaveTextContent("table_osm_roads · 2 lines");
  expect(screen.getByTestId("interaction-layer-table_osm_roads")).toHaveTextContent("properties: highway");
  expect(screen.getByTestId("interaction-layer-table_osm_buildings")).toHaveTextContent("table_osm_buildings · 2 areas");
  fireEvent.click(screen.getByTestId("interaction-layer-table_osm_roads"));
  const active = screen.getByTestId("interaction-active-layer");
  expect(active).toHaveAttribute("data-kind", "lines");
  expect(active).toHaveTextContent("What do you want to do?");
  expect(screen.getByTestId("interaction-action-add")).toHaveTextContent("+ Add lines");
  expect(screen.getByTestId("interaction-action-remove")).toHaveTextContent("Remove lines");
  // Plugged into no map, the drawing is on the node's own edit map.
  fireEvent.click(screen.getByTestId("interaction-action-add"));
  expect(await screen.findByTestId("interaction-edit-map")).toHaveAttribute("data-edit-mode", "draw");
});

test("a new layer is made with its geometry and properties, and the node's code makes it", async () => {
  const { settings, state } = mountLive(undefined);
  fireEvent.click(await screen.findByTestId("interaction-new-layer-open"));
  fireEvent.change(screen.getByTestId("interaction-new-layer-name"), { target: { value: "cooling_centers" } });
  fireEvent.click(screen.getByTestId("interaction-new-layer-Point"));
  fireEvent.click(screen.getByTestId("interaction-new-layer-create"));
  expect(settings().newLayers).toEqual([{ name: "cooling_centers", geometry: "Point", properties: [{ name: "name", type: "text", required: true }] }]);
  expect((state.setCode as jest.Mock).mock.calls.at(-1)[0]).toContain('new_layers=[{"name": "cooling_centers", "geometry": "Point"');
  // It is picked, ready to draw into.
  await waitFor(() => expect(screen.getByTestId("interaction-active-layer")).toHaveAttribute("data-layer", "cooling_centers"));
  fireEvent.click(screen.getByTestId("interaction-back"));
  fireEvent.click(screen.getByText("← All layers"));
  expect(screen.getByTestId("interaction-layer-cooling_centers")).toHaveTextContent("new layer · 0 points");
});

test("a property added to a layer is an add_column edit, and a second layer's edit names it and its id column", async () => {
  const { settings } = mountLive(undefined);
  fireEvent.click(await screen.findByTestId("interaction-layer-table_osm_buildings"));
  fireEvent.click(screen.getByTestId("interaction-action-property"));
  fireEvent.change(screen.getByTestId("interaction-property-name"), { target: { value: "kind" } });
  fireEvent.change(screen.getByTestId("interaction-property-value"), { target: { value: "office" } });
  fireEvent.click(screen.getByTestId("interaction-property-add"));
  expect(settings()).toEqual({
    layer: "table_osm_buildings",
    key: "building_id",
    edits: [{ op: "add_column", column: "kind", value: "office" }],
  });
  fireEvent.click(screen.getByText("← All layers"));
  fireEvent.click(screen.getByTestId("interaction-layer-table_osm_roads"));
  fireEvent.click(screen.getByTestId("interaction-action-property"));
  fireEvent.change(screen.getByTestId("interaction-property-name"), { target: { value: "surface" } });
  fireEvent.click(screen.getByTestId("interaction-property-add"));
  expect(settings().keys).toEqual({ table_osm_roads: "osm_id" });
  expect(settings().edits[1]).toEqual({ op: "add_column", layer: "table_osm_roads", column: "surface", value: null });
});

test("a lasso picks every road it encloses, and Edit sets one value on all of them", async () => {
  (Element.prototype as any).setPointerCapture ??= () => undefined;
  const { settings } = mountLive(undefined);
  fireEvent.click(await screen.findByTestId("interaction-layer-table_osm_roads"));
  fireEvent.click(screen.getByTestId("interaction-action-edit"));
  fireEvent.click(screen.getByTestId("interaction-lasso"));
  const map = await screen.findByTestId("interaction-edit-map");
  // An outline far around the map's whole view.
  const corners = [[-5000, -5000], [5000, -5000], [5000, 5000], [-5000, 5000]];
  fireEvent.pointerDown(map, { button: 0, clientX: corners[0][0], clientY: corners[0][1], pointerId: 1 });
  for (const [x, y] of corners.slice(1)) fireEvent.pointerMove(map, { clientX: x, clientY: y, pointerId: 1 });
  fireEvent.pointerUp(map, { clientX: corners[3][0], clientY: corners[3][1], pointerId: 1 });
  const many = await screen.findByTestId("interaction-edit-many");
  expect(many).toHaveTextContent("2 lines picked.");
  fireEvent.change(screen.getByTestId("interaction-rule-set-value"), { target: { value: "primary" } });
  fireEvent.click(screen.getByTestId("interaction-many-apply"));
  expect(settings().edits).toEqual([{ op: "set", ids: [7, 8], column: "highway", value: "primary" }]);
});
