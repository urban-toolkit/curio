/**
 * The Compare Scenarios node (#662) in Difference, on the canvas. The node
 * picks Difference for two rasters or two layers that have run and Chart for
 * anything else, writes its code for the view (and the key it joins rows on),
 * and the user can switch. Its body shows a table's difference through the
 * Vega-Lite node's code, and leaves a raster's or a layer's to an Autark node
 * after it: it calls no Autark map code.
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

// What a read of a reference finds, by its path: a raster only for a reader
// that takes rasters, as utils/grammarInput reads them.
let mockFrames: Record<string, any[]> = {};
jest.mock("../../../utils/grammarInput", () => ({
  readGrammarInput: jest.fn((ref: any, opts: any) =>
    Promise.resolve({
      frames: (mockFrames[ref?.path] ?? []).filter((frame: any) => frame.dataType !== "raster" || opts?.rasters),
    }),
  ),
}));

// The Autark node's map code, which the node never calls.
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
  data: { nodeId: id, nodeType: "curio.builtin/computation-analysis@1", code: "return input_0", ...data },
});
const edge = (source: string, target: string, targetHandle = "in") => ({
  id: `${source}-${target}-${targetHandle}`, source, target, sourceHandle: "out", targetHandle,
});

/** What each circle holds once the scenarios' outcomes have run. */
const holding = (dataType: string) => [
  { path: `${dataType}-a`, dataType },
  { path: `${dataType}-b`, dataType },
];

/** What the Difference tab says of a raster's or a layer's difference. */
const AUTARK_NOTE = "Draw this difference on a map with an Autark node after this one.";

/** A raster's difference, as a read of the node's output finds it. */
const RASTER_DIFFERENCE = [{
  dataType: "raster",
  payload: { envelope: { dataType: "raster", data: { features: [{ properties: { bands: [{ id: "band_1" }] } }] } } },
  schema: null,
  geometryName: null,
}];

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
    mount({ inputSlots: holding("raster"), code: "return input_0[1]", defaultCode: "return input_0[1]" });
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

  test("a raster's difference draws no map in the node: the tab leaves it to an Autark node after it", async () => {
    mockFrames["diff-1"] = RASTER_DIFFERENCE;
    const { view } = mount({ inputSlots: holding("raster"), code: DIFFERENCE }, nodeState(ran));
    const note = await screen.findByText(AUTARK_NOTE);
    expect(note.getAttribute("data-compare-difference-map")).toBe("autark");
    expect(view.container.querySelector('[data-compare-difference="raster"]')).not.toBeNull();
    // The Autark node's map code is never called from here, and the node holds no map.
    expect(mockAutk).not.toHaveBeenCalled();
    expect(view.container.querySelector("canvas, [data-compare-map-state]")).toBeNull();
    // Whether it gives each difference's size stays; what a map colors by is the map's.
    expect(screen.getByRole("combobox", { name: "Change" })).not.toBeNull();
    expect(screen.queryByRole("combobox", { name: "Color by" })).toBeNull();
    expect(screen.queryByText("Dark purple is the lowest difference and yellow the highest.")).toBeNull();
  });

  test("a layer's difference too, with the key it joins rows on", async () => {
    mockFrames["diff-1"] = [{
      dataType: "geodataframe",
      payload: { type: "FeatureCollection", features: [{ properties: { osm_id: 1, change: "changed", sunlight: -2 } }] },
      schema: { osm_id: "int64", change: "object", sunlight: "float64" },
      geometryName: "geometry",
    }];
    const { view } = mount({ inputSlots: holding("geodataframe"), code: DIFFERENCE }, nodeState(ran));
    expect(await screen.findByText(AUTARK_NOTE)).not.toBeNull();
    expect(view.container.querySelector('[data-compare-difference="layer"]')).not.toBeNull();
    expect(mockAutk).not.toHaveBeenCalled();
    expect(screen.getByRole("combobox", { name: "Key" })).not.toBeNull();
    expect(screen.queryByRole("combobox", { name: "Color by" })).toBeNull();
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

  test("switched back to Chart, the difference it left asks for a run, not a chart", async () => {
    mockFrames["diff-1"] = [{
      dataType: "raster",
      payload: { envelope: { dataType: "raster", data: { features: [{ properties: { bands: [{ id: "band_1" }] } }] } } },
      schema: null,
      geometryName: null,
    }];
    mount(
      { inputSlots: holding("raster"), code: STACKED, compareScenarios: { inputs: [BASE, TALL], mode: "chart" } },
      nodeState(ran),
    );
    expect(await screen.findByText("Run this node again to stack its inputs.")).not.toBeNull();
    expect(screen.getByRole("tab", { name: "Chart" })).not.toBeNull();
    expect(screen.queryByRole("combobox", { name: "Chart" })).toBeNull();
    expect(mockUseVega).not.toHaveBeenCalled();
    expect(mockAutk).not.toHaveBeenCalled();
  });

  test("a failed run says why, where the map goes", () => {
    const failed = {
      code: "error",
      content: "Compare Scenarios: input_1 (Twice as tall) minus input_0 (Baseline) cannot be computed: their grids differ in size.",
    };
    const { view } = mount({ inputSlots: holding("raster"), code: DIFFERENCE }, nodeState(failed));
    expect(view.container.querySelector("[data-compare-run-error]")!.textContent).toBe(failed.content);
    expect(mockAutk).not.toHaveBeenCalled();
  });
});

