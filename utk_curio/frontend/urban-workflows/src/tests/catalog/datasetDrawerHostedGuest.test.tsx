/**
 * The Data Catalog's Add on a dataflow a hosted guest never saved
 * (`isHostedGuest`: a guest on a Curio started with --deploy, where every
 * visitor shares the one guest account). Adding a dataset needs a saved
 * dataflow, and such a guest cannot save one, so the Add tells it to sign in
 * rather than doing nothing. On a dataflow it has, its Add goes on as before;
 * the local shared guest and a signed-in account keep today's behavior.
 */
import React from "react";
import { renderHook, act } from "@testing-library/react";

const mockShowToast = jest.fn();
const mockEnsureProjectId = jest.fn();
const mockCatalogReload = jest.fn(async () => {});
const mockCatalogItems: unknown[] = [];
let mockProjectId: string | null = null;

jest.mock("../../services/datasetCatalog", () => {
  const actual = jest.requireActual("../../services/datasetCatalog");
  return {
    ...actual,
    useDatasetCatalog: () => ({
      items: mockCatalogItems,
      facets: { origin: {} },
      loading: false,
      refreshing: false,
      error: null,
      reload: mockCatalogReload,
      install: jest.fn(),
      uninstall: jest.fn(),
      importDataset: jest.fn(),
    }),
  };
});
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    projectId: mockProjectId,
    ensureProjectId: mockEnsureProjectId,
    setDataflowDatasets: jest.fn(),
    outputs: [],
    nodes: [],
    defaultSaveOutputDataset: false,
    pendingInstalls: [],
    beginPendingInstall: jest.fn(),
    endPendingInstall: jest.fn(),
  }),
}));
jest.mock("../../utils/saveOutputDataset", () => ({
  buildSaveableLiveOutputs: jest.fn(() => []),
}));

import { useDatasetCatalogDrawer } from "../../components/datasets/catalog/useDatasetCatalogDrawer";
import { datasetCatalogApi } from "../../services/datasetCatalog";
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

const DATASET = {
  id: "imported.xaaa",
  title: "Tracts",
  origin: "imported" as const,
  format: "csv" as const,
  consumerNodeIds: [],
  tags: [],
  updatedAt: "2026-01-01T00:00:00Z",
};

const INSTALLED = {
  ...DATASET,
  dirName: "imported.xaaa@1",
  uri: "curio://datasets/imported.xaaa@1",
  installed: true,
};

function renderDrawerAs(value: UserContextValue) {
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <UserContext.Provider value={value}>{children}</UserContext.Provider>
  );
  return renderHook(() => useDatasetCatalogDrawer(true), { wrapper });
}

type DrawerResult = { current: ReturnType<typeof useDatasetCatalogDrawer> };

/** Add, then accept the confirmation the Data Catalog asks for first (#196). */
async function add(result: DrawerResult) {
  await act(async () => {
    await result.current.onInstall(DATASET as never);
  });
  const pending = result.current.confirmAction;
  expect(pending).not.toBeNull();
  await act(async () => {
    await pending!.run();
  });
}

function signInToasts(): string[] {
  return mockShowToast.mock.calls
    .map((call: unknown[]) => String(call[0]))
    .filter((message) => message.startsWith("Sign in"));
}

let installSpy: jest.SpyInstance;

beforeEach(() => {
  jest.clearAllMocks();
  installSpy = jest.spyOn(datasetCatalogApi, "installToDataflow").mockResolvedValue(INSTALLED as never);
});

afterEach(() => {
  installSpy.mockRestore();
});

describe("a hosted guest", () => {
  it("is told to sign in when it adds a dataset to a dataflow it never saved", async () => {
    // Never saved: no id, and none comes back, since a guest's save is skipped.
    mockProjectId = null;
    mockEnsureProjectId.mockResolvedValue(null);
    const { result } = renderDrawerAs(HOSTED_GUEST);

    await add(result);

    expect(mockShowToast).toHaveBeenCalledWith("Sign in to add datasets.", "warning");
    expect(installSpy).not.toHaveBeenCalled();
  });

  it("adds a dataset to a dataflow it has, as before", async () => {
    mockProjectId = "flow-1";
    mockEnsureProjectId.mockResolvedValue("flow-1");
    const { result } = renderDrawerAs(HOSTED_GUEST);

    await add(result);

    expect(installSpy).toHaveBeenCalledTimes(1);
    expect(installSpy.mock.calls[0].slice(0, 2)).toEqual(["flow-1", DATASET.id]);
    expect(signInToasts()).toEqual([]);
  });
});

describe.each([
  ["the local shared guest", LOCAL_GUEST],
  ["a signed-in account", SIGNED_IN_USER],
])("%s", (_who, value) => {
  it("adds a dataset to a dataflow never saved, once the save has created it", async () => {
    mockProjectId = null;
    mockEnsureProjectId.mockResolvedValue("flow-new");
    const { result } = renderDrawerAs(value);

    await add(result);

    expect(installSpy).toHaveBeenCalledTimes(1);
    expect(installSpy.mock.calls[0].slice(0, 2)).toEqual(["flow-new", DATASET.id]);
    expect(signInToasts()).toEqual([]);
  });

  it("is not told to sign in when that save fails", async () => {
    // ensureProjectId says why its save failed; the Add adds nothing to that.
    mockProjectId = null;
    mockEnsureProjectId.mockResolvedValue(null);
    const { result } = renderDrawerAs(value);

    await add(result);

    expect(installSpy).not.toHaveBeenCalled();
    expect(signInToasts()).toEqual([]);
  });
});
