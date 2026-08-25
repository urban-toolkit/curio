import { renderHook, act, waitFor } from "@testing-library/react";

jest.mock("../../api/packagesApi", () => ({
  packagesApi: { catalog: jest.fn(), listInstalled: jest.fn(), resolve: jest.fn() },
}));

import { packagesApi } from "../../api/packagesApi";
import { usePackageInstallReview } from "../../components/agents/attach/usePackageInstallReview";

const PKG = {
  dirName: "curio.weather@1",
  name: "Weather Analysis",
  publisher: "curio",
  version: "1.0.0",
  permissions: ["network.fetch"],
  dependencies: { python: { rasterio: ">=1.5.0" }, js: {}, packages: {} },
  installed: false,
};
const INSTALLED_OTHER = { ...PKG, dirName: "curio.builtin@1", name: "Builtin", installed: true };

// dev/105 A1: a package in the user's STORE but not in the committed catalog —
// an agent-authored notes package proposed on the reuse ladder's enlist rung.
const STORE_ONLY = {
  ...PKG,
  dirName: "curio.notes@1",
  name: "Simple Notes",
  publisher: "Package Builder",
  permissions: [],
  dependencies: { python: {}, js: {}, packages: {} },
  installed: true,
};

const mockCatalog = packagesApi.catalog as jest.Mock;
const mockListInstalled = packagesApi.listInstalled as jest.Mock;
const mockResolve = packagesApi.resolve as jest.Mock;

beforeEach(() => {
  jest.clearAllMocks();
  mockCatalog.mockResolvedValue({ packages: [PKG, INSTALLED_OTHER] });
  // The user's store: the built-in plus the agent-authored notes package.
  mockListInstalled.mockResolvedValue({ packages: [INSTALLED_OTHER, STORE_ONLY] });
  mockResolve.mockResolvedValue({ lockfile: {}, conflicts: [] });
});

