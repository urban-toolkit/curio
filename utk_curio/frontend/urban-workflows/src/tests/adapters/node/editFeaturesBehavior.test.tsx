/**
 * The Interaction node (#662; its type is still `curio.builtin/edit-features`)
 * on the canvas, its code its only state. Linked to no Autark map it feeds, it
 * says how to link one and keeps its list. Feeding a map and linked to it by
 * an interaction edge, it lists its log: each entry, switched off, deleted,
 * and each change an entry of its Provenance drawer, which Undo and Redo walk;
 * an edit making the node and every node below it out of date, the map among
 * them; Commit edits running them; a rule's matches and what it does; code
 * the node cannot read; and a layer with no column that identifies its
 * features.
 */
import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
import ProvenanceProvider, { useProvenanceContext, type NodeExecRecord } from "../../../providers/ProvenanceProvider";
import { editFeaturesCode, readEditFeaturesCode, type EditFeaturesSettings } from "../../../utils/editFeatures/editFeatures";

const NODE = "edit-1";
const MAP = "map";
const INPUT = { dataType: "outputs", data: [{ path: "art_roads" }, { path: "art_buildings" }] };

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
  geojsonObject: { type: "FeatureCollection", features: [feature({ osm_id: 7, highway: "primary" })] },
};

/** Two edits on the buildings, each naming its layer, as an edit on the map writes them. */
const LOG: EditFeaturesSettings = {
  keys: { table_osm_buildings: "building_id" },
  edits: [
    { op: "remove", ids: [119], layer: "table_osm_buildings" },
    { op: "set", ids: [136], column: "height", value: 30, layer: "table_osm_buildings" },
  ],
};

/**
 * The data nodes feed the node, the node feeds the map, which feeds a count,
 * which feeds a model; an interaction edge links the node and the map, and a
 * chart is linked to the map by an interaction edge only, which runs nothing.
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
    { id: "d3", source: NODE, target: MAP, sourceHandle: "out", targetHandle: "in" },
    { id: "link", source: NODE, target: MAP, sourceHandle: "in/out", targetHandle: "in/out", type: "BIDIRECTIONAL_EDGE" },
    { id: "d5", source: MAP, target: "count", sourceHandle: "out", targetHandle: "in" },
    { id: "d6", source: "count", target: "model", sourceHandle: "out", targetHandle: "in" },
    { id: "i1", source: MAP, target: "chart", sourceHandle: "in/out", targetHandle: "in/out", type: "BIDIRECTIONAL_EDGE" },
  ],
};

function nodeState(output = { code: "", content: "" }): UseNodeStateReturn {
  return { output, setOutput: jest.fn(), code: "", setCode: jest.fn() } as unknown as UseNodeStateReturn;
}

/** The edits a code holds, as the node reads them; undefined for code it cannot read. */
function settingsIn(code: unknown): EditFeaturesSettings | undefined {
  const read = readEditFeaturesCode(String(code ?? ""));
  return "problem" in read ? undefined : read.settings;
}

/**
 * The node on a canvas that keeps what it writes, so each edit sees the log
 * the one before it left, as on the canvas, under the provider that keeps its
 * Provenance drawer's entries. Its code holds *log*, fed by two circles.
 */
