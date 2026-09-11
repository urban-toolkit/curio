/**
 * Does loading a dataflow auto-install the packages it declares?
 *
 * `useEnsureWorkflowDeps` is the whole answer, and it had no test. It reads
 * `spec.dataflow.packages`, asks the backend which of them are missing, and
 * installs those - fire-and-forget, so the canvas stays usable while pip runs.
 *
 * The backend halves are covered by test_workflow_deps.py (9 tests over
 * /workflow-deps/check and /workflow-deps/install). What was untested is the
 * decision logic here: when to install at all, and - critically - that a
 * best-effort check failure never escalates into a spurious install or a
 * misleading toast.
 *
 * The companion security rule ("never for a foreign shared spec") lives in
 * ProjectLoader and is covered in projectLoaderTrustedDeps.test.ts.
 */
import { renderHook, act } from "@testing-library/react";

const mockShowToast = jest.fn();
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));
jest.mock("../../api/packagesApi", () => ({
  packagesApi: {
    checkWorkflowDeps: jest.fn(),
    installWorkflowDeps: jest.fn(),
  },
}));
jest.mock("../../registry/packageRegistryBootstrap", () => ({
  refreshPackageRegistry: jest.fn(),
}));

import { useEnsureWorkflowDeps } from "../../hook/useEnsureWorkflowDeps";
import { packagesApi } from "../../api/packagesApi";
import { refreshPackageRegistry } from "../../registry/packageRegistryBootstrap";

const mockCheck = packagesApi.checkWorkflowDeps as jest.Mock;
const mockInstall = packagesApi.installWorkflowDeps as jest.Mock;
const mockRefresh = refreshPackageRegistry as jest.Mock;