describe("usePackageInstallReview (dev/84)", () => {
  it("beginReview loads the row + drawer-shaped probe and opens the candidate", async () => {
    const apply = jest.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => usePackageInstallReview(apply));
    let flow!: Promise<void>;
    act(() => {
      flow = result.current.beginReview("p1", "curio.weather@1");
    });
    await waitFor(() => expect(result.current.candidate).not.toBeNull());
    expect(result.current.candidate!.pkg.name).toBe("Weather Analysis");
    expect(result.current.candidate!.conflicts).toEqual([]);
    // The probe carries every user-STORE package plus the candidate (dev/105
    // A1: the store feed, not the catalog's `installed` flag).
    expect(mockResolve).toHaveBeenCalledWith([
      "curio.builtin@1", "curio.notes@1", "curio.weather@1",
    ]);
    expect(apply).not.toHaveBeenCalled(); // the dialog gates the apply
    act(() => result.current.cancel());
    await flow;
  });

  it("a 409 probe response surfaces its conflict report in the dialog", async () => {
    mockResolve.mockRejectedValue({
      status: 409,
      body: { conflicts: [{ package: "numpy", ranges: [] }] },
    });
    const { result } = renderHook(() => usePackageInstallReview(jest.fn()));
    let flow!: Promise<void>;
    act(() => {
      flow = result.current.beginReview("p1", "curio.weather@1");
    });
    await waitFor(() => expect(result.current.candidate).not.toBeNull());
    expect(result.current.candidate!.conflicts).toEqual([{ package: "numpy", ranges: [] }]);
    act(() => result.current.cancel());
    await flow;
  });

  it("confirm fires the proposal apply and settles the begin promise", async () => {
    const apply = jest.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => usePackageInstallReview(apply));
    let flow!: Promise<void>;
    act(() => {
      flow = result.current.beginReview("p1", "curio.weather@1");
    });
    await waitFor(() => expect(result.current.candidate).not.toBeNull());
    await act(async () => {
      await result.current.confirm();
    });
    expect(apply).toHaveBeenCalledWith("p1");
    expect(result.current.candidate).toBeNull();
    await flow; // resolves — the card's act() completes without error
  });

  it("cancel closes without applying — the proposal stays pending", async () => {
    const apply = jest.fn();
    const { result } = renderHook(() => usePackageInstallReview(apply));
    let flow!: Promise<void>;
    act(() => {
      flow = result.current.beginReview("p1", "curio.weather@1");
    });
    await waitFor(() => expect(result.current.candidate).not.toBeNull());
    act(() => result.current.cancel());
    await flow; // resolves without error
    expect(apply).not.toHaveBeenCalled();
    expect(result.current.candidate).toBeNull();
  });

  it("an apply failure rejects the begin promise into the card's error line", async () => {
    const apply = jest.fn().mockRejectedValue(new Error("conflict — stale"));
    const { result } = renderHook(() => usePackageInstallReview(apply));
    let flow!: Promise<void>;
    act(() => {
      flow = result.current.beginReview("p1", "curio.weather@1");
    });
    await waitFor(() => expect(result.current.candidate).not.toBeNull());
    // Attach the rejection expectation BEFORE confirm settles the deferred,
    // so the rejection is never momentarily unhandled.
    const rejection = expect(flow).rejects.toThrow("conflict — stale");
    await act(async () => {
      await result.current.confirm();
    });
    await rejection;
    expect(result.current.candidate).toBeNull();
  });

  it("a package in neither the catalog nor the store rejects beginReview before any dialog", async () => {
    const { result } = renderHook(() => usePackageInstallReview(jest.fn()));
    await expect(
      result.current.beginReview("p1", "no.such.pkg@9"),
    ).rejects.toThrow("no longer in the Nodes Catalog or your installed packages");
    expect(result.current.candidate).toBeNull();
    expect(mockResolve).not.toHaveBeenCalled();
  });

  // dev/105 A1 — the live 2026-08-25 Apply failure: the Researcher proposed
  // enlisting `curio.notes@1` (agent-authored, in the user's store, NOT in the
  // committed catalog) and this hook refused "no longer in the Nodes Catalog"
  // before the store-aware backend apply ever ran.
  it("a store-only package (absent from the catalog) opens the dialog with the store row", async () => {
    const { result } = renderHook(() => usePackageInstallReview(jest.fn()));
    let flow!: Promise<void>;
    act(() => {
      flow = result.current.beginReview("p1", "curio.notes@1");
    });
    await waitFor(() => expect(result.current.candidate).not.toBeNull());
    expect(result.current.candidate!.pkg).toBe(STORE_ONLY);
    // Probe = every store package + the candidate (already in the store: once).
    expect(mockResolve).toHaveBeenCalledWith(["curio.builtin@1", "curio.notes@1"]);
    act(() => result.current.cancel());
    await flow;
  });

  it("a catalog-only package still resolves (regression)", async () => {
    mockListInstalled.mockResolvedValue({ packages: [INSTALLED_OTHER] });
    const { result } = renderHook(() => usePackageInstallReview(jest.fn()));
    let flow!: Promise<void>;
    act(() => {
      flow = result.current.beginReview("p1", "curio.weather@1");
    });
    await waitFor(() => expect(result.current.candidate).not.toBeNull());
    expect(result.current.candidate!.pkg).toBe(PKG);
    expect(mockResolve).toHaveBeenCalledWith(["curio.builtin@1", "curio.weather@1"]);
    act(() => result.current.cancel());
    await flow;
  });

  it("the probe's installed set comes from the store feed, not the catalog's flag", async () => {
    // The catalog marks nothing installed; the store still lists two packages.
    mockCatalog.mockResolvedValue({ packages: [PKG, { ...INSTALLED_OTHER, installed: false }] });
    const { result } = renderHook(() => usePackageInstallReview(jest.fn()));
    let flow!: Promise<void>;
    act(() => {
      flow = result.current.beginReview("p1", "curio.weather@1");
    });
    await waitFor(() => expect(result.current.candidate).not.toBeNull());
    expect(mockResolve).toHaveBeenCalledWith([
      "curio.builtin@1", "curio.notes@1", "curio.weather@1",
    ]);
    act(() => result.current.cancel());
    await flow;
  });

  it("the store row wins when both feeds carry the dirName", async () => {
    const storeCopy = { ...PKG, name: "Weather Analysis (store copy)", installed: true };
    mockListInstalled.mockResolvedValue({ packages: [INSTALLED_OTHER, storeCopy] });
    const { result } = renderHook(() => usePackageInstallReview(jest.fn()));
    let flow!: Promise<void>;
    act(() => {
      flow = result.current.beginReview("p1", "curio.weather@1");
    });
    await waitFor(() => expect(result.current.candidate).not.toBeNull());
    expect(result.current.candidate!.pkg).toBe(storeCopy);
    act(() => result.current.cancel());
    await flow;
  });
});
