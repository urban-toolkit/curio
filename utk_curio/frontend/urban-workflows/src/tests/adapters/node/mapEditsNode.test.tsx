/**
 * The Map Edits node (its type id is still `curio.builtin/edit-features`) on a
 * canvas that keeps what it writes: its input read by the Autark node's own
 * reader (utils/autkInput, not mocked), its map drawn by the Autark node's map
 * code (mocked: the input and document it is handed, and where a pick goes),
 * and its JSON field a stand-in for Monaco that holds the text and types it.
 *
 * The node's code is its only state: each Apply, Remove and put back writes a
 * new code, leaves the dataflow unsaved, makes it and every node below it that
 * ran stale, asks for an automatic run and files one entry in the node's
 * Provenance drawer, inside the real provider.
 */
import fs from "fs";
import path from "path";
import React from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { NodeBehaviorData, NodeBehaviorResult, UseNodeStateReturn } from "../../../registry/types";
import { VisInteractionType } from "../../../constants";

jest.mock("vega", () => ({}), { virtual: true });
jest.mock("vega-lite", () => ({}), { virtual: true });

const mockFlowContext = React.createContext<Record<string, any>>({});
jest.mock("../../../providers/FlowProvider", () => ({
  useFlowContext: () => require("react").useContext(mockFlowContext),
}));

// The Autark node's map code, as the node's map calls it: the last input,
// document and options it was handed, and where a pick goes.
const mockApply = jest.fn().mockResolvedValue(undefined);
let mockMapData: any = null;
let mockMapOptions: any = null;
jest.mock("../../../adapters/node/autkGrammarBehavior", () => ({
  useAutkGrammarBehavior: (data: any, _state: any, options: any) => {
    mockMapData = data;
    mockMapOptions = options;
    return { applyGrammar: mockApply, contentComponent: <div data-testid="autark-map" /> };
  },
}));

