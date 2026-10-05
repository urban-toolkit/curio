/**
 * The Compare Scenarios node (#662) in Difference, on the canvas. The node
 * picks Difference for two rasters or two layers that have run and Chart for
 * anything else, writes its code for the view (and the key it joins rows on),
 * and the user can switch. Its body maps a raster's or a layer's difference
 * through the Autark node's map code, and shows a table's through the
 * Vega-Lite node's.
 */
import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { NodeBehaviorData, UseNodeStateReturn } from "../../../registry/types";

let mockFlow: Record<string, any> = {};
const mockFlowContext = React.createContext<Record<string, any>>({});
const mockUpdateDataNode = jest.fn();
const mockMarkNodeStale = jest.fn();
const mockMarkDirty = jest.fn();
jest.mock("../../../providers/FlowProvider", () => ({
  useFlowContext: () => require("react").useContext(mockFlowContext),
}));

jest.mock("../../../utils/palettePackageFactoryDraft", () => ({
  resolveNodeDisplayLabel: (data: any) => data.title ?? data.nodeId,
}));

const mockCompile = jest.fn().mockResolvedValue({ rowsIn: 2, drawn: 2 });
const mockUseVega = jest.fn((_options: any) => ({ handleCompileGrammar: mockCompile }));
jest.mock("../../../hook/useVega", () => ({
  useVega: (options: any) => mockUseVega(options),
}));
jest.mock("vega", () => ({}), { virtual: true });
jest.mock("vega-lite", () => ({}), { virtual: true });

// What a read of a reference finds, by its path.
let mockFrames: Record<string, any[]> = {};
jest.mock("../../../utils/grammarInput", () => ({
  readGrammarInput: jest.fn((ref: any) => Promise.resolve({ frames: mockFrames[ref?.path] ?? [] })),
}));

// The Autark node's map code, as the difference map calls it.
const mockApply = jest.fn().mockResolvedValue(undefined);
const mockAutk = jest.fn((_data: any, _state: any, _options: any) => ({
  applyGrammar: mockApply,
  contentComponent: <div data-testid="autark-map" />,
}));
jest.mock("../../../adapters/node/autkGrammarBehavior", () => ({
  useAutkGrammarBehavior: (data: any, state: any, options: any) => mockAutk(data, state, options),
}));

import { useCompareScenariosBehavior } from "../../../adapters/node/compareScenariosBehavior";
import { differenceCode, stackCode } from "../../../utils/compare/compareCode";
import { differenceTableSpec } from "../../../utils/compare/compareDifference";

const COMPARE = "cmp";
const BASE = { scenario: "s-base", name: "Baseline", color: "#2a9d8f" };
const TALL = { scenario: "s-tall", name: "Twice as tall", color: "#e76f51" };
const INPUTS = [
  { slot: 0, label: BASE },
  { slot: 1, label: TALL },
];
const STACKED = stackCode(INPUTS);
const DIFFERENCE = differenceCode(INPUTS);

const node = (id: string, data: Record<string, unknown> = {}) => ({
  id,
  type: "__curioUniversalNode",
  data: { nodeId: id, nodeType: "curio.builtin/computation-analysis@1", code: "return arg", ...data },
});
const edge = (source: string, target: string, targetHandle = "in") => ({
  id: `${source}-${target}-${targetHandle}`, source, target, sourceHandle: "out", targetHandle,
});

/** What each circle holds once the scenarios' outcomes have run. */
const holding = (dataType: string) => [
  { path: `${dataType}-a`, dataType },
  { path: `${dataType}-b`, dataType },
];

function graph(compareData: Record<string, unknown> = {}) {
  const nodes = [
    node("a", { title: "Shade" }),
    node("b", { title: "Shade", copiedFrom: ["a"] }),
    node(COMPARE, {
      nodeType: "curio.builtin/compare-scenarios@1",
      title: "Compare",
      compareScenarios: { inputs: [BASE, TALL] },
      ...compareData,
    }),
  ];
  const edges = [edge("a", COMPARE, "in"), edge("b", COMPARE, "in_1")];
  const scenarios = [
    { id: "s-base", name: "Baseline", color: "#2a9d8f", nodes: ["a"] },
    { id: "s-tall", name: "Twice as tall", color: "#e76f51", nodes: ["b"] },
  ];
  return { nodes, edges, scenarios };
}

