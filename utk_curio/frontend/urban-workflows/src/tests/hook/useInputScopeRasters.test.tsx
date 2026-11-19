/**
 * What a node's editor reads of a raster on its input (hook/useInputScope):
 * a raster has no columns, so the header says so at once and reads nothing,
 * as for a value, and a chip's hover reads it once, for its size, its bands
 * and its CRS. Before, its columns waited for a read the hover made, and the
 * hover said only that it is a raster.
 *
 * A Python node's elevation raster feeds an Autark node's map on circle 0.
 */
import { act, renderHook, waitFor } from "@testing-library/react";

const MAP_ID = "elevation-map";
const DEM_ID = "elevation";

const mockFlow = {
  nodes: [{ id: DEM_ID, data: { nodeType: "curio.builtin/python-computation", title: "Elevation" } }],
  edges: [{ id: "e-in", source: DEM_ID, sourceHandle: "out", target: MAP_ID, targetHandle: "in" }],
  scenarios: [],
  nodeExecStatus: { [DEM_ID]: "executed" },
};
jest.mock("../../providers/FlowProvider", () => ({ useFlowContext: () => mockFlow }));

const mockFetchPreviewData = jest.fn();
jest.mock("../../services/api", () => ({
  fetchData: jest.fn(),
  fetchPreviewData: (...args: any[]) => mockFetchPreviewData(...args),
}));

import { useInputScope } from "../../hook/useInputScope";
import { ELEVATION, PYTHON_RASTER_REF } from "../_support/rasterInputFixtures";

const MAP = { nodeId: MAP_ID, nodeType: "curio.builtin/autk-grammar", input: PYTHON_RASTER_REF };

beforeEach(() => {
  mockFetchPreviewData.mockReset();
  mockFetchPreviewData.mockResolvedValue(ELEVATION);
});

describe("a raster on its own", () => {
  test("its chip has no columns at once, and the header's read of them reads nothing", () => {
    const { result } = renderHook(() => useInputScope(MAP));

    expect(result.current.inputs).toMatchObject([
      { slot: 0, edge: "e-in", label: "Elevation", dataType: "raster", columns: [], dtypes: {} },
    ]);
    act(() => result.current.loadColumns(0));
    expect(mockFetchPreviewData).not.toHaveBeenCalled();
  });

  test("its hover reads it once, for its size, its bands and its CRS", async () => {
    const { result } = renderHook(() => useInputScope(MAP));

    act(() => result.current.loadPreview(0));

    await waitFor(() => expect(result.current.previews[0].preview).toBeDefined());
    expect(result.current.previews[0].preview).toEqual({
      kind: "raster",
      raster: { width: 40, height: 30, bands: ["elevation_m", "band_2"], crs: "EPSG:3395" },
    });
    expect(mockFetchPreviewData.mock.calls.map(([read]) => read)).toEqual([PYTHON_RASTER_REF.path]);
  });
});
