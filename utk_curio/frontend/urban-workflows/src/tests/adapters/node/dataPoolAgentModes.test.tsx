/**
 * An agent's applied change to a Data Pool's conflict modes
 * (`node.settings.write`) reaches the pool's own setter, the one its two
 * selects pick through: the modes it gives in one change of the node, the
 * mode it leaves kept, so the pool resolves the selections it holds again.
 */
import { act, renderHook } from "@testing-library/react";
import type { NodeBehaviorData, UseNodeStateReturn } from "../../../registry/types";

jest.mock("reactflow", () => ({ useEdges: () => [] }));
const mockUpdateDataNode = jest.fn();
jest.mock("../../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ nodeExecStatus: {}, workflowNameRef: { current: "wf" }, updateDataNode: mockUpdateDataNode }),
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
import { writeNodeSettings } from "../../../utils/nodeSettingsWriters";

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

function mountPool(dataPool?: Record<string, string>) {
  const data = {
    nodeId: "pool-1",
    nodeType: "curio.builtin/data-pool@1",
    input: "",
    ...(dataPool ? { dataPool } : {}),
    outputCallback: jest.fn(),
    propagationCallback: jest.fn(),
    interactionsCallback: jest.fn(),
  } as unknown as NodeBehaviorData;
  renderHook(() => useDataPoolBehavior(data, nodeState()));
  const fallback = jest.fn();
  const write = (settings: Parameters<typeof writeNodeSettings>[2]) =>
    act(() => writeNodeSettings({ nodes: () => [{ id: "pool-1", data }], updateDataNode: fallback }, "pool-1", settings));
  return { write, fallback };
}

beforeEach(() => {
  mockUpdateDataNode.mockReset();
});

test("an agent's change picks both modes in one change of the pool, as its two selects pick each", () => {
  const { write, fallback } = mountPool({ insideChart: "MERGE_OR" });
  write({ dataPool: { insideChart: "OVERWRITE", betweenCharts: "MERGE_AND" } });
  expect(fallback).not.toHaveBeenCalled();
  expect(mockUpdateDataNode).toHaveBeenCalledTimes(1);
  expect(mockUpdateDataNode).toHaveBeenCalledWith("pool-1", expect.objectContaining({
    dataPool: { insideChart: "OVERWRITE", betweenCharts: "MERGE_AND" },
  }));
});

test("an agent's change of one mode keeps the other the pool holds", () => {
  const { write } = mountPool({ insideChart: "MERGE_OR" });
  write({ dataPool: { betweenCharts: "MERGE_AND" } });
  expect(mockUpdateDataNode).toHaveBeenCalledWith("pool-1", expect.objectContaining({
    dataPool: { insideChart: "MERGE_OR", betweenCharts: "MERGE_AND" },
  }));
});

test("a mode the pool already has writes nothing, as picking it again in its select does", () => {
  const { write, fallback } = mountPool({ betweenCharts: "MERGE_AND" });
  write({ dataPool: { betweenCharts: "MERGE_AND" } });
  expect(mockUpdateDataNode).not.toHaveBeenCalled();
  expect(fallback).not.toHaveBeenCalled();
});
