/**
 * A Data Pool linked to an Autark node of several views marks each layer of
 * its rows by the select made on it (adapters/node/dataPoolBehavior,
 * utils/autkSelects): the node sends one select per view, each naming its
 * table, so the map's pick marks the roads and the plot's brush the parks,
 * whichever came last. A node of one view's select marks its layer as before.
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import type { NodeBehaviorData, UseNodeStateReturn } from "../../../registry/types";
import { NodeType, VisInteractionType } from "../../../constants";

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

const feature = (n: number) => ({
  type: "Feature",
  geometry: { type: "Point", coordinates: [-87.6 + n / 1000, 41.88] },
  properties: { n },
});
const layer = (layerName: string, count: number) => ({
  dataType: "geodataframe",
  layerName,
  data: { type: "FeatureCollection", features: Array.from({ length: count }, (_, n) => feature(n)) },
});

/** What an Autark node hands on: its roads and its parks. */
const wrapper = () => ({ dataType: "outputs", data: [layer("roads", 3), layer("parks", 2)] });

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

const pick = (layerRef: string, data: number[], priority: number) =>
  ({ type: VisInteractionType.POINT, data, priority, source: NodeType.AUTK_GRAMMAR, layerRef });

/** The marks each layer of the pool's last output holds, by layer. */
const marksOf = (output: any) => Object.fromEntries(output.data.map((each: any) => [
  each.layerName, each.data.features.map((f: any) => f.properties.interacted),
]));

async function poolAfter(details: Record<string, unknown>) {
  const outputCallback = jest.fn();
  const input = wrapper();
  const { rerender } = renderHook(
    ({ d }: { d: NodeBehaviorData }) => useDataPoolBehavior(d, nodeState()),
    { initialProps: { d: { ...BASE, outputCallback, input } as unknown as NodeBehaviorData } },
  );
  await waitFor(() => expect(outputCallback).toHaveBeenCalledTimes(1));
  const interactions = [{ nodeId: "views-1", details, priority: 1 }];
  await act(async () => {
    rerender({ d: { ...BASE, outputCallback, input, interactions } as unknown as NodeBehaviorData });
  });
  await waitFor(() => expect(outputCallback).toHaveBeenCalledTimes(2));
  return outputCallback.mock.calls[1][1];
}

test("each view's select marks its own layer, the map's pick the roads and the plot's brush the parks", async () => {
  const output = await poolAfter({
    "autk_selection@city": pick("roads", [0, 2], 0),
    "autk_selection#1": pick("parks", [1], 1),
  });

  expect(marksOf(output)).toEqual({ roads: ["1", "0", "1"], parks: ["0", "1"] });
});

test("a node of one view's select marks its layer as before", async () => {
  const output = await poolAfter({ autk_selection: pick("parks", [0], 1) });

  expect(marksOf(output).parks).toEqual(["1", "0"]);
});
