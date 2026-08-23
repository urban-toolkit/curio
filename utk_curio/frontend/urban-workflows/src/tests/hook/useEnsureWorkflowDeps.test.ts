/**
 * Does loading a dataflow auto-install the packages it declares?
 *
 * `useEnsureWorkflowDeps` is the whole answer, and it had no test. It reads
 * `spec.dataflow.packages`, asks the backend which of them are missing, and
 * installs those — fire-and-forget, so the canvas stays usable while pip runs.
 *
 * The backend halves are covered by test_workflow_deps.py (9 tests over
 * /workflow-deps/check and /workflow-deps/install). What was untested is the
 * decision logic here: when to install at all, and — critically — that a
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

describe("useEnsureWorkflowDeps — when it does nothing", () => {
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

describe("useEnsureWorkflowDeps — the install path", () => {
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

describe("useEnsureWorkflowDeps — failure handling", () => {
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