function flowOf(g: ReturnType<typeof graph>, extra: Record<string, unknown> = {}) {
  return {
    ...g,
    outputs: [],
    updateDataNode: mockUpdateDataNode,
    markNodeStale: mockMarkNodeStale,
    markDirty: mockMarkDirty,
    dashboardOn: false,
    viewerMode: "owner",
    ...extra,
  };
}

function nodeState(output: { code: string; content?: string } = { code: "" }) {
  return { setCode: jest.fn(), output } as unknown as UseNodeStateReturn;
}

function Node({ data, state }: { data: any; state: UseNodeStateReturn }) {
  const behavior = useCompareScenariosBehavior(data as NodeBehaviorData, state);
  return <>{behavior.contentComponent}</>;
}

function Harness({ data, state }: { data: any; state: UseNodeStateReturn }) {
  return (
    <mockFlowContext.Provider value={mockFlow}>
      <Node data={data} state={state} />
    </mockFlowContext.Provider>
  );
}

function mount(compareData: Record<string, unknown>, state = nodeState(), extra: Record<string, unknown> = {}) {
  const g = graph(compareData);
  const compare = g.nodes.find((n) => n.id === COMPARE)!;
  mockFlow = flowOf(g, extra);
  return { view: render(<Harness data={compare.data} state={state} />), state };
}

/** The code the node wrote, if it wrote any. */
const writtenCode = () => mockUpdateDataNode.mock.calls.at(-1)?.[1]?.code;

beforeEach(() => {
  mockUpdateDataNode.mockReset();
  mockMarkNodeStale.mockReset();
  mockMarkDirty.mockReset();
  mockCompile.mockClear();
  mockUseVega.mockClear();
  mockApply.mockClear();
  mockAutk.mockClear();
  mockFrames = {};
});

describe("the view it picks, and the code it writes for it", () => {
  test("two rasters that have run: Difference, and a node that had run goes stale", () => {
    const { state } = mount({ inputSlots: holding("raster"), code: STACKED, defaultCode: STACKED }, nodeState({ code: "success" }));
    expect(writtenCode()).toBe(DIFFERENCE);
    expect(state.setCode).toHaveBeenCalledWith(DIFFERENCE);
    expect(mockUpdateDataNode.mock.calls.at(-1)![1].compareScenarios).toEqual({ inputs: [BASE, TALL] });
    expect(mockMarkNodeStale).toHaveBeenCalledWith(COMPARE);
  });

  test("two layers: Difference too", () => {
    mount({ inputSlots: holding("geodataframe"), code: STACKED, defaultCode: STACKED });
    expect(writtenCode()).toBe(DIFFERENCE);
  });

  test("two tables, or a raster beside a layer: the Chart it has", () => {
    mount({ inputSlots: holding("dataframe"), code: STACKED, defaultCode: STACKED });
    mount({ inputSlots: [holding("raster")[0], holding("geodataframe")[1]], code: STACKED, defaultCode: STACKED });
    expect(mockUpdateDataNode).not.toHaveBeenCalled();
  });

  test("while its inputs have not run, as after a load, the code stays as it was written", async () => {
    mount({ code: DIFFERENCE, defaultCode: DIFFERENCE });
    await act(async () => {});
    expect(mockUpdateDataNode).not.toHaveBeenCalled();
    expect(screen.getByRole("tab", { name: "Difference" })).not.toBeNull();
  });

  test("the user's choice wins over what the inputs call for", () => {
    mount({ inputSlots: holding("raster"), code: DIFFERENCE, compareScenarios: { inputs: [BASE, TALL], mode: "chart" } });
    expect(writtenCode()).toBe(STACKED);
    mockUpdateDataNode.mockReset();
    mount({ inputSlots: holding("dataframe"), code: STACKED, compareScenarios: { inputs: [BASE, TALL], mode: "difference" } });
    expect(writtenCode()).toBe(DIFFERENCE);
  });

  test("the key Difference joins rows on is written into its code", () => {
    mount({
      inputSlots: holding("dataframe"),
      code: DIFFERENCE,
      compareScenarios: { inputs: [BASE, TALL], mode: "difference", difference: { key: "segment" } },
    });
    expect(writtenCode()).toBe(differenceCode(INPUTS, "segment"));
  });

  test("code written by hand is left until an input changes", () => {
    mount({ inputSlots: holding("raster"), code: "return arg[1]", defaultCode: "return arg[1]" });
    expect(mockUpdateDataNode).not.toHaveBeenCalled();
  });
});