describe("each difference's size, absolute", () => {
  const ran = { code: "success", content: "Saved to file: diff-1" };
  const ABSOLUTE = differenceCode(INPUTS, undefined, undefined, true);
  const inDifference = (difference?: Record<string, unknown>, code = DIFFERENCE) => ({
    inputSlots: holding("raster"),
    code,
    defaultCode: code,
    compareScenarios: { inputs: [BASE, TALL], mode: "difference", ...(difference ? { difference } : {}) },
  });

  test("Change offers the difference or its size before any run, for a table too, and keeps Absolute", () => {
    mount({ ...inDifference(), inputSlots: holding("dataframe") });
    const select = screen.getByRole("combobox", { name: "Change" }) as HTMLSelectElement;
    expect(Array.from(select.options).map((option) => [option.value, option.textContent])).toEqual([
      ["signed", "Signed"],
      ["absolute", "Absolute"],
    ]);
    expect(select.value).toBe("signed");
    fireEvent.change(select, { target: { value: "absolute" } });
    expect(mockUpdateDataNode).toHaveBeenCalledWith(
      COMPARE,
      expect.objectContaining({
        compareScenarios: { inputs: [BASE, TALL], mode: "difference", difference: { absolute: true } },
      }),
    );
    expect(mockMarkDirty).toHaveBeenCalled();
  });

  test("a change of it rewrites the code, and a node that had run goes stale", () => {
    const state = nodeState({ code: "success" });
    const { view } = mount(inDifference(), state);
    expect(mockUpdateDataNode).not.toHaveBeenCalled();
    // Absolute picked: the node's settings say so, and its code follows.
    const picked = graph(inDifference({ absolute: true }));
    mockFlow = flowOf(picked);
    view.rerender(<Harness data={picked.nodes.find((n) => n.id === COMPARE)!.data} state={state} />);
    expect(writtenCode()).toContain("], absolute=True)\n");
    expect(writtenCode()).toBe(ABSOLUTE);
    expect(state.setCode).toHaveBeenCalledWith(ABSOLUTE);
    expect(mockMarkNodeStale).toHaveBeenCalledWith(COMPARE);
    // And back to the difference itself: the code loses it.
    mockUpdateDataNode.mockReset();
    const back = graph(inDifference(undefined, ABSOLUTE));
    mockFlow = flowOf(back);
    view.rerender(<Harness data={back.nodes.find((n) => n.id === COMPARE)!.data} state={state} />);
    expect(writtenCode()).toBe(DIFFERENCE);
  });

  test("code already written for it is left as it is, Change reads Absolute, and the node draws no map", async () => {
    mockFrames["diff-1"] = RASTER_DIFFERENCE;
    mount(inDifference({ absolute: true }, ABSOLUTE), nodeState(ran));
    expect(mockUpdateDataNode).not.toHaveBeenCalled();
    expect(await screen.findByText(AUTARK_NOTE)).not.toBeNull();
    expect((screen.getByRole("combobox", { name: "Change" }) as HTMLSelectElement).value).toBe("absolute");
    expect(mockAutk).not.toHaveBeenCalled();
  });

});
