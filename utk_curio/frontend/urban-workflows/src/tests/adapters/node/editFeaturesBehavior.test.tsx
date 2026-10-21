/**
 * The Interaction node (#662; its type is still `curio.builtin/edit-features`)
 * on the canvas. Linked to no Autark map it edits nothing and says how to link
 * one. Linked to a map by an interaction edge (the same data nodes feeding
 * both), it lists its log: each entry, deleted, undone and redone, an edit
 * making the node, the linked map and the nodes below the map out of date,
 * and Commit edits running the node and the map.
 */
import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { NodeBehaviorData, UseNodeStateReturn } from "../../../registry/types";

const mockFlowContext = React.createContext<Record<string, any>>({});
jest.mock("../../../providers/FlowProvider", () => ({
  useFlowContext: () => require("react").useContext(mockFlowContext),
}));

// The input, as the Autark map reads it: its layers by table name.
let mockSources: any[] = [];
jest.mock("../../../utils/autkInput", () => ({
  readAutkInput: jest.fn(() => Promise.resolve({ frames: mockSources.map((s: any) => ({ name: s.named ? s.outputTableName : null })) })),
  autkSourcesFrom: jest.fn(() => ({ sources: mockSources })),
}));

import { useEditFeaturesBehavior } from "../../../adapters/node/editFeaturesBehavior";
import { editFeaturesCode } from "../../../utils/editFeatures/editFeatures";

const NODE = "edit-1";
const MAP = "map";
const INPUT = { dataType: "outputs", data: [{ path: "art_roads" }, { path: "art_buildings" }] };

function feature(properties: Record<string, unknown>) {
  return { type: "Feature", geometry: { type: "Polygon", coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] }, properties };
}

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
  geojsonObject: { type: "FeatureCollection", features: [feature({ osm_id: 7, highway: "primary" })] },
};

/** Two edits on the buildings, each naming its layer, as an edit on the map writes them. */
const LOG = {
  keys: { table_osm_buildings: "building_id" },
  edits: [
    { op: "remove", ids: [119], layer: "table_osm_buildings" },
    { op: "set", ids: [136], column: "height", value: 30, layer: "table_osm_buildings" },
  ],
};

/**
 * The same data nodes feed the node and the map, an interaction edge links
 * the two, and the map feeds a count, which feeds a model; a chart is linked
 * to the map by an interaction edge only, which runs nothing.
 */
const LINKED = {
  more: [
    { id: "roads", type: "curio.builtin/data-loading", data: { title: "Roads" } },
    { id: "buildings", type: "curio.builtin/data-loading", data: { title: "Buildings" } },
    { id: MAP, type: "curio.builtin/autk-grammar", data: { title: "Downtown Chicago layers" } },
    { id: "count", type: "curio.builtin/computation-analysis", data: {} },
    { id: "model", type: "curio.builtin/computation-analysis", data: {} },
    { id: "chart", type: "curio.builtin/vis-vega", data: {} },
  ],
  edges: [
    { id: "d1", source: "roads", target: NODE, sourceHandle: "out", targetHandle: "in_0" },
    { id: "d2", source: "buildings", target: NODE, sourceHandle: "out", targetHandle: "in_1" },
    { id: "d3", source: "roads", target: MAP, sourceHandle: "out", targetHandle: "in_0" },
    { id: "d4", source: "buildings", target: MAP, sourceHandle: "out", targetHandle: "in_1" },
    { id: "link", source: NODE, target: MAP, sourceHandle: "in/out", targetHandle: "in/out", type: "BIDIRECTIONAL_EDGE" },
    { id: "d5", source: MAP, target: "count", sourceHandle: "out", targetHandle: "in" },
    { id: "d6", source: "count", target: "model", sourceHandle: "out", targetHandle: "in" },
    { id: "i1", source: MAP, target: "chart", sourceHandle: "in/out", targetHandle: "in/out", type: "BIDIRECTIONAL_EDGE" },
  ],
};

function nodeState(output = { code: "", content: "" }): UseNodeStateReturn {
  return { output, setOutput: jest.fn(), code: "", setCode: jest.fn() } as unknown as UseNodeStateReturn;
}

/**
 * The node on a canvas that keeps what it writes, so each edit sees the log
 * the one before it left, as on the canvas.
 */
function mountLive(editFeatures: unknown, flowExtra: Record<string, any> = {}, state = nodeState()) {
  const updateDataNode = jest.fn();
  const markNodeStale = jest.fn();
  const { more = [], edges = [], ...rest } = flowExtra;
  const first = { nodeId: NODE, input: INPUT, editFeatures, defaultCode: editFeaturesCode(undefined, 2), code: editFeaturesCode(undefined, 2) };
  function Canvas({ children }: { children: React.ReactNode }) {
    const [live, setLive] = React.useState<any>(first);
    const flow = {
      nodes: [{ id: NODE, type: "curio.builtin/edit-features", data: live }, ...more],
      edges,
      markNodeStale,
      updateDataNode: (id: string, data: any) => {
        updateDataNode(id, data);
        setLive(data);
      },
      ...rest,
    };
    return <mockFlowContext.Provider value={flow}>{children}</mockFlowContext.Provider>;
  }
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
  const log = () => (updateDataNode.mock.calls[updateDataNode.mock.calls.length - 1]?.[1]?.editFeatures?.edits ?? []) as any[];
  return { updateDataNode, markNodeStale, log };
}

const body = () => document.querySelector("[data-edit-body]") as HTMLElement;

