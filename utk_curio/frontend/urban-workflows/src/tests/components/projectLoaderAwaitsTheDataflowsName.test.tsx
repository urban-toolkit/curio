/**
 * ProjectLoader starts a hosted guest's load of a dataflow by making the
 * room's socket wait for the id the page names the dataflow by
 * (`awaitDataflowName`, `utils/requestHeaders.ts`), before it pins the
 * dataflow, which the room follows: on an example that is the guest's own
 * copy's id, which the load's answer gives (`useWorkflowOperations.loadProject`),
 * and which the server keeps on the backend process that id names. So no
 * guest's socket opens naming the example. However the load ends, answered,
 * failed, from the link, a served dashboard's or left, the socket waits no
 * more. An account's load names no copy: its socket opens at once, apart
 * from the load.
 *
 * A dashboard served with its data loads nothing: the page server built it
 * for the visitor's sign-in (`cli/static_server.py`), and a hosted guest's
 * names the guest's own copy (`copy_id`), which the page names from then on,
 * before it is loaded and starts a viewer's run, as a canvas names the copy
 * its load answers with.
 *
 * The helper is loaded in each test, so a checkout without it fails each test
 * on its own.
 */
import React from "react";
import { render, waitFor } from "@testing-library/react";

const mockLoadProject = jest.fn();
const mockLoadSharedProject = jest.fn();
const mockLoadTrill = jest.fn();
/** Whether the dataflow's name was known each time ProjectLoader pinned it. */
const mockKnownWhenPinned: boolean[] = [];

let mockRouteId = "new";
/** Whether the signed-in user is a hosted guest (`useHostedGuest`). */
let mockHostedGuest = true;

jest.mock("../../components/apiSettings/useHostedGuest", () => ({
  useHostedGuest: () => mockHostedGuest,
}));
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
    attachLatestRun: jest.fn(),
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
  setCurrentProject: jest.fn((id: string) => {
    mockKnownWhenPinned.push(require("../../utils/requestHeaders").dataflowNameKnown(id));
  }),
  setUnsavedDataflow: jest.fn(),
  setCurrentProjectPackages: jest.fn(),
}));
jest.mock("../../services/packages", () => ({
  packagesApi: { getDefaults: jest.fn().mockResolvedValue({ packages: [] }) },
}));

import { ProjectLoader, useProjectLoadState } from "../../components/ProjectLoader";
import { resetEmbeddedDashboardForTests } from "../../standalone/dashboardPayload";

const HEADER = "X-Curio-Dataflow";
const ROUTE_ID = "11111111-2222-4333-8444-555555555555";
/** A hosted guest's own copy of the dataflow of ROUTE_ID. */
const COPY = "99999999-8888-5777-a666-555555555555";
const SPEC = { dataflow: { nodes: [{ id: "py" }], edges: [] } };

/** The helper, loaded when a test asks for it. */
const names = (): any => require("../../utils/requestHeaders");

const notFound = () => Object.assign(new Error("not found"), { status: 404 });

const renderLoader = (presentation = false) =>
  render(<ProjectLoader presentation={presentation}><span /></ProjectLoader>);

beforeEach(() => {
  jest.clearAllMocks();
  mockKnownWhenPinned.length = 0;
  mockRouteId = ROUTE_ID;
  mockHostedGuest = true;
  mockLoadTrill.mockReturnValue({ nodes: SPEC.dataflow.nodes, edges: [] });
});

afterEach(() => names().resetDataflowNames?.());

test("a hosted guest's socket waits from before the dataflow is pinned until its load ends", async () => {
  let answer!: (value: unknown) => void;
  mockLoadProject.mockImplementation(() => new Promise((resolve) => {
    answer = resolve;
  }));

  renderLoader();

  expect(mockKnownWhenPinned).toEqual([false]);
  await waitFor(() => expect(mockLoadProject).toHaveBeenCalled());
  expect(names().dataflowNameKnown(ROUTE_ID)).toBe(false);

  answer({ spec: SPEC, outputs: [] });

  await waitFor(() => expect(names().dataflowNameKnown(ROUTE_ID)).toBe(true));
  expect(mockLoadTrill).toHaveBeenCalled();
});

