/**
 * What a Data Pool's raster tab says of its raster: that it is a raster, then
 * its size in cells, its bands and its CRS, in the words a chip's hover says
 * them in, from what the pool holds of it already: an Autark raster's
 * envelope, or what the sandbox read of a Python raster in a tuple, a list or
 * a dict, beside its file. A raster the pool holds by its reference alone is
 * not read (dataPoolRasters.test.tsx), so its tab says only that it is a
 * raster.
 *
 * And a Python node's dict that holds rasters alone is read as a dict holding
 * a table is: a tab per raster, named after its key, which the pool hands on
 * so that the node after it reads each raster by its place in the dict, as it
 * does fed directly.
 */
import React from "react";
import { fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import type { NodeBehaviorData, UseNodeStateReturn } from "../../../registry/types";

jest.mock("reactflow", () => ({ useEdges: () => [] }));
jest.mock("../../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ nodeExecStatus: {}, workflowNameRef: { current: "wf" }, updateDataNode: jest.fn(), edges: [] }),
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
jest.mock("../../../services/nodeRuntimeReport", () => ({ reportNodeRuntime: jest.fn() }));

import { useDataPoolBehavior } from "../../../adapters/node/dataPoolBehavior";
import { resolveRasterInputs } from "../../../adapters/node/autkRasters";
import { prepareAutkInput } from "../../../utils/autkInput";
import { normalizeFlowInput } from "../../../utils/flowOutputRef";
import wire from "../../../utils/raster/rasterWire.cases.json";

const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value));

const PARKS = {
  type: "FeatureCollection",
  features: [{ type: "Feature", geometry: { type: "Point", coordinates: [-87.62, 41.88] }, properties: { name: "Grant Park" } }],
};

/** What the sandbox read of a Python raster, as `/get` sends it beside its file. */
const meta = (width: number, height: number, bands: Array<string | null>) => ({
  width, height, count: bands.length, crs: "EPSG:32616", crsWkt: null,
  transform: [100, 0, 447000, 0, -100, 4637000], nodata: null, dtype: "float32", bands,
});

/** What `/get` answers for each artifact (sandbox/util/parsers.py `parseOutput`). */
const READ: Record<string, any> = {
  // An Autark data node's table and its heatmap, which it hands on after it.
  "art-tables": {
    dataType: "list",
    data: [
      { dataType: "dict", data: { name: "parks", type: "parks", geojson: PARKS } },
      { dataType: "dict", data: { ...wire.cases[0].envelope, layerName: "heat" } },
    ],
  },
  // A Python node's `return stations, depth`.
  "art-tuple": {
    dataType: "outputs",
    data: [
      { dataType: "geodataframe", data: PARKS },
      { dataType: "raster", data: ".curio/data/artifacts/depth.tif", meta: meta(40, 30, ["depth_m", null]) },
    ],
  },
  // A Python node's `return {"day": day, "night": night}`.
  "art-dict-rasters": {
    dataType: "dict",
    data: {
      day: { dataType: "raster", data: ".curio/data/artifacts/day.tif", meta: meta(4, 3, ["day_lights"]) },
      night: { dataType: "raster", data: ".curio/data/artifacts/night.tif", meta: meta(3, 2, ["night_lights"]) },
    },
  },
};

/** What `/raster` answers for each raster, by artifact and part: the GeoTIFF of
 * a raster-wire case and its description. Anything else is no raster. */
function served(at: number) {
  const { grid, bands } = wire.cases[at];
  return {
    ok: true,
    bytes: Uint8Array.from(Buffer.from(wire.cases[at].geotiff_base64, "base64")).buffer,
    meta: {
      width: grid.width, height: grid.height, count: Object.keys(bands).length, crs: grid.crs, crsWkt: null,
      transform: [grid.resX, 0, grid.originX, 0, grid.resY, grid.originY], nodata: null, dtype: "float32",
    },
  };
}
const RASTERS: Record<string, () => any> = {
  "art-dict-rasters#0": () => served(0),
  "art-dict-rasters#1": () => served(1),
};

