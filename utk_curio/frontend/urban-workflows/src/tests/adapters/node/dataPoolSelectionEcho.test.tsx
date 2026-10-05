/**
 * A Data Pool says when an output is a selection coming back, not new data.
 *
 * Every chart the pool feeds receives both kinds as a new `data.input`. A
 * selection only re-flags the rows (`interacted`), which a chart highlights in
 * the view it already has; new data is what a chart redraws for. The pool is the
 * only node that knows which one it is sending, so it says so on the emit.
 */
import React from "react";
import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import type { NodeBehaviorData, UseNodeStateReturn } from "../../../registry/types";
import { ResolutionType, VisInteractionType } from "../../../constants";

// The graph the pool sees, settable per test: which charts an interaction edge
// joins to it.
let mockEdges: any[] = [];
jest.mock("reactflow", () => ({ useEdges: () => mockEdges }));
const mockUpdateDataNode = jest.fn();
jest.mock("../../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    nodeExecStatus: {},
    workflowNameRef: { current: "wf" },
    updateDataNode: mockUpdateDataNode,
  }),
}));
jest.mock("../../../providers/ProvenanceProvider", () => ({
  useProvenanceContext: () => ({ nodeExecProv: jest.fn() }),
}));
jest.mock("../../../services/api", () => ({ fetchData: jest.fn() }));
jest.mock("../../../adapters/node/components/DataPoolContent", () => ({
  __esModule: true,
  default: () => null,
}));

import { useDataPoolBehavior } from "../../../adapters/node/dataPoolBehavior";

afterEach(() => {
  mockEdges = [];
  mockUpdateDataNode.mockClear();
});

function frame() {
  return {
    dataType: "dataframe",
    data: { label: ["a", "b", "c"], value: [1, 2, 3] },
  };
}

function nodeState(): UseNodeStateReturn {
  return {
    output: { code: "", content: "", outputType: "" },
    setOutput: jest.fn(),
    code: "",
    setCode: jest.fn(),
    templateData: {},
    setSendCodeCallback: jest.fn(),
  } as unknown as UseNodeStateReturn;
}

const pointOn = (index: number) => [
  {
    details: { highlight: { type: VisInteractionType.POINT, data: [index], priority: 1 } },
    priority: 1,
  },
];

test("a selection and another pool's propagation are echoes; new data is not", async () => {
  const outputCallback = jest.fn();
  const base = {
    nodeId: "pool-1",
    nodeType: "curio.builtin/data-pool@1",
    outputCallback,
    propagationCallback: jest.fn(),
    interactionsCallback: jest.fn(),
  };
  const state = nodeState();
  const input = frame();
  // One array, as the flow provider hands the pool: a new one is a new selection.
  const selection = pointOn(1);
  const { rerender } = renderHook(
    ({ d }: { d: NodeBehaviorData }) => useDataPoolBehavior(d, state),
    { initialProps: { d: { ...base, input } as unknown as NodeBehaviorData } },
  );

  // The first read is new data.
  await waitFor(() => expect(outputCallback).toHaveBeenCalledTimes(1));
  expect(outputCallback.mock.calls[0][2]).toBeUndefined();

  // A selection re-flags the same rows.
  await act(async () => {
    rerender({ d: { ...base, input, interactions: selection } as unknown as NodeBehaviorData });
  });
  await waitFor(() => expect(outputCallback).toHaveBeenCalledTimes(2));
  const [, echoed, echoOptions] = outputCallback.mock.calls[1];
  expect(echoOptions).toEqual({ selectionEcho: true });
  expect(Object.values(echoed.data.interacted)).toEqual(["0", "1", "0"]);

  // Another pool's propagation flips the toggle and leaves the input alone.
  await act(async () => {
    rerender({
      d: { ...base, input, interactions: selection, newPropagation: true } as unknown as NodeBehaviorData,
    });
  });
  await waitFor(() => expect(outputCallback).toHaveBeenCalledTimes(3));
  expect(outputCallback.mock.calls[2][2]).toEqual({ selectionEcho: true });

  // A new input is new data again.
  await act(async () => {
    rerender({
      d: { ...base, input: frame(), interactions: selection, newPropagation: true } as unknown as NodeBehaviorData,
    });
  });
  await waitFor(() => expect(outputCallback).toHaveBeenCalledTimes(4));
  expect(outputCallback.mock.calls[3][2]).toBeUndefined();
});

