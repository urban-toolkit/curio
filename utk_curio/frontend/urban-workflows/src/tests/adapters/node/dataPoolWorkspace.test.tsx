/**
 * A Data Pool hands an Autark node's layers on with each one's workspace
 * (autk-grammar 5.0.0's `workspace`), as docs/USAGE.md's Workspaces section
 * says: the layer records a data node's load hands on, and the envelopes a
 * compute step hands on, as new data and with a selection's flags.
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import type { NodeBehaviorData, UseNodeStateReturn } from "../../../registry/types";
import { VisInteractionType } from "../../../constants";

jest.mock("reactflow", () => ({ useEdges: () => [] }));
jest.mock("../../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ nodeExecStatus: {}, workflowNameRef: { current: "wf" }, updateDataNode: jest.fn() }),
}));
jest.mock("../../../providers/ProvenanceProvider", () => ({
  useProvenanceContext: () => ({ nodeExecProv: jest.fn() }),
}));
jest.mock("../../../services/api", () => ({ fetchData: (...a: any[]) => mockFetchData(...a) }));
jest.mock("../../../adapters/node/components/DataPoolContent", () => ({ __esModule: true, default: () => null }));

const mockFetchData = jest.fn();

import { useDataPoolBehavior } from "../../../adapters/node/dataPoolBehavior";

const line = (x: number) => ({
  type: "Feature",
  geometry: { type: "LineString", coordinates: [[x, 41.88], [x + 0.001, 41.881]] },
  properties: { x },
});
const lines = (...xs: number[]) => ({ type: "FeatureCollection", features: xs.map(line) });

/** What an Autark compute step hands on: `lines` in the default workspace and in `east`. */
function wrapper() {
  return {
    dataType: "outputs",
    data: [
      { dataType: "geodataframe", layerName: "lines", layerType: "polylines", data: lines(-87.6) },
      { dataType: "geodataframe", layerName: "lines", layerType: "polylines", workspace: "east", data: lines(-87.5, -87.49) },
    ],
  };
}

/** What an Autark data node's load hands on, as the sandbox serves its stored layer records. */
function records() {
  return {
    dataType: "list",
    data: [
      { dataType: "dict", data: { name: "lines", type: "polylines", geojson: lines(-87.6) } },
      { dataType: "dict", data: { name: "lines", type: "polylines", geojson: lines(-87.5, -87.49), workspace: "east" } },
    ],
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

const BASE = {
  nodeId: "pool-1",
  nodeType: "curio.builtin/data-pool@1",
  propagationCallback: jest.fn(),
  interactionsCallback: jest.fn(),
};

const workspacesOf = (output: any) => output.data.map((layer: any) => [layer.layerName, layer.workspace]);

beforeEach(() => mockFetchData.mockReset());

test("a Data Pool hands a data node's layers on in their workspaces", async () => {
  mockFetchData.mockResolvedValue(records());
  const outputCallback = jest.fn();
  const input = { path: "art-1", dataType: "list" };
  renderHook(
    ({ d }: { d: NodeBehaviorData }) => useDataPoolBehavior(d, nodeState()),
    { initialProps: { d: { ...BASE, outputCallback, input } as unknown as NodeBehaviorData } },
  );
  await waitFor(() => expect(outputCallback).toHaveBeenCalledTimes(1));
  expect(workspacesOf(outputCallback.mock.calls[0][1])).toEqual([["lines", undefined], ["lines", "east"]]);
});

test("a Data Pool hands a compute step's layers on in their workspaces, with a selection's flags too", async () => {
  const outputCallback = jest.fn();
  const input = wrapper();
  const { rerender } = renderHook(
    ({ d }: { d: NodeBehaviorData }) => useDataPoolBehavior(d, nodeState()),
    { initialProps: { d: { ...BASE, outputCallback, input } as unknown as NodeBehaviorData } },
  );
  await waitFor(() => expect(outputCallback).toHaveBeenCalledTimes(1));
  expect(workspacesOf(outputCallback.mock.calls[0][1])).toEqual([["lines", undefined], ["lines", "east"]]);

  const picked = [{ details: { highlight: { type: VisInteractionType.POINT, data: [0], priority: 1 } }, priority: 1 }];
  await act(async () => {
    rerender({ d: { ...BASE, outputCallback, input, interactions: picked } as unknown as NodeBehaviorData });
  });
  await waitFor(() => expect(outputCallback).toHaveBeenCalledTimes(2));
  expect(workspacesOf(outputCallback.mock.calls[1][1])).toEqual([["lines", undefined], ["lines", "east"]]);
});
