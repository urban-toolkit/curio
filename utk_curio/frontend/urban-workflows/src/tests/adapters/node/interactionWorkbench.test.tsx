/**
 * The Interaction node's Edit view (#662, `LayerWorkbench`), linked to an
 * Autark map: the layers it finds on its input, by geometry; a new layer and its properties; a
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
let mockSources: any[] = [];
jest.mock("../../../utils/autkInput", () => ({
  readAutkInput: jest.fn(() => Promise.resolve({ frames: mockSources.map((s: any) => ({ name: s.named ? s.outputTableName : null })) })),
  autkSourcesFrom: jest.fn(() => ({ sources: mockSources })),
}));
jest.mock("../../../adapters/node/autkGrammarBehavior", () => ({
  useAutkGrammarBehavior: () => ({ applyGrammar: jest.fn().mockResolvedValue(undefined), contentComponent: <div data-testid="autark-map" /> }),
}));

import { useEditFeaturesBehavior } from "../../../adapters/node/editFeaturesBehavior";
import { editFeaturesCode, readEditFeaturesCode } from "../../../utils/editFeatures/editFeatures";

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

/**
 * The node only edits on an Autark map it feeds and is linked to (an
 * interaction edge between them): every test mounts it so.
 */
const LINKED = {
  nodes: [
    { id: "map", type: "curio.builtin/autk-grammar", data: { title: "Downtown Chicago layers" } },
  ],
  edges: [
    { source: NODE, target: "map", sourceHandle: "out", targetHandle: "in" },
    { source: "map", target: NODE, sourceHandle: "in/out", targetHandle: "in/out", type: "BIDIRECTIONAL_EDGE" },
  ],
};

/** The node on a canvas that keeps what it writes, its code holding no edits yet. */
function mountLive(canvas: { nodes?: any[]; edges?: any[] } = LINKED) {
  const updateDataNode = jest.fn();
  const first = { nodeId: NODE, input: INPUT, defaultCode: editFeaturesCode(undefined), code: editFeaturesCode(undefined) };
  function Canvas({ children }: { children: React.ReactNode }) {
    const [live, setLive] = React.useState<any>(first);
    const flow = {
      nodes: [{ id: NODE, type: "curio.builtin/edit-features", data: live }, ...(canvas.nodes ?? [])],
      edges: canvas.edges ?? [],
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
  // The edits the node's code holds now, as the node reads them.
  const settings = () => {
    const read = readEditFeaturesCode(updateDataNode.mock.calls[updateDataNode.mock.calls.length - 1]?.[1]?.code);
    return "problem" in read ? undefined : read.settings;
  };
  return { updateDataNode, settings, state };
}

beforeEach(() => {
  mockSources = [ROADS, BUILDINGS];
});

test("the Edit view lists the input's layers by the geometry of their features", async () => {
  mountLive();
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
  // The drawing is on the linked map: the node has no map of its own.
  fireEvent.click(screen.getByTestId("interaction-action-add"));
  expect(screen.queryByTestId("interaction-edit-map")).toBeNull();
});

test("fed by two data nodes, feeding an Autark map and linked to it, the node edits on the map and hands on both circles", async () => {
  // The data nodes feed the node, the node feeds the map, and an interaction
  // edge links the node and the map, as two Autark views are linked.
  mockSources = [{ ...ROADS, outputTableName: "input_0", named: false }, { ...BUILDINGS, outputTableName: "input_1", named: false }];
  const { state } = mountLive({
    nodes: [
      { id: "roads", type: "curio.builtin/data-loading", data: { title: "Roads" } },
      { id: "buildings", type: "curio.builtin/data-loading", data: { title: "Buildings" } },
      { id: "map", type: "curio.builtin/autk-grammar", data: { title: "Downtown Chicago layers" } },
    ],
    edges: [
      { source: "roads", target: NODE, sourceHandle: "out", targetHandle: "in_0" },
      { source: "buildings", target: NODE, sourceHandle: "out", targetHandle: "in_1" },
      { source: NODE, target: "map", sourceHandle: "out", targetHandle: "in" },
      { source: NODE, target: "map", sourceHandle: "in/out", targetHandle: "in/out", type: "BIDIRECTIONAL_EDGE" },
    ],
  });
  expect(await screen.findByTestId("interaction-connected")).toHaveTextContent("Linked to Downtown Chicago layers");
  // Each circle's layer goes by the node that feeds it.
  expect(await screen.findByTestId("interaction-layer-input_0")).toHaveTextContent("Roads");
  expect(screen.getByTestId("interaction-layer-input_1")).toHaveTextContent("Buildings");
  // The code hands the step both circles, and names their layers input_0, input_1.
  await waitFor(() => expect((state.setCode as jest.Mock).mock.calls.at(-1)?.[0]).toContain("curio_edit_features([input_0, input_1], [], by_input=True)"));
  // The drawing happens on the linked map, not on an edit map of the node's own.
  fireEvent.click(screen.getByTestId("interaction-layer-input_0"));
  fireEvent.click(screen.getByTestId("interaction-action-add"));
  expect(screen.queryByTestId("interaction-edit-map")).toBeNull();
});

test("a new layer is made with its geometry and properties, and the node's code makes it", async () => {
  const { settings, state } = mountLive();
  fireEvent.click(await screen.findByTestId("interaction-new-layer-open"));
  fireEvent.change(screen.getByTestId("interaction-new-layer-name"), { target: { value: "cooling_centers" } });
  fireEvent.click(screen.getByTestId("interaction-new-layer-Point"));
  fireEvent.click(screen.getByTestId("interaction-new-layer-create"));
  expect(settings()?.newLayers).toEqual([{ name: "cooling_centers", geometry: "Point", properties: [{ name: "name", type: "text", required: true }] }]);
  expect((state.setCode as jest.Mock).mock.calls.at(-1)[0]).toContain('new_layers=[{"name": "cooling_centers", "geometry": "Point"');
  // It is picked, ready to draw into.
  await waitFor(() => expect(screen.getByTestId("interaction-active-layer")).toHaveAttribute("data-layer", "cooling_centers"));
  fireEvent.click(screen.getByTestId("interaction-back"));
  fireEvent.click(screen.getByText("← All layers"));
  expect(screen.getByTestId("interaction-layer-cooling_centers")).toHaveTextContent("new layer · 0 points");
});

test("a property added to a layer is an add_column edit, and a second layer's edit names it and its id column", async () => {
  const { settings } = mountLive();
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
  // The property added is one of the layer's properties now.
  expect(screen.getByTestId("interaction-layer-table_osm_buildings")).toHaveTextContent("kind");
  fireEvent.click(screen.getByTestId("interaction-layer-table_osm_roads"));
  fireEvent.click(screen.getByTestId("interaction-action-property"));
  fireEvent.change(screen.getByTestId("interaction-property-name"), { target: { value: "surface" } });
  fireEvent.click(screen.getByTestId("interaction-property-add"));
  expect(settings()?.keys).toEqual({ table_osm_roads: "osm_id" });
  expect(settings()?.edits?.[1]).toEqual({ op: "add_column", layer: "table_osm_roads", column: "surface", value: null });
});

