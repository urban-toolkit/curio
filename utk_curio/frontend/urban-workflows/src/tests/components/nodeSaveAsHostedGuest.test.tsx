import React from "react";
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import "@testing-library/jest-dom";

/**
 * Save as package node on a dataflow a hosted guest never saved
 * (`isHostedGuest`: a guest on a Curio started with --deploy). The package
 * goes into the dataflow's lockfile, which needs a saved dataflow, and such a
 * guest cannot save one: it is told to sign in before anything is made. On a
 * dataflow it has, the save goes on as before; the local shared guest and a
 * signed-in account keep today's behavior.
 *
 * The harness is nodeSaveAsProjectScope.test.tsx's.
 */
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
  useFlowContext: () => ({ ensureProjectId: mockEnsureProjectId }),
}));
jest.mock("../../registry", () => ({
  getPaletteNodeTypes: () => [],
  subscribeToRegistry: () => () => {},
}));
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
jest.mock("../../services/packages/packagesApi", () => ({
  packagesApi: {
    factoryInstall: (...args: unknown[]) => mockFactoryInstall(...args),
    installToProject: (...args: unknown[]) => mockInstallToProject(...args),
  },
}));
jest.mock("../../registry/packageRegistryBootstrap", () => ({
  refreshPackageRegistry: (...args: unknown[]) => mockRefreshRegistry(...args),
}));
jest.mock("../../services/packages/packagesBlobTransport", () => ({
  ...jest.requireActual("../../services/packages/packagesBlobTransport"),
  triggerBlobDownload: jest.fn(),
}));

import { NodeSaveAsModal } from "../../components/packages/editing/NodeSaveAsModal";
import { UserContext } from "../../providers/userContext";
import type { UserData } from "../../utils/authApi";

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

const NODE_ID = "n1";

beforeEach(() => {
  jest.clearAllMocks();
  mockStore.nodeInternals = new Map([
    [NODE_ID, {
      id: NODE_ID,
      type: "curio.builtin/computation-analysis",
      data: { nodeType: "curio.builtin/computation-analysis", code: "return [1]" },
    }],
  ]);
  mockFactoryInstall.mockResolvedValue({
    package: { dirName: "my.pkg@1", templates: [] },
  });
  mockInstallToProject.mockResolvedValue({ packages: ["my.pkg@1"] });
});

async function saveAs(value: UserContextValue) {
  render(
    <UserContext.Provider value={value}>
      <NodeSaveAsModal show nodeId={NODE_ID} onClose={jest.fn()} />
    </UserContext.Provider>,
  );
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
  });
}

function signInToasts(): string[] {
  return mockShowToast.mock.calls
    .map((call: unknown[]) => String(call[0]))
    .filter((message) => message.startsWith("Sign in"));
}

describe("a hosted guest", () => {
  test("is told to sign in when it saves a node as a package on a dataflow it never saved", async () => {
    // Never saved: no id comes back, since a guest's save is skipped.
    mockEnsureProjectId.mockResolvedValue(null);

    await saveAs(HOSTED_GUEST);

    await waitFor(() =>
      expect(mockShowToast).toHaveBeenCalledWith("Sign in to save nodes as packages.", "warning"),
    );
    expect(mockFactoryInstall).not.toHaveBeenCalled();
    expect(mockInstallToProject).not.toHaveBeenCalled();
  });

  test("saves a node as a package into a dataflow it has, as before", async () => {
    mockEnsureProjectId.mockResolvedValue("p1");

    await saveAs(HOSTED_GUEST);

    await waitFor(() => expect(mockInstallToProject).toHaveBeenCalledWith("p1", "my.pkg@1"));
    expect(signInToasts()).toEqual([]);
  });
});

describe.each([
  ["the local shared guest", LOCAL_GUEST],
  ["a signed-in account", SIGNED_IN_USER],
])("%s, on a dataflow never saved", (_who, value) => {
  test("saves the node as a package into the dataflow the save created", async () => {
    mockEnsureProjectId.mockResolvedValue("created-project-id");

    await saveAs(value);

    await waitFor(() => expect(mockInstallToProject).toHaveBeenCalledWith("created-project-id", "my.pkg@1"));
    expect(signInToasts()).toEqual([]);
  });

  test("still makes the package when that save fails, and is not told to sign in", async () => {
    mockEnsureProjectId.mockResolvedValue(null);

    await saveAs(value);

    await waitFor(() => expect(mockFactoryInstall).toHaveBeenCalled());
    expect(mockInstallToProject).not.toHaveBeenCalled();
    expect(signInToasts()).toEqual([]);
  });
});
