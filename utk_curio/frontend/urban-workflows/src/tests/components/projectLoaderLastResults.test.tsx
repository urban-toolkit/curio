/**
 * What a dataflow opens with. A canvas asks for the results it was left with
 * (`GET /api/projects/<id>?results=last`, `runs/reopen.py`): each node its
 * owner's runs ran shows its newest kept result, and the load builds those
 * nodes as having run. Its last run on the server is then followed only if it
 * still goes or waits for a tab. A dashboard opens with what was saved, and
 * its viewers' runs.
 */
import React from "react";
import { render, waitFor } from "@testing-library/react";

const mockLoadProject = jest.fn();
const mockLoadTrill = jest.fn();
const mockAttachLatestRun = jest.fn();
const mockHydrateRestoredOutputs = jest.fn();

jest.mock("react-router-dom", () => ({
  useParams: () => ({ id: "11111111-2222-3333-4444-555555555555" }),
  useNavigate: () => jest.fn(),
}));
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    loadProject: mockLoadProject,
    loadSharedProject: jest.fn(),
    setOutputs: jest.fn(),
    hydrateRestoredOutputs: mockHydrateRestoredOutputs,
    loadParsedTrill: jest.fn(),
    projectId: null,
    attachLatestRun: mockAttachLatestRun,
    markDirty: jest.fn(),
    setWorkflowName: jest.fn(),
  }),
}));
jest.mock("../../hook/useCode", () => ({
  useCode: () => ({ loadTrill: mockLoadTrill }),
}));
jest.mock("../../providers/packages/useEnsureWorkflowDeps", () => ({
  useEnsureWorkflowDeps: () => jest.fn(),
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
  beginProjectLoad: jest.fn(),
  settleProjectLoad: jest.fn(),
  setCurrentProject: jest.fn(),
  setUnsavedDataflow: jest.fn(),
  setCurrentProjectPackages: jest.fn(),
}));
jest.mock("../../services/packages", () => ({
  packagesApi: { getDefaults: jest.fn().mockResolvedValue({ packages: [] }) },
}));

import { ProjectLoader } from "../../components/ProjectLoader";

const ROUTE_ID = "11111111-2222-3333-4444-555555555555";
const SPEC = { dataflow: { nodes: [{ id: "load" }, { id: "count" }], edges: [{ source: "load", target: "count" }] } };
// "load" shows its saved output, "count" a result its last play kept.
const OUTPUTS = [
  { node_id: "load", filename: "1700000000000_deadbeef", data_type: "dataframe" },
  { node_id: "count", filename: "1700000000001_feedf00d", data_type: "int" },
];

const renderLoader = (presentation = false) =>
  render(<ProjectLoader presentation={presentation}><span /></ProjectLoader>);

beforeEach(() => {
  jest.clearAllMocks();
  mockLoadTrill.mockReturnValue({ nodes: SPEC.dataflow.nodes, edges: SPEC.dataflow.edges });
  mockLoadProject.mockResolvedValue({ spec: SPEC, outputs: OUTPUTS });
});

describe("what a dataflow opens with", () => {
  it("on a canvas: the results it was left with, each node built as having run", async () => {
    renderLoader();

    await waitFor(() => expect(mockAttachLatestRun).toHaveBeenCalled());
    expect(mockLoadProject).toHaveBeenCalledWith(ROUTE_ID, { lastResults: true });
    expect(mockLoadTrill).toHaveBeenCalledWith(SPEC, undefined, undefined, {
      load: "1700000000000_deadbeef",
      count: "1700000000001_feedf00d",
    });
    expect(mockHydrateRestoredOutputs).toHaveBeenCalledWith(
      [
        { nodeId: "load", output: { path: "1700000000000_deadbeef", dataType: "dataframe" } },
        { nodeId: "count", output: { path: "1700000000001_feedf00d", dataType: "int" } },
      ],
      SPEC.dataflow.edges,
    );
    // Its last run on the server is followed only if it goes on.
    expect(mockAttachLatestRun).toHaveBeenCalledWith(ROUTE_ID);
  });

  it("on a dashboard: what was saved, and no run of the canvas's", async () => {
    renderLoader(true);

    await waitFor(() => expect(mockLoadTrill).toHaveBeenCalled());
    expect(mockLoadProject).toHaveBeenCalledWith(ROUTE_ID, { lastResults: false });
    expect(mockAttachLatestRun).not.toHaveBeenCalled();
  });
});
