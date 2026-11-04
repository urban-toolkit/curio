import React from "react";
import { flushSync } from "react-dom";
import { createRoot } from "react-dom/client";
import { act, fireEvent, render } from "@testing-library/react";
import "@testing-library/jest-dom";

/**
 * Save as package node keeps what the person typed when the package list
 * refreshes.
 *
 * The modal fills its destination and its new package name with defaults: the
 * first writable package, and "<node label> package". It re-applied them every
 * time the package list changed, and that list follows the node registry, which
 * grows while packages load. A refresh landing while the modal was open threw
 * away the chosen destination and the typed name. In the save-as e2e test the
 * default name arrived in the middle of Playwright's fill, and the exported
 * package was called "Python Computation packageSaved Roundtrip Package".
 */

// Same cut as nodeSaveAsModalNodeSource.test.tsx: packagesApi re-exports
// refreshPackageRegistry, whose import graph deadlocks under Jest.
jest.mock("../../registry/packageRegistryBootstrap", () => ({
  refreshPackageRegistry: jest.fn(),
}));

const mockStore: { nodeInternals: Map<string, any> } = { nodeInternals: new Map() };
jest.mock("reactflow", () => ({
  useReactFlow: () => ({ setNodes: jest.fn(), getNodes: () => [] }),
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

/** The node registry as the modal sees it: palette types, and who to tell when they change. */
const mockRegistry: { types: any[]; listeners: Set<() => void> } = { types: [], listeners: new Set() };
jest.mock("../../registry", () => ({
  getPaletteNodeTypes: () => mockRegistry.types,
  subscribeToRegistry: (listener: () => void) => {
    mockRegistry.listeners.add(listener);
    return () => mockRegistry.listeners.delete(listener);
  },
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

/** A writable package's template, as the registry lists it once the package loads. */
function packageTemplate(packageId: string, name: string) {
  return {
    id: `${packageId}/node`,
    label: "Some node",
    source: "package",
    package: { packageId, major: 1, name, version: "1.0.0", readOnly: false },
  };
}

/** The registry gains *templates* and tells its listeners, as a package finishing its load does. */
function registryRefreshes(...templates: any[]) {
  act(() => {
    mockRegistry.types = [...mockRegistry.types, ...templates];
    mockRegistry.listeners.forEach((listener) => listener());
  });
}

const targetField = () => document.getElementById("save-as-package-target") as HTMLSelectElement;
const nameField = () => document.getElementById("save-as-new-package-name") as HTMLInputElement | null;

beforeEach(() => {
  mockRegistry.types = [];
  mockRegistry.listeners.clear();
  mockStore.nodeInternals = new Map([
    [NODE_ID, { id: NODE_ID, type: "curio.builtin/computation-analysis", data: { nodeType: "curio.builtin/computation-analysis" } }],
  ]);
});

describe("NodeSaveAsModal - a package list refresh while it is open", () => {
  test("keeps a typed package name", () => {
    render(<NodeSaveAsModal show nodeId={NODE_ID} onClose={jest.fn()} />);
    expect(nameField()).toHaveValue("Python Computation package");

    fireEvent.change(nameField()!, { target: { value: "Saved Roundtrip Package" } });
    registryRefreshes(packageTemplate("me.unrelated", "Unrelated"));

    // Typing a name is choosing the new package: the package that just loaded
    // does not take its place as the destination.
    expect(targetField().selectedOptions[0]?.textContent).toBe("New package…");
    expect(nameField()).toHaveValue("Saved Roundtrip Package");
  });

  test("keeps a chosen destination", () => {
    mockRegistry.types = [packageTemplate("me.first", "First")];
    render(<NodeSaveAsModal show nodeId={NODE_ID} onClose={jest.fn()} />);
    // The default is the first writable package; the person picks New package.
    const newPackage = Array.from(targetField().options).find((o) => o.textContent === "New package…")!;
    fireEvent.change(targetField(), { target: { value: newPackage.value } });
    fireEvent.change(nameField()!, { target: { value: "Saved Roundtrip Package" } });

    registryRefreshes(packageTemplate("me.second", "Second"));

    expect(targetField()).toHaveValue(newPackage.value);
    expect(nameField()).toHaveValue("Saved Roundtrip Package");
  });

  test("still follows the package list until the person changes something", () => {
    // Nothing chosen yet: a package that loads after the modal opened becomes
    // the default destination, as it would have been had it loaded first.
    render(<NodeSaveAsModal show nodeId={NODE_ID} onClose={jest.fn()} />);
    expect(nameField()).not.toBeNull();

    registryRefreshes(packageTemplate("me.first", "First"));

    expect(targetField().selectedOptions[0]?.textContent).toBe("First");
  });

  test("opens with fresh defaults the next time", () => {
    const { rerender } = render(<NodeSaveAsModal show nodeId={NODE_ID} onClose={jest.fn()} />);
    fireEvent.change(nameField()!, { target: { value: "Saved Roundtrip Package" } });

    rerender(<NodeSaveAsModal show={false} nodeId={NODE_ID} onClose={jest.fn()} />);
    rerender(<NodeSaveAsModal show nodeId={NODE_ID} onClose={jest.fn()} />);

    expect(nameField()).toHaveValue("Python Computation package");
  });
});

describe("NodeSaveAsModal - what it first draws", () => {
  // The first render holds the defaults. An effect used to set them, and React
  // renders the state an effect sets in a task of its own, so the modal was
  // drawn first with an empty name: Playwright's fill selected that empty
  // field, the default landed, and the typed name went after it ("Python
  // Computation packageSaved Roundtrip Package", stress dispatch 40814093594).
  // A root rendered with flushSync, outside act(), which would also run what
  // React defers, shows what the person has before React gets to it.
  test("shows the default destination and name before anything React defers", () => {
    const scope = globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean };
    const actEnvironment = scope.IS_REACT_ACT_ENVIRONMENT;
    scope.IS_REACT_ACT_ENVIRONMENT = false;
    const container = document.body.appendChild(document.createElement("div"));
    const root = createRoot(container);
    try {
      flushSync(() => root.render(<NodeSaveAsModal show nodeId={NODE_ID} onClose={jest.fn()} />));

      expect(targetField().selectedOptions[0]?.textContent).toBe("New package…");
      expect(nameField()).toHaveValue("Python Computation package");
    } finally {
      root.unmount();
      container.remove();
      scope.IS_REACT_ACT_ENVIRONMENT = actEnvironment;
    }
  });
});