test("a selection's echo names the chart it came from, so that chart can leave its own alone", async () => {
  const outputCallback = jest.fn();
  const base = {
    nodeId: "pool-1",
    nodeType: "curio.builtin/data-pool@1",
    outputCallback,
    propagationCallback: jest.fn(),
    interactionsCallback: jest.fn(),
  };
  const input = frame();
  const { rerender } = renderHook(
    ({ d }: { d: NodeBehaviorData }) => useDataPoolBehavior(d, nodeState()),
    { initialProps: { d: { ...base, input } as unknown as NodeBehaviorData } },
  );
  await waitFor(() => expect(outputCallback).toHaveBeenCalledTimes(1));

  // As applyNewInteractions (providers/flow/useInteractions.ts) hands a pool the latest selection: an
  // empty one, from a press between two bars, after the plot selected row 0.
  const interactions = [
    { nodeId: "plot-1", details: { autk_selection: { type: VisInteractionType.POINT, data: [0], priority: 1 } }, priority: 1 },
  ];
  await act(async () => {
    rerender({ d: { ...base, input, interactions } as unknown as NodeBehaviorData });
  });
  await waitFor(() => expect(outputCallback).toHaveBeenCalledTimes(2));
  expect(outputCallback.mock.calls[1][2]).toEqual({ selectionEcho: true, selectionSource: "plot-1" });

  const cleared = [
    { nodeId: "plot-1", details: { autk_selection: { type: VisInteractionType.UNDETERMINED, data: [], priority: 1 } }, priority: 1 },
  ];
  await act(async () => {
    rerender({ d: { ...base, input, interactions: cleared } as unknown as NodeBehaviorData });
  });
  await waitFor(() => expect(outputCallback).toHaveBeenCalledTimes(3));
  expect(outputCallback.mock.calls[2][2]).toEqual({ selectionEcho: true, selectionSource: "plot-1" });
});

// Building parts as an Autark data node hands them on: one feature per part,
// each carrying the building_id of the building it came from (#536).
function buildingParts() {
  const part = (building_id: number, height_m: number, x: number) => ({
    type: "Feature",
    geometry: { type: "Polygon", coordinates: [[[x, 0], [x + 1, 0], [x + 1, 1], [x, 1], [x, 0]]] },
    properties: { building_id, height_m },
  });
  return {
    dataType: "geodataframe",
    layerName: "table_osm_buildings",
    layerType: "buildings",
    data: {
      type: "FeatureCollection",
      features: [part(7, 12, 0), part(7, 30, 1), part(9, 150, 2), part(11, 20, 3), part(11, 45, 4)],
    },
  };
}

// What an Autark plot or map sends: rows of its input.
const autkRows = (rows: number[]) => [
  {
    details: {
      autk_selection: {
        type: VisInteractionType.POINT,
        data: rows,
        priority: 1,
        source: "AUTK_GRAMMAR",
        layerRef: "table_osm_buildings",
      },
    },
    priority: 1,
  },
];

