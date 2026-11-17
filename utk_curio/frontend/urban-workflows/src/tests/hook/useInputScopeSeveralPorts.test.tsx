/**
 * What a node's editor reads of each of its inputs (hook/useInputScope): each
 * input chip's type and columns, a chip's hover (the node feeding it, the
 * state of its output, and what the input holds once read), and the inputs a
 * run waits for.
 *
 * A node with several input ports (the Spatial Join's `in` and `in_1`) keeps
 * each port's input by handle (`data.portInputs`) and holds no `inputSlots`.
 * Its run reads them port k on circle k (`nodeInputFromPorts`), and so must its
 * editor. The hook read circle 0 from `data.input`, the run's bundle of both
 * inputs, and circle 1 from nothing, on every canvas: input_0's chip read as
 * one value of type "outputs", input_1's hover said its node had not run, a
 * hover of input_0 read both outputs, and a run in the browser was refused with
 * both inputs saying "has no value yet" (dev 0.17.332, example 32 and example
 * 25, a hosted guest's Run All).
 *
 * The join is example 32's, its data put on it by the canvas's own writers
 * (`withPortValues`, `nodeInputFromPorts`).
 */
import { act, renderHook, waitFor } from "@testing-library/react";

const JOIN_ID = "idot-objects-in-zones";
const ON_THE_GROUND_ID = "idot-on-the-ground";
const ZONES_ID = "idot-zones-on-the-ground";

const mockFlow = {
  nodes: [
    { id: ON_THE_GROUND_ID, data: { nodeType: "curio.builtin/python-computation", title: "On the ground" } },
    { id: ZONES_ID, data: { nodeType: "curio.builtin/python-computation", title: "Zones on the ground" } },
  ],
  edges: [
    { id: "e-in", source: ON_THE_GROUND_ID, sourceHandle: "out", target: JOIN_ID, targetHandle: "in" },
    { id: "e-in_1", source: ZONES_ID, sourceHandle: "out", target: JOIN_ID, targetHandle: "in_1" },
  ],
  scenarios: [],
  nodeExecStatus: { [ON_THE_GROUND_ID]: "executed", [ZONES_ID]: "executed" },
};
jest.mock("../../providers/FlowProvider", () => ({ useFlowContext: () => mockFlow }));

const mockFetchPreviewData = jest.fn();
jest.mock("../../services/api", () => ({
  fetchData: jest.fn(),
  fetchPreviewData: (...args: any[]) => mockFetchPreviewData(...args),
}));

import { useInputScope } from "../../hook/useInputScope";
import { nodeInputFromPorts, withPortValues } from "../../utils/inputSlots";

/** What each node feeding the join handed it, from dev's evidence. */
const ON_THE_GROUND = { path: "1794945771869_ab89a326", dataType: "geodataframe" };
const ZONES = { path: "1794945771387_fd09adaa", dataType: "geodataframe" };

/** The join's data once the inputs in *arrivals* reached it, in that order, as
 *  the canvas's writers leave it (providers/flow/useGraphEdits). */
function joinData(arrivals: Array<[string, unknown]>) {
  let portInputs: Record<string, unknown> = {};
  for (const [handle, value] of arrivals) portInputs = withPortValues(portInputs, [handle], value);
  return {
    nodeId: JOIN_ID,
    nodeType: "curio.builtin/spatial-join",
    portInputs,
    input: nodeInputFromPorts(portInputs, [0, 1]),
  };
}

const BOTH = joinData([["in_1", ZONES], ["in", ON_THE_GROUND]]);

beforeEach(() => {
  mockFetchPreviewData.mockReset();
  mockFetchPreviewData.mockResolvedValue({
    dataType: "geodataframe",
    data: { type: "FeatureCollection", features: [] },
  });
});

describe("a node with several input ports reads each input from its port", () => {
  test("both arrived: each chip has its own port's type, and a run waits for neither", () => {
    const { result } = renderHook(() => useInputScope(BOTH));

    expect(result.current.inputs.map(({ slot, label, dataType }) => ({ slot, label, dataType }))).toEqual([
      { slot: 0, label: "On the ground", dataType: "geodataframe" },
      { slot: 1, label: "Zones on the ground", dataType: "geodataframe" },
    ]);
    expect(result.current.emptyInputs).toEqual([]);
  });

  test("both arrived: each chip's hover says the node feeding it is done", () => {
    const { result } = renderHook(() => useInputScope(BOTH));

    expect(
      Object.entries(result.current.previews).map(([slot, state]) => [slot, state.source.title, state.source.status]),
    ).toEqual([
      ["0", "On the ground", "done"],
      ["1", "Zones on the ground", "done"],
    ]);
  });

  test("only the zones arrived: input_0 is the one a run waits for, and its hover says its node has not run", () => {
    const { result } = renderHook(() => useInputScope(joinData([["in_1", ZONES]])));

    expect(result.current.emptyInputs).toEqual([0]);
    expect(result.current.inputs.map((input) => input.dataType)).toEqual([undefined, "geodataframe"]);
    expect(Object.values(result.current.previews).map((state) => state.source.status)).toEqual(["not-run", "done"]);
  });

  test.each([
    [0, ON_THE_GROUND.path],
    [1, ZONES.path],
  ])("a hover of input_%i reads its own port's output, and nothing else", async (slot, path) => {
    const { result } = renderHook(() => useInputScope(BOTH));

    act(() => result.current.loadPreview(slot));

    await waitFor(() => expect(result.current.previews[slot].preview).toBeDefined());
    expect(mockFetchPreviewData.mock.calls.map(([read]) => read)).toEqual([path]);
  });
});

describe("a growing node reads its circles as before", () => {
  test("each circle from its inputSlots, and a run waits for the empty one", () => {
    const growing = { nodeId: JOIN_ID, nodeType: "curio.builtin/python-computation", inputSlots: [ON_THE_GROUND, undefined], input: "" };
    const { result } = renderHook(() => useInputScope(growing));

    expect(result.current.inputs.map((input) => input.dataType)).toEqual(["geodataframe", undefined]);
    expect(result.current.emptyInputs).toEqual([1]);
  });
});
