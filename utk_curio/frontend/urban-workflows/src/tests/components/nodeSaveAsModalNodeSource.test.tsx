import React from "react";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

/**
 * Where ``NodeSaveAsModal`` gets the node it packages.
 *
 * The only way into this modal is the Node settings modal's "Save as package
 * node...", whose ``onSave`` (styles.tsx) calls ``updateDataNode`` and
 * ``setSaveAsOpen(true)`` in a single batch. ``updateDataNode`` writes
 * FlowProvider's ``useNodesState`` array, which reaches React Flow's store only
 * when its prop-sync effect runs - after the render in which ``show`` flips
 * true. So on that first render the store still holds the *pre-edit* node.
 *
 * The modal used to read it with
 * ``useMemo(() => getNodes().find(...), [show, nodeId, getNodes])``, which
 * sampled exactly that render and, because none of those deps ever change
 * again, kept the stale node for the modal's whole lifetime. Every edit made in
 * Node settings - label, description, ports - was silently dropped from the
 * saved package.
 *
 * The fix is to select off the store instead of sampling it. The regression
 * this file guards is a return to sampling, in any form: the assertion is that
 * a node change *after mount* is picked up, which a snapshot cannot do.
 * ``test_package_metadata_roundtrip_e2e.py`` proves the same thing end to end;
 * this catches it in milliseconds.
 */

// packagesApi re-exports refreshPackageRegistry, which drags in the whole
// node-adapter graph (packagesClient -> adapters/node -> vegaBehavior ->
// FlowProvider -> registry -> adapters/node) and deadlocks on the cycle under
// Jest's CommonJS interop. Stubbing the bootstrap cuts the edge; nothing here
// touches it. Same trick as nodeSaveAsExport.test.ts.
jest.mock("../../registry/packageRegistryBootstrap", () => ({
  refreshPackageRegistry: jest.fn(),
}));

const mockStore: { nodeInternals: Map<string, any> } = {
  nodeInternals: new Map(),
};

jest.mock("reactflow", () => ({
  useReactFlow: () => ({ setNodes: jest.fn(), getNodes: () => [] }),
  // The real hook subscribes and re-runs the selector against current state.
  // Running it against the live object on every render is enough to tell a
  // selector apart from a snapshot.
  useStore: (selector: (s: unknown) => unknown) => selector(mockStore),
}));

jest.mock("../../providers/StarterProvider", () => ({
  useStarterContext: () => ({ getStarters: () => [] }),
}));
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ projectId: "p1" }),
}));
jest.mock("../../registry", () => ({
  getPaletteNodeTypes: () => [],
  subscribeToRegistry: () => () => {},
}));
jest.mock("../../registry/nodeRegistry", () => ({
  tryGetNodeDescriptor: () => ({
    id: "curio.builtin/computation-analysis",
    label: "Python Computation",
  }),
}));
jest.mock("../../utils/flowNodeCanonicalType", () => ({
  getFlowNodeCanonicalType: () => "curio.builtin/computation-analysis",
}));

import { NodeSaveAsModal } from "../../components/packages/editing/NodeSaveAsModal";

const NODE_ID = "n1";

/** Put a node in the store the way React Flow's prop-sync would. */
function setStoreNode(label?: string) {
  mockStore.nodeInternals = new Map([
    [
      NODE_ID,
      {
        id: NODE_ID,
        type: "curio.builtin/computation-analysis",
        data: {
          nodeType: "curio.builtin/computation-analysis",
          ...(label ? { packageTemplateLabel: label } : {}),
        },
      },
    ],
  ]);
}

/** The modal seeds this from the node's label, so it is the visible proxy. */
const packageNameField = () =>
  document.getElementById("save-as-new-package-name") as HTMLInputElement;

beforeEach(() => {
  mockStore.nodeInternals = new Map();
});

describe("NodeSaveAsModal - the node it packages", () => {
  test("reads the node's label out of the store", () => {
    setStoreNode("Configured Kind");
    render(<NodeSaveAsModal show nodeId={NODE_ID} onClose={jest.fn()} />);
    expect(packageNameField()).toHaveValue("Configured Kind package");
  });

  test("picks up a node that only reaches the store after mount", () => {
    // Exactly the Node settings handoff: the modal renders with `show` true
    // while the store still holds the pre-edit node, and the edited one lands
    // one sync later. A snapshot taken on the first render never sees it.
    setStoreNode();
    const { rerender } = render(
      <NodeSaveAsModal show nodeId={NODE_ID} onClose={jest.fn()} />,
    );
    expect(packageNameField()).toHaveValue("Python Computation package");

    setStoreNode("Configured Kind");
    rerender(<NodeSaveAsModal show nodeId={NODE_ID} onClose={jest.fn()} />);

    expect(packageNameField()).toHaveValue("Configured Kind package");
  });

  test("renders nothing while closed, whatever the store holds", () => {
    // The `show` guard is load-bearing for cost: this modal is rendered once
    // per canvas node, so the closed ones must select a stable null rather than
    // a node object that changes identity on every store write.
    setStoreNode("Configured Kind");
    render(<NodeSaveAsModal show={false} nodeId={NODE_ID} onClose={jest.fn()} />);
    expect(screen.queryByText("Save as package node")).toBeNull();
  });
});
