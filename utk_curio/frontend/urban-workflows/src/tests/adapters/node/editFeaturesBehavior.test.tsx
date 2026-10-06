/**
 * The Edit Features node (#662) on the canvas: its input drawn by the Autark
 * node's map code with the layer to edit pickable, a pick adding the picked
 * features' ids to its list, Remove turning them into an edit that is written
 * with the code it makes, and a layer with no column that identifies its
 * features refused.
 */
import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { NodeBehaviorData, UseNodeStateReturn } from "../../../registry/types";
import { VisInteractionType } from "../../../constants";

const mockFlowContext = React.createContext<Record<string, any>>({});
jest.mock("../../../providers/FlowProvider", () => ({
  useFlowContext: () => require("react").useContext(mockFlowContext),
}));

// Only what a failed run says, from the Compare Scenarios node.
jest.mock("../../../adapters/node/compareScenariosBehavior", () => ({
  failureLine: (content: unknown) => String(content ?? ""),
}));

// The input, as the Autark map reads it: its layers by table name.
let mockSources: any[] = [];
jest.mock("../../../utils/autkInput", () => ({
  readAutkInput: jest.fn(() => Promise.resolve({ frames: mockSources.map((s: any) => ({ name: s.named ? s.outputTableName : null })) })),
  autkSourcesFrom: jest.fn(() => ({ sources: mockSources })),
}));

// The Autark node's map code, as the node's map calls it.
const mockApply = jest.fn().mockResolvedValue(undefined);
let mockMapData: any = null;
jest.mock("../../../adapters/node/autkGrammarBehavior", () => ({
  useAutkGrammarBehavior: (data: any) => {
    mockMapData = data;
    return { applyGrammar: mockApply, contentComponent: <div data-testid="autark-map" /> };
  },
}));

import { useEditFeaturesBehavior } from "../../../adapters/node/editFeaturesBehavior";
import { editFeaturesCode } from "../../../utils/editFeatures/editFeatures";

const NODE = "edit-1";
const INPUT = { path: "art_layers", dataType: "dict" };

function feature(properties: Record<string, unknown>) {
  return { type: "Feature", geometry: { type: "Polygon", coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] }, properties };
}

/** Autark's buildings: a building's parts share its building_id. */
const BUILDINGS = {
  outputTableName: "table_osm_buildings",
  named: true,
  layerType: "buildings",
  geojsonObject: {
    type: "FeatureCollection",
    features: [feature({ building_id: 119, height: 240 }), feature({ building_id: 119, height: 60 }), feature({ building_id: 136, height: 60 })],
  },
};
const ROADS = {
  outputTableName: "table_osm_roads",
  named: true,
  layerType: "roads",
  geojsonObject: { type: "FeatureCollection", features: [feature({ highway: "primary" }), feature({ highway: "primary" })] },
};

function nodeState(output = { code: "", content: "" }): UseNodeStateReturn {
  return { output, setOutput: jest.fn(), code: "", setCode: jest.fn() } as unknown as UseNodeStateReturn;
}

function mount(editFeatures: unknown, state = nodeState()) {
  const updateDataNode = jest.fn();
  const markNodeStale = jest.fn();
  const live = { nodeId: NODE, input: INPUT, editFeatures, defaultCode: editFeaturesCode(undefined), code: editFeaturesCode(undefined) };
  const flow = { nodes: [{ id: NODE, data: live }], edges: [], updateDataNode, markNodeStale };
  function Host() {
    const behavior = useEditFeaturesBehavior(live as unknown as NodeBehaviorData, state);
    return <>{behavior.contentComponent}</>;
  }
  const view = render(
    <mockFlowContext.Provider value={flow}>
      <Host />
    </mockFlowContext.Provider>,
  );
  return { ...view, updateDataNode, markNodeStale, state };
}

/** A pick on the map, as an Autark node reports it: the input rows it names. */
function pick(rows: number[]) {
  act(() => {
    mockMapData.interactionsCallback({
      autk_selection: { type: VisInteractionType.POINT, data: rows, priority: 1, layerRef: "table_osm_buildings" },
    }, NODE);
  });
}

beforeEach(() => {
  mockSources = [ROADS, BUILDINGS];
  mockMapData = null;
  mockApply.mockClear();
});

