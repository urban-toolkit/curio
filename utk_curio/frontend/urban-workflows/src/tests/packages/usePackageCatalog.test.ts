import { renderHook, act, waitFor } from "@testing-library/react";

jest.mock("../../services/packages/packagesApi", () => ({
  packagesApi: {
    catalog: jest.fn(),
    listInstalled: jest.fn(),
    factoryCapabilities: jest.fn(),
    getDefaults: jest.fn(),
    getProjectPackages: jest.fn(),
    resolve: jest.fn(),
    installToProject: jest.fn(),
    uninstallFromProject: jest.fn(),
    installToDefaults: jest.fn(),
    factoryPublishCatalog: jest.fn(),
    unpublishFromCatalog: jest.fn(),
    installFromCatalog: jest.fn(),
    download: jest.fn(),
  },
}));

import { packagesApi } from "../../services/packages/packagesApi";
import { probeInstallConflicts, usePackageCatalog } from "../../services/packages/usePackageCatalog";
import type { PackagePayload } from "../../services/packages";

const api = packagesApi as jest.Mocked<typeof packagesApi>;

function pkg(id: string, extra: Partial<PackagePayload> = {}): PackagePayload {
  return {
    packageId: id, major: 1, version: "1.0.0", name: id, publisher: "t", description: "",
    license: null, permissions: [], dependencies: { packages: {}, python: {}, js: {} },
    templates: [], dirName: `${id}@1`, lineage: null, familyKey: `${id}@1`, channel: "stable",
    ...extra,
  };
}

const CATALOG = [pkg("ai.test.alpha"), pkg("ai.test.beta")];
const STORE = [pkg("ai.test.alpha")];

beforeEach(() => {
  jest.clearAllMocks();
  api.catalog.mockResolvedValue({ packages: CATALOG, families: [], catalogCollisions: [] });
  api.listInstalled.mockResolvedValue({ packages: STORE });
  api.factoryCapabilities.mockResolvedValue({ catalogPublish: true });
  api.getDefaults.mockResolvedValue({ packages: ["ai.test.alpha@1"] });
  api.getProjectPackages.mockResolvedValue({ packages: ["ai.test.alpha@1"] });
  api.resolve.mockResolvedValue({ lockfile: { installedPackages: [], pythonDeps: {}, jsDeps: {} }, conflicts: [] });
  api.installToProject.mockResolvedValue({ packages: ["ai.test.alpha@1", "ai.test.beta@1"], importErrors: {} });
  api.uninstallFromProject.mockResolvedValue({ packages: ["ai.test.alpha@1"], pruned: ["ai.test.beta@1"], removedFromDefaults: [] });
  api.installToDefaults.mockResolvedValue({ packages: ["ai.test.alpha@1", "ai.test.beta@1"], projects: [{ id: "p1", ok: true }, { id: "p2", ok: true }] });
  api.factoryPublishCatalog.mockResolvedValue({} as never);
  api.unpublishFromCatalog.mockResolvedValue(undefined);
  api.installFromCatalog.mockResolvedValue({} as never);
  api.download.mockResolvedValue(undefined);
});

function projectHook(overrides: Partial<Parameters<typeof usePackageCatalog>[0]> = {}) {
  const showToast = jest.fn();
  const refreshRegistry = jest.fn(async () => undefined);
  const onInstalledToProject = jest.fn();
  const onProjectLockfile = jest.fn();
  const beforeReload = jest.fn(() => 7);
  const hook = renderHook(() =>
    usePackageCatalog({
      scope: { kind: "project", projectId: "p1" },
      showToast, refreshRegistry, onInstalledToProject, onProjectLockfile, beforeReload,
      publishDraft: (row) => ({ manifest: { id: row.packageId } }),
      logLabel: "test",
      ...overrides,
    }),
  );
  return { ...hook, showToast, refreshRegistry, onInstalledToProject, onProjectLockfile, beforeReload };
}

