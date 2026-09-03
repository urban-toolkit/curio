/**
 * SECURITY: auto-install of a dataflow's declared packages is owner-only.
 *
 * `ProjectLoader` loads a project two ways: the owner-scoped endpoint, and - on
 * a 404 - the share-link endpoint for visitors. Only the first is `trusted`, and
 * only `trusted` reaches `ensureWorkflowDeps`. The hook's own doc comment spells
 * out why: the declared package names come from a spec the loader cannot vet,
 * and installing pulls a package into the visitor's store server-side. Opening
 * someone's share link must never install anything.
 *
 * That rule lived in a comment and a single `if` with no test. This is the test.
 */
import React from "react";
import { render, waitFor } from "@testing-library/react";

const mockEnsureWorkflowDeps = jest.fn();
const mockLoadProject = jest.fn();
const mockLoadSharedProject = jest.fn();
const mockLoadTrill = jest.fn();

let mockRouteId = "11111111-2222-3333-4444-555555555555";

jest.mock("react-router-dom", () => ({
  useParams: () => ({ id: mockRouteId }),
  useNavigate: () => jest.fn(),
}));
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    loadProject: mockLoadProject,
    loadSharedProject: mockLoadSharedProject,
    setOutputs: jest.fn(),
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
jest.mock("../../TrillGenerator", () => ({
  TrillGenerator: { reset: jest.fn() },
}));
jest.mock("../../registry/packageRegistryBootstrap", () => ({
  refreshPackageRegistry: jest.fn().mockResolvedValue(undefined),
}));
jest.mock("../../registry/projectPackagesStore", () => ({
  clearCurrentProject: jest.fn(),
  setCurrentProject: jest.fn(),
  // An unsaved dataflow now gets a real scope seeded from the account defaults
  // rather than "no project, show everything" (#204).
  setUnsavedDataflow: jest.fn(),
  setCurrentProjectPackages: jest.fn(),
}));

import { ProjectLoader } from "../../components/ProjectLoader";

const SPEC_WITH_DEPS = {
  dataflow: { nodes: [], edges: [], packages: ["ai.urbanlab.uhvi@1"] },
};

const notFound = () => Object.assign(new Error("not found"), { status: 404 });

const renderLoader = () =>
  render(
    <ProjectLoader>
      <div>child</div>
    </ProjectLoader>,
  );

beforeEach(() => {
  jest.clearAllMocks();
  // A fresh id each test: ProjectLoader dedupes by id in a ref, and the effect
  // keys on [id], so reusing one across tests would skip the load entirely.
  mockRouteId = `11111111-2222-3333-4444-${String(Date.now()).slice(-12)}`;
});

it("auto-installs declared deps for the owner's own project", async () => {
  mockLoadProject.mockResolvedValue({ spec: SPEC_WITH_DEPS, outputs: [] });
  renderLoader();
  await waitFor(() => expect(mockLoadTrill).toHaveBeenCalled());
  expect(mockEnsureWorkflowDeps).toHaveBeenCalledWith(SPEC_WITH_DEPS);
});

it("renders a shared project but never installs its declared deps", async () => {
  mockLoadProject.mockRejectedValue(notFound());
  mockLoadSharedProject.mockResolvedValue({ spec: SPEC_WITH_DEPS, outputs: [] });
  renderLoader();
  // The spec IS applied - a visitor still sees the dataflow…
  await waitFor(() => expect(mockLoadTrill).toHaveBeenCalledWith(SPEC_WITH_DEPS));
  // …but nothing is installed on their behalf.
  expect(mockEnsureWorkflowDeps).not.toHaveBeenCalled();
});

it("does not fall back to the share endpoint on a non-404 failure", async () => {
  mockLoadProject.mockRejectedValue(Object.assign(new Error("boom"), { status: 500 }));
  const spy = jest.spyOn(console, "error").mockImplementation(() => {});
  renderLoader();
  await waitFor(() => expect(mockLoadProject).toHaveBeenCalled());
  expect(mockLoadSharedProject).not.toHaveBeenCalled();
  expect(mockEnsureWorkflowDeps).not.toHaveBeenCalled();
  spy.mockRestore();
});

it("installs nothing for a brand-new dataflow", async () => {
  mockRouteId = "new";
  renderLoader();
  await waitFor(() => expect(mockEnsureWorkflowDeps).not.toHaveBeenCalled());
  expect(mockLoadProject).not.toHaveBeenCalled();
});

it("rejects a spec with no loadable dataflow instead of installing from it", async () => {
  mockLoadProject.mockResolvedValue({ spec: { dataflow: null }, outputs: [] });
  const spy = jest.spyOn(console, "error").mockImplementation(() => {});
  renderLoader();
  await waitFor(() => expect(mockLoadProject).toHaveBeenCalled());
  expect(mockLoadTrill).not.toHaveBeenCalled();
  expect(mockEnsureWorkflowDeps).not.toHaveBeenCalled();
  spy.mockRestore();
});
