/**
 * The Data Catalog page's Add to all projects and Remove from all projects for
 * a hosted guest (`isHostedGuest`: a guest on a Curio started with --deploy).
 * Every such guest shares one account, whose list of datasets for all projects
 * every guest's dataflows start with, so each tells the guest to sign in, as
 * the Node Catalog drawer's refusals do, and sends nothing. The drawer's
 * buttons and the cards' right-click menu both go through these handlers. The
 * local shared guest and a signed-in account change the list as before.
 */
import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { MemoryRouter, Route, Routes } from "react-router-dom";

const mockShowToast = jest.fn();

jest.mock("../../registry/packageRegistryBootstrap", () => ({
  refreshPackageRegistry: jest.fn(),
}));
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ projectId: null }),
}));
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));
jest.mock("../../services/packages/packagesApi", () => ({
  packagesApi: { factoryCapabilities: jest.fn(() => Promise.resolve({ catalogPublish: true })) },
}));
jest.mock("../../components/datasets/catalog/DatasetDetailModal", () => ({
  DatasetDetailModal: () => null,
}));

const mockItem = {
  id: "imported.bikes",
  title: "Bike Routes",
  origin: "imported",
  format: "csv",
  uri: "curio://datasets/imported.bikes",
  consumerNodeIds: [],
  updatedAt: "2026-01-01T00:00:00Z",
  tags: [],
  installed: false,
};

// The drawer is where these actions are pressed; stand in for it with one
// button per handler the page hands it.
jest.mock("../../pages/dataCatalog/DataCatalogBrowseDrawer", () => ({
  DataCatalogBrowseDrawer: (props: Record<string, (d: unknown) => void>) => (
    <div>
      <button type="button" onClick={() => props.onAddToAllProjects(mockItem)}>add</button>
      <button type="button" onClick={() => props.onRemoveFromAllProjects(mockItem)}>remove</button>
    </div>
  ),
}));

jest.mock("../../services/datasetCatalog", () => {
  const actual = jest.requireActual("../../services/datasetCatalog");
  return {
    ...actual,
    useDatasetCatalog: () => ({
      items: [mockItem],
      facets: { format: { csv: 1 }, origin: { imported: 1 } },
      loading: false,
      refreshing: false,
      error: null,
      reload: jest.fn(),
      importDataset: jest.fn(),
    }),
    useDatasetImport: () => ({ importing: false, importFile: jest.fn() }),
    datasetCatalogApi: {
      ...actual.datasetCatalogApi,
      listDatasetDefaults: jest.fn(() => Promise.resolve({ datasets: [] })),
      addDatasetToDefaults: jest.fn(() => Promise.resolve({ datasets: ["imported.bikes"], projects: [] })),
      removeDatasetFromDefaults: jest.fn(() => Promise.resolve({ datasets: [], projects: [] })),
    },
  };
});

import { DataCatalogBrowse } from "../../pages/dataCatalog/DataCatalogBrowse";
import { DatasetDetailsProvider } from "../../components/datasets/catalog/DatasetDetailsProvider";
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

const api = datasetCatalogApi as unknown as Record<string, jest.Mock>;

function renderPageAs(value: UserContextValue) {
  return render(
    <UserContext.Provider value={value}>
      <MemoryRouter initialEntries={["/catalog/data"]}>
        <DatasetDetailsProvider closeOnNavigate>
          <Routes>
            <Route path="/catalog/data/:datasetId?" element={<DataCatalogBrowse />} />
          </Routes>
        </DatasetDetailsProvider>
      </MemoryRouter>
    </UserContext.Provider>,
  );
}

function signInToasts(): string[] {
  return mockShowToast.mock.calls
    .map((call: unknown[]) => String(call[0]))
    .filter((message) => message.startsWith("Sign in"));
}

beforeEach(() => jest.clearAllMocks());

describe("a hosted guest", () => {
  test.each([
    ["add", "addDatasetToDefaults", "Sign in to add datasets to all projects."],
    ["remove", "removeDatasetFromDefaults", "Sign in to remove datasets from all projects."],
  ])("is told to sign in when it presses %s, and nothing is sent", async (button, method, note) => {
    renderPageAs(HOSTED_GUEST);

    fireEvent.click(await screen.findByRole("button", { name: button }));

    await waitFor(() => expect(mockShowToast).toHaveBeenCalledWith(note, "warning"));
    expect(api[method]).not.toHaveBeenCalled();
  });
});

describe.each([
  ["the local shared guest", LOCAL_GUEST],
  ["a signed-in account", SIGNED_IN_USER],
])("%s", (_who, value) => {
  test.each([
    ["add", "addDatasetToDefaults"],
    ["remove", "removeDatasetFromDefaults"],
  ])("changes the list for all projects when it presses %s", async (button, method) => {
    renderPageAs(value);

    fireEvent.click(await screen.findByRole("button", { name: button }));

    await waitFor(() => expect(api[method]).toHaveBeenCalledWith("imported.bikes"));
    expect(signInToasts()).toEqual([]);
  });
});
