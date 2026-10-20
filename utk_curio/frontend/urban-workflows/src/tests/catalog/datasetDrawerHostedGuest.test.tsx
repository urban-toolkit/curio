/**
 * The Data Catalog's Add, Remove and Publish on a dataflow a hosted guest never
 * saved (`isHostedGuest`: a guest on a Curio started with --deploy, where every
 * visitor shares the one guest account). Each needs a saved dataflow, and such
 * a guest cannot save one, so each tells it to sign in rather than doing
 * nothing. On a dataflow it has, its actions go on as before; the local shared
 * guest and a signed-in account keep today's behavior.
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

/** Accept the confirmation the action just raised (#196, #197). */
async function confirm(result: DrawerResult) {
  const pending = result.current.confirmAction;
  expect(pending).not.toBeNull();
  await act(async () => {
    await pending!.run();
  });
}

async function add(result: DrawerResult) {
  await act(async () => {
    await result.current.onInstall(DATASET as never);
  });
  await confirm(result);
}

async function remove(result: DrawerResult) {
  await act(async () => {
    await result.current.onUninstall(DATASET as never);
  });
  await confirm(result);
}

async function publish(result: DrawerResult) {
  await act(async () => {
    await result.current.onPublish(DATASET.id);
  });
}

function signInToasts(): string[] {
  return mockShowToast.mock.calls
    .map((call: unknown[]) => String(call[0]))
    .filter((message) => message.startsWith("Sign in"));
}

let installSpy: jest.SpyInstance;
let uninstallSpy: jest.SpyInstance;
let publishSpy: jest.SpyInstance;
let usageSpy: jest.SpyInstance;

beforeEach(() => {
  jest.clearAllMocks();
  installSpy = jest.spyOn(datasetCatalogApi, "installToDataflow").mockResolvedValue(INSTALLED as never);
  uninstallSpy = jest.spyOn(datasetCatalogApi, "uninstallFromDataflow").mockResolvedValue({ id: DATASET.id } as never);
  publishSpy = jest.spyOn(datasetCatalogApi, "publishDataset").mockResolvedValue(INSTALLED as never);
  usageSpy = jest.spyOn(datasetCatalogApi, "datasetUsage").mockResolvedValue([] as never);
});

afterEach(() => {
  installSpy.mockRestore();
  uninstallSpy.mockRestore();
  publishSpy.mockRestore();
  usageSpy.mockRestore();
});

describe("a hosted guest", () => {
  describe("on a dataflow it never saved", () => {
    beforeEach(() => {
      // No id, and none comes back, since a guest's save is skipped.
      mockProjectId = null;
      mockEnsureProjectId.mockResolvedValue(null);
    });

    it("is told to sign in when it adds a dataset", async () => {
      const { result } = renderDrawerAs(HOSTED_GUEST);

      await add(result);

      expect(mockShowToast).toHaveBeenCalledWith("Sign in to add datasets.", "warning");
      expect(installSpy).not.toHaveBeenCalled();
    });

    it("is told to sign in when it removes a dataset", async () => {
      const { result } = renderDrawerAs(HOSTED_GUEST);

      await remove(result);

      expect(mockShowToast).toHaveBeenCalledWith("Sign in to remove datasets.", "warning");
      expect(uninstallSpy).not.toHaveBeenCalled();
    });

    it("is told to sign in when it publishes a dataset", async () => {
      const { result } = renderDrawerAs(HOSTED_GUEST);

      await publish(result);

      expect(mockShowToast).toHaveBeenCalledWith("Sign in to publish datasets.", "warning");
      expect(publishSpy).not.toHaveBeenCalled();
    });
  });

  describe("on a dataflow it has", () => {
    beforeEach(() => {
      mockProjectId = "flow-1";
      mockEnsureProjectId.mockResolvedValue("flow-1");
    });

    it("adds a dataset, as before", async () => {
      const { result } = renderDrawerAs(HOSTED_GUEST);

      await add(result);

      expect(installSpy).toHaveBeenCalledTimes(1);
      expect(installSpy.mock.calls[0].slice(0, 2)).toEqual(["flow-1", DATASET.id]);
      expect(signInToasts()).toEqual([]);
    });

    it("removes a dataset, as before", async () => {
      const { result } = renderDrawerAs(HOSTED_GUEST);

      await remove(result);

      expect(uninstallSpy).toHaveBeenCalledWith("flow-1", DATASET.id);
      expect(signInToasts()).toEqual([]);
    });
  });
});

describe.each([
  ["the local shared guest", LOCAL_GUEST],
  ["a signed-in account", SIGNED_IN_USER],
])("%s", (_who, value) => {
  describe("on a dataflow never saved, once the save has created it", () => {
    beforeEach(() => {
      mockProjectId = null;
      mockEnsureProjectId.mockResolvedValue("flow-new");
    });

    it("adds a dataset to it", async () => {
      const { result } = renderDrawerAs(value);

      await add(result);

      expect(installSpy).toHaveBeenCalledTimes(1);
      expect(installSpy.mock.calls[0].slice(0, 2)).toEqual(["flow-new", DATASET.id]);
      expect(signInToasts()).toEqual([]);
    });

    it("removes a dataset from it", async () => {
      const { result } = renderDrawerAs(value);

      await remove(result);

      expect(uninstallSpy).toHaveBeenCalledWith("flow-new", DATASET.id);
      expect(signInToasts()).toEqual([]);
    });

    it("publishes a dataset from it", async () => {
      const { result } = renderDrawerAs(value);

      await publish(result);

      expect(publishSpy).toHaveBeenCalledWith(DATASET.id, expect.objectContaining({ dataflowId: "flow-new" }));
      expect(signInToasts()).toEqual([]);
    });
  });

  describe("when that save fails", () => {
    beforeEach(() => {
      // ensureProjectId says why its save failed; the action adds nothing to that.
      mockProjectId = null;
      mockEnsureProjectId.mockResolvedValue(null);
    });

    it("is not told to sign in when it adds, removes or publishes", async () => {
      const { result } = renderDrawerAs(value);

      await add(result);
      await remove(result);
      await publish(result);

      expect(installSpy).not.toHaveBeenCalled();
      expect(uninstallSpy).not.toHaveBeenCalled();
      expect(publishSpy).not.toHaveBeenCalled();
      expect(signInToasts()).toEqual([]);
    });
  });
});