test.each([
  ["one part", [2], ["0", "0", "1", "0", "0"]],
  ["parts of two buildings, not their other parts", [0, 3], ["1", "0", "0", "1", "0"]],
])("a selection of building parts flags those rows: %s", async (_, rows, flags) => {
  const outputCallback = jest.fn();
  const base = {
    nodeId: "pool-1",
    nodeType: "curio.builtin/data-pool@1",
    outputCallback,
    propagationCallback: jest.fn(),
    interactionsCallback: jest.fn(),
  };
  const input = buildingParts();
  const { rerender } = renderHook(
    ({ d }: { d: NodeBehaviorData }) => useDataPoolBehavior(d, nodeState()),
    { initialProps: { d: { ...base, input } as unknown as NodeBehaviorData } },
  );
  await waitFor(() => expect(outputCallback).toHaveBeenCalledTimes(1));

  await act(async () => {
    rerender({ d: { ...base, input, interactions: autkRows(rows) } as unknown as NodeBehaviorData });
  });
  await waitFor(() => expect(outputCallback).toHaveBeenCalledTimes(2));
  const [, echoed] = outputCallback.mock.calls[1];
  expect(echoed.data.features.map((f: any) => f.properties.interacted)).toEqual(flags);
});

// Three points, as a GeoDataFrame reaches the pool inline.
function places(): any {
  const at = (x: number) => ({
    type: "Feature",
    geometry: { type: "Point", coordinates: [x, 0] },
    properties: { name: `p${x}` },
  });
  return { dataType: "geodataframe", data: { type: "FeatureCollection", features: [at(0), at(1), at(2)] } };
}

const dfFlags = (out: any) => Object.values(out.data.interacted);
const geoFlags = (out: any) => out.data.features.map((f: any) => f.properties.interacted);
const point = (rows: number[], priority = 1) => ({ type: VisInteractionType.POINT, data: rows, priority });
const clearedBrush = () => ({ type: VisInteractionType.INTERVAL, data: {}, priority: 1 });
// An interaction edge between a chart and the pool, as the canvas draws one.
const linkEdge = (chart: string) => ({
  id: `${chart}-pool`, source: chart, target: "pool-1", sourceHandle: "in/out", targetHandle: "in/out",
});

/**
 * A mounted pool, and the two things that happen to one: its node data
 * changes, and a chart selects. A selection arrives as
 * applyNewInteractions (providers/flow/useInteractions.ts) hands it over: the chart that just
 * selected, alone, with priority 1 and its node id.
 */
function mountPool(input: any, extra: Record<string, unknown> = {}) {
  const outputCallback = jest.fn();
  const propagationCallback = jest.fn();
  let d: any = {
    nodeId: "pool-1",
    nodeType: "curio.builtin/data-pool@1",
    outputCallback,
    propagationCallback,
    interactionsCallback: jest.fn(),
    input,
    ...extra,
  };
  const state = nodeState();
  const hook = renderHook(
    ({ d: current }: { d: NodeBehaviorData }) => useDataPoolBehavior(current, state),
    { initialProps: { d: d as NodeBehaviorData } },
  );
  const update = async (changes: Record<string, unknown>) => {
    d = { ...d, ...changes };
    await act(async () => {
      hook.rerender({ d: d as NodeBehaviorData });
    });
  };
  const select = async (nodeId: string, details: Record<string, unknown>) => {
    const before = outputCallback.mock.calls.length;
    await update({ interactions: [{ nodeId, details, priority: 1 }] });
    await waitFor(() => expect(outputCallback.mock.calls.length).toBe(before + 1));
    return outputCallback.mock.calls[before];
  };
  const ready = () => waitFor(() => expect(outputCallback).toHaveBeenCalledTimes(1));
  return { hook, outputCallback, propagationCallback, update, select, ready };
}

