/**
 * A Data Pool that reads several layers from one artifact names it, and a code
 * node it feeds is sent that artifact (#662): the reference an isolated
 * sandbox can stage and a run on the server passes through the pool, as for a
 * pool of one layer. A chart it feeds still gets the rows inline, with their
 * flags; a bundle of several inputs is still sent as it is.
 */
import { renderHook, waitFor } from "@testing-library/react";
import type { NodeBehaviorData, UseNodeStateReturn } from "../../../registry/types";

jest.mock("reactflow", () => ({ useEdges: () => [] }));
jest.mock("../../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ nodeExecStatus: {}, workflowNameRef: { current: "wf" }, updateDataNode: jest.fn() }),
}));
jest.mock("../../../providers/ProvenanceProvider", () => ({
  useProvenanceContext: () => ({ nodeExecProv: jest.fn() }),
}));
const mockFetchData = jest.fn();
jest.mock("../../../services/api", () => ({ fetchData: (...args: any[]) => mockFetchData(...args) }));
jest.mock("../../../adapters/node/components/DataPoolContent", () => ({
  __esModule: true,
  default: () => null,
}));

import { useDataPoolBehavior } from "../../../adapters/node/dataPoolBehavior";
import { executionInputRef } from "../../../utils/flowOutputRef";

function layer(name: string, type: string, properties: Record<string, unknown>) {
  return {
    dataType: "dict",
    data: {
      name,
      type,
      geojson: {
        type: "FeatureCollection",
        features: [{ type: "Feature", geometry: { type: "Point", coordinates: [0, 0] }, properties }],
      },
    },
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

test("a pool of an Autark node's layers names the artifact it read, and a code node is sent that artifact", async () => {
  // What /get answers for an Autark data node's layers: a list of records.
  mockFetchData.mockResolvedValue({
    dataType: "list",
    filename: "art_layers",
    data: [layer("table_osm_roads", "roads", { highway: "primary" }), layer("table_osm_buildings", "buildings", { building_id: 7 })],
  });
  const outputCallback = jest.fn();
  const data = {
    nodeId: "pool-1",
    nodeType: "curio.builtin/data-pool@1",
    input: { path: "art_layers", dataType: "list" },
    outputCallback,
    propagationCallback: jest.fn(),
    interactionsCallback: jest.fn(),
  } as unknown as NodeBehaviorData;
  renderHook(() => useDataPoolBehavior(data, nodeState()));
  await waitFor(() => expect(outputCallback).toHaveBeenCalledTimes(1));
  const [, emitted] = outputCallback.mock.calls[0];

  // A chart gets the layers inline, each flagged, under their names.
  expect(emitted.dataType).toBe("outputs");
  expect(emitted.filename).toBe("art_layers");
  expect(emitted.data.map((item: any) => item.layerName)).toEqual(["table_osm_roads", "table_osm_buildings"]);
  expect(emitted.data[1].data.features[0].properties.interacted).toBe("0");

  // A code node is sent the artifact, without the rows.
  expect(executionInputRef(emitted)).toEqual({ filename: "art_layers", dataType: "outputs" });
});

test("a pool of several inputs names no one artifact, and its bundle is sent as it is", async () => {
  mockFetchData.mockImplementation((id: string) => Promise.resolve({
    dataType: "geodataframe",
    filename: id,
    data: { type: "FeatureCollection", features: [{ type: "Feature", geometry: null, properties: { id } }] },
  }));
  const outputCallback = jest.fn();
  const data = {
    nodeId: "pool-2",
    nodeType: "curio.builtin/data-pool@1",
    input: { dataType: "outputs", data: [{ path: "art_a", dataType: "geodataframe" }, { path: "art_b", dataType: "geodataframe" }] },
    outputCallback,
    propagationCallback: jest.fn(),
    interactionsCallback: jest.fn(),
  } as unknown as NodeBehaviorData;
  renderHook(() => useDataPoolBehavior(data, nodeState()));
  await waitFor(() => expect(outputCallback).toHaveBeenCalledTimes(1));
  const [, emitted] = outputCallback.mock.calls[0];
  expect(emitted.dataType).toBe("outputs");
  expect(emitted.filename).toBeUndefined();
  expect(executionInputRef(emitted)).toBe(emitted);
});