test.each([
  ["from the link", () => {
    mockLoadProject.mockRejectedValue(notFound());
    mockLoadSharedProject.mockResolvedValue({ spec: SPEC, outputs: [] });
  }],
  ["refused", () => {
    mockLoadProject.mockRejectedValue(Object.assign(new Error("boom"), { status: 500 }));
  }],
  ["not found anywhere", () => {
    mockLoadProject.mockRejectedValue(notFound());
    mockLoadSharedProject.mockRejectedValue(notFound());
  }],
])("a load %s lets the socket go on", async (_how, set) => {
  set();

  renderLoader();

  expect(mockKnownWhenPinned).toEqual([false]);
  await waitFor(() => expect(names().dataflowNameKnown(ROUTE_ID)).toBe(true));
});

test("a load the page leaves lets the socket go on", async () => {
  mockLoadProject.mockImplementation(() => new Promise(() => {}));
  const { unmount } = renderLoader();
  await waitFor(() => expect(mockLoadProject).toHaveBeenCalled());
  expect(names().dataflowNameKnown(ROUTE_ID)).toBe(false);

  unmount();

  expect(names().dataflowNameKnown(ROUTE_ID)).toBe(true);
});

test("an account's socket waits for nothing: it opens at once, apart from the load", async () => {
  mockHostedGuest = false;
  mockLoadProject.mockImplementation(() => new Promise(() => {}));

  renderLoader();

  expect(mockKnownWhenPinned).toEqual([true]);
  await waitFor(() => expect(mockLoadProject).toHaveBeenCalled());
  expect(names().dataflowNameKnown(ROUTE_ID)).toBe(true);
});

test("a new dataflow, which no load names, waits for nothing", () => {
  mockRouteId = "new";

  renderLoader();

  expect(mockKnownWhenPinned).toEqual([]);
  expect(names().dataflowNameKnown(ROUTE_ID)).toBe(true);
});

describe("a dashboard served with its data", () => {
  const PAYLOAD_ID = "curio-dashboard-payload";

  /** The page as the page server served it, with *payload* inside. */
  const servedWith = (payload: object) => {
    const element = document.createElement("script");
    element.id = PAYLOAD_ID;
    element.type = "application/json";
    element.textContent = JSON.stringify(payload);
    document.body.appendChild(element);
    resetEmbeddedDashboardForTests();
  };

  afterEach(() => {
    document.getElementById(PAYLOAD_ID)?.remove();
    resetEmbeddedDashboardForTests();
    window.history.replaceState(null, "", "/");
  });

  test("names the copy its page was built for before the page is loaded", async () => {
    // A hosted guest's page names no account (UserProvider's viewer), and the
    // browser holds no session the page could ask with.
    mockHostedGuest = false;
    window.history.replaceState(null, "", `/dashboard/${ROUTE_ID}`);
    servedWith({
      meta: { projectId: ROUTE_ID, name: "Example" },
      spec: SPEC,
      outputs: {},
      outputRefs: [],
      copy_id: COPY,
    });
    /** What a request names each time the page reads as loaded. */
    const named: string[] = [];
    const Probe: React.FC = () => {
      if (useProjectLoadState() === "loaded") named.push(names().requestHeaders("tok")[HEADER]);
      return null;
    };

    render(<ProjectLoader presentation><Probe /></ProjectLoader>);

    await waitFor(() => expect(named.length).toBeGreaterThan(0));
    expect(named[0]).toBe(COPY);
    expect(names().requestHeaders("tok", {}, ROUTE_ID)[HEADER]).toBe(COPY);
    expect(mockLoadProject).not.toHaveBeenCalled();
    expect(mockLoadSharedProject).not.toHaveBeenCalled();
  });
});
