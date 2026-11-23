import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import type { Node } from "reactflow";

/**
 * Save as package node gives the saved node its package's new kind, and leaves
 * every other node of the canvas as it is: a node another tab or an agent added
 * as the save ended stays.
 *
 * Curio's canvas hands React Flow its nodes as props (`nodes=`, no
 * `defaultNodes`). React Flow's `setNodes` then hands its updater React Flow's
 * own copy of the nodes, which React Flow takes from the canvas in an effect
 * after each commit, and makes what the updater returns the canvas's whole node
 * list (`reset` changes, through `applyNodeChanges`). The save's rebind went
 * through it, so a node the canvas had just taken was dropped, and the canvas
 * then wrote its removal into the dataflow's doc for everyone. Here React
 * Flow's copy lacks such a node, and its `setNodes` does what React Flow 11's
 * does on Curio's canvas.
 */

// Same cut as nodeSaveAsProjectScope.test.tsx: packagesApi re-exports
// refreshPackageRegistry, whose import graph deadlocks under Jest.
jest.mock("../../registry/packageRegistryBootstrap", () => ({
  refreshPackageRegistry: jest.fn(),
}));

/** The canvas's own nodes, and React Flow's copy of them, which lacks the node
 *  that has just landed. */
const mockCanvas: { nodes: Node[]; copy: Node[] } = { nodes: [], copy: [] };
const mockEnsureProjectId = jest.fn();
const mockShowToast = jest.fn();
const mockInstallToProject = jest.fn();
const mockFactoryInstall = jest.fn();

jest.mock("reactflow", () => {
  const { applyNodeChanges } = jest.requireActual("reactflow");
  return {
    useReactFlow: () => ({
      getNodes: () => mockCanvas.copy,
      getNode: (id: string) => mockCanvas.copy.find((node) => node.id === id),
      // React Flow 11's setNodes on a canvas that hands it its nodes: the
      // updater gets React Flow's copy, and what it returns becomes the
      // canvas's whole list.
      setNodes: (payload: any) => {
        const next = typeof payload === "function" ? payload(mockCanvas.copy) : payload;
        mockCanvas.nodes = applyNodeChanges(next.map((item: Node) => ({ type: "reset", item })), mockCanvas.nodes);
      },
    }),
    useStore: (selector: (s: unknown) => unknown) =>
      selector({ nodeInternals: new Map(mockCanvas.copy.map((node) => [node.id, node])) }),
  };
});
jest.mock("../../providers/StarterProvider", () => ({
  useStarterContext: () => ({ getStarters: () => [] }),
}));
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    ensureProjectId: mockEnsureProjectId,
    // The canvas's own change of one node's data (`useWorkflowOperations`'s
    // updateDataNode): that node's data becomes the one given.
    updateDataNode: (nodeId: string, data: any) => {
      mockCanvas.nodes = mockCanvas.nodes.map((node) => (node.id === nodeId ? { ...node, data: { ...data } } : node));
    },
  }),
}));
jest.mock("../../registry", () => ({
  getPaletteNodeTypes: () => [],
  subscribeToRegistry: () => () => {},
}));
jest.mock("../../registry/nodeRegistry", () => ({
  tryGetNodeDescriptor: () => ({
    id: "curio.builtin/python-computation",
    label: "Python Computation",
    category: "computation",
    engine: "python",
    editor: "code",
    description: "",
    hasCode: true,
    hasWidgets: false,
    hasGrammar: false,
    inputPorts: [{ types: ["JSON"], cardinality: "1" }],
    outputPorts: [{ types: ["JSON"], cardinality: "1" }],
    package: { id: "curio.builtin", major: 1, source: "python_computation.py" },
  }),
}));
jest.mock("../../utils/flowNodeCanonicalType", () => ({
  getFlowNodeCanonicalType: () => "curio.builtin/python-computation",
}));
jest.mock("../../registry/projectPackagesStore", () => ({
  setCurrentProjectPackages: jest.fn(),
}));
jest.mock("../../services/packages/packagesApi", () => ({
  packagesApi: {
    factoryInstall: (...args: unknown[]) => mockFactoryInstall(...args),
    installToProject: (...args: unknown[]) => mockInstallToProject(...args),
  },
}));
jest.mock("../../services/packages/packagesBlobTransport", () => ({
  ...jest.requireActual("../../services/packages/packagesBlobTransport"),
  triggerBlobDownload: jest.fn(),
}));

import { NodeSaveAsModal } from "../../components/packages/editing/NodeSaveAsModal";

const NODE_ID = "n1";
const LANDED = "landed";

function canvasNode(id: string, code: string): Node {
  return {
    id,
    type: "curio.builtin/python-computation",
    position: { x: 0, y: 0 },
    data: { nodeType: "curio.builtin/python-computation", code },
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  const saved = canvasNode(NODE_ID, "return [1]");
  mockCanvas.copy = [saved];
  mockCanvas.nodes = [saved, canvasNode(LANDED, "return [2]")];
  mockEnsureProjectId.mockResolvedValue("p1");
  // The package the save makes: its one kind has the node's label, so the
  // node is bound to it.
  mockFactoryInstall.mockResolvedValue({
    package: {
      dirName: "my.pkg@1",
      packageId: "my.pkg",
      name: "Python Computation package",
      templates: [{ id: "my.pkg/python-computation", label: "Python Computation" }],
    },
  });
  mockInstallToProject.mockResolvedValue({ packages: ["my.pkg@1"] });
});

test("the saved node takes its package's kind, and a node the canvas has just taken stays", async () => {
  const onClose = jest.fn();
  render(<NodeSaveAsModal show nodeId={NODE_ID} onClose={onClose} />);
  fireEvent.click(screen.getByRole("button", { name: "Save" }));

  await waitFor(() => expect(onClose).toHaveBeenCalled());
  expect(mockShowToast).toHaveBeenCalledWith(expect.stringContaining('"Python Computation"'), "success");
  const saved = mockCanvas.nodes.find((node) => node.id === NODE_ID);
  expect(saved?.data).toMatchObject({ nodeType: "my.pkg/python-computation", code: "return [1]", defaultCode: "return [1]" });
  expect(mockCanvas.nodes.map((node) => node.id)).toEqual([NODE_ID, LANDED]);
});