function mountLive(log: EditFeaturesSettings | undefined, flowExtra: Record<string, any> = {}, state = nodeState(), extra: Record<string, unknown> = {}) {
  const updateDataNode = jest.fn();
  const markNodeStale = jest.fn();
  const markDirty = jest.fn();
  const { more = [], edges = [], ...rest } = flowExtra;
  const code = typeof extra.code === "string" ? extra.code : editFeaturesCode(log, 2);
  const first = { nodeId: NODE, input: INPUT, ...extra, defaultCode: code, code };
  const provenance: { current: ReturnType<typeof useProvenanceContext> | null } = { current: null };
  function Probe() {
    provenance.current = useProvenanceContext();
    return null;
  }
  function Canvas({ children }: { children: React.ReactNode }) {
    const [live, setLive] = React.useState<any>(first);
    const flow = {
      nodes: [{ id: NODE, type: "curio.builtin/edit-features", data: live }, ...more],
      edges,
      markNodeStale,
      markDirty,
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
    <ProvenanceProvider>
      <Probe />
      <Canvas>
        <Host />
      </Canvas>
    </ProvenanceProvider>,
  );
  /** The code the node holds now. */
  const codeNow = () => String(updateDataNode.mock.calls.at(-1)?.[1]?.code ?? code);
  return {
    updateDataNode,
    markNodeStale,
    markDirty,
    codeNow,
    log: () => settingsIn(codeNow())?.edits ?? [],
    /** The entries of the node's Provenance drawer. */
    entries: (): NodeExecRecord[] => provenance.current?.getAllNodeProvenance()[NODE] ?? [],
  };
}

const body = () => document.querySelector("[data-edit-body]") as HTMLElement;

beforeEach(() => {
  mockSources = [ROADS, BUILDINGS];
});

test("linked to no Autark map it feeds, the node says how to link one, and keeps its list", () => {
  mountLive(undefined, { more: LINKED.more.slice(0, 2), edges: LINKED.edges.slice(0, 2) });
  expect(screen.getByTestId("interaction-unlinked")).toHaveTextContent("Not linked to a map");
  expect(screen.getByTestId("interaction-unlinked")).toHaveTextContent("Connect this node to an Autark map, then link the two with an interaction edge");
  // No layers, no map, no tools; the list stays, empty.
  for (const id of ["interaction-layers", "interaction-workbench", "interaction-edit-map", "edit-features-remove"]) {
    expect(screen.queryByTestId(id)).toBeNull();
  }
  expect(document.querySelector("[data-edit-list]")?.getAttribute("data-edit-list")).toBe("0");
});

test("unlinked, the list the node's code holds stays, to switch off or delete", () => {
  const { log } = mountLive(LOG);
  expect(screen.getByTestId("interaction-unlinked")).toHaveTextContent("Not linked to a map");
  expect(document.querySelector("[data-edit-list]")?.getAttribute("data-edit-list")).toBe("2");
  fireEvent.click(screen.getByLabelText("Delete edit 1"));
  expect(log()).toEqual([LOG.edits![1]]);
});

test("a map that is linked but not fed is not the node's: it says to link the map it feeds", () => {
  const notFed = LINKED.edges.filter((edge) => edge.id !== "d3");
  mountLive(LOG, { more: LINKED.more, edges: notFed });
  expect(screen.getByTestId("interaction-unlinked")).toHaveTextContent("Not linked to a map");
  expect(screen.queryByTestId("interaction-connected")).toBeNull();
});

test("linked, the log lists each entry, and the × deletes the one it is on", async () => {
  const { log } = mountLive(LOG, LINKED);
  expect(await screen.findByTestId("interaction-connected")).toHaveTextContent("Linked to Downtown Chicago layers");
  const list = document.querySelector("[data-edit-list]")!;
  expect(list.getAttribute("data-edit-list")).toBe("2");
  expect(list.textContent).toContain("Remove building_id 119");
  fireEvent.click(screen.getByLabelText("Delete edit 1"));
  // The removal of 119 is gone; the change of 136 stays.
  expect(log()).toEqual([LOG.edits![1]]);
  expect(JSON.stringify(log())).not.toContain("119");
  expect(document.querySelector("[data-edit-list]")!.textContent).not.toContain("119");
});

test("an edit leaves the dataflow Unsaved and makes the node and every node below it stale, the map among them; a chart linked by an interaction edge is not below it", async () => {
  const status = { [NODE]: "executed", [MAP]: "executed", count: "executed", model: "executed", chart: "executed" };
  const { markNodeStale, markDirty } = mountLive(LOG, { ...LINKED, nodeExecStatus: status }, nodeState({ code: "success", content: "" }));
  await screen.findByTestId("interaction-connected");
  fireEvent.click(screen.getByLabelText("Delete edit 1"));
  expect([...new Set(markNodeStale.mock.calls.map((call) => call[0]))].sort()).toEqual([NODE, MAP, "count", "model"].sort());
  expect(markDirty).toHaveBeenCalled();
});

test("Commit edits runs the node and every node below it, the map it feeds among them", async () => {
  const runDownstream = jest.fn();
  const status = { [NODE]: "stale", [MAP]: "stale", count: "stale", model: "executed" };
  mountLive(LOG, { ...LINKED, nodeExecStatus: status, runDownstream });
  await screen.findByTestId("interaction-connected");
  const foot = screen.getByTestId("interaction-commit");
  expect(foot).toHaveAttribute("data-commit-state", "stale");
  expect(foot).toHaveTextContent("The downstream nodes don't have these edits yet.");
  const update = screen.getByTestId("interaction-update");
  expect(update).toHaveTextContent(/^Commit edits$/);
  expect(update).toHaveAttribute("title", "Runs this node and the 3 nodes below it with the edits");
  fireEvent.click(update);
  expect(runDownstream).toHaveBeenCalledWith([NODE]);
});

test("the foot says the edits are committed once the nodes below ran, and Commit waits while a run goes, in the browser or on the server", async () => {
  const done = { [NODE]: "executed", [MAP]: "executed", count: "executed", model: "executed" };
  mountLive(LOG, { ...LINKED, nodeExecStatus: done, runDownstream: jest.fn() });
  await screen.findByTestId("interaction-connected");
  expect(screen.getByTestId("interaction-commit")).toHaveAttribute("data-commit-state", "done");
  expect(screen.getByTestId("interaction-commit")).toHaveTextContent("✓ Edits committed");
  cleanup();
  // The node ran; the map and the nodes below it never did.
  mountLive(LOG, { ...LINKED, nodeExecStatus: { [NODE]: "executed" }, runDownstream: jest.fn() });
  await screen.findByTestId("interaction-connected");
  expect(screen.getByTestId("interaction-commit")).toHaveAttribute("data-commit-state", "stale");
  expect(screen.getByTestId("interaction-commit")).not.toHaveTextContent(/edits committed/i);
  cleanup();
  mountLive(LOG, { ...LINKED, nodeExecStatus: { ...done, [NODE]: "stale" }, isRunActive: true });
  await screen.findByTestId("interaction-connected");
  expect(screen.getByTestId("interaction-update")).toHaveTextContent(/^Running…$/);
  expect(screen.getByTestId("interaction-update")).toBeDisabled();
  cleanup();
  mountLive(LOG, { ...LINKED, nodeExecStatus: { ...done, [NODE]: "stale" }, serverRunActive: true });
  await screen.findByTestId("interaction-connected");
  expect(screen.getByTestId("interaction-update")).toBeDisabled();
});

test("Commit edits is offered only with nodes below the node", async () => {
  mountLive(LOG, { more: LINKED.more.slice(0, 2), edges: LINKED.edges.slice(0, 2), runDownstream: jest.fn() });
  expect(screen.queryByTestId("interaction-update")).toBeNull();
});

test("an entry switched off is kept, drawn off and skipped, and on again", async () => {
  const { log } = mountLive(
    { key: "building_id", layer: "table_osm_buildings", edits: [{ op: "remove", ids: [119] }, { op: "offset", ids: [136], column: "height", value: 3 }] },
    LINKED,
  );
  await screen.findByTestId("interaction-connected");
  // Counted once the layers are read.
  await waitFor(() => expect(screen.getByTestId("interaction-counts")).toHaveTextContent("2 removed, 1 changed"));
  fireEvent.click(screen.getByLabelText("Use edit 1"));
  expect(log()).toEqual([
    { op: "remove", ids: [119], enabled: false },
    { op: "offset", ids: [136], column: "height", value: 3 },
  ]);
  const entries = document.querySelectorAll("[data-edit-op]");
  expect(entries[0].getAttribute("data-edit-enabled")).toBe("false");
  expect(entries[1].getAttribute("data-edit-enabled")).toBe("true");
  expect(screen.getByTestId("interaction-counts")).toHaveTextContent("0 removed, 1 changed");
  fireEvent.click(screen.getByLabelText("Use edit 1"));
  expect(log()).toEqual([{ op: "remove", ids: [119] }, { op: "offset", ids: [136], column: "height", value: 3 }]);
  expect(screen.getByTestId("interaction-counts")).toHaveTextContent("2 removed, 1 changed");
});

test("each change adds one entry to the node's Provenance drawer at once, named by what it changed, holding the code it left", async () => {
  const { codeNow, entries } = mountLive(LOG, LINKED);
  await screen.findByTestId("interaction-connected");
  expect(entries()).toHaveLength(0);

  fireEvent.click(screen.getByLabelText("Use edit 1"));
  expect(entries()).toHaveLength(1);
  expect(entries()[0]).toMatchObject({ kind: "edit", label: "Switch off: Remove building_id 119 in table_osm_buildings", code: codeNow(), inputs: [], outputs: [] });

  fireEvent.click(screen.getByLabelText("Delete edit 2"));
  expect(entries()).toHaveLength(2);
  expect(entries()[1]).toMatchObject({ kind: "edit", label: "Delete: Set height to 30 on building_id 136 in table_osm_buildings", code: codeNow() });
  expect(entries()[1].parentId).toBe(entries()[0].id);

  // An action: a property added to the buildings.
  fireEvent.click(await screen.findByTestId("interaction-layer-table_osm_buildings"));
  fireEvent.click(screen.getByTestId("interaction-action-property"));
  fireEvent.change(screen.getByTestId("interaction-property-name"), { target: { value: "kind" } });
  fireEvent.change(screen.getByTestId("interaction-property-value"), { target: { value: "office" } });
  fireEvent.click(screen.getByTestId("interaction-property-add"));
  expect(entries()).toHaveLength(3);
  expect(entries()[2].label).toMatch(/^Add a property kind/);
  expect(entries()[2].code).toBe(codeNow());
  expect(settingsIn(codeNow())?.edits?.at(-1)).toMatchObject({ op: "add_column", column: "kind", value: "office" });
});

test("Undo puts back the entry before and Redo the newest one after it, by the buttons and the keys; neither adds an entry, and the next change branches from there", async () => {
  const { log, entries } = mountLive(LOG, LINKED);
  await screen.findByTestId("interaction-connected");
  const undo = () => screen.getByTestId("interaction-undo");
  const redo = () => screen.getByTestId("interaction-redo");
  // Nothing in the node's history yet.
  expect(undo()).toBeDisabled();
  expect(redo()).toBeDisabled();

  fireEvent.click(screen.getByLabelText("Delete edit 2"));
  fireEvent.click(screen.getByLabelText("Use edit 1"));
  const off = [{ ...LOG.edits![0], enabled: false }];
  expect(log()).toEqual(off);
  expect(entries()).toHaveLength(2);

  fireEvent.click(undo());
  expect(log()).toEqual([LOG.edits![0]]);
  // Back before the node's first change, to the code it held.
  fireEvent.keyDown(body(), { key: "z", ctrlKey: true });
  expect(log()).toEqual(LOG.edits);
  expect(undo()).toBeDisabled();

  fireEvent.click(redo());
  expect(log()).toEqual([LOG.edits![0]]);
  fireEvent.keyDown(body(), { key: "z", ctrlKey: true, shiftKey: true });
  expect(log()).toEqual(off);
  expect(redo()).toBeDisabled();
  expect(entries()).toHaveLength(2);

  // Back one, then a change: it branches from the entry put back.
  fireEvent.keyDown(body(), { key: "z", metaKey: true });
  expect(log()).toEqual([LOG.edits![0]]);
  fireEvent.click(screen.getByLabelText("Delete edit 1"));
  expect(log()).toEqual([]);
  expect(entries()).toHaveLength(3);
  expect(entries()[2].parentId).toBe(entries()[0].id);
  expect(redo()).toBeDisabled();
  fireEvent.click(undo());
  expect(log()).toEqual([LOG.edits![0]]);
});

test("an old save's metadata.editFeatures is ignored: the node reads its code", async () => {
  mountLive(LOG, LINKED, nodeState(), { editFeatures: { key: "building_id", edits: [{ op: "remove", ids: [999] }] } });
  await screen.findByTestId("interaction-connected");
  const list = document.querySelector("[data-edit-list]")!;
  expect(list.getAttribute("data-edit-list")).toBe("2");
  expect(list.textContent).not.toContain("999");
});

test("code of another shape is never rewritten: the node says why it cannot read it and offers nothing", async () => {
  const { updateDataNode } = mountLive(undefined, LINKED, nodeState(), { code: "return input_0\n" });
  const unreadable = screen.getByTestId("interaction-unreadable");
  expect(unreadable).toHaveTextContent("holds something else");
  for (const id of ["interaction-layers", "interaction-workbench", "interaction-log", "interaction-undo", "interaction-connected"]) {
    expect(screen.queryByTestId(id)).toBeNull();
  }
  // Fed by two circles, the code is not written for them either.
  await act(async () => {});
  expect(updateDataNode).not.toHaveBeenCalled();
});

test("a rule says how many features it matches, on the layer as the log leaves it, and removes them or computes a column for them", async () => {
  const { log } = mountLive(undefined, LINKED);
  fireEvent.click(await screen.findByTestId("interaction-layer-table_osm_buildings"));
  fireEvent.click(screen.getByTestId("interaction-action-remove"));
  fireEvent.click(screen.getByTestId("interaction-remove-by-rule"));
  fireEvent.change(screen.getByLabelText("Test"), { target: { value: ">" } });
  fireEvent.change(screen.getByTestId("interaction-rule-value-0"), { target: { value: "100" } });
  expect(screen.getByTestId("interaction-matching")).toHaveTextContent("Matches 1 area of 3");
  fireEvent.click(screen.getByTestId("interaction-remove-picked"));
  expect(log()).toEqual([{ op: "remove", where: "height > 100" }]);
  // Removed, the tower matches no more.
  expect(screen.getByTestId("interaction-matching")).toHaveTextContent("Matches 0 areas of 2");
  expect(screen.getByTestId("interaction-remove-picked")).toBeDisabled();

  fireEvent.click(screen.getByTestId("interaction-back"));
  fireEvent.click(screen.getByTestId("interaction-action-edit"));
  fireEvent.click(screen.getByTestId("interaction-edit-by-rule"));
  fireEvent.change(screen.getByTestId("interaction-rule-value-0"), { target: { value: "50" } });
  expect(screen.getByTestId("interaction-matching")).toHaveTextContent("Matches 2 areas of 2");
  fireEvent.change(screen.getByTestId("interaction-rule-op"), { target: { value: "expr" } });
  fireEvent.change(screen.getByTestId("interaction-rule-set-value"), { target: { value: "height / 2" } });
  fireEvent.click(screen.getByTestId("interaction-rule-apply"));
  expect(log()).toEqual([
    { op: "remove", where: "height > 100" },
    { op: "expr", where: "height > 50", column: "height", value: "height / 2" },
  ]);
  // Halved, they match no more.
  expect(screen.getByTestId("interaction-matching")).toHaveTextContent("Matches 0 areas of 2");
});

test("a layer with no column that identifies its features is refused: nothing in it can be picked or edited", async () => {
  mockSources = [{
    outputTableName: "input_0",
    named: false,
    geojsonObject: {
      type: "FeatureCollection",
      features: [feature({ __row_index__: 0, kind: "x" }), feature({ __row_index__: 1, kind: "x" })],
    },
  }];
  mountLive(undefined, {
    more: LINKED.more,
    edges: [LINKED.edges[0], { ...LINKED.edges[2] }, LINKED.edges[3]],
  }, nodeState(), { code: editFeaturesCode(undefined, 1) });
  const card = await screen.findByTestId("interaction-layer-input_0");
  expect(card).toHaveTextContent("no id column");
  fireEvent.click(card);
  expect(screen.getByTestId("interaction-active-layer")).toHaveTextContent("This layer has no column that identifies its features");
  for (const action of ["add", "edit", "remove", "property"]) {
    expect(screen.getByTestId(`interaction-action-${action}`)).toBeDisabled();
  }
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