/** Run the hook's fire-and-forget body to completion. */
const ensure = async (spec: unknown) => {
  const { result } = renderHook(() => useEnsureWorkflowDeps());
  await act(async () => {
    result.current(spec as Parameters<typeof result.current>[0]);
    // The hook kicks off an unawaited async IIFE; drain the microtask queue.
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
};

beforeEach(() => {
  jest.clearAllMocks();
  mockCheck.mockResolvedValue({ packages: [] });
  mockInstall.mockResolvedValue({ installedPackages: [] });
  mockRefresh.mockResolvedValue(undefined);
});

describe("useEnsureWorkflowDeps - when it does nothing", () => {
  it.each([
    ["undefined spec", undefined],
    ["no dataflow", {}],
    ["no packages key", { dataflow: {} }],
    ["empty packages", { dataflow: { packages: [] } }],
    ["packages not an array", { dataflow: { packages: "curio.weather@1" } }],
  ])("skips the check entirely for %s", async (_label, spec) => {
    await ensure(spec);
    expect(mockCheck).not.toHaveBeenCalled();
    expect(mockInstall).not.toHaveBeenCalled();
    expect(mockShowToast).not.toHaveBeenCalled();
  });

  it("drops non-string entries before asking the backend", async () => {
    await ensure({
      dataflow: { packages: ["curio.weather@1", 42, null, { a: 1 }, "ai.x.y@2"] },
    });
    expect(mockCheck).toHaveBeenCalledWith(["curio.weather@1", "ai.x.y@2"]);
  });

  it("skips the check when every entry is non-string", async () => {
    await ensure({ dataflow: { packages: [1, 2, 3] } });
    expect(mockCheck).not.toHaveBeenCalled();
  });

  it("installs nothing when the backend says nothing is needed", async () => {
    mockCheck.mockResolvedValue({ packages: [] });
    await ensure({ dataflow: { packages: ["curio.weather@1"] } });
    expect(mockCheck).toHaveBeenCalledTimes(1);
    expect(mockInstall).not.toHaveBeenCalled();
    // No toast: a dataflow whose deps are already satisfied must open silently.
    expect(mockShowToast).not.toHaveBeenCalled();
  });
});

describe("useEnsureWorkflowDeps - the install path", () => {
  it("installs only what the check reported as missing", async () => {
    mockCheck.mockResolvedValue({ packages: ["ai.urbanlab.uhvi@1"] });
    await ensure({
      dataflow: { packages: ["curio.weather@1", "ai.urbanlab.uhvi@1"] },
    });
    // The declared set is what we ask about; the *needed* subset is what we
    // install. Installing the full declared set would redo satisfied work.
    expect(mockCheck).toHaveBeenCalledWith([
      "curio.weather@1",
      "ai.urbanlab.uhvi@1",
    ]);
    expect(mockInstall).toHaveBeenCalledWith(["ai.urbanlab.uhvi@1"]);
  });

  it("warns before installing and confirms after", async () => {
    mockCheck.mockResolvedValue({ packages: ["a.b.c@1", "d.e.f@2"] });
    await ensure({ dataflow: { packages: ["a.b.c@1", "d.e.f@2"] } });
    expect(mockShowToast).toHaveBeenCalledWith(
      expect.stringContaining("a.b.c@1, d.e.f@2"),
      "warning",
    );
    expect(mockShowToast).toHaveBeenCalledWith(
      "Installed a.b.c@1, d.e.f@2.",
      "success",
    );
  });

  it("refreshes the registry so the palette shows the new nodes", async () => {
    mockCheck.mockResolvedValue({ packages: ["a.b.c@1"] });
    await ensure({ dataflow: { packages: ["a.b.c@1"] } });
    expect(mockRefresh).toHaveBeenCalledTimes(1);
  });
});

describe("useEnsureWorkflowDeps - failure handling", () => {
  it("stays completely silent when the check fails", async () => {
    // Best-effort by design: an older backend without the route, or a dev
    // reloader restart, must not assert an install failure for packages that
    // may already be fine.
    mockCheck.mockRejectedValue(new Error("404 route missing"));
    const spy = jest.spyOn(console, "error").mockImplementation(() => {});
    await ensure({ dataflow: { packages: ["a.b.c@1"] } });
    expect(mockInstall).not.toHaveBeenCalled();
    expect(mockShowToast).not.toHaveBeenCalled();
    spy.mockRestore();
  });

  it("reports an install failure as actionable, not silent", async () => {
    mockCheck.mockResolvedValue({ packages: ["a.b.c@1"] });
    mockInstall.mockRejectedValue(new Error("pip exploded"));
    const spy = jest.spyOn(console, "error").mockImplementation(() => {});
    await ensure({ dataflow: { packages: ["a.b.c@1"] } });
    expect(mockShowToast).toHaveBeenCalledWith(
      expect.stringContaining("Could not install a.b.c@1"),
      "error",
    );
    expect(mockShowToast).not.toHaveBeenCalledWith(
      expect.stringContaining("Installed"),
      "success",
    );
    spy.mockRestore();
  });

  it("still reports success when only the palette refresh fails", async () => {
    // The install already landed; a palette refresh failure must not be
    // reported as an install failure.
    mockCheck.mockResolvedValue({ packages: ["a.b.c@1"] });
    mockRefresh.mockRejectedValue(new Error("registry hiccup"));
    await ensure({ dataflow: { packages: ["a.b.c@1"] } });
    expect(mockShowToast).toHaveBeenCalledWith("Installed a.b.c@1.", "success");
    expect(mockShowToast).not.toHaveBeenCalledWith(
      expect.anything(),
      "error",
    );
  });
});

describe("useEnsureWorkflowDeps - a dep that is installed but will not import", () => {
  // The gap a version check cannot see: a wheel whose native extension fails to
  // load records a perfectly good version, so `is_satisfied` says yes and the
  // dataflow used to load clean - the user meeting the failure later as a raw
  // ImportError from whichever node ran first.
  const BROKEN = {
    package: "curio.weather@1",
    dep: "rasterio",
    error: "ImportError: DLL load failed while importing _base",
  };

  it("warns, naming the library and the actual error", async () => {
    mockCheck.mockResolvedValue({ packages: [], broken: [BROKEN] });

    await ensure({ dataflow: { packages: ["curio.weather@1"] } });

    expect(mockShowToast).toHaveBeenCalledTimes(1);
    const [message, level] = mockShowToast.mock.calls[0];
    expect(level).toBe("error");
    expect(message).toContain("rasterio");
    expect(message).toContain("DLL load failed");
  });

  it("does NOT try to install it — reinstalling cannot fix a broken extension", async () => {
    // pip would report "already satisfied" and change nothing, so an install
    // here would be a no-op dressed up as a repair.
    mockCheck.mockResolvedValue({ packages: [], broken: [BROKEN] });

    await ensure({ dataflow: { packages: ["curio.weather@1"] } });

    expect(mockInstall).not.toHaveBeenCalled();
  });

  it("still installs what is genuinely missing alongside the warning", async () => {
    // The two conditions are independent: one package broken, another absent.
    mockCheck.mockResolvedValue({ packages: ["curio.uhvi@1"], broken: [BROKEN] });
    mockInstall.mockResolvedValue({ packages: ["curio.uhvi@1"] });

    await ensure({ dataflow: { packages: ["curio.weather@1", "curio.uhvi@1"] } });

    expect(mockInstall).toHaveBeenCalledWith(["curio.uhvi@1"]);
    const levels = mockShowToast.mock.calls.map((c) => c[1]);
    expect(levels).toContain("error");
  });

  it("says nothing when the backend reports nothing broken", async () => {
    mockCheck.mockResolvedValue({ packages: [], broken: [] });

    await ensure({ dataflow: { packages: ["curio.weather@1"] } });

    expect(mockShowToast).not.toHaveBeenCalled();
  });

  it("tolerates an older backend that omits the field entirely", async () => {
    // `broken` is optional in the response type; a missing key must not throw.
    mockCheck.mockResolvedValue({ packages: [] });

    await ensure({ dataflow: { packages: ["curio.weather@1"] } });

    expect(mockShowToast).not.toHaveBeenCalled();
    expect(mockInstall).not.toHaveBeenCalled();
  });
});

describe("useEnsureWorkflowDeps - one library, one notice", () => {
  it("does not repeat a library the check already reported", async () => {
    // /check names installed-but-unimportable libraries, then /install runs and
    // reports the same ones - pip counts them satisfied and skips, so the
    // install cannot have repaired them. Two persistent red toasts about one
    // library reads as two problems.
    mockCheck.mockResolvedValue({
      packages: ["curio.weather@1"],
      broken: [{ package: "curio.weather@1", dep: "rasterio", error: "ImportError: DLL load failed" }],
    });
    mockInstall.mockResolvedValue({
      installedPackages: ["curio.weather@1"],
      importErrors: { rasterio: "ImportError: DLL load failed" },
    });

    await ensure({ dataflow: { packages: ["curio.weather@1"] } });

    const mentions = mockShowToast.mock.calls.filter(([msg]) =>
      String(msg).includes("rasterio"),
    );
    expect(mentions).toHaveLength(1);
  });

  it("still reports a library only the install found", async () => {
    // The check clears a dep it considers satisfied; the install's probe is
    // what actually tries the import. Suppressing by name must not suppress
    // a verdict nobody has shown yet.
    mockCheck.mockResolvedValue({ packages: ["curio.weather@1"], broken: [] });
    mockInstall.mockResolvedValue({
      installedPackages: ["curio.weather@1"],
      importErrors: { rasterstats: "ImportError: DLL load failed" },
    });

    await ensure({ dataflow: { packages: ["curio.weather@1"] } });

    expect(
      mockShowToast.mock.calls.some(([msg]) => String(msg).includes("rasterstats")),
    ).toBe(true);
  });
});
