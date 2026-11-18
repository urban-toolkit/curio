/**
 * A raster through a Data Pool reaches the node after it as it does without
 * the pool, and the pool shows it as a raster.
 *
 * One table of what a node upstream of a pool makes (`hook/dataPoolHandOn.cases.json`,
 * whose other half `test_execution/test_data_pool_hand_on.py` runs in the
 * backend and the sandbox), each fed to the next node directly and through the
 * pool, read by each node's own code:
 * - an Autark node loads the same rasters either way: their names, grids,
 *   bands, cells and GeoTIFF bytes, asked of the sandbox by the same artifact
 *   and part (`prepareAutkInput`, then `resolveRasterInputs`);
 * - a Python or JavaScript node sends the backend the input the case names
 *   (`executionInputRef`), which the backend's half reads as the same rasters.
 * Through two pools in a row, and after a selection reaches the pool, the same.
 */
import React from "react";
import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import type { NodeBehaviorData, UseNodeStateReturn } from "../../../registry/types";
import { VisInteractionType } from "../../../constants";

let mockEdges: any[] = [];
jest.mock("reactflow", () => ({ useEdges: () => mockEdges }));
jest.mock("../../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ nodeExecStatus: {}, workflowNameRef: { current: "wf" }, updateDataNode: jest.fn(), edges: mockEdges }),
}));
jest.mock("../../../providers/ProvenanceProvider", () => ({
  useProvenanceContext: () => ({ nodeExecProv: jest.fn() }),
}));
const mockFetchData = jest.fn();
const mockFetchPreviewData = jest.fn();
const mockFetchRaster = jest.fn();
jest.mock("../../../services/api", () => ({
  fetchData: (...a: any[]) => mockFetchData(...a),
  fetchPreviewData: (...a: any[]) => mockFetchPreviewData(...a),
  fetchRaster: (...a: any[]) => mockFetchRaster(...a),
}));
const mockReport = jest.fn();
jest.mock("../../../services/nodeRuntimeReport", () => ({
  reportNodeRuntime: (...a: any[]) => mockReport(...a),
}));

import { useDataPoolBehavior } from "../../../adapters/node/dataPoolBehavior";
import { resolveRasterInputs } from "../../../adapters/node/autkRasters";
import { prepareAutkInput } from "../../../utils/autkInput";
import { executionInputRef, normalizeFlowInput } from "../../../utils/flowOutputRef";
import table from "../../../hook/dataPoolHandOn.cases.json";
import wire from "../../../utils/raster/rasterWire.cases.json";

const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value));
const base64Of = (buffer: ArrayBuffer) => Buffer.from(new Uint8Array(buffer)).toString("base64");

// ---------------------------------------------------------------------------
// What each artifact of the table holds, as the sandbox answers for it.
// ---------------------------------------------------------------------------

const square = (x: number, y: number) => ({
  type: "Polygon",
  coordinates: [[[x, y], [x + 0.001, y], [x + 0.001, y + 0.001], [x, y + 0.001], [x, y]]],
});
const PARKS = {
  type: "FeatureCollection",
  features: [
    { type: "Feature", geometry: square(-87.62, 41.88), properties: { name: "Grant Park" } },
    { type: "Feature", geometry: square(-87.61, 41.87), properties: { name: "Maggie Daley Park" } },
  ],
};
const STATIONS = {
  type: "FeatureCollection",
  features: [{ type: "Feature", geometry: { type: "Point", coordinates: [-87.62, 41.88] }, properties: { name: "Loop" } }],
};
/** A heatmap an Autark node made, in the envelope it hands a raster on in. */
const HEAT = { ...wire.cases[0].envelope, layerName: "heat" };

/** What `/get` answers for each artifact (sandbox/util/parsers.py `parseOutput`). */
const READ: Record<string, any> = {
  "art-raster": { dataType: "raster", data: ".curio/data/artifacts/heat.tif" },
  "art-tuple": {
    dataType: "outputs",
    data: [{ dataType: "geodataframe", data: STATIONS }, { dataType: "raster", data: ".curio/data/artifacts/depth.tif" }],
  },
  "art-rasters": {
    dataType: "list",
    data: [{ dataType: "raster", data: ".curio/data/artifacts/day.tif" }, { dataType: "raster", data: ".curio/data/artifacts/night.tif" }],
  },
  "art-tables": {
    dataType: "list",
    data: [{ dataType: "dict", data: { name: "parks", type: "polygons", geojson: PARKS } }, { dataType: "dict", data: HEAT }],
  },
  "art-heatmap": { dataType: "list", data: [{ dataType: "dict", data: HEAT }] },
  "art-envelope": { dataType: "dict", data: HEAT },
  "art-text": { dataType: "str", data: "a note" },
};