test("the map draws the input with the layer to edit pickable, on top", async () => {
  mount({ key: "building_id", layer: "table_osm_buildings" });
  await screen.findByTestId("autark-map");
  await waitFor(() => expect(mockApply).toHaveBeenCalled());
  const doc = JSON.parse(mockApply.mock.calls[mockApply.mock.calls.length - 1][0]);
  expect(doc.map.layerRefs).toEqual([{ dataRef: "table_osm_roads" }, { dataRef: "table_osm_buildings", isPick: true }]);
  expect(mockMapData.input).toBe(INPUT);
  expect(screen.getByRole("combobox", { name: "Id" })).toHaveValue("building_id");
  expect(screen.getByRole("combobox", { name: "Layer" })).toHaveValue("table_osm_buildings");
  expect(document.querySelector("[data-edit-building-note]")?.textContent).toMatch(/applies to the whole building/);
});

test("each pick adds the picked features' ids to the list, and Remove makes them an edit with its code", async () => {
  const { updateDataNode, markNodeStale, state } = mount(
    { key: "building_id", layer: "table_osm_buildings" },
    nodeState({ code: "success", content: "Saved to file: art_out" }),
  );
  await screen.findByTestId("autark-map");
  const picked = () => document.querySelector("[data-edit-picked]")!;
  expect(picked().getAttribute("data-edit-picked")).toBe("");
  // Both parts of building 119: one id.
  pick([0, 1]);
  expect(picked().textContent).toBe("Picked: building_id 119");
  pick([2]);
  pick([1]);
  expect(picked().getAttribute("data-edit-picked")).toBe("119 136");
  // A click on nothing picks nothing and keeps the list.
  pick([]);
  expect(picked().getAttribute("data-edit-picked")).toBe("119 136");

  fireEvent.click(screen.getByTestId("edit-features-remove"));
  const settings = { key: "building_id", layer: "table_osm_buildings", edits: [{ op: "remove", ids: [119, 136] }] };
  const code = editFeaturesCode(settings as any);
  expect(code).toContain('{"op": "remove", "ids": [119, 136]},');
  expect(updateDataNode).toHaveBeenCalledWith(NODE, expect.objectContaining({ editFeatures: settings, code, defaultCode: code }));
  expect(state.setCode).toHaveBeenCalledWith(code);
  expect(markNodeStale).toHaveBeenCalledWith(NODE);
  // The pick is spent.
  expect(picked().getAttribute("data-edit-picked")).toBe("");
});

test("Set value writes a number into a column of numbers", async () => {
  const { updateDataNode } = mount({ key: "building_id", layer: "table_osm_buildings" });
  await screen.findByTestId("autark-map");
  pick([2]);
  fireEvent.change(screen.getByTestId("edit-features-column"), { target: { value: "height" } });
  fireEvent.change(screen.getByTestId("edit-features-value"), { target: { value: "30" } });
  fireEvent.click(screen.getByTestId("edit-features-set"));
  expect(updateDataNode).toHaveBeenCalledWith(NODE, expect.objectContaining({
    editFeatures: { key: "building_id", layer: "table_osm_buildings", edits: [{ op: "set", ids: [136], column: "height", value: 30 }] },
  }));
});

test("the edit list shows each edit, and the × deletes one", async () => {
  const { updateDataNode } = mount({
    key: "building_id",
    layer: "table_osm_buildings",
    edits: [{ op: "remove", ids: [119] }, { op: "restore", ids: [119] }],
  });
  await screen.findByTestId("autark-map");
  const list = document.querySelector("[data-edit-list]")!;
  expect(list.getAttribute("data-edit-list")).toBe("2");
  expect(list.textContent).toContain("Remove building_id 119");
  expect(list.textContent).toContain("Restore building_id 119");
  fireEvent.click(screen.getByLabelText("Delete edit 1"));
  expect(updateDataNode).toHaveBeenCalledWith(NODE, expect.objectContaining({
    editFeatures: { key: "building_id", layer: "table_osm_buildings", edits: [{ op: "restore", ids: [119] }] },
  }));
});

test("a layer with no column that identifies its features is refused, and nothing can be picked", async () => {
  mockSources = [{
    outputTableName: "input_0",
    named: false,
    geojsonObject: {
      type: "FeatureCollection",
      features: [feature({ __row_index__: 0, kind: "x" }), feature({ __row_index__: 1, kind: "x" })],
    },
  }];
  mount(undefined);
  const refusal = await waitFor(() => {
    const el = document.querySelector("[data-edit-refusal]");
    expect(el).not.toBeNull();
    return el!;
  });
  expect(refusal.textContent).toMatch(/has no column that identifies its features/);
  expect(screen.queryByTestId("autark-map")).toBeNull();
  expect(screen.queryByTestId("edit-features-remove")).toBeNull();
});