describe("the pool writes its flags into copies (#582)", () => {
  test.each([
    ["a dataframe", frame, dfFlags],
    ["a geodataframe", places, geoFlags],
  ])("a later selection leaves the run output and earlier echoes as they were: %s", async (_, make, flags) => {
    const pool = mountPool(make());
    await pool.ready();
    const runOutput = pool.outputCallback.mock.calls[0][1];

    const [, first] = await pool.select("bar", { highlight: point([1]) });
    expect(flags(first)).toEqual(["0", "1", "0"]);
    const [, second] = await pool.select("bar", { highlight: point([2]) });
    expect(flags(second)).toEqual(["0", "0", "1"]);

    expect(flags(first)).toEqual(["0", "1", "0"]);
    expect(flags(runOutput)).toEqual(["0", "0", "0"]);
  });

  test.each([
    ["a dataframe", frame],
    ["a geodataframe", places],
  ])("an input handed over inline is left as it came: %s", async (_, make) => {
    const input = make();
    const pool = mountPool(input);
    await pool.ready();
    await pool.select("bar", { highlight: point([1]) });
    expect(input).toEqual(make());
  });

  test("a geodataframe's echo flags its features, not the collection", async () => {
    const pool = mountPool(places());
    await pool.ready();
    const [, echoed] = await pool.select("bar", { highlight: point([1]) });
    expect(echoed.data).not.toHaveProperty("interacted");
  });

  test("a selected feature that links rows of another pool passes them on", async () => {
    const input = places();
    input.data.features[1].properties.linked = [4, 5];
    const pool = mountPool(input);
    await pool.ready();
    const [, echoed] = await pool.select("bar", { highlight: point([1]) });
    expect(geoFlags(echoed)).toEqual(["0", "1", "0"]);
    expect(pool.propagationCallback).toHaveBeenLastCalledWith({
      nodeId: "pool-1",
      propagation: { 4: "1", 5: "1" },
    });
  });
});