describe("usePackageCatalog — listing", () => {
  it("project scope lists the catalog, the store and the capabilities, marks store rows installed, and hands the lockfile back with the token captured before the fetch", async () => {
    const h = projectHook();
    await waitFor(() => expect(h.result.current.catalog).toHaveLength(2));
    expect(h.result.current.catalog.find((p) => p.dirName === "ai.test.alpha@1")?.installed).toBe(true);
    expect(h.result.current.catalog.find((p) => p.dirName === "ai.test.beta@1")?.installed).toBe(false);
    expect(h.result.current.installed).toEqual(STORE);
    expect(h.result.current.catalogPublishAllowed).toBe(true);
    expect(h.beforeReload).toHaveBeenCalled();
    expect(h.onProjectLockfile).toHaveBeenCalledWith(["ai.test.alpha@1"], 7);
    expect(api.getDefaults).not.toHaveBeenCalled();
  });

  it("defaults scope lists the account's always-installed set and never asks for a project lockfile", async () => {
    const { result } = renderHook(() => usePackageCatalog({ scope: { kind: "defaults" } }));
    await waitFor(() => expect(result.current.defaults.has("ai.test.alpha@1")).toBe(true));
    expect(api.getProjectPackages).not.toHaveBeenCalled();
    expect(result.current.installedByDir.get("ai.test.alpha@1")).toEqual(STORE[0]);
  });

  it("a failed listing is a banner, dismissable", async () => {
    api.catalog.mockRejectedValueOnce(new Error("boom"));
    const { result } = renderHook(() => usePackageCatalog({ scope: { kind: "defaults" } }));
    await waitFor(() => expect(result.current.actionError).toBe("Couldn't load catalog: boom"));
    act(() => result.current.dismissActionError());
    expect(result.current.actionError).toBeNull();
  });
});

describe("usePackageCatalog — the install review", () => {
  it("probes the candidate against the store and keeps the conflict report", async () => {
    const h = projectHook();
    await waitFor(() => expect(h.result.current.installed).toHaveLength(1));
    await act(() => h.result.current.probeInstall(CATALOG[1]));
    expect(api.resolve).toHaveBeenCalledWith(["ai.test.alpha@1", "ai.test.beta@1"]);
    expect(h.result.current.installCandidate?.dirName).toBe("ai.test.beta@1");
    expect(h.result.current.conflictReport).toEqual([]);
    act(() => h.result.current.cancelInstall());
    expect(h.result.current.installCandidate).toBeNull();
  });

  it("a 409 probe keeps the candidate with the body's conflicts; any other failure drops it", async () => {
    const h = projectHook();
    await waitFor(() => expect(h.result.current.installed).toHaveLength(1));
    api.resolve.mockRejectedValueOnce(Object.assign(new Error("conflict"), { status: 409, body: { conflicts: [{ package: "numpy", ranges: [] }] } }));
    await act(() => h.result.current.probeInstall(CATALOG[1]));
    expect(h.result.current.conflictReport).toEqual([{ package: "numpy", ranges: [] }]);
    api.resolve.mockRejectedValueOnce(Object.assign(new Error("down"), { status: 500 }));
    await act(() => h.result.current.probeInstall(CATALOG[1]));
    expect(h.result.current.installCandidate).toBeNull();
  });

  it("project scope saves an unsaved dataflow first and gives up quietly when the save is refused", async () => {
    const onEnsureProject = jest.fn(async () => null);
    const h = projectHook({ scope: { kind: "project", projectId: null }, onEnsureProject });
    await waitFor(() => expect(h.result.current.installed).toHaveLength(1));
    await act(() => h.result.current.probeInstall(CATALOG[1]));
    expect(onEnsureProject).toHaveBeenCalled();
    expect(api.resolve).not.toHaveBeenCalled();
    expect(h.result.current.installCandidate).toBeNull();
    expect(h.result.current.actionError).toBeNull(); // a null answer was already reported by the saver
  });

  it("project scope reports a save that throws, labelled with what the save was for", async () => {
    const onEnsureProject = jest.fn(async () => { throw new Error("guests cannot save"); });
    const h = projectHook({ scope: { kind: "project", projectId: null }, onEnsureProject });
    await waitFor(() => expect(h.result.current.installed).toHaveLength(1));
    await act(() => h.result.current.probeInstall(CATALOG[1]));
    expect(h.result.current.actionError).toBe("Couldn't save dataflow before adding: guests cannot save");
    expect(h.result.current.effectiveProjectId).toBeNull();
    const id = await act(() => h.result.current.ensureProjectId("Couldn't save dataflow before importing"));
    expect(id).toBeNull();
  });

  it("an auto-saved id is the effective project id until the prop catches up", async () => {
    const onEnsureProject = jest.fn(async () => "p-new");
    const h = projectHook({ scope: { kind: "project", projectId: null }, onEnsureProject });
    await waitFor(() => expect(h.result.current.installed).toHaveLength(1));
    await act(() => h.result.current.probeInstall(CATALOG[1]));
    expect(h.result.current.effectiveProjectId).toBe("p-new");
    await act(() => h.result.current.confirmInstall());
    expect(api.installToProject).toHaveBeenCalledWith("p-new", "ai.test.beta@1");
  });
});

