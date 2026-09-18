import React from "react";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

/**
 * Save As must scope the package to a project, even from an unsaved dataflow
 * (#346).
 *
 * The new-package branch only called ``installToProject`` when a ``projectId``
 * already existed. On ``/dataflow/new`` there is none, and nothing gates the
 * "Save as package node... -> New package..." button on save state - so
 * ``factoryInstall`` ran, the success toast appeared, and the package entered
 * the user store belonging to no project at all.
 *
 * That is worse than invisible. The backend listings that feed the node catalog
 * scope by store-intersect-lockfile and do not even report a package they skip
 * (``available_templates_report``), so an agent asking for the template is told
 * it does not exist. And ``preserve_project_packages`` makes ``dataflow.packages``
 * backend-owned on update, so on a project that already declares packages the
 * lockfile backfill never runs to rescue it.
 *
 * The fix reuses ``ensureProjectId`` - the same auto-save-first helper the
 * catalog drawer got for #220/#256 - so the scoping step always has a real id.
 */
jest.mock("../../registry/packageRegistryBootstrap", () => ({
  refreshPackageRegistry: jest.fn(),
}));

const mockStore: { nodeInternals: Map<string, any> } = { nodeInternals: new Map() };
const mockEnsureProjectId = jest.fn();
const mockShowToast = jest.fn();
const mockInstallToProject = jest.fn();
const mockFactoryInstall = jest.fn();
const mockSetCurrentProjectPackages = jest.fn();
const mockRefreshRegistry = jest.fn();

jest.mock("reactflow", () => ({
  useReactFlow: () => ({ setNodes: jest.fn(), getNodes: () => [] }),
  useStore: (selector: (s: unknown) => unknown) => selector(mockStore),
}));
jest.mock("../../providers/StarterProvider", () => ({
  useStarterContext: () => ({ getStarters: () => [] }),
}));
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));
jest.mock("../../providers/FlowProvider", () => ({
  // No projectId at all: this IS the unsaved dataflow.
  useFlowContext: () => ({ ensureProjectId: mockEnsureProjectId }),
}));
jest.mock("../../registry", () => ({
  getPaletteNodeTypes: () => [],
  subscribeToRegistry: () => () => {},
}));
// A fuller descriptor than the sibling suite's: that one never clicks Save, so
// it never reaches the draft builder, which reads ports and category off this.
jest.mock("../../registry/nodeRegistry", () => ({
  tryGetNodeDescriptor: () => ({
    id: "curio.builtin/computation-analysis",
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
    package: { id: "curio.builtin", major: 1, source: "computation_analysis.py" },
  }),
}));
jest.mock("../../utils/flowNodeCanonicalType", () => ({
  getFlowNodeCanonicalType: () => "curio.builtin/computation-analysis",
}));
jest.mock("../../registry/projectPackagesStore", () => ({
  setCurrentProjectPackages: (...args: unknown[]) => mockSetCurrentProjectPackages(...args),
}));
// NodeSaveAsModal imports refreshPackageRegistry from here, not from the
// bootstrap module, so it has to be part of this mock.
jest.mock("../../api/packagesApi", () => ({
  packagesApi: {
    factoryInstall: (...args: unknown[]) => mockFactoryInstall(...args),
    installToProject: (...args: unknown[]) => mockInstallToProject(...args),
  },
  refreshPackageRegistry: (...args: unknown[]) => mockRefreshRegistry(...args),
  triggerBlobDownload: jest.fn(),
}));

import { NodeSaveAsModal } from "../../components/packages/editing/NodeSaveAsModal";

const NODE_ID = "n1";

function setStoreNode() {
  mockStore.nodeInternals = new Map([
    [NODE_ID, {
      id: NODE_ID,
      type: "curio.builtin/computation-analysis",
      data: { nodeType: "curio.builtin/computation-analysis", code: "return [1]" },
    }],
  ]);
}

beforeEach(() => {
  jest.clearAllMocks();
  setStoreNode();
  mockFactoryInstall.mockResolvedValue({
    package: { dirName: "my.pkg@1", templates: [] },
  });
  mockInstallToProject.mockResolvedValue({ packages: ["my.pkg@1"] });
});

function save() {
  render(<NodeSaveAsModal show nodeId={NODE_ID} onClose={jest.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
}

describe("Save as package node, from an unsaved dataflow", () => {
  test("saves the dataflow first, then scopes the package to it", async () => {
    mockEnsureProjectId.mockResolvedValue("created-project-id");

    save();

    await waitFor(() => expect(mockInstallToProject).toHaveBeenCalled());
    expect(mockEnsureProjectId).toHaveBeenCalled();
    // The id the auto-save produced, not the one the modal started with (none).
    expect(mockInstallToProject).toHaveBeenCalledWith("created-project-id", "my.pkg@1");
    expect(mockSetCurrentProjectPackages).toHaveBeenCalledWith(["my.pkg@1"]);
  });

  test("scopes it before the registry refresh, not after", async () => {
    // refreshPackageRegistry filters by the project lockfile, so a refresh that
    // ran first would register nothing and the palette would stay empty until
    // the next reload.
    const order: string[] = [];
    mockEnsureProjectId.mockResolvedValue("p9");
    mockInstallToProject.mockImplementation(async () => {
      order.push("installToProject");
      return { packages: [] };
    });
    mockRefreshRegistry.mockImplementation(async () => {
      order.push("refresh");
    });

    save();

    await waitFor(() => expect(order).toEqual(["installToProject", "refresh"]));
  });

  test("does not install to a project when the dataflow could not be saved", async () => {
    // ensureProjectId toasts its own failure; installing against `null` would
    // 404 and replace that message with a worse one.
    mockEnsureProjectId.mockResolvedValue(null);

    save();

    await waitFor(() => expect(mockFactoryInstall).toHaveBeenCalled());
    expect(mockInstallToProject).not.toHaveBeenCalled();
  });
});

describe("Save as package node, on a saved dataflow", () => {
  test("still scopes the package, without creating anything", async () => {
    // ensureProjectId returns the existing id without forcing a save.
    mockEnsureProjectId.mockResolvedValue("p1");

    save();

    await waitFor(() => expect(mockInstallToProject).toHaveBeenCalledWith("p1", "my.pkg@1"));
  });
});