beforeEach(() => {
  mockSources = [ROADS, BUILDINGS];
});

test("linked to no Autark map, the node edits nothing and says how to link one", () => {
  mountLive(undefined, { more: LINKED.more.slice(0, 2), edges: LINKED.edges.slice(0, 2) });
  expect(screen.getByTestId("interaction-unlinked")).toHaveTextContent("Link an Autark map to edit");
  expect(screen.getByTestId("interaction-unlinked")).toHaveTextContent("drag from the dot on top of this node to the dot on top of the map");
  // No layers, no map, no tools, no log.
  for (const id of ["interaction-layers", "interaction-workbench", "interaction-edit-map", "interaction-log", "edit-features-remove"]) {
    expect(screen.queryByTestId(id)).toBeNull();
  }
  expect(screen.queryByTestId("interaction-kept-edits")).toBeNull();
});

test("unlinked, a log the node already holds is kept, and said to be", () => {
  mountLive(LOG);
  expect(screen.getByTestId("interaction-kept-edits")).toHaveTextContent("2 edits are kept; link the map to see and change them.");
  expect(screen.queryByTestId("interaction-log")).toBeNull();
});

test("linked, the log lists each entry, and the × deletes one", async () => {
  const { updateDataNode } = mountLive(LOG, LINKED);
  expect(await screen.findByTestId("interaction-connected")).toHaveTextContent("Linked to Downtown Chicago layers");
  const list = document.querySelector("[data-edit-list]")!;
  expect(list.getAttribute("data-edit-list")).toBe("2");
  expect(list.textContent).toContain("119");
  fireEvent.click(screen.getByLabelText("Delete edit 1"));
  expect(updateDataNode).toHaveBeenLastCalledWith(NODE, expect.objectContaining({
    editFeatures: expect.objectContaining({ edits: [LOG.edits[1]] }),
  }));
});

test("an edit makes the node, the linked map and every node below the map stale; a chart linked by an interaction edge is not below it", async () => {
  const status = { [NODE]: "executed", [MAP]: "executed", count: "executed", model: "executed", chart: "executed" };
  const { markNodeStale } = mountLive(LOG, { ...LINKED, nodeExecStatus: status }, nodeState({ code: "success", content: "" }));
  await screen.findByTestId("interaction-connected");
  fireEvent.click(screen.getByLabelText("Delete edit 1"));
  expect([...new Set(markNodeStale.mock.calls.map((call) => call[0]))].sort()).toEqual([NODE, MAP, "count", "model"].sort());
});

test("Commit edits runs the node and the linked map, with every node below them", async () => {
  const runDownstream = jest.fn();
  const status = { [NODE]: "stale", [MAP]: "stale", count: "stale", model: "executed" };
  mountLive(LOG, { ...LINKED, nodeExecStatus: status, runDownstream });
  await screen.findByTestId("interaction-connected");
  const foot = screen.getByTestId("interaction-commit");
  expect(foot).toHaveAttribute("data-commit-state", "stale");
  expect(foot).toHaveTextContent("The downstream nodes don't have these edits yet.");
  const update = screen.getByTestId("interaction-update");
  expect(update).toHaveTextContent(/^Commit edits$/);
  fireEvent.click(update);
  expect(runDownstream).toHaveBeenCalledWith([NODE, MAP]);
});

test("with nothing out of date the foot says the edits are committed, and it waits while a run goes", async () => {
  const done = { [NODE]: "executed", [MAP]: "executed", count: "executed", model: "executed" };
  mountLive(LOG, { ...LINKED, nodeExecStatus: done, runDownstream: jest.fn() });
  await screen.findByTestId("interaction-connected");
  expect(screen.getByTestId("interaction-commit")).toHaveAttribute("data-commit-state", "done");
  expect(screen.getByTestId("interaction-commit")).toHaveTextContent("✓ Edits committed");
  cleanup();
  mountLive(LOG, { ...LINKED, nodeExecStatus: { ...done, [NODE]: "stale" }, isRunActive: true });
  await screen.findByTestId("interaction-connected");
  expect(screen.getByTestId("interaction-update")).toHaveTextContent(/^Running…$/);
  expect(screen.getByTestId("interaction-update")).toBeDisabled();
});

test("Undo takes back the last entry and Redo makes it again, by the buttons and the keys", async () => {
  const { log } = mountLive(LOG, LINKED);
  await screen.findByTestId("interaction-connected");
  fireEvent.click(screen.getByTestId("interaction-undo"));
  expect(log()).toEqual([LOG.edits[0]]);
  fireEvent.click(screen.getByTestId("interaction-redo"));
  expect(log()).toEqual(LOG.edits);
  fireEvent.keyDown(body(), { key: "z", ctrlKey: true });
  expect(log()).toEqual([LOG.edits[0]]);
  fireEvent.keyDown(body(), { key: "z", ctrlKey: true, shiftKey: true });
  expect(log()).toEqual(LOG.edits);
});

// Compare Scenarios is gone (step 6.4 of the plan answering komar41's review
// of the #914 merges), and What differs, which listed this node's edits, with
// it: the node's behavior takes nothing from it.
test("the node's behavior imports nothing of Compare Scenarios", () => {
  const fs = require("fs");
  const path = require("path");
  const source: string = fs.readFileSync(
    path.resolve(__dirname, "../../../adapters/node/editFeaturesBehavior.tsx"),
    "utf-8",
  );
  expect(source.match(/from\s+["'][^"']*compare[^"']*["']/gi) ?? []).toEqual([]);
});