beforeEach(() => {
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

function poolData(input: unknown, outputCallback: jest.Mock): NodeBehaviorData {
  return {
    nodeId: "pool",
    nodeType: "curio.builtin/data-pool@1",
    projectId: "flow-1",
    input,
    outputCallback,
    propagationCallback: jest.fn(),
    interactionsCallback: jest.fn(),
  } as unknown as NodeBehaviorData;
}

function Pool({ input }: { input: unknown }) {
  const behavior = useDataPoolBehavior(poolData(input, jest.fn()), nodeState());
  return <>{behavior.contentComponent}</>;
}

const tabTitles = () => Array.from(screen.getByTestId("data-pool-tabs").querySelectorAll(".nav-link")).map((tab) => tab.textContent);

/** The lines the active tab's raster is described in, under its title. */
const describedAs = () => Array.from(document.querySelectorAll("[data-curio-node-line]")).map((line) => line.textContent);

describe("a Data Pool's raster tab says what the raster is", () => {
  test("an Autark node's heatmap: its size in cells, its band and its CRS", async () => {
    render(<Pool input={normalizeFlowInput({ path: "art-tables", dataType: "list" })} />);
    await waitFor(() => expect(tabTitles()).toEqual(["parks", "heat"]));

    fireEvent.click(screen.getByText("heat"));

    expect(await screen.findByText("A raster")).toBeInTheDocument();
    expect(describedAs()).toEqual(["4 by 3 cells · 1 band · Raster, EPSG:32616", "Band: band_1"]);
  });

  test("a Python node's raster in a tuple: what the sandbox read of it", async () => {
    render(<Pool input={normalizeFlowInput({ path: "art-tuple", dataType: "outputs" })} />);
    await waitFor(() => expect(tabTitles()).toEqual(["Tab 1", "Tab 2"]));

    fireEvent.click(screen.getByText("Tab 2"));

    expect(await screen.findByText("A raster")).toBeInTheDocument();
    expect(describedAs()).toEqual(["40 by 30 cells · 2 bands · Raster, EPSG:32616", "Bands: depth_m, band_2"]);
    expect(mockFetchPreviewData).not.toHaveBeenCalled();
  });

  test("a Python node's raster on its own, held by its reference, says only that it is a raster", async () => {
    render(<Pool input={normalizeFlowInput({ path: "art-raster", dataType: "raster" })} />);

    expect(await screen.findByText("A raster")).toBeInTheDocument();
    expect(describedAs()).toEqual([]);
    expect(mockFetchData).not.toHaveBeenCalled();
    expect(mockFetchPreviewData).not.toHaveBeenCalled();
  });
});

describe("a Python node's dict that holds rasters alone", () => {
  test("is a tab per raster, named after its key, each saying what it is", async () => {
    render(<Pool input={normalizeFlowInput({ path: "art-dict-rasters", dataType: "dict" })} />);
    await waitFor(() => expect(tabTitles()).toEqual(["day", "night"]));

    fireEvent.click(screen.getByText("night"));

    expect(await screen.findByText("A raster")).toBeInTheDocument();
    expect(describedAs()).toEqual(["3 by 2 cells · 1 band · Raster, EPSG:32616", "Band: night_lights"]);
  });

  test("the node after the pool reads each raster by its place in the dict, as it does fed directly", async () => {
    const direct = normalizeFlowInput({ path: "art-dict-rasters", dataType: "dict" });
    const outputCallback = jest.fn();
    const { result } = renderHook(() => useDataPoolBehavior(poolData(direct, outputCallback), nodeState()));
    await waitFor(() => expect(result.current.outputOverride).toMatchObject({ code: "success" }));
    const pooled = normalizeFlowInput(outputCallback.mock.calls[outputCallback.mock.calls.length - 1][1]);

    const loads = async (input: unknown) => {
      mockFetchRaster.mockClear();
      const prepared = await prepareAutkInput(clone(input), {});
      const resolved = await resolveRasterInputs(prepared.rasters);
      return {
        rasters: resolved.sources.map((source) => [source.outputTableName, source.cells]),
        refused: resolved.problems,
        asked: mockFetchRaster.mock.calls.map(([artifact, opts]) => [artifact, opts?.part ?? null]),
      };
    };
    const fed = await loads(direct);
    expect(fed).toEqual({
      rasters: [["day", 12], ["night", 6]],
      refused: [],
      asked: [["art-dict-rasters", 0], ["art-dict-rasters", 1]],
    });
    expect(await loads(pooled)).toEqual(fed);
  });
});
