/**
 * A scenario dropped on a dataflow a hosted guest never saved (`isHostedGuest`:
 * a guest on a Curio started with --deploy). The drop copies into the open
 * dataflow, so it needs a saved one, and such a guest cannot save: it is told
 * to sign in, not to "save this dataflow first", which it cannot do. On a
 * dataflow it has, its drop goes on; the local shared guest and a signed-in
 * account keep today's behavior.
 */
import React from "react";
import { act, renderHook } from "@testing-library/react";

const mockShowToast = jest.fn();
const mockFlow = {
  scenarios: [],
  nodes: [],
  setScenarios: jest.fn(),
  setOutputs: jest.fn(),
  hydrateRestoredOutputs: jest.fn(),
  markDirty: jest.fn(),
  ensureProjectId: jest.fn(),
  workflowNameRef: { current: "Elsewhere" },
  workflowGoal: "",
};
const mockReactFlow = { getNodes: () => [], getEdges: () => [] };
const mockLoadTrill = jest.fn(() => ({ nodes: [], edges: [] }));

jest.mock("reactflow", () => ({ useReactFlow: () => mockReactFlow }));
jest.mock("../../providers/FlowProvider", () => ({ useFlowContext: () => mockFlow }));
jest.mock("../../providers/ToastProvider", () => ({ useToastContext: () => ({ showToast: mockShowToast }) }));
jest.mock("../../hook/useCode", () => ({ useCode: () => ({ loadTrill: mockLoadTrill }) }));
jest.mock("../../registry/packageRegistryBootstrap", () => ({ refreshPackageRegistry: jest.fn() }));
jest.mock("../../registry/projectPackagesStore", () => ({ setCurrentProjectPackages: jest.fn() }));
jest.mock("../../services/datasetCatalog", () => ({ buildDatasetLoaderNodeOptions: jest.fn() }));
jest.mock("../../TrillGenerator", () => ({
  TrillGenerator: { generateTrill: () => ({ dataflow: { nodes: [], edges: [] } }) },
}));
jest.mock("../../utils/scenarios/scenarioParts", () => ({ liveScenarios: (saved: unknown) => saved }));
jest.mock("../../utils/scenarios/scenarioDrop", () => ({
  planScenarioDrop: () => ({
    outputs: [],
    loaders: [],
    scenarios: [{ id: "dropped", name: "Existing", color: "#2a9d8f", nodes: [] }],
    set: { id: "set-new", name: "Park shade (copy)" },
  }),
  dropGraph: () => ({ nodes: [], edges: [] }),
  loaderNodes: () => [],
}));
jest.mock("../../services/scenarioCatalog", () => ({
  scenarioCatalogApi: { getCopyPlan: jest.fn(), copyInto: jest.fn() },
}));
jest.mock("../../services/runs/runsApi", () => {
  const actual = jest.requireActual("../../services/runs/runsApi");
  return { ...actual, runsApi: { start: jest.fn(), follow: jest.fn(), get: jest.fn() } };
});

import { useScenarioDrop } from "../../components/scenarios/useScenarioDrop";
import { scenarioCatalogApi } from "../../services/scenarioCatalog";
import { UserContext } from "../../providers/userContext";
import type { UserData } from "../../utils/authApi";

const catalog = scenarioCatalogApi as unknown as { getCopyPlan: jest.Mock; copyInto: jest.Mock };

type UserContextValue = React.ContextType<typeof UserContext>;

function userContext(user: UserData, enableUserAuth: boolean): UserContextValue {
  return {
    user,
    loading: false,
    isAuthenticated: true,
    enableUserAuth,
    skipProjectPage: false,
    allowGuest: true,
    sharedGuestUsername: "guest_shared",
    isSharedGuest: user.is_guest && user.username === "guest_shared",
    signup: async () => null,
    signin: async () => null,
    signinGuest: async () => null,
    signout: async () => {},
    updateProfile: async () => {},
    updateTokens: async () => {},
    saveUserType: async () => {},
    logout: () => {},
  };
}

