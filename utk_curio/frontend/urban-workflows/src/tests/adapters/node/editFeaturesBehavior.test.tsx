/**
 * The Interaction node (#662; its type is still `curio.builtin/edit-features`)
 * on the canvas: its input drawn by the Autark node's map code with the layer
 * to edit pickable, a pick adding the picked features' ids to its list, Remove
 * turning them into an edit that is written with the code it makes, and a
 * layer with no column that identifies its features refused. Then its log:
 * the keys, conditions, the picked features' table, entries switched off,
 * deleted or undone, and Commit edits.
 */
import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { NodeBehaviorData, UseNodeStateReturn } from "../../../registry/types";
import { VisInteractionType } from "../../../constants";

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

/**
 * These tests are of the Map view (the Autark map and its tools): open it as
 * soon as the node shows its views. The Edit view opens first.
 */
function openMapView() {
  void screen
    .findByTestId("interaction-view-map")
    .then((tab) => act(() => { fireEvent.click(tab); }))
    .catch(() => undefined);
}

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
  openMapView();
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
  // With no edits yet, both can still change.
  expect(screen.getByRole("combobox", { name: "Id" })).toBeEnabled();
  expect(screen.getByRole("combobox", { name: "Layer" })).toBeEnabled();
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
  // The edits name features of this layer by this column: neither can change under them.
  for (const name of ["Layer", "Id"]) {
    const menu = screen.getByRole("combobox", { name });
    expect(menu).toBeDisabled();
    expect(menu.getAttribute("title")).toMatch(/delete them to pick another/);
  }
  fireEvent.click(screen.getByLabelText("Delete edit 1"));
  expect(updateDataNode).toHaveBeenCalledWith(NODE, expect.objectContaining({
    editFeatures: { key: "building_id", layer: "table_osm_buildings", edits: [{ op: "restore", ids: [119] }] },
  }));
});

