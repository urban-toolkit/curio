import { useLayoutEffect } from "react";
import { renderHook, act } from "@testing-library/react";

/**
 * A goal written on an agent chat's Goal line reaches the dataflow's doc in
 * the commit that sets it. The doc's writer (useDataflowDoc) is a layout effect
 * that runs when `workflowGoal` changes and reads `workflowGoalRef`; layout
 * effects run before passive ones. A ref moved by an effect gave the writer
 * the goal before this one, so the new goal waited for some later canvas
 * change to reach the server, and a reload lost it (the dev check of #1623 on
 * 11-25, ci-reports/goal-in-chat-dev-1125).
 */
jest.mock("reactflow", () => ({
  useReactFlow: () => ({ getNodes: () => [], getEdges: () => [] }),
  useNodesInitialized: () => false,
}));
jest.mock("../../providers/ProvenanceProvider", () => ({
  useProvenanceContext: () => ({ getAllNodeProvenance: () => ({}) }),
}));
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));
jest.mock("../../providers/UserProvider", () => ({
  useUserContext: () => ({ user: null, enableUserAuth: false }),
}));
jest.mock("../../api/projectsApi", () => ({
  projectsApi: {
    create: jest.fn(), update: jest.fn(), get: jest.fn(), getShared: jest.fn(),
    recordOutputs: jest.fn(), renameShared: jest.fn(),
  },
}));
jest.mock("../../TrillGenerator", () => ({
  TrillGenerator: {
    generateTrill: jest.fn(() => ({ dataflow: { datasets: [] } })),
    getSerializableDataflowProvenance: jest.fn(() => ({})),
    reset: jest.fn(),
  },
}));
jest.mock("../../utils/saveOutputDataset", () => ({
  buildSaveableLiveOutputs: jest.fn(() => []),
}));
jest.mock("../../registry/projectPackagesStore", () => ({
  getCurrentProjectPackagesList: jest.fn(() => []),
  getCurrentProjectId: jest.fn(() => undefined),
  whenProjectSettled: jest.fn(async () => {}),
  setCurrentProject: jest.fn(),
  setCurrentProjectPackages: jest.fn(),
  subscribe: jest.fn(() => jest.fn()),
}));

import { useWorkflowOperations } from "../../hook/useWorkflowOperations";

const makeDeps = () =>
  ({
    nodes: [],
    edges: [],
    setNodes: jest.fn(),
    setEdges: jest.fn(),
    setOutputs: jest.fn(),
    outputsRef: { current: [] },
    setInteractions: jest.fn(),
    setDashboardPins: jest.fn(),
    setWorkflowName: jest.fn(),
    workflowNameRef: { current: "Loaded name" },
    setWorkflowDescription: jest.fn(),
    workflowDescriptionRef: { current: "" },
    onEdgesDelete: jest.fn(),
    onNodesDelete: jest.fn(),
    onNodesChange: jest.fn(),
    onConnect: jest.fn(),
    addNode: jest.fn(),
    defaultSaveOutputDataset: false,
    docBridgeRef: {
      current: {
        bound: () => true,
        whenBound: jest.fn(async () => true),
        whenKept: jest.fn(async () => true),
        canvasNow: jest.fn(() => ({})),
      },
    },
  }) as any;

describe("the dataflow's goal reaches the doc in the commit that sets it", () => {
  it("is in its ref when a layout effect of that commit reads it, as the doc's writer does", () => {
    // The writer's shape: a layout effect on the goal that reads its ref.
    const writes: string[] = [];
    const deps = makeDeps();
    const { result } = renderHook(() => {
      const ops = useWorkflowOperations(deps);
      useLayoutEffect(() => {
        writes.push(ops.workflowGoalRef.current);
      }, [ops.workflowGoal]);
      return ops;
    });

    act(() => {
      result.current.setWorkflowGoal("Find heat islands in Chicago");
    });

    expect(result.current.workflowGoal).toBe("Find heat islands in Chicago");
    expect(writes[writes.length - 1]).toBe("Find heat islands in Chicago");
  });

  it("moves its ref as it is set, before any render", () => {
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));
    let read: string | null = null;
    act(() => {
      result.current.setWorkflowGoal("Map tree canopy");
      read = result.current.workflowGoalRef.current;
    });
    expect(read).toBe("Map tree canopy");
  });

  it("clears the same way", () => {
    const writes: string[] = [];
    const deps = makeDeps();
    const { result } = renderHook(() => {
      const ops = useWorkflowOperations(deps);
      useLayoutEffect(() => {
        writes.push(ops.workflowGoalRef.current);
      }, [ops.workflowGoal]);
      return ops;
    });
    act(() => {
      result.current.setWorkflowGoal("Find heat islands");
    });
    act(() => {
      result.current.setWorkflowGoal("");
    });
    expect(writes[writes.length - 1]).toBe("");
  });
});