const GUEST: UserData = {
  id: 1,
  username: "guest_shared",
  name: "Guest",
  email: null,
  profile_image: null,
  type: null,
  is_guest: true,
};
const SIGNED_IN: UserData = { ...GUEST, id: 2, username: "ada", name: "Ada", is_guest: false };

const HOSTED_GUEST = userContext(GUEST, true);
const LOCAL_GUEST = userContext(GUEST, false);
const SIGNED_IN_USER = userContext(SIGNED_IN, true);

const PAYLOAD = { projectId: "src", setId: "park", setName: "Park shade", scenarioIds: ["existing"], names: ["Existing"] };
const SAVE_FIRST = "Save this dataflow first, then drag the scenario again.";

/** What the server says the drop copies: nothing left to run, nothing refused. */
const READY = {
  scenario: { id: "existing", name: "Existing", color: "#2a9d8f", description: "" },
  scenarios: [{ id: "existing", name: "Existing", color: "#2a9d8f", description: "", levers: [], context: [], outcomes: [] }],
  set: { id: "park", name: "Park shade" },
  shared: [],
  project: { id: "src", name: "Chicago Loop shadow with towers removed or edited" },
  levers: [],
  context: [],
  outcomes: [],
  dataflow: { nodes: [], edges: [] },
  packages: [],
  problems: [],
  toRun: [],
};

async function dropAs(value: UserContextValue) {
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <UserContext.Provider value={value}>{children}</UserContext.Provider>
  );
  const { result } = renderHook(() => useScenarioDrop(), { wrapper });
  let dropped: unknown;
  await act(async () => {
    dropped = await result.current(PAYLOAD, { x: 10, y: 20 });
  });
  return dropped;
}

function toastsShown(): string[] {
  return mockShowToast.mock.calls.map((call: unknown[]) => String(call[0]));
}

beforeEach(() => {
  jest.clearAllMocks();
  catalog.getCopyPlan.mockResolvedValue(READY);
  catalog.copyInto.mockResolvedValue({ packages: [], added: [], datasets: {}, outputs: [] });
});

describe("a hosted guest", () => {
  it("is told to sign in when it drops a scenario on a dataflow it never saved", async () => {
    // Never saved: no id comes back, since a guest's save is skipped.
    mockFlow.ensureProjectId.mockResolvedValue(null);

    const dropped = await dropAs(HOSTED_GUEST);

    expect(dropped).toBeNull();
    expect(mockShowToast).toHaveBeenCalledWith("Sign in to add scenarios.", "warning");
    expect(toastsShown()).not.toContain(SAVE_FIRST);
    expect(catalog.getCopyPlan).not.toHaveBeenCalled();
  });

  it("drops a scenario on a dataflow it has, as before", async () => {
    mockFlow.ensureProjectId.mockResolvedValue("target");

    await dropAs(HOSTED_GUEST);

    expect(catalog.getCopyPlan).toHaveBeenCalledWith(PAYLOAD, "target");
    expect(toastsShown().filter((message) => message.startsWith("Sign in"))).toEqual([]);
  });
});

describe.each([
  ["the local shared guest", LOCAL_GUEST],
  ["a signed-in account", SIGNED_IN_USER],
])("%s", (_who, value) => {
  it("is asked to save first when the dataflow could not be saved", async () => {
    mockFlow.ensureProjectId.mockResolvedValue(null);

    const dropped = await dropAs(value);

    expect(dropped).toBeNull();
    expect(mockShowToast).toHaveBeenCalledWith(SAVE_FIRST, "warning");
    expect(toastsShown().filter((message) => message.startsWith("Sign in"))).toEqual([]);
    expect(catalog.getCopyPlan).not.toHaveBeenCalled();
  });

  it("drops a scenario on a dataflow never saved, once the save has created it", async () => {
    mockFlow.ensureProjectId.mockResolvedValue("target");

    await dropAs(value);

    expect(catalog.getCopyPlan).toHaveBeenCalledWith(PAYLOAD, "target");
  });
});