describe("usePackageCatalog — project install and uninstall", () => {
  it("confirmInstall installs into the project, syncs the mirror, refreshes the registry, reloads and toasts success", async () => {
    const h = projectHook();
    await waitFor(() => expect(h.result.current.installed).toHaveLength(1));
    await act(() => h.result.current.probeInstall(CATALOG[1]));
    await act(() => h.result.current.confirmInstall());
    expect(api.installToProject).toHaveBeenCalledWith("p1", "ai.test.beta@1");
    expect(h.onInstalledToProject).toHaveBeenCalledWith(["ai.test.alpha@1", "ai.test.beta@1"]);
    expect(h.refreshRegistry).toHaveBeenCalled();
    expect(api.catalog).toHaveBeenCalledTimes(2);
    expect(h.showToast).toHaveBeenCalledWith("Added ai.test.beta to this project.", "success");
    expect(h.result.current.installCandidate).toBeNull();
    expect(h.result.current.restartNoticeText).toBeNull();
  });

  it("a restart recommendation becomes the restart notice; a broken library is an error toast instead of the success line", async () => {
    api.installToProject.mockResolvedValueOnce({
      packages: ["ai.test.beta@1"], restartRecommended: { libs: ["numpy"] }, importErrors: { numpy: "DLL load failed" },
    });
    const h = projectHook();
    await waitFor(() => expect(h.result.current.installed).toHaveLength(1));
    await act(() => h.result.current.probeInstall(CATALOG[1]));
    await act(() => h.result.current.confirmInstall());
    expect(h.result.current.restartNoticeText).toMatch(/numpy/);
    expect(h.showToast).toHaveBeenCalledTimes(1);
    expect(h.showToast.mock.calls[0][1]).toBe("error");
    act(() => h.result.current.dismissRestartNotice());
    expect(h.result.current.restartNoticeText).toBeNull();
  });

  it("a failed install is a banner naming the package", async () => {
    api.installToProject.mockRejectedValueOnce(Object.assign(new Error("nope"), { status: 502 }));
    const h = projectHook();
    await waitFor(() => expect(h.result.current.installed).toHaveLength(1));
    await act(() => h.result.current.probeInstall(CATALOG[1]));
    await act(() => h.result.current.confirmInstall());
    expect(h.result.current.actionError).toBe("Couldn't add ai.test.beta: nope");
    expect(h.result.current.busy).toBe(false);
  });

  it("uninstallFromProject syncs the mirror, refreshes, reloads, and says what the prune did", async () => {
    const h = projectHook();
    await waitFor(() => expect(h.result.current.installed).toHaveLength(1));
    await act(() => h.result.current.uninstallFromProject(CATALOG[1]));
    expect(api.uninstallFromProject).toHaveBeenCalledWith("p1", "ai.test.beta@1");
    expect(h.onInstalledToProject).toHaveBeenCalledWith(["ai.test.alpha@1"]);
    expect(h.refreshRegistry).toHaveBeenCalled();
    expect(h.showToast).toHaveBeenCalledWith("Removed ai.test.beta from this project and from your account.", "success");
    expect(h.result.current.cardActionDir).toBeNull();
  });

  it("uninstallFromProject is a no-op in defaults scope", async () => {
    const { result } = renderHook(() => usePackageCatalog({ scope: { kind: "defaults" } }));
    await waitFor(() => expect(result.current.installed).toHaveLength(1));
    await act(() => result.current.uninstallFromProject(CATALOG[1]));
    expect(api.uninstallFromProject).not.toHaveBeenCalled();
  });
});

describe("usePackageCatalog — defaults install", () => {
  it("confirmInstall installs into every project and summarises the count", async () => {
    const showToast = jest.fn(); const refreshRegistry = jest.fn(async () => undefined);
    const { result } = renderHook(() => usePackageCatalog({ scope: { kind: "defaults" }, showToast, refreshRegistry }));
    await waitFor(() => expect(result.current.installed).toHaveLength(1));
    await act(() => result.current.probeInstall(CATALOG[1]));
    await act(() => result.current.confirmInstall());
    expect(api.installToDefaults).toHaveBeenCalledWith("ai.test.beta@1");
    expect(result.current.lastInstallSummary).toBe("Added ai.test.beta to 2 projects");
    expect(refreshRegistry).toHaveBeenCalled();
    expect(showToast).not.toHaveBeenCalled();
    act(() => result.current.dismissInstallSummary());
    expect(result.current.lastInstallSummary).toBeNull();
  });

  it("partial failures and the no-projects case read as the page always said", async () => {
    api.installToDefaults.mockResolvedValueOnce({ packages: [], projects: [{ id: "p1", ok: true }, { id: "p2", ok: false, error: "x" }] });
    const { result } = renderHook(() => usePackageCatalog({ scope: { kind: "defaults" } }));
    await waitFor(() => expect(result.current.installed).toHaveLength(1));
    await act(() => result.current.probeInstall(CATALOG[1]));
    await act(() => result.current.confirmInstall());
    expect(result.current.lastInstallSummary).toBe("Added to 1/2 projects; 1 failed: p2");
    api.installToDefaults.mockResolvedValueOnce({ packages: [], projects: [] });
    await act(() => result.current.probeInstall(CATALOG[1]));
    await act(() => result.current.confirmInstall());
    expect(result.current.lastInstallSummary).toBe("Added ai.test.beta to 0 projects (no existing projects; will seed into new ones)");
  });

  it("confirmInstall without a candidate does nothing", async () => {
    const { result } = renderHook(() => usePackageCatalog({ scope: { kind: "defaults" } }));
    await waitFor(() => expect(result.current.installed).toHaveLength(1));
    await act(() => result.current.confirmInstall());
    expect(api.installToDefaults).not.toHaveBeenCalled();
  });
});