/** What `/raster` answers for a Python raster, by artifact and part: the
 * GeoTIFF and its description. Anything else is no raster, as the sandbox says. */
function served(at: number) {
  const { grid, bands } = wire.cases[at];
  return {
    ok: true,
    bytes: Uint8Array.from(Buffer.from(wire.cases[at].geotiff_base64, "base64")).buffer,
    meta: {
      width: grid.width,
      height: grid.height,
      count: Object.keys(bands).length,
      crs: grid.crs,
      crsWkt: null,
      transform: [grid.resX, 0, grid.originX, 0, grid.resY, grid.originY],
      nodata: null,
      dtype: "float32",
    },
  };
}
const RASTERS: Record<string, () => any> = {
  "art-raster#": () => served(0),
  "art-tuple#1": () => served(1),
  "art-rasters#0": () => served(0),
  "art-rasters#1": () => served(1),
};

beforeEach(() => {
  mockEdges = [];
  mockReport.mockReset();
  mockFetchData.mockReset();
  mockFetchData.mockImplementation(async (id: string) => {
    if (!(id in READ)) throw new Error(`no artifact ${id}`);
    return { ...clone(READ[id]), filename: id };
  });
  mockFetchPreviewData.mockReset();
  mockFetchPreviewData.mockRejectedValue(new Error("no preview in these tests"));
  mockFetchRaster.mockReset();
  mockFetchRaster.mockImplementation(async (artifact: string, opts: { part?: number }) => {
    const answer = RASTERS[`${artifact}#${opts?.part ?? ""}`];
    return answer ? answer() : { ok: false, status: 422, message: `artifact ${artifact} is not a raster` };
  });
});

// ---------------------------------------------------------------------------
// The pool, and the nodes after it.
// ---------------------------------------------------------------------------

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

function poolData(input: unknown, outputCallback: jest.Mock, interactions?: unknown): NodeBehaviorData {
  return {
    nodeId: "pool",
    nodeType: "curio.builtin/data-pool@1",
    projectId: "flow-1",
    input,
    interactions,
    outputCallback,
    propagationCallback: jest.fn(),
    interactionsCallback: jest.fn(),
  } as unknown as NodeBehaviorData;
}

/** What a pool fed *input* hands on, as the node it feeds receives it. */
async function throughPool(input: unknown): Promise<any> {
  const outputCallback = jest.fn();
  const { result } = renderHook(() => useDataPoolBehavior(poolData(input, outputCallback), nodeState()));
  await waitFor(() => expect(result.current.outputOverride).toMatchObject({ code: "success" }));
  expect(outputCallback).toHaveBeenCalled();
  const calls = outputCallback.mock.calls;
  return normalizeFlowInput(calls[calls.length - 1][1]);
}

/** What an Autark node loads of *input*: its rasters, as autk-db is handed
 * them, and what it asked the sandbox for. */
async function autarkLoads(input: unknown) {
  mockFetchRaster.mockClear();
  const prepared = await prepareAutkInput(clone(input), {});
  const resolved = await resolveRasterInputs(prepared.rasters);
  return {
    rasters: resolved.sources.map((source) => ({
      name: source.outputTableName,
      workspace: source.workspace ?? null,
      grid: source.grid,
      cells: source.cells,
      bands: source.bands ?? null,
      load: source.load,
      geotiff: base64Of(source.geotiffArrayBuffer),
    })),
    refused: resolved.problems,
    asked: mockFetchRaster.mock.calls.map(([artifact, opts]) => [artifact, opts?.part ?? null]),
  };
}

type Case = (typeof table.cases)[number];
const CASES: Array<[string, Case]> = table.cases.map((c) => [c.name, c]);