// Monaco, as the field drives it: an editor that holds its text, takes a new
// text through executeEdits (useMonacoExternalValue) and reports each change.
jest.mock("@monaco-editor/react", () => {
  const React: typeof import("react") = require("react");
  function Editor(props: any) {
    const [value, setValue] = React.useState<string>(props.defaultValue ?? "");
    const held = React.useRef(value);
    held.current = value;
    React.useEffect(() => {
      props.onMount?.({
        getModel: () => ({ getFullModelRange: () => ({}), validatePosition: (p: unknown) => p }),
        getValue: () => held.current,
        setValue: (next: string) => {
          held.current = next;
          setValue(next);
        },
        getPosition: () => null,
        executeEdits: (_source: string, edits: Array<{ text: string }>) => {
          held.current = edits[0].text;
          setValue(edits[0].text);
          props.onChange?.(edits[0].text);
          return true;
        },
        pushUndoStop: () => {},
      });
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
    return (
      <textarea
        data-testid="mock-monaco"
        readOnly={!!props.options?.readOnly}
        value={value}
        onChange={(event) => {
          setValue(event.target.value);
          props.onChange?.(event.target.value);
        }}
      />
    );
  }
  return { __esModule: true, default: Editor };
});

import ProvenanceProvider, { useProvenanceContext, type NodeExecRecord } from "../../../providers/ProvenanceProvider";
import { useMapEditsBehavior } from "../../../adapters/node/mapEditsBehavior";
import { mapEditsCode, readMapEdits, type MapEdits } from "../../../utils/mapEdits/mapEdits";
import { METRES_PER_LEVEL } from "../../../utils/buildingHeight";

const NODE = "edit-1";

function feature(properties: Record<string, unknown>) {
  return { type: "Feature", geometry: { type: "Polygon", coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] }, properties };
}

/** A layer as an Autark node hands it on: a `{name, type, geojson}` record. */
function layer(name: string, type: string, properties: Array<Record<string, unknown>>) {
  return { name, type, geojson: { type: "FeatureCollection", features: properties.map(feature) } };
}

/** Buildings as Curio's Autark node hands them on: one row per part, a building's parts sharing its building_id. */
const BUILDINGS = layer("table_osm_buildings", "buildings", [
  { building_id: 119, height: 240 },
  { building_id: 119, height: 60 },
  { building_id: 136, height: 60 },
]);
const ROADS = layer("table_osm_roads", "roads", [{ highway: "primary" }, { highway: "primary" }]);

/** The node's input, inline, as the Autark reader takes it with no fetch. */
const inputOf = (...layers: unknown[]) => ({ dataType: "list", data: layers });

const codeOf = (edits: Partial<MapEdits>) =>
  mapEditsCode({ key: "building_id", remove: [], change: [], ...edits });

type Mounted = {
  setCode: jest.Mock;
  markDirty: jest.Mock;
  markNodeStale: jest.Mock;
  requestAutoRun: jest.Mock;
  /** The node's data as the canvas holds it now. */
  live: () => any;
  /** The edits the node's code holds now. */
  edits: () => MapEdits;
  /** The entries the node's Provenance drawer lists. */
  entries: () => NodeExecRecord[];
  /** What the node's behavior returned last. */
  behavior: () => NodeBehaviorResult;
};

/** The node on a canvas whose flow writes what the node writes, inside the real provenance provider. */
function mountNode({
  code = "",
  input = inputOf(BUILDINGS),
  flow: extra = {},
  output = { code: "", content: "" },
}: {
  code?: string;
  input?: unknown;
  flow?: Record<string, any>;
  output?: { code: string; content: string };
} = {}): Mounted {
  const calls = { setCode: jest.fn(), markDirty: jest.fn(), markNodeStale: jest.fn(), requestAutoRun: jest.fn() };
  let current: any = { nodeId: NODE, input, code, defaultCode: code };
  const seen: { provenance?: ReturnType<typeof useProvenanceContext>; behavior?: NodeBehaviorResult } = {};

  function Node({ data, state }: { data: any; state: UseNodeStateReturn }) {
    const behavior = useMapEditsBehavior(data as NodeBehaviorData, state);
    seen.behavior = behavior;
    return <>{behavior.contentComponent}</>;
  }
  function Probe() {
    seen.provenance = useProvenanceContext();
    return null;
  }
  function Canvas() {
    const [live, setLive] = React.useState<any>(current);
    current = live;
    const { more = [], ...rest } = extra;
    const flow = {
      nodes: [{ id: NODE, data: live }, ...more],
      edges: [],
      nodeExecStatus: {},
      updateDataNode: (id: string, next: any) => {
        if (id === NODE) setLive({ ...next });
      },
      markNodeStale: calls.markNodeStale,
      markDirty: calls.markDirty,
      requestAutoRun: calls.requestAutoRun,
      ...rest,
    };
    const state = { output, setOutput: jest.fn(), code: live.code ?? "", setCode: calls.setCode } as unknown as UseNodeStateReturn;
    return (
      <mockFlowContext.Provider value={flow}>
        <Node data={live} state={state} />
      </mockFlowContext.Provider>
    );
  }

  render(
    <ProvenanceProvider>
      <Probe />
      <Canvas />
    </ProvenanceProvider>,
  );
  return {
    ...calls,
    live: () => current,
    edits: () => {
      const read = readMapEdits(current.code);
      if (!("edits" in read)) throw new Error(read.problem);
      return read.edits;
    },
    entries: () => seen.provenance!.provenanceGraphNodes[NODE] ?? [],
    behavior: () => seen.behavior!,
  };
}

/** A pick on the map, as an Autark node reports one: the drawn rows it names. */
function pickRows(rows: number[]) {
  act(() => {
    mockMapData.interactionsCallback({
      autk_selection: { type: VisInteractionType.POINT, data: rows, priority: 1, layerRef: "table_osm_buildings" },
    }, NODE);
  });
}

/** A pick by a view that names its rows by building_id, as the before-run test sends one. */
function pickBuilding(id: number) {
  act(() => {
    mockMapData.interactionsCallback({
      autk_selection: { type: VisInteractionType.POINT, data: [{ building_id: id }], priority: 1 },
    }, NODE);
  });
}

const body = () => document.querySelector(`[data-map-edits-body="${NODE}"]`) as HTMLElement;
const panel = () => document.querySelector("[data-map-edits-panel]") as HTMLElement;
const selectedId = () => panel().getAttribute("data-map-edits-selected");
const field = () => screen.getByTestId("mock-monaco") as HTMLTextAreaElement;
const fieldJson = () => JSON.parse(field().value);
const typeJson = (value: unknown) => fireEvent.change(field(), { target: { value: JSON.stringify(value, null, 2) } });
const apply = () => fireEvent.click(screen.getByTestId("map-edits-apply"));
const remove = () => fireEvent.click(screen.getByTestId("edit-features-remove"));
/** The ids of the features the map was last handed for the layer to edit. */
const drawnIds = (table = "table_osm_buildings") =>
  mockMapData.input.data.find((record: any) => record.name === table).geojson.features.map((f: any) => f.properties.building_id);

beforeEach(() => {
  mockMapData = null;
  mockMapOptions = null;
  mockApply.mockClear();
});

describe("the panel shows what Autark gives (plan 2.0)", () => {
  // Curio's Autark node hands a building on one row per part; this one's
  // second part has only building:levels, so the reader derives its height.
  const TWO_PARTS = layer("table_osm_buildings", "buildings", [
    { building_id: 34, height: 120, name: "Tower" },
    { building_id: 34, "building:levels": 10 },
  ]);

  test("a pick names one part: the field holds exactly that row's properties as the map drew them", async () => {
    mountNode({ input: inputOf(TWO_PARTS) });
    await screen.findByTestId("autark-map");
    pickRows([1]);

    expect(selectedId()).toBe("34");
    expect(field().value).toBe(JSON.stringify({ building_id: 34, "building:levels": 10, height: METRES_PER_LEVEL * 10 }, null, 2));
    expect(screen.getByTestId("map-edits-applies-to")).toHaveTextContent("Applies to the 2 features with building_id 34");
  });

  test("editing another key writes only that key: the derived height is never written", async () => {
    const node = mountNode({ input: inputOf(TWO_PARTS) });
    await screen.findByTestId("autark-map");
    pickRows([1]);
    typeJson({ ...fieldJson(), name: "Annex" });
    apply();

    expect(node.edits().change).toEqual([{ id: 34, values: { name: "Annex" } }]);
    expect(node.entries().map((entry) => entry.label)).toEqual(['name "Annex" on building_id 34']);
  });
});

describe("a pick", () => {
  test("selects the first row it names, one feature at a time, and a pick on nothing keeps it", async () => {
    mountNode();
    await screen.findByTestId("autark-map");
    expect(selectedId()).toBeNull();
    expect(panel()).toHaveTextContent("Double-click a building to see and edit its OSM information.");

    pickRows([1, 2]);
    expect(selectedId()).toBe("119");
    expect(fieldJson()).toEqual({ building_id: 119, height: 60 });
    pickRows([2]);
    expect(selectedId()).toBe("136");
    pickRows([]);
    expect(selectedId()).toBe("136");
  });

  test("names a row of the layer as the edits leave it, which is the input row it stands for", async () => {
    mountNode({ code: codeOf({ remove: [119] }) });
    await screen.findByTestId("autark-map");
    // The map draws 136 alone, at its row 0.
    expect(drawnIds()).toEqual([136]);
    pickRows([0]);
    expect(selectedId()).toBe("136");
    expect(fieldJson()).toEqual({ building_id: 136, height: 60 });
  });

  test("Escape on the body clears it; Escape in the field is the field's", async () => {
    mountNode();
    await screen.findByTestId("autark-map");
    pickRows([2]);
    fireEvent.keyDown(field(), { key: "Escape" });
    expect(selectedId()).toBe("136");
    expect(fireEvent.keyDown(body(), { key: "Escape" })).toBe(false);
    expect(selectedId()).toBeNull();
  });
});

describe("Apply", () => {
  test("writes what differs for the feature's id, and the feature stays in the panel with its new values", async () => {
    const node = mountNode();
    await screen.findByTestId("autark-map");
    pickRows([2]);
    expect(screen.queryByTestId("map-edits-applies-to")).toBeNull();
    typeJson({ building_id: 136, height: 75 });
    apply();

    expect(node.edits()).toEqual({ key: "building_id", remove: [], change: [{ id: 136, values: { height: 75 } }] });
    expect(node.setCode).toHaveBeenLastCalledWith(node.live().code);
    expect(node.live().defaultCode).toBe(node.live().code);
    expect(selectedId()).toBe("136");
    await waitFor(() => expect(fieldJson()).toEqual({ building_id: 136, height: 75 }));
    // The map draws the new height at once.
    const drawn = mockMapData.input.data[0].geojson.features.map((f: any) => f.properties);
    expect(drawn).toEqual([{ building_id: 119, height: 240 }, { building_id: 119, height: 60 }, { building_id: 136, height: 75 }]);
  });

  test("a value typed back to the input's leaves the edits, and a deleted key is written as null", async () => {
    const node = mountNode({ code: codeOf({ change: [{ id: 136, values: { height: 75 } }] }) });
    await screen.findByTestId("autark-map");
    pickRows([2]);
    expect(fieldJson()).toEqual({ building_id: 136, height: 75 });
    typeJson({ building_id: 136, height: 60 });
    apply();
    expect(node.edits().change).toEqual([]);

    typeJson({ building_id: 136 });
    apply();
    expect(node.edits().change).toEqual([{ id: 136, values: { height: null } }]);
    expect(node.entries().map((entry) => entry.label)).toEqual(["height 60 on building_id 136", "height cleared on building_id 136"]);
  });

  test("an Apply that changes nothing writes no code and files no entry", async () => {
    const node = mountNode();
    await screen.findByTestId("autark-map");
    pickRows([2]);
    apply();
    // The same values, written another way.
    fireEvent.change(field(), { target: { value: '{"height":60,"building_id":136}' } });
    apply();
    expect(node.setCode).not.toHaveBeenCalled();
    expect(node.markDirty).not.toHaveBeenCalled();
    expect(node.entries()).toEqual([]);
    expect(screen.queryByTestId("map-edits-problem")).toBeNull();
  });

  test("refuses a new value of the Id column, and says why under the field", async () => {
    const node = mountNode();
    await screen.findByTestId("autark-map");
    pickRows([2]);
    typeJson({ building_id: 137, height: 60 });
    apply();
    expect(screen.getByTestId("map-edits-problem")).toHaveTextContent("building_id identifies the feature, so its value cannot change.");
    expect(node.setCode).not.toHaveBeenCalled();
    // The next keystroke takes the refusal away.
    typeJson({ building_id: 136, height: 61 });
    expect(screen.queryByTestId("map-edits-problem")).toBeNull();
  });

  test("JSON that does not read shows the parser's message and holds Apply", async () => {
    const node = mountNode();
    await screen.findByTestId("autark-map");
    pickRows([2]);
    fireEvent.change(field(), { target: { value: '{"building_id": 136, "height": }' } });
    let reason = "";
    try {
      JSON.parse('{"building_id": 136, "height": }');
    } catch (error) {
      reason = (error as Error).message;
    }
    expect(screen.getByTestId("map-edits-problem")).toHaveTextContent(reason);
    expect(screen.getByTestId("map-edits-apply")).toBeDisabled();
    apply();
    expect(node.setCode).not.toHaveBeenCalled();
    typeJson({ building_id: 136, height: 60 });
    expect(screen.getByTestId("map-edits-apply")).toBeEnabled();
  });

  test("a feature of several parts: Apply writes the change for its id, which every part takes", async () => {
    const node = mountNode();
    await screen.findByTestId("autark-map");
    pickRows([0]);
    expect(screen.getByTestId("map-edits-applies-to")).toHaveTextContent("Applies to the 2 features with building_id 119");
    typeJson({ building_id: 119, height: 200 });
    apply();
    expect(node.edits().change).toEqual([{ id: 119, values: { height: 200 } }]);
    const heights = mockMapData.input.data[0].geojson.features.map((f: any) => f.properties.height);
    expect(heights).toEqual([200, 200, 60]);
  });
});

describe("Remove and put back", () => {
  test("Remove takes out the features with the selected id, clears the selection and lists the id", async () => {
    const node = mountNode();
    await screen.findByTestId("autark-map");
    pickRows([1]);
    remove();

    expect(node.edits()).toEqual({ key: "building_id", remove: [119], change: [] });
    expect(selectedId()).toBeNull();
    expect(drawnIds()).toEqual([136]);
    const removed = screen.getByTestId("map-edits-removed");
    expect(removed).toHaveTextContent(/^Removed: 119$/);
    expect(removed.querySelector('[data-map-edits-put-back="119"]')).toHaveTextContent(/^119$/);
  });

  test("Delete or Backspace on the body removes; in the field it is the field's", async () => {
    const node = mountNode();
    await screen.findByTestId("autark-map");
    pickRows([2]);
    fireEvent.keyDown(field(), { key: "Delete" });
    fireEvent.keyDown(field(), { key: "Backspace" });
    expect(node.setCode).not.toHaveBeenCalled();
    expect(selectedId()).toBe("136");

    // Handled here, so the canvas neither deletes the node nor moves it.
    expect(fireEvent.keyDown(body(), { key: "Backspace" })).toBe(false);
    expect(node.edits().remove).toEqual([136]);
    // Nothing selected: the node leaves Delete alone.
    expect(fireEvent.keyDown(body(), { key: "Delete" })).toBe(true);
  });

  test("a click on a removed id puts its features back and clears the selection", async () => {
    const node = mountNode({ code: codeOf({ remove: [119, 136] }) });
    await screen.findByTestId("autark-map");
    fireEvent.click(document.querySelector('[data-map-edits-put-back="119"]')!);

    expect(node.edits().remove).toEqual([136]);
    expect(screen.getByTestId("map-edits-removed")).toHaveTextContent(/^Removed: 136$/);
    expect(drawnIds()).toEqual([119, 119]);
    expect(node.entries().map((entry) => entry.label)).toEqual(["put back building_id 119"]);
  });

  test("the Removed line lists about 40 ids, then how many more", async () => {
    const ids = Array.from({ length: 45 }, (_, i) => 1000 + i);
    mountNode({ code: codeOf({ remove: ids }) });
    await screen.findByTestId("autark-map");
    const removed = screen.getByTestId("map-edits-removed");
    expect(removed.querySelectorAll("[data-map-edits-put-back]")).toHaveLength(40);
    expect(removed).toHaveTextContent(/1039 and 5 more$/);
  });

  test("a click on a changed id shows that feature's properties", async () => {
    mountNode({ code: codeOf({ change: [{ id: 136, values: { height: 75 } }] }) });
    await screen.findByTestId("autark-map");
    const changed = screen.getByTestId("map-edits-changed");
    expect(changed).toHaveTextContent(/^Changed: 136$/);
    fireEvent.click(within(changed).getByRole("button", { name: "136" }));
    expect(selectedId()).toBe("136");
    expect(fieldJson()).toEqual({ building_id: 136, height: 75 });
  });
});

describe("each change", () => {
  /**
   * The node feeds a rasterizer, which feeds a model; a chart is linked to it
   * by an interaction edge only, which carries a selection and runs nothing.
   */
  const BELOW = {
    more: [{ id: "rasterize", data: {} }, { id: "model", data: {} }, { id: "chart", data: {} }],
    edges: [
      { id: "e1", source: NODE, target: "rasterize", sourceHandle: "out", targetHandle: "in" },
      { id: "e2", source: "rasterize", target: "model", sourceHandle: "out", targetHandle: "in" },
      { id: "e3", source: NODE, target: "chart", sourceHandle: "in/out", targetHandle: "in/out" },
    ],
    nodeExecStatus: { [NODE]: "executed", rasterize: "executed", model: "executed", chart: "executed" },
  };

  test("leaves the dataflow unsaved, makes the node and every node below it that ran stale, and asks for an automatic run", async () => {
    const node = mountNode({ flow: BELOW, output: { code: "success", content: "Saved to file: art_out" } });
    await screen.findByTestId("autark-map");
    pickRows([2]);
    remove();

    expect(node.markDirty).toHaveBeenCalledTimes(1);
    expect(node.markNodeStale.mock.calls.map((call) => call[0]).sort()).toEqual([NODE, "model", "rasterize"]);
    expect(node.requestAutoRun).toHaveBeenCalledWith([NODE]);
  });

  test("files one entry in the node's Provenance at once, holding the code it left, each descending from the one before", async () => {
    const node = mountNode();
    await screen.findByTestId("autark-map");
    pickRows([2]);
    typeJson({ building_id: 136, height: 75 });
    apply();
    const afterApply = node.live().code;
    pickRows([0]);
    remove();
    const afterRemove = node.live().code;
    fireEvent.click(document.querySelector('[data-map-edits-put-back="119"]')!);

    const entries = node.entries();
    expect(entries.map((entry) => entry.label)).toEqual([
      "height 75 on building_id 136",
      "remove building_id 119",
      "put back building_id 119",
    ]);
    expect(entries.map((entry) => entry.kind)).toEqual(["edit", "edit", "edit"]);
    expect(entries.map((entry) => entry.code)).toEqual([afterApply, afterRemove, node.live().code]);
    expect(entries.map((entry) => entry.parentId)).toEqual([null, entries[0].id, entries[1].id]);
    expect(entries.every((entry) => entry.inputs.length === 0 && entry.outputs.length === 0)).toBe(true);
  });

  test("keeps the comment lines above the code's call", async () => {
    const node = mountNode({ code: `# SCOUT's 15 removed buildings.\n${codeOf({ remove: [119] })}` });
    await screen.findByTestId("autark-map");
    // The map draws what the code leaves: building 136 alone, at row 0.
    pickRows([0]);
    remove();
    expect(node.live().code.startsWith("# SCOUT's 15 removed buildings.\n")).toBe(true);
    expect(node.edits().remove).toEqual([119, 136]);
  });
});

describe("the map", () => {
  test("draws every layer inline, the one to edit as the edits leave it, on top and pickable, and keeps its view", async () => {
    mountNode({ code: codeOf({ layer: "table_osm_buildings", remove: [136] }), input: inputOf(ROADS, BUILDINGS) });
    await screen.findByTestId("autark-map");
    await waitFor(() => expect(mockApply).toHaveBeenCalled());

    expect(mockMapData.input.dataType).toBe("list");
    expect(mockMapData.input.data.map((record: any) => [record.name, record.type])).toEqual([
      ["table_osm_roads", "roads"],
      ["table_osm_buildings", "buildings"],
    ]);
    expect(mockMapData.input.data[0].geojson.features).toHaveLength(2);
    expect(drawnIds()).toEqual([119, 119]);
    const doc = JSON.parse(mockApply.mock.calls[mockApply.mock.calls.length - 1][0]);
    expect(doc.map.layerRefs).toEqual([{ dataRef: "table_osm_roads" }, { dataRef: "table_osm_buildings", isPick: true }]);
    // A draw of the map is not a run of the node, and an edit keeps the view.
    expect(mockMapOptions).toEqual({ marksNodeErrored: false, recordsProvenance: false, keepsView: true });
  });

  test("an edit draws the map again, with no run", async () => {
    mountNode();
    await screen.findByTestId("autark-map");
    await waitFor(() => expect(mockApply).toHaveBeenCalledTimes(1));
    pickRows([2]);
    remove();
    await waitFor(() => expect(mockApply).toHaveBeenCalledTimes(2));
    expect(drawnIds()).toEqual([119, 119]);
  });
});

describe("the Layer and Id menus", () => {
  const KEYED = layer("table_osm_buildings", "buildings", [
    { osm_id: 1001, building_id: 7, height: 30 },
    { osm_id: 1002, building_id: 7, height: 40 },
  ]);

  test("show while the node holds no edits; a new Id writes the code, with no entry and no run", async () => {
    const node = mountNode({ input: inputOf(ROADS, KEYED) });
    await screen.findByTestId("autark-map");
    const id = screen.getByRole("combobox", { name: "Id" });
    expect(id).toHaveValue("osm_id");
    expect(id).toBeEnabled();
    expect(screen.getByRole("combobox", { name: "Layer" })).toHaveValue("table_osm_buildings");
    expect(screen.getByRole("combobox", { name: "Layer" })).toBeEnabled();

    fireEvent.change(id, { target: { value: "building_id" } });
    expect(node.edits()).toEqual({ key: "building_id", layer: "table_osm_buildings", remove: [], change: [] });
    expect(node.markDirty).toHaveBeenCalled();
    expect(node.requestAutoRun).not.toHaveBeenCalled();
    expect(node.entries()).toEqual([]);
  });

  test("are held while the node has edits, and say why", async () => {
    mountNode({ code: codeOf({ key: "osm_id", layer: "table_osm_buildings", remove: [1001] }), input: inputOf(ROADS, KEYED) });
    await screen.findByTestId("autark-map");
    for (const name of ["Layer", "Id"]) {
      const menu = screen.getByRole("combobox", { name });
      expect(menu).toBeDisabled();
      expect(menu.getAttribute("title")).toMatch(/neither can change while the node holds any/);
    }
  });

  test("a single layer shows no Layer menu", async () => {
    mountNode();
    await screen.findByTestId("autark-map");
    expect(screen.queryByTestId("edit-features-layer")).toBeNull();
    expect(screen.getByTestId("edit-features-key")).toHaveValue("building_id");
  });
});

test("code of another shape is never rewritten: the node says why, offers nothing, and draws the input as it came", async () => {
  const code = "# A hand edit.\nreturn input_0\n";
  const node = mountNode({ code });
  await screen.findByTestId("autark-map");
  const read = readMapEdits(code);
  expect(screen.getByTestId("map-edits-unreadable")).toHaveTextContent("problem" in read ? read.problem : "");
  expect(drawnIds()).toEqual([119, 119, 136]);
  pickRows([2]);
  expect(selectedId()).toBeNull();
  expect(screen.queryByTestId("edit-features-remove")).toBeNull();
  expect(screen.queryByTestId("map-edits-apply")).toBeNull();
  expect(screen.getByRole("combobox", { name: "Id" })).toBeDisabled();
  fireEvent.keyDown(body(), { key: "Delete" });
  expect(node.setCode).not.toHaveBeenCalled();
  expect(node.live().code).toBe(code);
});

test.each([
  ["on the dashboard", { dashboardOn: true }],
  ["in a shared view", { viewerMode: "shared" }],
])("%s the panel only shows: the field is read-only, and there is no Apply, Remove or put back", async (_where, flow) => {
  const node = mountNode({ code: codeOf({ remove: [119] }), flow });
  await screen.findByTestId("autark-map");
  expect(screen.getByTestId("map-edits-removed")).toHaveTextContent(/^Removed: 119$/);
  expect(document.querySelector("[data-map-edits-put-back]")).toBeNull();
  pickRows([0]);
  expect(selectedId()).toBe("136");
  expect(field().readOnly).toBe(true);
  expect(screen.queryByTestId("map-edits-apply")).toBeNull();
  expect(screen.queryByTestId("edit-features-remove")).toBeNull();
  fireEvent.keyDown(body(), { key: "Delete" });
  expect(node.setCode).not.toHaveBeenCalled();
  expect(node.entries()).toEqual([]);
});

test("a layer with no column that identifies its features is refused, and nothing can be picked", async () => {
  mountNode({ input: inputOf(layer("lots", "polygons", [{ __row_index__: 0, kind: "x" }, { __row_index__: 1, kind: "x" }])) });
  const refusal = await waitFor(() => {
    const element = document.querySelector("[data-map-edits-refusal]");
    expect(element).not.toBeNull();
    return element!;
  });
  expect(refusal.textContent).toMatch(/^lots has no column that identifies its features/);
  expect(refusal.textContent).toMatch(/Map Edits matches features by such a column/);
  expect(screen.queryByTestId("autark-map")).toBeNull();
  expect(screen.queryByTestId("edit-features-remove")).toBeNull();
  expect(document.querySelector("[data-map-edits-panel]")).toBeNull();
});

test("a failed run says why in a line of its own", async () => {
  mountNode({ output: { code: "error", content: "Traceback (most recent call last):\nValueError: Map Edits: the input has no layer roads." } });
  await screen.findByTestId("autark-map");
  expect(document.querySelector("[data-map-edits-run-error]")).toHaveTextContent(/^Map Edits: the input has no layer roads\.$/);
});

test("a node just dropped gets the code of no edits, which the node reads", async () => {
  const node = mountNode();
  await screen.findByTestId("autark-map");
  const code = node.behavior().defaultValueOverride!;
  expect(readMapEdits(code)).toEqual({ edits: { remove: [], change: [] }, comments: expect.any(Array) });
  expect(code).toContain("return curio_map_edits(\n    input_0,");
});

// Compare Scenarios is gone (step 6.4 of the plan answering komar41's review
// of the #914 merges), and What differs, which listed this node's edits, with
// it: the node's behavior takes nothing from it.
test("the node's behavior imports nothing of Compare Scenarios", () => {
  const source = fs.readFileSync(path.resolve(__dirname, "../../../adapters/node/mapEditsBehavior.tsx"), "utf-8");
  expect(source.match(/from\s+["'][^"']*compare[^"']*["']/gi) ?? []).toEqual([]);
});
