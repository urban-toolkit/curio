/**
 * A project that will not open says so (#350).
 *
 * #251 gave the File > Load dataflow picker toasts on every failure path. The
 * /dataflow/:id route - normal project open, deep link, share link - goes
 * through ProjectLoader instead, which only ever called console.error. The user
 * saw an empty canvas at a project URL, which is indistinguishable from an empty
 * project, and the only trace was in the browser console.
 *
 * Note the malformed-spec case: applyResult already threw a sentence written
 * for a user ("Project spec is missing a valid dataflow payload...") and it
 * reached nothing but the console. That message is the cheapest part of the fix.
 */
import React from "react";
import { render, waitFor } from "@testing-library/react";

const mockShowToast = jest.fn();
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
    hydrateRestoredOutputs: jest.fn(),
    loadParsedTrill: jest.fn(),
    projectId: null,
  }),
}));
jest.mock("../../hook/useCode", () => ({
  useCode: () => ({ loadTrill: mockLoadTrill }),
}));
jest.mock("../../hook/useEnsureWorkflowDeps", () => ({
  useEnsureWorkflowDeps: () => jest.fn(),
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
  setUnsavedDataflow: jest.fn(),
  setCurrentProjectPackages: jest.fn(),
}));
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));

import { ProjectLoader, PROJECT_LOAD_FAILED_MESSAGE } from "../../components/ProjectLoader";

/** Parses as JSON, but `dataflow.nodes`/`edges` are not arrays. */
const MALFORMED_SPEC = { spec: { dataflow: { nodes: "not-an-array" } } };

function notFound() {
  return Object.assign(new Error("not found"), { status: 404 });
}

let consoleError: jest.SpyInstance;

beforeEach(() => {
  jest.clearAllMocks();
  // The loader dedupes by id in a ref, so each test needs its own route.
  mockRouteId = `1111111${Math.floor(Math.random() * 9)}-2222-3333-4444-555555555555`;
  // The fix logs AND toasts; the log is expected, so keep it out of the output.
  consoleError = jest.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  consoleError.mockRestore();
});

function renderLoader() {
  return render(
    <ProjectLoader>
      <div>canvas</div>
    </ProjectLoader>,
  );
}

describe("ProjectLoader reports what the console used to keep to itself", () => {
  test("toasts when a stored spec has no loadable dataflow", async () => {
    // The reported case: valid JSON, wrong shape, canvas silently unchanged.
    mockLoadProject.mockResolvedValue(MALFORMED_SPEC);

    renderLoader();

    await waitFor(() => expect(mockShowToast).toHaveBeenCalled());
    const [message, variant] = mockShowToast.mock.calls[0];
    // applyResult's own sentence survives to the user, rather than being
    // replaced by something vaguer.
    expect(message).toContain("missing a valid dataflow payload");
    expect(variant).toBe("error");
  });

  test("toasts when the project cannot be fetched at all", async () => {
    mockLoadProject.mockRejectedValue(new Error("network down"));

    renderLoader();

    await waitFor(() => expect(mockShowToast).toHaveBeenCalled());
    expect(mockShowToast.mock.calls[0][0]).toContain("network down");
  });

  test("toasts when a 404 falls through to the share endpoint and that fails too", async () => {
    // How a share link that was revoked (or never shared) behaves.
    mockLoadProject.mockRejectedValue(notFound());
    mockLoadSharedProject.mockRejectedValue(notFound());

    renderLoader();

    await waitFor(() => expect(mockShowToast).toHaveBeenCalled());
    expect(mockShowToast).toHaveBeenCalledWith(PROJECT_LOAD_FAILED_MESSAGE, "error");
  });

  test("a shared spec that is malformed says so, not 'may have been deleted'", async () => {
    // The endpoint answered; the payload is the problem. Telling the visitor
    // the link may be unshared would send them to the wrong person.
    mockLoadProject.mockRejectedValue(notFound());
    mockLoadSharedProject.mockResolvedValue(MALFORMED_SPEC);

    renderLoader();

    await waitFor(() => expect(mockShowToast).toHaveBeenCalled());
    expect(mockShowToast.mock.calls[0][0]).toContain("missing a valid dataflow payload");
  });

  test("says nothing when the project loads", async () => {
    // Guards the tests above: a toast on every load would satisfy them while
    // making the app unusable.
    mockLoadProject.mockResolvedValue({ spec: { dataflow: { nodes: [], edges: [] } } });

    renderLoader();

    await waitFor(() => expect(mockLoadTrill).toHaveBeenCalled());
    expect(mockShowToast).not.toHaveBeenCalled();
  });

  test("leaves no console.error as the only report of a failure", async () => {
    // The UpMenu rule, asserted rather than trusted: log AND toast.
    mockLoadProject.mockRejectedValue(new Error("network down"));

    renderLoader();

    await waitFor(() => expect(mockShowToast).toHaveBeenCalled());
    expect(consoleError).toHaveBeenCalled();
    expect(mockShowToast.mock.calls.length).toBeGreaterThanOrEqual(
      consoleError.mock.calls.length,
    );
  });
});
