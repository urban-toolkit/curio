/**
 * A node's `executedCode` is the run key its output came from: its code, its
 * widget values and the ids its selection tags hold. A play runs a node again
 * when its key differs (`runLevels.nodesToRunUpTo`).
 *
 * The node stamps it when it shows a success (useNodeState). A run's result
 * carries the key the run started with (`NodeOutput.runKey`), and that is the
 * one it is stamped with: a tag emptied while the node ran (a chart drawn
 * anew) must leave the node stale, not pass the old rows on as current.
 */
import { act, renderHook } from "@testing-library/react";

jest.mock("../../providers/StarterProvider", () => ({
  useStarterContext: () => ({ editUserStarter: jest.fn() }),
}));
jest.mock("../../providers/UserProvider", () => ({
  useUserContext: () => ({ user: null }),
}));
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ projectId: "p1", nodes: [] }),
}));
jest.mock("../../services/nodeRuntimeReport", () => ({
  reportFromNodeOutput: () => null,
  reportNodeRuntime: jest.fn(),
}));

import { useNodeState } from "../../hook/useNodeState";
import { runKeyOf } from "../../utils/references/runKeys";

const CODE = "ids = [!! selection picked !!]\nreturn input_0[input_0['osm_id'].isin(ids)]";
const picked = (ids: number[]) => [{ name: "picked", node: "scatter", column: "osm_id", ids }];

/** A counting node whose tag the chart's redraw has just emptied. */
function countingNode() {
  const data: any = { nodeId: "count", code: CODE, selections: picked([]) };
  const hook = renderHook(() => useNodeState(data, "curio.builtin/computation-analysis" as any));
  return { data, hook };
}

test("a result is stamped with the key its run started with, not the node's current one", () => {
  const { data, hook } = countingNode();
  const ranWith = runKeyOf(CODE, undefined, picked([1001, 1002, 1003, 1004, 1005]));

  act(() => hook.result.current.setOutput({ code: "success", content: "Saved to file: art", runKey: ranWith }));

  expect(data.executedCode).toBe(ranWith);
  expect(data.executedCode).not.toBe(runKeyOf(CODE, undefined, picked([])));
});

test("a result that carries no key is stamped with the node's current one", () => {
  const { data, hook } = countingNode();

  act(() => hook.result.current.setOutput({ code: "success", content: "Saved to file: art" }));

  expect(data.executedCode).toBe(runKeyOf(CODE, undefined, picked([])));
});
