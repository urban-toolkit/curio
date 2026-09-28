/**
 * A Data Pool says when an output is a selection coming back, not new data.
 *
 * Every chart the pool feeds receives both kinds as a new `data.input`. A
 * selection only re-flags the rows (`interacted`), which a chart highlights in
 * the view it already has; new data is what a chart redraws for. The pool is the
 * only node that knows which one it is sending, so it says so on the emit.
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import type { NodeBehaviorData, UseNodeStateReturn } from "../../../registry/types";
import { VisInteractionType } from "../../../constants";

jest.mock("reactflow", () => ({ useEdges: () => [] }));
jest.mock("../../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ nodeExecStatus: {}, workflowNameRef: { current: "wf" } }),
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
