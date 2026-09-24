/**
 * The monitor page as a whole.
 *
 * The charts are mocked: vega does not render under jsdom, and what matters
 * here is that the page composes, polls, pauses and survives a failed request.
 */
import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

jest.mock("../../pages/monitor/MonitorCharts", () => ({
  DurationHistogram: () => <div data-testid="duration-chart" />,
  StoreSizeHistogram: () => <div data-testid="store-chart" />,
}));

jest.mock("../../components/VersionBadge", () => ({
  __esModule: true,
  default: () => <div data-testid="version-badge" />,
}));

// GlobalPageHeader reaches UserProvider, which boots the whole node registry.
// Stubbed here so this stays a test of the page rather than of the app graph.
// The stub keeps the signout-button testid, because whether that control is
// rendered to an anonymous visitor is exactly what the last test checks.
jest.mock("../../components/layout/GlobalPageHeader", () => ({
  GlobalPageHeader: () => (
    <div data-testid="global-header">
      <button data-testid="signout-button" type="button">
        Sign out
      </button>
    </div>
  ),
}));

jest.mock("../../components/layout/AppSectionTabs", () => ({
  __esModule: true,
  default: () => <nav data-testid="section-tabs" />,
}));

const mockUser: { current: { name: string } | null } = { current: null };
jest.mock("../../providers/UserProvider", () => ({
  useUserContext: () => ({ user: mockUser.current }),
}));

jest.mock("../../api/monitorApi", () => ({
  fetchMonitor: jest.fn(),
  fetchMonitorStorage: jest.fn(),
  fetchMonitorErrors: jest.fn(),
  postClientError: jest.fn(),
}));

import {
  fetchMonitor,
  fetchMonitorErrors,
  fetchMonitorStorage,
} from "../../api/monitorApi";
import MonitorPage from "../../pages/monitor/MonitorPage";

const monitorPayload = {
  generatedAt: "2026-09-22T14:03:11Z",
  uptimeSeconds: 48213,
  deployment: {
    version: "0.16.114", isolation: "fork", isolationActive: "fork",
    execUserConfigured: true, authEnabled: true, projectsEnabled: true,
    guestLoginAllowed: true, collabEnabled: false, sharedInstallsAllowed: false,
    factoryPublishAllowed: true, saveNodeOutputDefault: false,
    llmProviderConfigured: true, searchToolConfigured: false, env: "prod",
    platform: "macOS-27.0-arm64", pythonVersion: "3.12.1",
  },
  hardware: {
    cpu: { model: "Apple M1", arch: "arm64", logicalCores: 8,
           physicalCores: 8, maxFrequencyMhz: 3200, usagePercent: 12.5 },
    memory: { totalBytes: 17179869184, availableBytes: 8589934592,
              usedPercent: 50, swapTotalBytes: 0, swapUsedBytes: 0 },
    load: { avg1m: 1.5, avg5m: 1.2, avg15m: 0.9, perCore: 0.19 },
    processes: { backendRssBytes: 104857600, sandboxRssBytes: 209715200 },
  },
  execution: {
    backend: {
      total: 1482, ok: 1391, error: 91, python: 1402, javascript: 80,
      inFlight: 2, distinctNodeTypes: 17,
      lastExecutionAt: "2026-09-22T14:02:57Z",
      durations: { windowSize: 200, count: 200, p50Ms: 412, p90Ms: 3180,
                   p99Ms: 21400, maxMs: 58200, buckets: [] },
    },
    sandbox: {
      reachable: true, isolation: "fork", isolationActive: "fork",
      zygoteRunning: true, parallelism: 2, slotsInUse: 1, memoryLimitMb: 4096,
      cpuSecondsLimit: 300, wallTimeoutSeconds: 300, total: 1482,
      isolated: 1482, inProcess: 0, childDeaths: { oom: 7 },
    },
  },
  accounts: {
    total: 14, registered: 13, guest: 1, createdLast24h: 2,
    sessions: { active: 3, seenLast5m: 2, seenLast1h: 5 },
    signIn: { windowMinutes: 60, success: 6, failure: 11, distinctSources: 4 },
  },
  content: {
    projects: { total: 41, createdLast24h: 3, openedLast24h: 9,
                storesWithProjects: 11 },
    datasets: { total: 128, imported: 74, computed: 54, stores: 12,
                totalBytes: 2469606195, largestBytes: 671088640,
                medianBytes: 4194304 },
    execCacheEntries: 302,
  },
};

const storagePayload = {
  computedAt: "2026-09-22T14:02:40Z", ageSeconds: 31, ttlSeconds: 60,
  walkMs: 412, truncated: false,
  userStores: { count: 14, totalBytes: 2469606195, largestBytes: 671088640,
                medianBytes: 8388608, buckets: [] },
  breakdown: [{ area: "users", bytes: 2469606195, files: 3812 }],
  disk: { totalBytes: 494384795648, freeBytes: 120034512896 },
};