describe("the Interaction node", () => {
  /**
   * The node feeds a rasterizer, which feeds a model; a chart is linked to it
   * by an interaction edge only, which carries a selection and runs nothing.
   */
  const BELOW = {
    more: [{ id: "rasterize" }, { id: "model" }, { id: "chart" }],
    edges: [
      { id: "e1", source: NODE, target: "rasterize", sourceHandle: "out", targetHandle: "in" },
      { id: "e2", source: "rasterize", target: "model", sourceHandle: "out", targetHandle: "in" },
      { id: "e3", source: NODE, target: "chart", sourceHandle: "in/out", targetHandle: "in/out" },
    ],
  };

  /**
   * The node on a canvas that keeps what it writes, so each edit sees the log
   * the one before it left, as on the canvas.
   */
  function mountLive(editFeatures: unknown, flowExtra: Record<string, any> = {}, state = nodeState()) {
    const updateDataNode = jest.fn();
    const markNodeStale = jest.fn();
    const { more = [], edges = [], ...rest } = flowExtra;
    const first = { nodeId: NODE, input: INPUT, editFeatures, defaultCode: editFeaturesCode(undefined), code: editFeaturesCode(undefined) };
    function Canvas({ children }: { children: React.ReactNode }) {
      const [live, setLive] = React.useState<any>(first);
      const flow = {
        nodes: [{ id: NODE, data: live }, ...more],
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
    openMapView();
    const log = () => (updateDataNode.mock.calls[updateDataNode.mock.calls.length - 1]?.[1]?.editFeatures?.edits ?? []) as any[];
    return { updateDataNode, markNodeStale, log };
  }

  const body = () => document.querySelector("[data-edit-body]") as HTMLElement;
  const picked = () => document.querySelector("[data-edit-picked]")!.getAttribute("data-edit-picked");
  const KEYED = { key: "building_id", layer: "table_osm_buildings" };

  test("an edit makes the node and every node after it that ran stale; an interaction edge's chart is not after it", async () => {
    const status = { [NODE]: "executed", rasterize: "executed", model: "executed", chart: "executed" };
    const { markNodeStale } = mountLive(KEYED, { ...BELOW, nodeExecStatus: status }, nodeState({ code: "success", content: "" }));
    await screen.findByTestId("autark-map");
    pick([2]);
    fireEvent.click(screen.getByTestId("edit-features-remove"));
    expect(markNodeStale.mock.calls.map((call) => call[0]).sort()).toEqual([NODE, "model", "rasterize"]);
  });

  test("Commit edits runs the node and every node after it, at the log's foot, which says the nodes below lack the edits", async () => {
    const runDownstream = jest.fn();
    const status = { [NODE]: "stale", rasterize: "stale", model: "executed" };
    mountLive(KEYED, { ...BELOW, nodeExecStatus: status, runDownstream });
    await screen.findByTestId("autark-map");
    const foot = screen.getByTestId("interaction-commit");
    expect(foot).toHaveAttribute("data-commit-state", "stale");
    expect(foot).toHaveTextContent("The downstream nodes don't have these edits yet.");
    const update = screen.getByTestId("interaction-update");
    expect(update).toHaveTextContent(/^Commit edits$/);
    expect(update).toBeEnabled();
    fireEvent.click(update);
    expect(runDownstream).toHaveBeenCalledWith([NODE]);
  });

  test("with edits and nothing below out of date, the log's foot says the edits are committed", async () => {
    const status = { [NODE]: "executed", rasterize: "executed", model: "executed" };
    mountLive(KEYED, { ...BELOW, nodeExecStatus: status, runDownstream: jest.fn() });
    await screen.findByTestId("autark-map");
    expect(screen.queryByTestId("interaction-commit")).toBeNull();
    pick([2]);
    fireEvent.click(screen.getByTestId("edit-features-remove"));
    const foot = await screen.findByTestId("interaction-commit");
    expect(foot).toHaveAttribute("data-commit-state", "done");
    expect(foot).toHaveTextContent("✓ Edits committed");
    expect(screen.queryByTestId("interaction-update")).toBeNull();
  });

  test("Commit edits is offered only with nodes after the node, and waits while a run goes", async () => {
    mountLive(KEYED, { runDownstream: jest.fn() });
    await screen.findByTestId("autark-map");
    expect(screen.queryByTestId("interaction-commit")).toBeNull();
    cleanup();
    mountLive(KEYED, { ...BELOW, isRunActive: true });
    await screen.findByTestId("autark-map");
    expect(screen.getByTestId("interaction-update")).toHaveTextContent(/^Running…$/);
    expect(screen.getByTestId("interaction-update")).toBeDisabled();
    cleanup();
    mountLive(KEYED, { ...BELOW, serverRunActive: true });
    await screen.findByTestId("autark-map");
    expect(screen.getByTestId("interaction-update")).toBeDisabled();
  });

  test("the keys: arrows raise and lower the pick as one entry, Delete removes it, Escape clears it, and undo and redo", async () => {
    const { log } = mountLive(KEYED);
    await screen.findByTestId("autark-map");
    pick([2]);
    // A height column moves a floor, 3 m, a press.
    fireEvent.keyDown(body(), { key: "ArrowUp" });
    expect(log()).toEqual([{ op: "offset", ids: [136], column: "height", value: 3 }]);
    fireEvent.keyDown(body(), { key: "ArrowUp" });
    expect(log()).toEqual([{ op: "offset", ids: [136], column: "height", value: 6 }]);
    fireEvent.keyDown(body(), { key: "ArrowDown" });
    expect(log()).toEqual([{ op: "offset", ids: [136], column: "height", value: 3 }]);
    // Handled here, so the canvas neither deletes the node nor moves it.
    expect(fireEvent.keyDown(body(), { key: "Delete" })).toBe(false);
    expect(log()).toEqual([{ op: "offset", ids: [136], column: "height", value: 3 }, { op: "remove", ids: [136] }]);
    expect(picked()).toBe("");
    fireEvent.keyDown(body(), { key: "z", ctrlKey: true });
    expect(log()).toEqual([{ op: "offset", ids: [136], column: "height", value: 3 }]);
    fireEvent.keyDown(body(), { key: "z", ctrlKey: true, shiftKey: true });
    expect(log()).toEqual([{ op: "offset", ids: [136], column: "height", value: 3 }, { op: "remove", ids: [136] }]);
    pick([0]);
    expect(picked()).toBe("119");
    fireEvent.keyDown(body(), { key: "Escape" });
    expect(picked()).toBe("");
    // Nothing picked: the node leaves Delete alone.
    expect(fireEvent.keyDown(body(), { key: "Delete" })).toBe(true);
  });

  test("a key typed in one of the node's fields is the field's", async () => {
    const { updateDataNode } = mountLive(KEYED);
    await screen.findByTestId("autark-map");
    pick([2]);
    fireEvent.keyDown(screen.getByTestId("interaction-where"), { key: "ArrowUp" });
    fireEvent.keyDown(screen.getByTestId("interaction-where"), { key: "Delete" });
    expect(updateDataNode).not.toHaveBeenCalled();
    expect(picked()).toBe("136");
  });

  test("a condition says how many features it picks, on the layer as the log leaves it, and applies to all of them", async () => {
    const { log } = mountLive(KEYED);
    await screen.findByTestId("autark-map");
    fireEvent.change(screen.getByTestId("interaction-where"), { target: { value: "height >= 60" } });
    expect(screen.getByTestId("interaction-matching")).toHaveTextContent(/^3 features$/);
    fireEvent.change(screen.getByTestId("interaction-where-op"), { target: { value: "scale" } });
    fireEvent.change(screen.getByTestId("interaction-where-column"), { target: { value: "height" } });
    fireEvent.change(screen.getByTestId("interaction-where-value"), { target: { value: "0.5" } });
    fireEvent.click(screen.getByTestId("interaction-where-apply"));
    expect(log()).toEqual([{ op: "scale", where: "height >= 60", column: "height", value: 0.5 }]);
    // Halved, only the tallest part is still 60 m or more.
    expect(screen.getByTestId("interaction-matching")).toHaveTextContent(/^1 feature$/);
    fireEvent.change(screen.getByTestId("interaction-where"), { target: { value: "height >" } });
    expect(screen.getByTestId("interaction-where-apply")).toBeDisabled();
    expect(screen.getByTestId("interaction-where-problem").textContent).not.toBe("");
  });

  test("a condition can compute a column with an expression, or remove what it picks", async () => {
    const { log } = mountLive(KEYED);
    await screen.findByTestId("autark-map");
    fireEvent.change(screen.getByTestId("interaction-where"), { target: { value: "building_id == 119" } });
    fireEvent.change(screen.getByTestId("interaction-where-op"), { target: { value: "expr" } });
    fireEvent.change(screen.getByTestId("interaction-where-column"), { target: { value: "height" } });
    fireEvent.change(screen.getByTestId("interaction-where-value"), { target: { value: "height / 2" } });
    fireEvent.click(screen.getByTestId("interaction-where-apply"));
    fireEvent.change(screen.getByTestId("interaction-where-op"), { target: { value: "remove" } });
    fireEvent.click(screen.getByTestId("interaction-where-apply"));
    expect(log()).toEqual([
      { op: "expr", where: "building_id == 119", column: "height", value: "height / 2" },
      { op: "remove", where: "building_id == 119" },
    ]);
  });

  test("the picked features' table shows them as the log leaves them, and a value typed into it is an edit", async () => {
    const { log } = mountLive({ ...KEYED, edits: [{ op: "offset", ids: [136], column: "height", value: 3 }] });
    await screen.findByTestId("autark-map");
    pick([2]);
    const cell = screen.getByLabelText("height of 136") as HTMLInputElement;
    expect(cell.value).toBe("63");
    fireEvent.change(cell, { target: { value: "70" } });
    fireEvent.blur(cell);
    expect(log()).toEqual([
      { op: "offset", ids: [136], column: "height", value: 3 },
      { op: "set", ids: [136], column: "height", value: 70 },
    ]);
    // Text in a column of numbers is no value.
    const again = screen.getByLabelText("height of 136") as HTMLInputElement;
    fireEvent.change(again, { target: { value: "tall" } });
    fireEvent.blur(again);
    expect(log()).toHaveLength(2);
  });

  test("an entry switched off is kept, drawn off and skipped; entries are deleted and undone; the map draws the input", async () => {
    const { log } = mountLive({
      ...KEYED,
      edits: [{ op: "remove", ids: [119] }, { op: "offset", ids: [136], column: "height", value: 3 }],
    });
    await screen.findByTestId("autark-map");
    expect(screen.getByTestId("interaction-counts")).toHaveTextContent("2 removed, 1 changed");
    fireEvent.click(screen.getByLabelText("Use edit 1"));
    expect(log()).toEqual([
      { op: "remove", ids: [119], enabled: false },
      { op: "offset", ids: [136], column: "height", value: 3 },
    ]);
    const entries = document.querySelectorAll("[data-edit-op]");
    expect(entries[0].getAttribute("data-edit-enabled")).toBe("false");
    expect(entries[1].getAttribute("data-edit-enabled")).toBe("true");
    expect(screen.getByTestId("interaction-counts")).toHaveTextContent("0 removed, 1 changed");
    fireEvent.click(screen.getByLabelText("Delete edit 2"));
    expect(log()).toEqual([{ op: "remove", ids: [119], enabled: false }]);
    fireEvent.click(screen.getByTestId("interaction-undo"));
    expect(log()).toEqual([]);
    fireEvent.click(screen.getByTestId("interaction-redo"));
    expect(log()).toEqual([{ op: "remove", ids: [119], enabled: false }]);
    // The map shows the node's input as it came; the run applies the log.
    expect(mockMapData.input).toBe(INPUT);
  });

  test("Scale multiplies the picked features' number by the factor", async () => {
    const { log } = mountLive(KEYED);
    await screen.findByTestId("autark-map");
    pick([0]);
    fireEvent.change(screen.getByTestId("interaction-factor"), { target: { value: "2" } });
    fireEvent.click(screen.getByTestId("interaction-scale"));
    expect(log()).toEqual([{ op: "scale", ids: [119], column: "height", value: 2 }]);
  });
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