describe("the conflict modes are chosen in the pool and applied (#581)", () => {
  const RealDataPoolContent = jest.requireActual(
    "../../../adapters/node/components/DataPoolContent",
  ).default;

  function renderBody(pool: ReturnType<typeof mountPool>) {
    const element = pool.hook.result.current.contentComponent as React.ReactElement;
    return render(<RealDataPoolContent {...(element.props as object)} />);
  }

  test("each select offers exactly the resolution types and starts on Overwrite", async () => {
    const pool = mountPool(frame());
    await pool.ready();
    renderBody(pool);
    for (const label of ["Conflict inside visualization", "Conflict between visualizations"]) {
      const select = screen.getByLabelText(label) as HTMLSelectElement;
      expect(Array.from(select.options).map((o) => o.value)).toEqual(Object.values(ResolutionType));
      expect(select.value).toBe(ResolutionType.OVERWRITE);
    }
  });

  test("a choice is saved on the node, and a saved choice is what the select shows", async () => {
    const pool = mountPool(frame(), { dataPool: { insideChart: ResolutionType.MERGE_AND } });
    await pool.ready();
    renderBody(pool);
    expect((screen.getByLabelText("Conflict inside visualization") as HTMLSelectElement).value)
      .toBe(ResolutionType.MERGE_AND);

    fireEvent.change(screen.getByLabelText("Conflict between visualizations"), {
      target: { value: ResolutionType.MERGE_OR },
    });
    expect(mockUpdateDataNode).toHaveBeenCalledWith("pool-1", expect.objectContaining({
      dataPool: { insideChart: ResolutionType.MERGE_AND, betweenCharts: ResolutionType.MERGE_OR },
    }));
  });

  // OVERWRITE is the control: the default reads the newest select, as before.
  test.each([
    [ResolutionType.OVERWRITE, ["0", "1", "1"]],
    [ResolutionType.MERGE_OR, ["1", "1", "1"]],
    [ResolutionType.MERGE_AND, ["0", "1", "0"]],
  ])("inside one chart, %s resolves the chart's selects", async (mode, flags) => {
    const pool = mountPool(frame(), { dataPool: { insideChart: mode } });
    await pool.ready();
    const [, echoed] = await pool.select("bar", { older: point([0, 1], 0), newer: point([1, 2], 1) });
    expect(dfFlags(echoed)).toEqual(flags);
  });

  test("inside one chart, MERGE_AND leaves out a select with nothing selected", async () => {
    const pool = mountPool(frame(), { dataPool: { insideChart: ResolutionType.MERGE_AND } });
    await pool.ready();
    const [, echoed] = await pool.select("scatter", { click: point([0, 1], 0), brush: clearedBrush() });
    expect(dfFlags(echoed)).toEqual(["1", "1", "0"]);
  });

  test.each([
    [ResolutionType.OVERWRITE, ["0", "1", "1"]],
    [ResolutionType.MERGE_OR, ["1", "1", "1"]],
    [ResolutionType.MERGE_AND, ["0", "1", "0"]],
  ])("between two charts, %s resolves each chart's latest selection", async (mode, flags) => {
    mockEdges = [linkEdge("bar"), linkEdge("scatter")];
    const pool = mountPool(frame(), { dataPool: { betweenCharts: mode } });
    await pool.ready();
    await pool.select("bar", { highlight: point([0, 1]) });
    const [, echoed] = await pool.select("scatter", { brush: point([1, 2]) });
    expect(dfFlags(echoed)).toEqual(flags);
  });

  test("between two charts, MERGE_AND leaves out a chart with nothing selected", async () => {
    mockEdges = [linkEdge("bar"), linkEdge("scatter")];
    const pool = mountPool(frame(), { dataPool: { betweenCharts: ResolutionType.MERGE_AND } });
    await pool.ready();
    await pool.select("bar", { highlight: point([0, 1]) });
    const [, echoed] = await pool.select("scatter", { brush: clearedBrush() });
    expect(dfFlags(echoed)).toEqual(["1", "1", "0"]);
  });

  test("a merged echo names the chart that just selected, so that chart can leave it alone", async () => {
    mockEdges = [linkEdge("bar"), linkEdge("scatter")];
    const pool = mountPool(frame(), { dataPool: { betweenCharts: ResolutionType.MERGE_OR } });
    await pool.ready();
    const [, , first] = await pool.select("bar", { highlight: point([0]) });
    expect(first).toEqual({ selectionEcho: true, selectionSource: "bar" });
    const [, echoed, second] = await pool.select("scatter", { brush: point([2]) });
    expect(dfFlags(echoed)).toEqual(["1", "0", "1"]);
    expect(second).toEqual({ selectionEcho: true, selectionSource: "scatter" });
  });

  test("a chart whose interaction edge is removed drops out of the merge", async () => {
    mockEdges = [linkEdge("bar"), linkEdge("scatter")];
    const pool = mountPool(frame(), { dataPool: { betweenCharts: ResolutionType.MERGE_AND } });
    await pool.ready();
    await pool.select("bar", { highlight: point([0, 1]) });
    const [, both] = await pool.select("scatter", { brush: point([1, 2]) });
    expect(dfFlags(both)).toEqual(["0", "1", "0"]);

    mockEdges = [linkEdge("bar")];
    await pool.update({});
    const [, alone] = await pool.select("bar", { highlight: point([0, 1]) });
    expect(dfFlags(alone)).toEqual(["1", "1", "0"]);
  });

  test("choosing another mode resolves the selections the pool holds again", async () => {
    mockEdges = [linkEdge("bar"), linkEdge("scatter")];
    const pool = mountPool(frame());
    await pool.ready();
    await pool.select("bar", { highlight: point([0]) });
    const [, latest] = await pool.select("scatter", { brush: point([2]) });
    expect(dfFlags(latest)).toEqual(["0", "0", "1"]);

    const before = pool.outputCallback.mock.calls.length;
    await pool.update({ dataPool: { betweenCharts: ResolutionType.MERGE_OR } });
    await waitFor(() => expect(pool.outputCallback.mock.calls.length).toBe(before + 1));
    const [, merged, options] = pool.outputCallback.mock.calls[before];
    expect(dfFlags(merged)).toEqual(["1", "0", "1"]);
    expect(options).toEqual({ selectionEcho: true, selectionSource: "scatter" });
  });
});
