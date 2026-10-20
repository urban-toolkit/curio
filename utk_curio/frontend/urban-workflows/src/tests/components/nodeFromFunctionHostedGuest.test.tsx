import React from "react";
import { render, screen, waitFor, fireEvent, within, act } from "@testing-library/react";
import "@testing-library/jest-dom";

/**
 * New node from a Python function on a dataflow a hosted guest never saved
 * (`isHostedGuest`: a guest on a Curio started with --deploy). The node's
 * package goes into the dataflow's lockfile, which needs a saved dataflow, and
 * such a guest cannot save one: it is told to sign in before anything is
 * written. On a dataflow it has, the node is made as before; the local shared
 * guest and a signed-in account keep today's behavior.
 *
 * The harness is nodeFromFunctionModal.test.tsx's.
 */
const mockListFunctions = jest.fn();
const mockFunctionTemplate = jest.fn();
const mockListInstalled = jest.fn();
const mockFactoryInstall = jest.fn();
const mockInstallToProject = jest.fn();
const mockSetCurrentProjectPackages = jest.fn();
const mockRefreshRegistry = jest.fn();
const mockEnsureProjectId = jest.fn();
const mockShowToast = jest.fn();

jest.mock("../../services/packages/packagesApi", () => ({
  packagesApi: {
    listFunctions: (...args: unknown[]) => mockListFunctions(...args),
    functionTemplate: (...args: unknown[]) => mockFunctionTemplate(...args),
    listInstalled: (...args: unknown[]) => mockListInstalled(...args),
    factoryInstall: (...args: unknown[]) => mockFactoryInstall(...args),
    installToProject: (...args: unknown[]) => mockInstallToProject(...args),
  },
}));
jest.mock("../../registry/packageRegistryBootstrap", () => ({
  refreshPackageRegistry: (...args: unknown[]) => mockRefreshRegistry(...args),
}));
jest.mock("../../registry/projectPackagesStore", () => ({
  setCurrentProjectPackages: (...args: unknown[]) => mockSetCurrentProjectPackages(...args),
}));
jest.mock("../../registry", () => ({
  getPaletteNodeTypes: () => [],
  subscribeToRegistry: () => () => {},
}));
jest.mock("../../registry/nodeRegistry", () => ({
  tryGetNodeDescriptor: () => undefined,
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

import { NodeFromFunctionModal } from "../../components/packages/editing/NodeFromFunctionModal";
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

const SOURCE_DIR = "ai.test.fnsrc@1";
const SCALE_KEY = `${SOURCE_DIR}|fn_scale.ops|scale`;

/** One module with one function a node can call, read-only so the node goes into a new package. */
const FUNCTIONS = {
  packages: [{
    dirName: SOURCE_DIR,
    packageId: "ai.test.fnsrc",
    major: 1,
    name: "Function source",
    readOnly: true,
    modules: [{
      module: "fn_scale.ops",
      problem: null,
      functions: [{
        name: "scale",
        doc: "Scale a value.",
        problem: null,
        parameters: [
          { name: "value", kind: "positional-or-keyword", annotation: null, hasDefault: false, widget: null, use: "input" },
        ],
      }],
    }],
  }],
};

const WRITTEN = {
  template: {
    id: "scale", label: "Scale", category: "computation", engine: "python", editor: "code",
    behavior: "code", iconRef: "fa-brands:python", description: "Scale a value. Calls scale from fn_scale.ops.",
    hasCode: true, hasWidgets: false, hasGrammar: false,
    inputPorts: [{ types: ["VALUE"], cardinality: "1" }],
    outputPorts: [{ types: ["VALUE"], cardinality: "[1,n]" }],
    source: "sources/scale.py",
    widgets: [],
  },
  source: {
    filename: "scale.py",
    code: "from fn_scale.ops import scale\n\nreturn scale(\n    value=[!! input_0 !!],\n)\n",
  },
  package: { dirName: SOURCE_DIR, packageId: "ai.test.fnsrc", major: 1, readOnly: true },
  dependency: { [SOURCE_DIR]: "*" },
};

beforeEach(() => {
  jest.clearAllMocks();
  mockListFunctions.mockResolvedValue(FUNCTIONS);
  mockFunctionTemplate.mockResolvedValue(WRITTEN);
  mockFactoryInstall.mockImplementation(async (envelope: { manifest: { id: string; name: string } }) => ({
    package: { dirName: `${envelope.manifest.id}@1`, name: envelope.manifest.name, templates: [] },
  }));
  mockInstallToProject.mockImplementation(async (_project: string, dirName: string) => ({ packages: [dirName] }));
  mockRefreshRegistry.mockResolvedValue(undefined);
});

/** Opens the dialog as *value*, picks the function, and presses Create node. */
async function createAs(value: UserContextValue) {
  render(
    <UserContext.Provider value={value}>
      <NodeFromFunctionModal show onClose={jest.fn()} onSaved={jest.fn()} />
    </UserContext.Provider>,
  );
  const choice = await screen.findByLabelText("Function");
  await waitFor(() =>
    expect(within(choice).getByRole("option", { name: "fn_scale.ops.scale(value)" })).toBeInTheDocument(),
  );
  fireEvent.change(choice, { target: { value: SCALE_KEY } });
  const create = screen.getByRole("button", { name: "Create node" });
  expect(create).toBeEnabled();
  await act(async () => {
    fireEvent.click(create);
  });
}

function signInToasts(): string[] {
  return mockShowToast.mock.calls
    .map((call: unknown[]) => String(call[0]))
    .filter((message) => message.startsWith("Sign in"));
}

describe("a hosted guest", () => {
  test("is told to sign in when it makes a node from a function on a dataflow it never saved", async () => {
    // Never saved: no id comes back, since a guest's save is skipped.
    mockEnsureProjectId.mockResolvedValue(null);

    await createAs(HOSTED_GUEST);

    await waitFor(() =>
      expect(mockShowToast).toHaveBeenCalledWith("Sign in to make nodes from Python functions.", "warning"),
    );
    expect(mockFunctionTemplate).not.toHaveBeenCalled();
    expect(mockFactoryInstall).not.toHaveBeenCalled();
  });

  test("makes the node into a dataflow it has, as before", async () => {
    mockEnsureProjectId.mockResolvedValue("project-1");

    await createAs(HOSTED_GUEST);

    await waitFor(() => expect(mockInstallToProject).toHaveBeenCalled());
    expect(mockInstallToProject.mock.calls[0][0]).toBe("project-1");
    expect(signInToasts()).toEqual([]);
  });
});

describe.each([
  ["the local shared guest", LOCAL_GUEST],
  ["a signed-in account", SIGNED_IN_USER],
])("%s, on a dataflow never saved", (_who, value) => {
  test("makes the node into the dataflow the save created", async () => {
    mockEnsureProjectId.mockResolvedValue("project-new");

    await createAs(value);

    await waitFor(() => expect(mockInstallToProject).toHaveBeenCalled());
    expect(mockInstallToProject.mock.calls[0][0]).toBe("project-new");
    expect(signInToasts()).toEqual([]);
  });

  test("still makes the package when that save fails, and is not told to sign in", async () => {
    mockEnsureProjectId.mockResolvedValue(null);

    await createAs(value);

    await waitFor(() => expect(mockFactoryInstall).toHaveBeenCalled());
    expect(mockInstallToProject).not.toHaveBeenCalled();
    expect(signInToasts()).toEqual([]);
  });
});
