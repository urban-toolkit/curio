/**
 * The node of type `curio.builtin/edit-features`, as the canvas resolves it:
 * the behavior curio.builtin@1's manifest names for the type, from the
 * registry (registry/builtinBehaviors). Its edits are held in its code, so a
 * run's code put back from the Provenance drawer shows that run's edits; an
 * edit leaves the dataflow unsaved; and its map draws the layer as the edits
 * leave it.
 *
 * Written only against what the node offers whatever its body: its input read
 * by utils/autkInput, its map drawn by the Autark node's map code, a pick
 * reported as an Autark node reports one, naming the building by its
 * building_id, and the Remove button's test id.
 */
import fs from "fs";
import path from "path";
import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { NodeBehaviorData, UseNodeStateReturn } from "../../../registry/types";
import { VisInteractionType } from "../../../constants";

// The built-in behaviors pull in vega and vega-lite, whose ESM Jest's default
// transform skips; this suite never compiles a chart.
jest.mock("vega", () => ({}), { virtual: true });
jest.mock("vega-lite", () => ({}), { virtual: true });

const mockFlowContext = React.createContext<Record<string, any>>({});
jest.mock("../../../providers/FlowProvider", () => ({
  useFlowContext: () => require("react").useContext(mockFlowContext),
}));

// The input, as the Autark map reads it: its layers by table name.
let mockSources: any[] = [];
jest.mock("../../../utils/autkInput", () => ({
  ...jest.requireActual("../../../utils/autkInput"),
  readAutkInput: jest.fn(() => Promise.resolve({ frames: mockSources.map((s: any) => ({ name: s.outputTableName })) })),
  autkSourcesFrom: jest.fn(() => ({ sources: mockSources })),
}));

// The Autark node's map code, as the node's map calls it: the last input it
// was handed, and where a pick goes.
const mockApply = jest.fn().mockResolvedValue(undefined);
let mockMapData: any = null;
jest.mock("../../../adapters/node/autkGrammarBehavior", () => ({
  useAutkGrammarBehavior: (data: any) => {
    mockMapData = data;
    return { applyGrammar: mockApply, contentComponent: <div data-testid="autark-map" /> };
  },
}));

import { getBehavior } from "../../../registry/behaviorRegistry";
import "../../../registry/builtinBehaviors";
import { noteCodeEdit } from "../../../utils/references/codeEdits";

const MANIFEST = JSON.parse(
  fs.readFileSync(path.resolve(__dirname, "../../../../../../../packages/curio.builtin@1/manifest.json"), "utf8"),
);
const TEMPLATE = MANIFEST.templates.find((template: any) => template.id === "edit-features");
const useNodeBehavior = getBehavior(TEMPLATE.behavior)!;

const NODE = "edit-1";
const INPUT = { path: "art_buildings", dataType: "geodataframe" };

function feature(properties: Record<string, unknown>) {
  return { type: "Feature", geometry: { type: "Polygon", coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] }, properties };
}

/** Buildings as Curio's Autark node hands them on: one row per part, a building's parts sharing its building_id. */
const BUILDINGS = {
  outputTableName: "table_osm_buildings",
  layerType: "buildings",
  geojsonObject: {
    type: "FeatureCollection",
    features: [
      feature({ building_id: 119, height: 240 }),
      feature({ building_id: 119, height: 60 }),
      feature({ building_id: 136, height: 60 }),
    ],
  },
};

/** The node on a canvas whose flow writes what the node writes, as the canvas does. */
function mountNode() {
  const markDirty = jest.fn();
  const markNodeStale = jest.fn();
  const setCode = jest.fn();
  let current: any = { nodeId: NODE, input: INPUT, code: "", defaultCode: "" };

  function Node({ data, state }: { data: any; state: UseNodeStateReturn }) {
    const behavior = useNodeBehavior(data as NodeBehaviorData, state);
    return <>{behavior.contentComponent}</>;
  }

  function Canvas() {
    const [live, setLive] = React.useState<any>(current);
    current = live;
    const flow = {
      nodes: [{ id: NODE, data: live }],
      edges: [],
      nodeExecStatus: {},
      updateDataNode: (id: string, next: any) => {
        if (id === NODE) setLive({ ...next });
      },
      markNodeStale,
      markDirty,
      requestAutoRun: jest.fn(),
    };
    const state = { output: { code: "", content: "" }, setOutput: jest.fn(), code: live.code ?? "", setCode } as unknown as UseNodeStateReturn;
    return (
      <mockFlowContext.Provider value={flow}>
        <Node data={live} state={state} />
      </mockFlowContext.Provider>
    );
  }

  render(<Canvas />);
  return { markDirty, setCode, live: () => current };
}

/** A pick on the map, as an Autark node reports one whose layer names building_id. */
function pickBuilding(buildingId: number) {
  act(() => {
    mockMapData.interactionsCallback({
      autk_selection: {
        type: VisInteractionType.POINT,
        data: [{ building_id: buildingId }],
        priority: 1,
        layerRef: "table_osm_buildings",
      },
    }, NODE);
  });
}

function removePicked() {
  fireEvent.click(screen.getByTestId("edit-features-remove"));
}

/** Whether the node says *id* is removed: an element whose own text names it after "Remove". */
function shownAsRemoved(id: number): boolean {
  const says = new RegExp(`\\bremov(e|ed)\\b[^]*\\b${id}\\b`, "i");
  return Array.from(document.body.querySelectorAll("*")).some(
    (element) =>
      says.test(element.textContent ?? "")
      && Array.from(element.children).every((child) => !says.test(child.textContent ?? "")),
  );
}

/** The ids, in *key*, of every feature the map was handed. */
function featureIdsIn(value: unknown, key: string): unknown[] {
  const found: unknown[] = [];
  const walk = (item: any) => {
    if (!item || typeof item !== "object") return;
    if (Array.isArray(item)) {
      item.forEach(walk);
      return;
    }
    if (item.type === "Feature" && item.properties) {
      found.push(item.properties[key]);
      return;
    }
    Object.values(item).forEach(walk);
  };
  walk(value);
  return found;
}

beforeEach(() => {
  mockSources = [BUILDINGS];
  mockMapData = null;
  mockApply.mockClear();
});

test("a run's code put back in the node shows that run's edits", async () => {
  const node = mountNode();
  await screen.findByTestId("autark-map");
  pickBuilding(119);
  removePicked();
  await waitFor(() => expect(node.setCode).toHaveBeenCalled());
  const firstRun = node.setCode.mock.calls[node.setCode.mock.calls.length - 1][0];

  pickBuilding(136);
  removePicked();
  await waitFor(() => expect(shownAsRemoved(136)).toBe(true));

  // The Provenance drawer's "Put this code back in the node" writes the code
  // into the node, as useNodeState does, and the code's edits are the node's.
  act(() => {
    node.live().code = firstRun;
    noteCodeEdit();
  });
  await waitFor(() => expect(shownAsRemoved(136)).toBe(false));
  expect(shownAsRemoved(119)).toBe(true);
});

test("an edit leaves the dataflow unsaved", async () => {
  const node = mountNode();
  await screen.findByTestId("autark-map");
  pickBuilding(119);
  removePicked();
  await waitFor(() => expect(node.markDirty).toHaveBeenCalled());
});

test("the map draws the layer as the edits leave it", async () => {
  mountNode();
  await screen.findByTestId("autark-map");
  pickBuilding(119);
  removePicked();
  await waitFor(() => {
    const drawn = featureIdsIn(mockMapData.input, "building_id");
    expect(drawn).toContain(136);
    expect(drawn).not.toContain(119);
  });
});