describe("a node fed through a Data Pool receives what it receives fed directly", () => {
  test.each(CASES)("%s", async (_name, c) => {
    const direct = normalizeFlowInput(c.handedOn);
    const pooled = await throughPool(direct);

    const loads = await autarkLoads(direct);
    expect(loads.rasters).toHaveLength(c.rasters);
    expect(await autarkLoads(pooled)).toEqual(loads);

    expect(executionInputRef(direct)).toEqual(c.sent.direct);
    expect(executionInputRef(pooled)).toEqual(c.sent.pool);
  });

  test.each(CASES)("%s, through two pools in a row", async (_name, c) => {
    const direct = normalizeFlowInput(c.handedOn);
    const twice = await throughPool(await throughPool(direct));

    expect(await autarkLoads(twice)).toEqual(await autarkLoads(direct));
    expect(executionInputRef(twice)).toEqual(c.sent.pool);
  });

  test("a selection that reaches the pool flags the layer's rows and hands the heatmap on as it was", async () => {
    const direct = normalizeFlowInput(table.cases.find((c) => c.artifact === "tables")!.handedOn);
    const outputCallback = jest.fn();
    const { result, rerender } = renderHook(
      ({ d }: { d: NodeBehaviorData }) => useDataPoolBehavior(d, nodeState()),
      { initialProps: { d: poolData(direct, outputCallback) } },
    );
    await waitFor(() => expect(result.current.outputOverride).toMatchObject({ code: "success" }));
    expect(outputCallback).toHaveBeenCalledTimes(1);

    const picked = [{ nodeId: "chart", details: { highlight: { type: VisInteractionType.POINT, data: [1], priority: 1 } }, priority: 1 }];
    await act(async () => {
      rerender({ d: poolData(direct, outputCallback, picked) });
    });
    await waitFor(() => expect(outputCallback).toHaveBeenCalledTimes(2));

    const echo = normalizeFlowInput(outputCallback.mock.calls[1][1]);
    const [parks, heat] = (echo as any).data;
    expect(parks.data.features.map((f: any) => f.properties.interacted)).toEqual(["0", "1"]);
    expect(heat).toEqual((normalizeFlowInput(outputCallback.mock.calls[0][1]) as any).data[1]);
    expect(await autarkLoads(echo)).toEqual(await autarkLoads(direct));
  });
});

// ---------------------------------------------------------------------------
// What the pool shows.
// ---------------------------------------------------------------------------

function Pool({ input }: { input: unknown }) {
  const behavior = useDataPoolBehavior(poolData(input, jest.fn()), nodeState());
  return <>{behavior.contentComponent}</>;
}

const tabTitles = () => Array.from(screen.getByTestId("data-pool-tabs").querySelectorAll(".nav-link")).map((tab) => tab.textContent);

describe("a raster in a Data Pool", () => {
  test("is a tab of its own beside the layers, named after its table, that says it is a raster", async () => {
    render(<Pool input={normalizeFlowInput({ path: "art-tables", dataType: "list" })} />);
    await waitFor(() => expect(tabTitles()).toEqual(["parks", "heat"]));

    fireEvent.click(screen.getByText("heat"));

    expect(await screen.findByText("A raster")).toBeInTheDocument();
    expect(screen.queryByText("No rows to preview")).toBeNull();
  });

  test("a Python node's raster is a tab that says it is a raster, and is not read for rows", async () => {
    render(<Pool input={normalizeFlowInput({ path: "art-raster", dataType: "raster" })} />);

    expect(await screen.findByText("A raster")).toBeInTheDocument();
    expect(tabTitles()).toEqual(["Tab 1"]);
    expect(mockFetchData).not.toHaveBeenCalled();
    expect(mockFetchPreviewData).not.toHaveBeenCalled();
  });

  test("an input that holds no table nor raster is a tab that says it is not tabular", async () => {
    render(<Pool input={normalizeFlowInput({ path: "art-text", dataType: "str" })} />);

    expect(await screen.findByText("Nothing to display")).toBeInTheDocument();
    expect(screen.getByText("This input is not tabular data.")).toBeInTheDocument();
    expect(tabTitles()).toEqual(["Tab 1"]);
  });

  test("the pool's run is told to the node's journal as ok for a raster, and as an input it cannot show for a text", async () => {
    mockEdges = [{ id: "e", source: "up", target: "pool", sourceHandle: "out", targetHandle: "in" }];
    const outputCallback = jest.fn();
    const raster = renderHook(() => useDataPoolBehavior(
      poolData(normalizeFlowInput({ path: "art-raster", dataType: "raster" }), outputCallback), nodeState(),
    ));
    await waitFor(() => expect(raster.result.current.outputOverride).toMatchObject({ code: "success" }));
    await waitFor(() => expect(mockReport).toHaveBeenLastCalledWith(expect.objectContaining({ nodeId: "pool", status: "ok" })));
    expect(mockReport).not.toHaveBeenCalledWith(expect.objectContaining({ status: "error" }));
    raster.unmount();

    mockReport.mockClear();
    const text = renderHook(() => useDataPoolBehavior(
      poolData(normalizeFlowInput({ path: "art-text", dataType: "str" }), jest.fn()), nodeState(),
    ));
    await waitFor(() => expect(text.result.current.outputOverride).toMatchObject({ code: "success" }));
    await waitFor(() => expect(mockReport).toHaveBeenLastCalledWith(
      expect.objectContaining({ nodeId: "pool", status: "error", kind: "bad-input:not-tabular" }),
    ));
  });
});
