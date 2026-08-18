import { renderHook, act, waitFor } from "@testing-library/react";

jest.mock("../../api/packagesApi", () => ({
  packagesApi: { catalog: jest.fn(), resolve: jest.fn() },
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

const mockCatalog = packagesApi.catalog as jest.Mock;
const mockResolve = packagesApi.resolve as jest.Mock;

beforeEach(() => {
  jest.clearAllMocks();
  mockCatalog.mockResolvedValue({ packages: [PKG, INSTALLED_OTHER] });
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
    // The probe carries every installed package plus the candidate.
    expect(mockResolve).toHaveBeenCalledWith(["curio.builtin@1", "curio.weather@1"]);
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

  it("a package gone from the catalog rejects beginReview before any dialog", async () => {
    const { result } = renderHook(() => usePackageInstallReview(jest.fn()));
    await expect(
      result.current.beginReview("p1", "no.such.pkg@9"),
    ).rejects.toThrow("no longer in the Nodes Catalog");
    expect(result.current.candidate).toBeNull();
  });
});
