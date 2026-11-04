/**
 * The Node and Model Catalog drawers on a dataflow a hosted guest never saved
 * (`isHostedGuest`: a guest on a Curio started with --deploy). Add, Remove and
 * Import write the dataflow's lockfile, so they save a dataflow that has no id
 * first, and such a guest cannot save one: each tells it to sign in, naming
 * what it was doing, and nothing is saved or sent. The local shared guest and
 * a signed-in account keep today's behavior: the save creates the dataflow and
 * the action goes on.
 *
 * The harness is modelCatalogDrawer.test.tsx's, with a dataflow that has no id.
 */
import React from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { MemoryRouter } from "react-router-dom";

import { ModelCatalogDrawer } from "../../components/models/catalog/ModelCatalogDrawer";
import { NodeCatalogDrawer } from "../../components/packages/publishing/NodeCatalogDrawer";
import { UserContext } from "../../providers/userContext";
import type { UserData } from "../../utils/authApi";
import {
  builtinPackage,
  ddrnetPackage,
  deepUmbraPackage,
  importedModelPackage,
  scoutPackage,
} from "../_support/modelPackages";

// The drawer reaches the node registry, whose built-in behaviors load Vega's
// ESM build: mocked virtually, as testing-gotchas prescribes.
jest.mock("vega", () => ({}), { virtual: true });
jest.mock("vega-lite", () => ({}), { virtual: true });

const mockApi = {
  catalog: jest.fn(),
  listInstalled: jest.fn(),
  factoryCapabilities: jest.fn(),
  getProjectPackages: jest.fn(),
  getDefaults: jest.fn(),
  resolve: jest.fn(),
  installToProject: jest.fn(),
  uninstallFromProject: jest.fn(),
  uploadArchive: jest.fn(),
  weightsLicense: jest.fn(),
  usage: jest.fn(),
};
jest.mock("../../services/packages/packagesApi", () => ({
  packagesApi: new Proxy({}, { get: (_target, name: string) => (mockApi as any)[name] }),
}));
jest.mock("../../utils/authApi", () => ({
  apiFetch: jest.fn().mockResolvedValue({ items: [] }),
  getToken: jest.fn(() => "token"),
}));
const mockShowToast = jest.fn();
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));
const mockLockfile = ["curio.scout@1", "model.curio.ddrnet23-slim@1"];
// The save every Add, Remove and Import makes first on a dataflow with no id.
const mockRequestProjectSave = jest.fn();
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    // Never saved.
    projectId: null,
    projectName: null,
    packages: mockLockfile,
    nodes: [],
    requestProjectSave: mockRequestProjectSave,
    saveCurrentProject: jest.fn(),
    projectDirty: true,
  }),
}));
jest.mock("../../registry/packageRegistryBootstrap", () => ({
  refreshPackageRegistry: jest.fn().mockResolvedValue(undefined),
}));
jest.mock("../../registry/projectPackagesStore", () => ({
  // The node registry subscribes to the store at import.
  ...jest.requireActual("../../registry/projectPackagesStore"),
  applyProjectLockfile: jest.fn(() => false),
  getPackagesRevision: jest.fn(() => 0),
  setCurrentProjectPackages: jest.fn(),
}));

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

const MODEL_DRAWER = '[data-curio-model-catalog-drawer="true"]';
const NODE_DRAWER = '[data-curio-node-catalog-drawer="true"]';

function renderModelDrawerAs(value: UserContextValue) {
  return render(
    <UserContext.Provider value={value}>
      <MemoryRouter>
        <ModelCatalogDrawer presented onRequestClose={jest.fn()} onExitComplete={jest.fn()} />
      </MemoryRouter>
    </UserContext.Provider>,
  );
}

function renderNodeDrawerAs(value: UserContextValue) {
  return render(
    <UserContext.Provider value={value}>
      <MemoryRouter>
        <NodeCatalogDrawer presented onRequestClose={jest.fn()} onExitComplete={jest.fn()} />
      </MemoryRouter>
    </UserContext.Provider>,
  );
}

function card(root: string, dirName: string): HTMLElement | null {
  return document.querySelector(`${root} article[data-pkg-dir="${dirName}"]`);
}

async function modelCard(dirName: string): Promise<HTMLElement> {
  await waitFor(() => expect(card(MODEL_DRAWER, dirName)).not.toBeNull());
  return card(MODEL_DRAWER, dirName)!;
}

function tab(name: "Browse all" | "In project"): HTMLElement {
  return screen.getByRole("button", { name: new RegExp(`^${name}`) });
}

/** Add on Deep Umbra, a model the dataflow does not have. */
async function addDeepUmbra() {
  const deepUmbra = await modelCard("model.scout.deep-umbra@1");
  const add = within(deepUmbra).getByRole("button", { name: "Add to project" });
  await act(async () => {
    fireEvent.click(add);
  });
}

/** Remove on DDRNet, a model in the dataflow's lockfile, through its confirmation. */
async function removeDdrnet() {
  await modelCard("model.curio.ddrnet23-slim@1");
  fireEvent.click(tab("In project"));
  const ddrnet = await modelCard("model.curio.ddrnet23-slim@1");
  fireEvent.click(within(ddrnet).getByRole("button", { name: "Remove from project" }));
  const confirm = await screen.findByRole("dialog", { name: "Remove DDRNet23-Slim (street scenes)?" });
  await act(async () => {
    fireEvent.click(within(confirm).getByRole("button", { name: "Remove" }));
  });
}