describe("usePackageCatalog — publish, unpublish, reload, export", () => {
  it("publish rebuilds the draft through the injected mapping, replaces, reloads and toasts", async () => {
    const h = projectHook();
    await waitFor(() => expect(h.result.current.installed).toHaveLength(1));
    await act(() => h.result.current.publish("ai.test.alpha@1"));
    expect(api.factoryPublishCatalog).toHaveBeenCalledWith({ manifest: { id: "ai.test.alpha" }, replace: true });
    expect(h.showToast).toHaveBeenCalledWith("Published ai.test.alpha.", "success");
    expect(h.result.current.publishingPackageKey).toBeNull();
  });

  it("publish of a package not in the store is a no-op", async () => {
    const h = projectHook();
    await waitFor(() => expect(h.result.current.installed).toHaveLength(1));
    await act(() => h.result.current.publish("ai.test.beta@1"));
    expect(api.factoryPublishCatalog).not.toHaveBeenCalled();
  });

  it("unpublish takes a row or a dirName and names the package", async () => {
    const h = projectHook();
    await waitFor(() => expect(h.result.current.installed).toHaveLength(1));
    await act(() => h.result.current.unpublish(CATALOG[1]));
    await act(() => h.result.current.unpublish("ai.test.alpha@1"));
    expect(api.unpublishFromCatalog).toHaveBeenCalledWith("ai.test.beta@1");
    expect(h.showToast).toHaveBeenCalledWith("Unpublished ai.test.beta.", "success");
    expect(h.showToast).toHaveBeenCalledWith("Unpublished ai.test.alpha.", "success");
  });

  it("reloadFromCatalog re-copies and reloads the window; a failure clears the spinner", async () => {
    const reloadWindow = jest.fn();
    const h = projectHook({ reloadWindow });
    await waitFor(() => expect(h.result.current.installed).toHaveLength(1));
    await act(() => h.result.current.reloadFromCatalog(CATALOG[0]));
    expect(api.installFromCatalog).toHaveBeenCalledWith("ai.test.alpha@1", { replace: true });
    expect(reloadWindow).toHaveBeenCalled();
    api.installFromCatalog.mockRejectedValueOnce(new Error("off"));
    await act(() => h.result.current.reloadFromCatalog(CATALOG[0]));
    expect(h.result.current.actionError).toBe("Couldn't reload ai.test.alpha: off");
    expect(h.result.current.reloadingPackageKey).toBeNull();
  });

  it("exportArchive downloads; a failure is a banner", async () => {
    api.download.mockRejectedValueOnce(new Error("gone"));
    const h = projectHook();
    await waitFor(() => expect(h.result.current.installed).toHaveLength(1));
    await act(() => h.result.current.exportArchive(CATALOG[0]));
    expect(h.result.current.actionError).toBe("Couldn't export ai.test.alpha@1: gone");
    await act(() => h.result.current.exportArchive(CATALOG[1]));
    expect(api.download).toHaveBeenCalledWith("ai.test.beta@1");
  });
});

describe("probeInstallConflicts (the ONE pre-install probe, memo dev/143 rule 2)", () => {
  it("answers the resolver's conflicts", async () => {
    api.resolve.mockResolvedValueOnce({ conflicts: [{ kind: "x" } as never], plan: [] } as never);
    await expect(probeInstallConflicts(["a@1", "b@1"])).resolves.toEqual([{ kind: "x" }]);
    expect(api.resolve).toHaveBeenCalledWith(["a@1", "b@1"]);
  });

  it("reads a 409 body as the conflict report, not a failure", async () => {
    api.resolve.mockRejectedValueOnce({ status: 409, body: { conflicts: [{ kind: "clash" }] } });
    await expect(probeInstallConflicts(["a@1"])).resolves.toEqual([{ kind: "clash" }]);
    api.resolve.mockRejectedValueOnce({ status: 409, body: {} });
    await expect(probeInstallConflicts(["a@1"])).resolves.toEqual([]);
  });

  it("propagates any other failure to the caller", async () => {
    api.resolve.mockRejectedValueOnce(new Error("offline"));
    await expect(probeInstallConflicts(["a@1"])).rejects.toThrow("offline");
  });
});
