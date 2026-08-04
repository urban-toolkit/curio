import React from "react";
import { render, act, waitFor } from "@testing-library/react";

const mockCreateCodeNode = jest.fn();
jest.mock("../../hook/useCode", () => ({
  useCode: () => ({ createCodeNode: mockCreateCodeNode }),
}));

const mockApplyNodeContent = jest.fn();
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ applyNodeContent: mockApplyNodeContent }),
}));

const mockGetNodes = jest.fn(() => [] as Array<{ id: string }>);
const mockSetCenter = jest.fn();
const mockGetZoom = jest.fn(() => 0.8);
jest.mock("reactflow", () => ({
  useReactFlow: () => ({
    getNodes: mockGetNodes,
    setCenter: mockSetCenter,
    getZoom: mockGetZoom,
  }),
}));

const mockRefreshPackageRegistry = jest.fn(() => Promise.resolve());
jest.mock("../../registry/packageRegistryBootstrap", () => ({
  refreshPackageRegistry: (...a: unknown[]) => mockRefreshPackageRegistry(...a),
}));

const mockGetCurrentProjectPackages = jest.fn((): ReadonlySet<string> | null => new Set(["curio.builtin@1"]));
const mockSetCurrentProjectPackages = jest.fn();
jest.mock("../../registry/projectPackagesStore", () => ({
  getCurrentProjectPackages: () => mockGetCurrentProjectPackages(),
  setCurrentProjectPackages: (p: Iterable<string>) => mockSetCurrentProjectPackages(p),
}));

import { useAgentCanvasMutations } from "../../components/agents/attach/useAgentCanvasMutations";
import {
  notifyAgentCanvasMutation,
  subscribeAgentCanvasMutations,
} from "../../utils/agentCanvasEvents";

const Host: React.FC = () => {
  useAgentCanvasMutations();
  return null;
};

const NODE = {
  id: "server-minted-id",
  type: "curio.builtin/computation-analysis",
  content: "print('new')",
  goal: "sum it",
  x: 500,
  y: 60,
};

beforeEach(() => {
  jest.clearAllMocks();
  mockGetNodes.mockReturnValue([]);
});

describe("agentCanvasEvents", () => {
  it("notify reaches subscribers and unsubscribe stops delivery", () => {
    const seen: unknown[] = [];
    const off = subscribeAgentCanvasMutations((m) => seen.push(m));
    notifyAgentCanvasMutation({ kind: "node-content-applied", nodeId: "n1", content: "c" });
    off();
    notifyAgentCanvasMutation({ kind: "node-content-applied", nodeId: "n2", content: "c" });
    expect(seen).toEqual([{ kind: "node-content-applied", nodeId: "n1", content: "c" }]);
  });
});

describe("useAgentCanvasMutations (the apply→canvas bridge, dev/48 §3.3 + dev/51)", () => {
  it("node-created inserts through the existing factory with the SERVER id", () => {
    render(<Host />);
    act(() => notifyAgentCanvasMutation({ kind: "node-created", node: NODE }));
    expect(mockCreateCodeNode).toHaveBeenCalledWith("curio.builtin/computation-analysis", {
      nodeId: "server-minted-id",
      code: "print('new')",
      goal: "sum it",
      position: { x: 500, y: 60 },
    });
    // No registry writes for an existing template.
    expect(mockRefreshPackageRegistry).not.toHaveBeenCalled();
    expect(mockSetCurrentProjectPackages).not.toHaveBeenCalled();
  });

  it("centers the viewport on the created node at the current zoom (dev/51 defect 1)", () => {
    render(<Host />);
    act(() => notifyAgentCanvasMutation({ kind: "node-created", node: NODE }));
    expect(mockSetCenter).toHaveBeenCalledWith(675, 160, { zoom: 0.8, duration: 400 });
  });

  it("a double event is a no-op when the node already exists live", () => {
    mockGetNodes.mockReturnValue([{ id: "server-minted-id" }]);
    render(<Host />);
    act(() => notifyAgentCanvasMutation({ kind: "node-created", node: NODE }));
    expect(mockCreateCodeNode).not.toHaveBeenCalled();
  });

  it("a re-fired event before the store syncs is a no-op (dev/51 defect 3)", () => {
    // The store never reports the node (sync lag) — the processed-ids ref
    // must still stop the second insert.
    mockGetNodes.mockReturnValue([]);
    render(<Host />);
    act(() => notifyAgentCanvasMutation({ kind: "node-created", node: NODE }));
    act(() => notifyAgentCanvasMutation({ kind: "node-created", node: NODE }));
    expect(mockCreateCodeNode).toHaveBeenCalledTimes(1);
  });

  it("a created TEMPLATE lands in the store + registry BEFORE the node inserts", async () => {
    const order: string[] = [];
    mockSetCurrentProjectPackages.mockImplementation(() => order.push("store"));
    mockRefreshPackageRegistry.mockImplementation(() => {
      order.push("registry");
      return Promise.resolve();
    });
    mockCreateCodeNode.mockImplementation(() => order.push("insert"));
    render(<Host />);
    act(() =>
      notifyAgentCanvasMutation({
        kind: "node-created",
        node: { ...NODE, type: "curio.agent.scorer/scorer" },
        createdPackageDir: "curio.agent.scorer@1",
      }),
    );
    await waitFor(() => expect(order).toEqual(["store", "registry", "insert"]));
    const stored = mockSetCurrentProjectPackages.mock.calls[0][0] as string[];
    expect(Array.from(stored)).toEqual(["curio.builtin@1", "curio.agent.scorer@1"]);
  });

  it("node-content-applied routes through FlowProvider.applyNodeContent (dev/51 defect 2)", () => {
    render(<Host />);
    act(() =>
      notifyAgentCanvasMutation({
        kind: "node-content-applied",
        nodeId: "n1",
        content: "print(2)",
      }),
    );
    expect(mockApplyNodeContent).toHaveBeenCalledWith("n1", "print(2)");
  });
});