/** The footer's Import package, with an archive picked. */
async function importArchive(root: string) {
  const drawer = document.querySelector(root) as HTMLElement;
  expect(within(drawer).getByRole("button", { name: "Import package" })).toBeInTheDocument();
  const input = drawer.querySelector('input[type="file"]') as HTMLInputElement;
  expect(input).not.toBeNull();
  await act(async () => {
    fireEvent.change(input, { target: { files: [new File(["zip"], "segformer.curio.zip")] } });
  });
}

/** Let the handlers' awaited calls settle. */
async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

function signInToasts(): string[] {
  return mockShowToast.mock.calls
    .map((call: unknown[]) => String(call[0]))
    .filter((message) => message.startsWith("Sign in"));
}

beforeEach(() => {
  jest.clearAllMocks();
  mockApi.catalog.mockResolvedValue({
    packages: [ddrnetPackage(), deepUmbraPackage(), builtinPackage(), scoutPackage()],
    families: [],
    catalogCollisions: [],
  });
  mockApi.listInstalled.mockResolvedValue({
    packages: [ddrnetPackage(), builtinPackage(), scoutPackage(), importedModelPackage()],
  });
  mockApi.factoryCapabilities.mockResolvedValue({ catalogPublish: true });
  mockApi.getProjectPackages.mockResolvedValue({ packages: mockLockfile });
  mockApi.getDefaults.mockResolvedValue({ packages: [] });
  mockApi.resolve.mockResolvedValue({ lockfile: [], conflicts: [] });
  mockApi.installToProject.mockResolvedValue({ packages: [...mockLockfile, "model.scout.deep-umbra@1"] });
  mockApi.uninstallFromProject.mockResolvedValue({ packages: ["curio.scout@1"] });
  mockApi.uploadArchive.mockResolvedValue({ package: importedModelPackage() });
  mockApi.weightsLicense.mockResolvedValue("MIT License");
  mockApi.usage.mockResolvedValue([]);
  // How the save queue answers anyone but a hosted guest: the save creates the dataflow.
  mockRequestProjectSave.mockResolvedValue({ id: "p-new" });
});

describe("a hosted guest, on a dataflow it never saved", () => {
  beforeEach(() => {
    // How the save queue answers a hosted guest.
    mockRequestProjectSave.mockRejectedValue(new Error("Guest users cannot save projects"));
  });

  test("is told to sign in when it adds a model, and nothing is saved or reviewed", async () => {
    renderModelDrawerAs(HOSTED_GUEST);

    await addDeepUmbra();
    await settle();

    expect(mockShowToast).toHaveBeenCalledWith("Sign in to add models.", "warning");
    expect(mockRequestProjectSave).not.toHaveBeenCalled();
    expect(mockApi.resolve).not.toHaveBeenCalled();
  });

  test("is told to sign in when it removes a model, and nothing is saved or removed", async () => {
    renderModelDrawerAs(HOSTED_GUEST);

    await removeDdrnet();
    await settle();

    expect(mockShowToast).toHaveBeenCalledWith("Sign in to remove models.", "warning");
    expect(mockRequestProjectSave).not.toHaveBeenCalled();
    expect(mockApi.uninstallFromProject).not.toHaveBeenCalled();
  });

  test("is told to sign in when it imports a model package, and nothing is saved or uploaded", async () => {
    renderModelDrawerAs(HOSTED_GUEST);
    await modelCard("model.curio.ddrnet23-slim@1");

    await importArchive(MODEL_DRAWER);
    await settle();

    expect(mockShowToast).toHaveBeenCalledWith("Sign in to import models.", "warning");
    expect(mockRequestProjectSave).not.toHaveBeenCalled();
    expect(mockApi.uploadArchive).not.toHaveBeenCalled();
  });

  test("is told in the Node Catalog's words when it imports a node package", async () => {
    renderNodeDrawerAs(HOSTED_GUEST);
    await waitFor(() => expect(card(NODE_DRAWER, "curio.scout@1")).not.toBeNull());

    await importArchive(NODE_DRAWER);
    await settle();

    expect(mockShowToast).toHaveBeenCalledWith("Sign in to import packages.", "warning");
    expect(mockRequestProjectSave).not.toHaveBeenCalled();
    expect(mockApi.uploadArchive).not.toHaveBeenCalled();
  });
});

describe.each([
  ["the local shared guest", LOCAL_GUEST],
  ["a signed-in account", SIGNED_IN_USER],
])("%s, on a dataflow never saved", (_who, value) => {
  test("adds a model once the save has created the dataflow", async () => {
    renderModelDrawerAs(value);

    await addDeepUmbra();

    await waitFor(() => expect(mockApi.resolve).toHaveBeenCalled());
    expect(mockRequestProjectSave).toHaveBeenCalledTimes(1);
    expect(signInToasts()).toEqual([]);
  });

  test("removes a model from the dataflow the save created", async () => {
    renderModelDrawerAs(value);

    await removeDdrnet();

    await waitFor(() =>
      expect(mockApi.uninstallFromProject).toHaveBeenCalledWith("p-new", "model.curio.ddrnet23-slim@1"),
    );
    expect(mockRequestProjectSave).toHaveBeenCalledTimes(1);
    expect(signInToasts()).toEqual([]);
  });

  test("imports a package archive into the dataflow the save created", async () => {
    renderModelDrawerAs(value);
    await modelCard("model.curio.ddrnet23-slim@1");

    await importArchive(MODEL_DRAWER);

    await waitFor(() =>
      expect(mockApi.installToProject).toHaveBeenCalledWith("p-new", "imported.xabc123def456@1"),
    );
    expect(mockRequestProjectSave).toHaveBeenCalledTimes(1);
    expect(signInToasts()).toEqual([]);
  });
});