describe("its body in Difference", () => {
  const ran = { code: "success", content: "Saved to file: diff-1" };

  test("its first tab is Difference, and Compare as switches it to Chart", () => {
    mount({ inputSlots: holding("raster"), code: DIFFERENCE });
    expect(screen.getByRole("tab", { name: "Difference" })).not.toBeNull();
    const select = screen.getByRole("combobox", { name: "Compare as" }) as HTMLSelectElement;
    expect(select.value).toBe("difference");
    fireEvent.change(select, { target: { value: "chart" } });
    expect(mockUpdateDataNode).toHaveBeenCalledWith(
      COMPARE,
      expect.objectContaining({ compareScenarios: { inputs: [BASE, TALL], mode: "chart" } }),
    );
    expect(mockMarkDirty).toHaveBeenCalled();
  });

  test("a raster's difference is mapped by the Autark node's map code, which hands nothing on", async () => {
    mockFrames["diff-1"] = [{
      dataType: "raster",
      payload: { envelope: { dataType: "raster", data: { features: [{ properties: { bands: [{ id: "band_1" }] } }] } } },
      schema: null,
      geometryName: null,
    }];
    mount({ inputSlots: holding("raster"), code: DIFFERENCE }, nodeState(ran));
    await screen.findByTestId("autark-map");
    const [data, state, options] = mockAutk.mock.calls.at(-1)!;
    // The node's own canvas, autk-grammar-map-<its id>, over its own output.
    expect(data.nodeId).toBe(COMPARE);
    expect(data.input).toEqual({ path: "diff-1" });
    expect(data.outputCallback).toBeUndefined();
    expect(data.interactionsCallback).toBeUndefined();
    // A map that cannot draw leaves the node's outcome as its run left it.
    expect(options).toEqual({ marksNodeErrored: false });
    expect(state.output).toEqual({ code: "", content: "" });
    await waitFor(() => expect(mockApply).toHaveBeenCalled());
    expect(JSON.parse(mockApply.mock.calls.at(-1)![0])).toEqual({
      map: { layerRefs: [{ dataRef: "input_0", getFnv: "band_1", colorMapInterpolator: "interpolateRdBu" }] },
    });
    expect(screen.getByText(/the middle color is halfway between them, not zero/)).not.toBeNull();
    expect(screen.queryByRole("combobox", { name: "Key" })).toBeNull();
  });

  test("a layer's difference is colored by its first number, or by its change", async () => {
    mockFrames["diff-1"] = [{
      dataType: "geodataframe",
      payload: { type: "FeatureCollection", features: [{ properties: { osm_id: 1, change: "changed", sunlight: -2 } }] },
      schema: { osm_id: "int64", change: "object", sunlight: "float64" },
      geometryName: "geometry",
    }];
    mount({ inputSlots: holding("geodataframe"), code: DIFFERENCE }, nodeState(ran));
    await screen.findByTestId("autark-map");
    await waitFor(() => expect(mockApply).toHaveBeenCalled());
    expect(JSON.parse(mockApply.mock.calls.at(-1)![0]).map.layerRefs[0]).toEqual({
      dataRef: "input_0", getFnv: "sunlight", getFnvType: "quantitative", colorMapInterpolator: "interpolateRdBu",
    });
    fireEvent.change(screen.getByRole("combobox", { name: "Color by" }), { target: { value: "change" } });
    expect(mockUpdateDataNode).toHaveBeenCalledWith(
      COMPARE,
      expect.objectContaining({ compareScenarios: { inputs: [BASE, TALL], difference: { value: "change" } } }),
    );
  });

  test("the key it joins on is offered from the columns both inputs have", async () => {
    mockFrames["dataframe-a"] = [{ dataType: "dataframe", payload: { segment: { 0: "r1" }, sunlight: { 0: 1 } }, schema: { segment: "object", sunlight: "float64" }, geometryName: null }];
    mockFrames["dataframe-b"] = [{ dataType: "dataframe", payload: { segment: { 0: "r1" }, shade: { 0: 1 } }, schema: { segment: "object", shade: "float64" }, geometryName: null }];
    mount({ inputSlots: holding("dataframe"), code: DIFFERENCE, compareScenarios: { inputs: [BASE, TALL], mode: "difference" } });
    const select = (await screen.findByRole("combobox", { name: "Key" })) as HTMLSelectElement;
    await waitFor(() => expect(Array.from(select.options).map((o) => o.value)).toEqual(["", "segment"]));
    fireEvent.change(select, { target: { value: "segment" } });
    expect(mockUpdateDataNode).toHaveBeenCalledWith(
      COMPARE,
      expect.objectContaining({ compareScenarios: { inputs: [BASE, TALL], mode: "difference", difference: { key: "segment" } } }),
    );
  });

  test("a table's difference is shown as a table, through the Vega-Lite node's code", async () => {
    mockFrames["diff-1"] = [{
      dataType: "dataframe",
      payload: { osm_id: { 0: 1 }, change: { 0: "added" }, sunlight: { 0: null } },
      schema: { osm_id: "int64", change: "object", sunlight: "float64" },
      geometryName: null,
    }];
    mount({ inputSlots: holding("dataframe"), code: DIFFERENCE, compareScenarios: { inputs: [BASE, TALL], mode: "difference" } }, nodeState(ran));
    await waitFor(() => expect(mockUseVega).toHaveBeenCalled());
    const options = mockUseVega.mock.calls.at(-1)![0];
    expect(options.code).toBe(JSON.stringify(differenceTableSpec(["osm_id", "change", "sunlight"])));
    expect(options.data.input).toEqual({ path: "diff-1", dataType: "dataframe" });
    expect(mockAutk).not.toHaveBeenCalled();
  });

  test("an output from before the switch, a stacked table, asks for a run", async () => {
    mockFrames["diff-1"] = [{
      dataType: "dataframe",
      payload: { scenario: { 0: "s-base" }, scenario_name: { 0: "Baseline" }, sunlight: { 0: 5 } },
      schema: { scenario: "object", scenario_name: "object", sunlight: "float64" },
      geometryName: null,
    }];
    mount({ inputSlots: holding("dataframe"), code: DIFFERENCE, compareScenarios: { inputs: [BASE, TALL], mode: "difference" } }, nodeState(ran));
    expect(await screen.findByText("Run this node again to compute the difference.")).not.toBeNull();
    expect(mockUseVega).not.toHaveBeenCalled();
    expect(mockAutk).not.toHaveBeenCalled();
  });

  test("a failed run says why, where the map goes", () => {
    const failed = {
      code: "error",
      content: "Compare Scenarios: input 1 (Twice as tall) minus input 0 (Baseline) cannot be computed: their grids differ in size.",
    };
    const { view } = mount({ inputSlots: holding("raster"), code: DIFFERENCE }, nodeState(failed));
    expect(view.container.querySelector("[data-compare-run-error]")!.textContent).toBe(failed.content);
    expect(mockAutk).not.toHaveBeenCalled();
  });
});