const errorsPayload = {
  generatedAt: "2026-09-22T14:03:11Z", serverWindow: 200, clientWindow: 50,
  sandboxWindow: 50, droppedClient: 0,
  errors: [{ at: "2026-09-22T14:02:57Z", source: "node" as const,
             summary: "KeyError: 'population'", detail: "Traceback",
             context: {}, count: 1 }],
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/monitor"]}>
      <MonitorPage />
    </MemoryRouter>
  );
}

describe("MonitorPage", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUser.current = null;
    (fetchMonitor as jest.Mock).mockResolvedValue(monitorPayload);
    (fetchMonitorStorage as jest.Mock).mockResolvedValue(storagePayload);
    (fetchMonitorErrors as jest.Mock).mockResolvedValue(errorsPayload);
  });

  test("renders every section", async () => {
    renderPage();
    for (const heading of [
      "Deployment", "Hardware", "Execution", "Accounts and content",
      "Storage", "Recent errors",
    ]) {
      expect(
        await screen.findByRole("heading", { name: heading })
      ).toBeInTheDocument();
    }
  });

  test("shows the headline numbers from the payload", async () => {
    renderPage();
    expect(await screen.findByText("1482")).toBeInTheDocument();
    expect(screen.getByText("1391 ok · 91 failed")).toBeInTheDocument();
    expect(screen.getByText("14")).toBeInTheDocument();
  });

  test("shows the hardware the instance is running on", async () => {
    renderPage();
    await screen.findByRole("heading", { name: "Hardware" });
    // Scoped to the tile row: the load figures deliberately appear twice, once
    // as a headline tile and once in the load-average table beneath it.
    const tiles = within(screen.getByTestId("monitor-hardware"));

    expect(tiles.getByText(/Apple M1/)).toBeInTheDocument();
    // formatBytes drops the decimal at 10 and above, so 16 GiB is "16 GB".
    expect(tiles.getByText("16 GB")).toBeInTheDocument();
    expect(tiles.getByText("8.0 GB available")).toBeInTheDocument();
    expect(tiles.getByText("1.5")).toBeInTheDocument();
    expect(tiles.getByText("0.19 per core")).toBeInTheDocument();
    expect(tiles.getByText("sandbox 200 MB")).toBeInTheDocument();
  });

  test("shows a last-updated stamp", async () => {
    renderPage();
    expect(await screen.findByText(/Last updated/)).toBeInTheDocument();
  });

  test("pausing stops further polling and the button changes", async () => {
    renderPage();
    await waitFor(() => expect(fetchMonitor).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    expect(await screen.findByRole("button", { name: "Resume" })).toBeInTheDocument();

    const callsWhenPaused = (fetchMonitor as jest.Mock).mock.calls.length;
    await new Promise((r) => setTimeout(r, 50));
    expect((fetchMonitor as jest.Mock).mock.calls.length).toBe(callsWhenPaused);
  });

  test("an unreachable sandbox is stated, and the rest of the page still renders", async () => {
    (fetchMonitor as jest.Mock).mockResolvedValue({
      ...monitorPayload,
      execution: {
        ...monitorPayload.execution,
        sandbox: { ...monitorPayload.execution.sandbox, reachable: false },
      },
    });
    renderPage();
    expect(
      await screen.findByText(/The sandbox is not answering/)
    ).toBeInTheDocument();
    expect(screen.getByText("1482")).toBeInTheDocument();
  });

  test("a failed poll keeps the numbers on screen and shows a banner", async () => {
    renderPage();
    expect(await screen.findByText("1482")).toBeInTheDocument();

    (fetchMonitor as jest.Mock).mockRejectedValue(new Error("backend down"));
    // Force the next tick rather than waiting out the 5s interval.
    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    fireEvent.click(await screen.findByRole("button", { name: "Resume" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      /Could not reach the backend/
    );
    // The stale numbers are still there: an empty page would be worse.
    expect(screen.getByText("1482")).toBeInTheDocument();
  });

  test("the error log is rendered from its own payload", async () => {
    renderPage();
    expect(await screen.findByText("KeyError: 'population'")).toBeInTheDocument();
  });

  describe("chrome", () => {
    test("an anonymous visitor gets no signed-in header", async () => {
      // GlobalPageHeader renders an avatar, a name and a Sign out button
      // whenever auth is on, which on a deployed instance is always. A
      // stranger reading the public monitor must not be shown any of it.
      renderPage();
      await screen.findByRole("heading", { name: "Deployment" });

      expect(screen.queryByTestId("global-header")).not.toBeInTheDocument();
      expect(screen.queryByTestId("signout-button")).not.toBeInTheDocument();
      expect(screen.queryByTestId("section-tabs")).not.toBeInTheDocument();
      // They still get a way back into the app.
      expect(screen.getByAltText("Curio")).toBeInTheDocument();
    });

    test("a signed-in user gets the normal app chrome", async () => {
      mockUser.current = { name: "Alice" };
      renderPage();
      await screen.findByRole("heading", { name: "Deployment" });

      expect(screen.getByTestId("global-header")).toBeInTheDocument();
      expect(screen.getByTestId("section-tabs")).toBeInTheDocument();
    });
  });
});
