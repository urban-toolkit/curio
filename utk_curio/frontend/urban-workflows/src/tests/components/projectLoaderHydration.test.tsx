/**
 * How a load hands saved outputs back to the nodes, and what a dashboard load
 * does not do.
 *
 * A saved output reaches a tile through `hydrateRestoredOutputs`, which pushes it
 * into every node downstream of its producer. Which nodes those are was read off
 * React Flow's store - written from an effect, so a render behind the load, and
 * empty at the moment the restore ran. Whether a restore reached anyone was a
 * race. The canvas hid it behind the Play button; the dashboard has no Play. So
 * the loader now passes the edges the load itself just built.
 *
 * A dashboard load also must not auto-install the dataflow's Python packages:
 * opening a page to look at it is not consent to install anything server-side.
 */
import React from "react";
import { render, waitFor } from "@testing-library/react";

const mockEnsureWorkflowDeps = jest.fn();
const mockLoadProject = jest.fn();
const mockLoadSharedProject = jest.fn();
const mockLoadTrill = jest.fn();
const mockSetOutputs = jest.fn();
const mockHydrateRestoredOutputs = jest.fn();

let mockRouteId = "11111111-2222-3333-4444-555555555555";

jest.mock("react-router-dom", () => ({
  useParams: () => ({ id: mockRouteId }),
  useNavigate: () => jest.fn(),
}));
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    loadProject: mockLoadProject,
    loadSharedProject: mockLoadSharedProject,
    setOutputs: mockSetOutputs,
    hydrateRestoredOutputs: mockHydrateRestoredOutputs,
    loadParsedTrill: jest.fn(),
    projectId: null,
  }),
}));
jest.mock("../../hook/useCode", () => ({
  useCode: () => ({ loadTrill: mockLoadTrill }),
}));
jest.mock("../../hook/useEnsureWorkflowDeps", () => ({
  useEnsureWorkflowDeps: () => mockEnsureWorkflowDeps,
}));
jest.mock("../../TrillGenerator", () => ({ TrillGenerator: { reset: jest.fn() } }));
jest.mock("../../registry/packageRegistryBootstrap", () => ({
  refreshPackageRegistry: jest.fn().mockResolvedValue(undefined),
}));
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));
jest.mock("../../registry/projectPackagesStore", () => ({
  clearCurrentProject: jest.fn(),
  setCurrentProject: jest.fn(),
  setUnsavedDataflow: jest.fn(),
  setCurrentProjectPackages: jest.fn(),
}));

import { ProjectLoader, useProjectLoadState } from "../../components/ProjectLoader";

const SPEC = {
  dataflow: { nodes: [{ id: "py" }, { id: "chart" }], edges: [], packages: ["x@1"] },
};
const BUILT_EDGES = [{ id: "e1", source: "py", target: "chart", sourceHandle: "out", targetHandle: "in" }];
const OUTPUTS = [{ node_id: "py", filename: "1700000000000_deadbeef_output.parquet", data_type: "dataframe" }];

const notFound = () => Object.assign(new Error("not found"), { status: 404 });

/** Renders the load state into the DOM, so the test reads it like the page does. */
const StateProbe: React.FC = () => <span data-testid="state">{useProjectLoadState()}</span>;

const renderLoader = (presentation = false) =>
  render(
    <ProjectLoader presentation={presentation}>
      <StateProbe />
    </ProjectLoader>,
  );

beforeEach(() => {
  jest.clearAllMocks();
  mockRouteId = `11111111-2222-3333-4444-${String(Date.now()).slice(-12)}`;
  mockLoadTrill.mockReturnValue({ nodes: SPEC.dataflow.nodes, edges: BUILT_EDGES });
});

describe("restoring saved outputs", () => {
  it("hydrates against the edges the load built", async () => {
    mockLoadProject.mockResolvedValue({ spec: SPEC, outputs: OUTPUTS });

    renderLoader();

    await waitFor(() => expect(mockHydrateRestoredOutputs).toHaveBeenCalled());
    const [restored, edges] = mockHydrateRestoredOutputs.mock.calls[0];
    // The TYPE travels with the name: a Vega node refuses an input whose type it
    // cannot see, so a bare filename restored a chart that then refused its own
    // data.
    expect(restored).toEqual([{
      nodeId: "py",
      output: { path: OUTPUTS[0].filename, dataType: "dataframe" },
    }]);
    // Not the store: React Flow has not seen these edges yet.
    expect(edges).toBe(BUILT_EDGES);
    expect(mockSetOutputs).toHaveBeenCalled();
  });

  it("does the same for a visitor on the shared endpoint", async () => {
    mockLoadProject.mockRejectedValue(notFound());
    mockLoadSharedProject.mockResolvedValue({ spec: SPEC, outputs: OUTPUTS });

    renderLoader(true);

    await waitFor(() => expect(mockHydrateRestoredOutputs).toHaveBeenCalled());
    expect(mockHydrateRestoredOutputs.mock.calls[0][1]).toBe(BUILT_EDGES);
  });

  it("falls back to the bare name when the manifest recorded no type", async () => {
    // Older manifests have refs without one; they must still restore.
    mockLoadProject.mockResolvedValue({
      spec: SPEC,
      outputs: [{ node_id: "py", filename: "art_py" }],
    });

    renderLoader();

    await waitFor(() => expect(mockHydrateRestoredOutputs).toHaveBeenCalled());
    expect(mockHydrateRestoredOutputs.mock.calls[0][0]).toEqual([
      { nodeId: "py", output: "art_py" },
    ]);
  });

  it("restores nothing when nothing was saved", async () => {
    mockLoadProject.mockResolvedValue({ spec: SPEC, outputs: [] });

    renderLoader();

    await waitFor(() => expect(mockLoadTrill).toHaveBeenCalled());
    expect(mockHydrateRestoredOutputs).not.toHaveBeenCalled();
  });
});

describe("a dashboard load", () => {
  it("never auto-installs the dataflow's packages, even for the owner", async () => {
    mockLoadProject.mockResolvedValue({ spec: SPEC, outputs: [] });

    renderLoader(true);

    await waitFor(() => expect(mockLoadTrill).toHaveBeenCalled());
    expect(mockEnsureWorkflowDeps).not.toHaveBeenCalled();
  });

  it("a canvas load still does, for the owner", async () => {
    mockLoadProject.mockResolvedValue({ spec: SPEC, outputs: [] });

    renderLoader(false);

    await waitFor(() => expect(mockEnsureWorkflowDeps).toHaveBeenCalledWith(SPEC));
  });
});

describe("the load state a page can read", () => {
  it("goes from loading to loaded", async () => {
    let resolve: (value: unknown) => void = () => {};
    mockLoadProject.mockReturnValue(new Promise((r) => { resolve = r; }));

    const { getByTestId } = renderLoader(true);

    await waitFor(() => expect(getByTestId("state").textContent).toBe("loading"));
    resolve({ spec: SPEC, outputs: [] });
    await waitFor(() => expect(getByTestId("state").textContent).toBe("loaded"));
  });

  it("ends in failed when neither endpoint can produce the project", async () => {
    mockLoadProject.mockRejectedValue(notFound());
    mockLoadSharedProject.mockRejectedValue(notFound());

    const { getByTestId } = renderLoader(true);

    await waitFor(() => expect(getByTestId("state").textContent).toBe("failed"));
  });

  it("ends in failed on any other error too", async () => {
    mockLoadProject.mockRejectedValue(Object.assign(new Error("boom"), { status: 500 }));

    const { getByTestId } = renderLoader(true);

    await waitFor(() => expect(getByTestId("state").textContent).toBe("failed"));
  });
});
