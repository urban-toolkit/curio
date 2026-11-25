/**
 * The monitor page as a whole: its two tabs, Status at /monitor and Usage at
 * /monitor/usage, each polling its own routes alone.
 *
 * The charts are mocked: vega does not render under jsdom, and what matters
 * here is that the page composes, polls, pauses and survives a failed request.
 */
import React from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

jest.mock("../../pages/monitor/MonitorCharts", () => ({
  DurationHistogram: () => <div data-testid="duration-chart" />,
  StoreSizeHistogram: () => <div data-testid="store-chart" />,
  // What a line chart was handed: its name, each line's values added up over
  // its points (a point with no value adds nothing), whether its values are
  // durations, whether its y axis is a log one, and the labels of its marks.
  LinesOverTime: ({ label, rows, colors, valueField, durations, logY, marks }: any) => (
    <div
      data-testid="lines-chart"
      aria-label={label}
      data-durations={String(Boolean(durations))}
      data-log={String(Boolean(logY))}
      data-marks={(marks ?? []).map((mark: any) => mark.label).join(",")}
    >
      {colors.domain.map((line: string, index: number) => (
        <span key={line} data-color={colors.range[index]}>
          {`${line}: ${rows
            .filter((row: any) => row.line === line)
            .reduce((sum: number, row: any) => sum + (row[valueField] ?? 0), 0)} over ${
            rows.filter((row: any) => row.line === line).length
          } points`}
        </span>
      ))}
    </div>
  ),
}));

jest.mock("../../components/VersionBadge", () => ({
  __esModule: true,
  default: () => <div data-testid="version-badge" />,
}));

// GlobalPageHeader reaches UserProvider, which boots the whole node registry.
// Stubbed here so this stays a test of the page rather than of the app graph.
// The stub keeps the signout-button testid, because whether that control is
// rendered to an anonymous visitor is exactly what the last test checks. It
// renders its children: the page puts its section links in the bar.
jest.mock("../../components/layout/GlobalPageHeader", () => ({
  GlobalPageHeader: ({ children }: any) => (
    <div data-testid="global-header">
      {children}
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
  fetchMonitorLlm: jest.fn(),
  fetchMonitorOpenFiles: jest.fn(),
  fetchMonitorUsage: jest.fn(),
  postClientError: jest.fn(),
}));

import {
  fetchMonitor,
  fetchMonitorErrors,
  fetchMonitorLlm,
  fetchMonitorOpenFiles,
  fetchMonitorStorage,
  fetchMonitorUsage,
} from "../../api/monitorApi";
import MonitorPage from "../../pages/monitor/MonitorPage";
import { getByTooltip } from "../_support/tooltips";

const monitorPayload = {
  generatedAt: "2026-09-22T14:03:11Z",
  uptimeSeconds: 48213,
  deployment: {
    version: "0.16.114", isolation: "fork", isolationActive: "fork",
    memoryLimit: "cgroup", memoryLimitReason: null,
    execUserConfigured: true, authEnabled: true, projectsEnabled: true,
    guestLoginAllowed: true,
    factoryPublishAllowed: true, saveNodeOutputDefault: false,
    llmProviderConfigured: true, searchToolConfigured: false,
    searchProvider: "api.duckduckgo.com",
    bucketMounts: "passed", bucketMountsProblem: null, env: "prod",
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

const qwen = { model: "qwen3", requests: 2, failed: 0, averageMs: 3500, p95Ms: 4700, firstTokenMs: null,
               tokensPerSecond: null };
const llmPayload = {
  computedAt: "2026-09-22T14:03:11Z", maxDays: 90, ageSeconds: 4, ttlSeconds: 60,
  views: {
    "24h": {
      from: "2026-09-21T14:05:00Z", to: "2026-09-22T14:00:00Z", stepSeconds: 300,
      rows: [
        { at: "2026-09-22T12:35:00Z", model: "gemma4", requests: 4, failed: 1, ms: 4800 },
        { at: "2026-09-22T13:10:00Z", model: "gemma4", requests: 5, failed: 0, ms: 4500 },
        { at: "2026-09-22T13:10:00Z", model: "qwen3", requests: 2, failed: 0, ms: 7000 },
      ],
      models: [
        { model: "gemma4", requests: 9, failed: 1, averageMs: 1033, p95Ms: 2380, firstTokenMs: 310,
          tokensPerSecond: 41.2 },
        qwen,
      ],
      all: { requests: 11, failed: 1, averageMs: 1482, p95Ms: 4100, firstTokenMs: 310, tokensPerSecond: 41.2 },
    },
    "7d": {
      from: "2026-09-15T15:00:00Z", to: "2026-09-22T14:00:00Z", stepSeconds: 3600,
      rows: [
        { at: "2026-09-20T09:00:00Z", model: "gemma4", requests: 1200, failed: 3, ms: 1500000 },
        { at: "2026-09-22T12:00:00Z", model: "gemma4", requests: 4, failed: 1, ms: 4800 },
        { at: "2026-09-22T13:00:00Z", model: "gemma4", requests: 5, failed: 0, ms: 4500 },
        { at: "2026-09-22T13:00:00Z", model: "qwen3", requests: 2, failed: 0, ms: 7000 },
      ],
      models: [
        { model: "gemma4", requests: 1209, failed: 4, averageMs: 1248, p95Ms: 2940, firstTokenMs: 290,
          tokensPerSecond: 38.5 },
        qwen,
      ],
      all: { requests: 1211, failed: 4, averageMs: 1252, p95Ms: 2950, firstTokenMs: 290, tokensPerSecond: 38.5 },
    },
    "90d": {
      from: "2026-06-25T00:00:00Z", to: "2026-09-22T00:00:00Z", stepSeconds: 86400,
      rows: [
        { at: "2026-07-01T00:00:00Z", model: "gemma4", requests: 500, failed: 0, ms: 600000 },
        { at: "2026-09-20T00:00:00Z", model: "gemma4", requests: 1200, failed: 3, ms: 1500000 },
        { at: "2026-09-22T00:00:00Z", model: "gemma4", requests: 9, failed: 1, ms: 9300 },
        { at: "2026-09-22T00:00:00Z", model: "qwen3", requests: 2, failed: 0, ms: 7000 },
      ],
      models: [
        { model: "gemma4", requests: 1709, failed: 4, averageMs: 1235, p95Ms: 2900, firstTokenMs: 295,
          tokensPerSecond: 38.1 },
        qwen,
      ],
      all: { requests: 1711, failed: 4, averageMs: 1238, p95Ms: 2910, firstTokenMs: 295, tokensPerSecond: 38.1 },
    },
  },
};

/** No request in any window: every view empty. */
const noLlm = {
  ...llmPayload,
  views: Object.fromEntries(
    Object.entries(llmPayload.views).map(([name, view]) => [
      name,
      { ...view, rows: [], models: [],
        all: { requests: 0, failed: 0, averageMs: null, p95Ms: null, firstTokenMs: null, tokensPerSecond: null } },
    ])
  ),
};

/** No sample yet, as before the backend's first: the card draws no chart. */
const noOpenFiles = {
  computedAt: "2026-09-22T14:03:11Z", startedAt: "2026-09-22T14:03:00Z",
  maxDays: 90, intervalSeconds: 3600, warnAbovePercent: 80, clearBelowPercent: 70,
  samples: [],
};

const openFilesPayload = {
  ...noOpenFiles,
  samples: [
    { at: "2026-09-22T12:03:05Z", backend: { open: 212, limit: 65536 }, sandbox: { open: 96, limit: 65536 } },
    { at: "2026-09-22T13:03:05Z", backend: { open: 230, limit: 65536 }, sandbox: { open: 101, limit: 65536 } },
  ],
  deploys: [{ at: "2026-09-22T12:30:00Z", version: "0.16.114" }],
};

/** A measure's work over a window: nothing, unless given. */
function work(key: string, count = 0, failed = 0, ms = 0, averageMs: number | null = null,
              p95Ms: number | null = null) {
  return { key, count, failed, ms, averageMs, p95Ms };
}

const usagePayload = {
  computedAt: "2026-09-22T14:03:11Z", maxDays: 90, ageSeconds: 3, ttlSeconds: 60,
  measures: ["node.python", "node.javascript", "run", "turn", "request"],
  sessionsLast24h: { accounts: 12, guests: 30 },
  views: {
    "24h": {
      from: "2026-09-21T14:05:00Z", to: "2026-09-22T14:00:00Z", stepSeconds: 300,
      rows: [
        { at: "2026-09-22T13:10:00Z", key: "node.python", count: 4, failed: 1, ms: 4800, p95Ms: 2380 },
        { at: "2026-09-22T13:10:00Z", key: "node.javascript", count: 1, failed: 0, ms: 300, p95Ms: 475 },
        { at: "2026-09-22T13:10:00Z", key: "request", count: 200, failed: 0, ms: 9000, p95Ms: 120 },
        { at: "2026-09-22T13:15:00Z", key: "turn", count: 2, failed: 0, ms: 30000, p95Ms: 29000 },
      ],
      measures: [
        work("node.python", 4, 1, 4800, 1200, 2380),
        work("node.javascript", 1, 0, 300, 300, 475),
        work("run"),
        work("turn", 2, 0, 30000, 15000, 29000),
        work("request", 200, 0, 9000, 45, 120),
      ],
      sessions: [{ at: "2026-09-22T13:10:00Z", accounts: 3, guests: 7 }],
      deploys: [{ at: "2026-09-22T09:30:12Z", version: "0.16.114" }],
    },
    "7d": {
      from: "2026-09-15T15:00:00Z", to: "2026-09-22T14:00:00Z", stepSeconds: 3600,
      rows: [
        { at: "2026-09-20T09:00:00Z", key: "node.python", count: 1200, failed: 3, ms: 1500000, p95Ms: 4100 },
        { at: "2026-09-22T13:00:00Z", key: "node.python", count: 4, failed: 1, ms: 4800, p95Ms: 2380 },
        { at: "2026-09-22T13:00:00Z", key: "run", count: 2, failed: 1, ms: 9000, p95Ms: 7000 },
        { at: "2026-09-22T13:00:00Z", key: "request", count: 200, failed: 0, ms: 9000, p95Ms: 120 },
      ],
      measures: [
        work("node.python", 1204, 4, 1504800, 1248, 4100),
        work("node.javascript"),
        work("run", 2, 1, 9000, 4500, 7000),
        work("turn"),
        work("request", 200, 0, 9000, 45, 120),
      ],
      sessions: [
        { at: "2026-09-20T09:00:00Z", accounts: 40, guests: 2 },
        { at: "2026-09-22T13:00:00Z", accounts: 5, guests: 9 },
      ],
      deploys: [
        { at: "2026-09-18T10:00:00Z", version: "0.16.110" },
        { at: "2026-09-22T09:30:12Z", version: "0.16.114" },
      ],
    },
    "90d": {
      from: "2026-06-25T00:00:00Z", to: "2026-09-22T00:00:00Z", stepSeconds: 86400,
      rows: [
        { at: "2026-07-01T00:00:00Z", key: "node.python", count: 500, failed: 0, ms: 600000, p95Ms: 2000 },
        { at: "2026-09-20T00:00:00Z", key: "node.python", count: 1200, failed: 3, ms: 1500000, p95Ms: 4100 },
      ],
      measures: [
        work("node.python", 1700, 3, 2100000, 1235, 4000),
        work("node.javascript"),
        work("run"),
        work("turn"),
        work("request"),
      ],
      sessions: [{ at: "2026-09-22T00:00:00Z", accounts: 20, guests: 40 }],
      deploys: [
        { at: "2026-07-02T08:00:00Z", version: "0.16.90" },
        { at: "2026-09-18T10:00:00Z", version: "0.16.110" },
        { at: "2026-09-22T09:30:12Z", version: "0.16.114" },
      ],
    },
  },
};

/** The page's path, as the page's URL holds it. */
function Where() {
  const location = useLocation();
  return <p data-testid="where">{location.pathname}</p>;
}

function renderPage(path = "/monitor") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/monitor/:tab?" element={<><MonitorPage /><Where /></>} />
      </Routes>
    </MemoryRouter>
  );
}

/** The chart a page shows under *label*. */
const chartNamed = (label: string) => screen.getByLabelText(label);

describe("MonitorPage", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUser.current = null;
    (fetchMonitor as jest.Mock).mockResolvedValue(monitorPayload);
    (fetchMonitorStorage as jest.Mock).mockResolvedValue(storagePayload);
    (fetchMonitorErrors as jest.Mock).mockResolvedValue(errorsPayload);
    (fetchMonitorLlm as jest.Mock).mockResolvedValue(llmPayload);
    (fetchMonitorOpenFiles as jest.Mock).mockResolvedValue(noOpenFiles);
    (fetchMonitorUsage as jest.Mock).mockResolvedValue(usagePayload);
  });

  test("the Status tab renders every section of the deployment as it is now", async () => {
    renderPage();
    for (const heading of [
      "Deployment", "Hardware", "Execution", "Accounts and content", "Storage", "Recent errors",
    ]) {
      expect(
        await screen.findByRole("heading", { name: heading })
      ).toBeInTheDocument();
    }
    // LLM performance is the Usage tab's.
    expect(screen.queryByRole("heading", { name: "LLM performance" })).not.toBeInTheDocument();
  });

  test("the Usage tab renders the activity and the LLM performance", async () => {
    renderPage("/monitor/usage");
    for (const heading of [
      "Activity", "Sessions seen", "Count", "Average time", "95th percentile time", "By measure",
      "LLM performance", "Average response time", "By model",
    ]) {
      expect(
        await screen.findByRole("heading", { name: heading })
      ).toBeInTheDocument();
    }
    expect(screen.queryByRole("heading", { name: "Deployment" })).not.toBeInTheDocument();
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

  test("the hardware section charts each server's open files against their limit", async () => {
    (fetchMonitorOpenFiles as jest.Mock).mockResolvedValue(openFilesPayload);
    renderPage();
    const hardware = (await screen.findByRole("heading", { name: "Hardware" })).closest("section") as HTMLElement;
    expect(within(hardware).getByRole("heading", { name: "Open files" })).toBeInTheDocument();

    const chart = await within(hardware).findByTestId("lines-chart");
    expect(chart).toHaveAttribute(
      "aria-label", "Open files of the backend and the sandbox, every hour, against their limits"
    );
    expect(within(chart).getByText("Backend: 442 over 2 points")).toBeInTheDocument();
    expect(within(chart).getByText("Sandbox: 197 over 2 points")).toBeInTheDocument();
    expect(within(chart).getByText("Limit: 131072 over 2 points")).toBeInTheDocument();
    // The deploy between the two samples is marked, with its version.
    expect(chart).toHaveAttribute("data-marks", "0.16.114");
    // Read once as the page opens; the next read is 10 minutes later.
    expect(fetchMonitorOpenFiles).toHaveBeenCalledTimes(1);
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

  test.each([
    ["passed", null, "on, self-test passed"],
    ["pending", null, "on, self-test running"],
    [
      "unavailable",
      "the test mount did not reach this container",
      "unavailable: the test mount did not reach this container",
    ],
    ["none", null, "none"],
  ])("the deployment says how the bucket mount service's self-test went: %s", async (state, problem, text) => {
    (fetchMonitor as jest.Mock).mockResolvedValue({
      ...monitorPayload,
      deployment: { ...monitorPayload.deployment, bucketMounts: state, bucketMountsProblem: problem },
    });
    renderPage();
    const deployment = await screen.findByTestId("monitor-deployment");
    const label = await within(deployment).findByText("Bucket mounts");
    // The chip shows "…" until the payload lands.
    await waitFor(() => expect(label.nextElementSibling?.textContent).toBe(text));
  });

  test.each([
    ["cgroup", null, "cgroup limit"],
    [
      "address space",
      "the container's cgroups are read-only (Docker's writable-cgroups option)",
      "address-space cap: the container's cgroups are read-only (Docker's writable-cgroups option)",
    ],
    ["none", null, "none"],
  ])("the deployment names the memory limit isolated nodes run under: %s", async (limit, reason, text) => {
    (fetchMonitor as jest.Mock).mockResolvedValue({
      ...monitorPayload,
      deployment: { ...monitorPayload.deployment, memoryLimit: limit, memoryLimitReason: reason },
    });
    renderPage();
    const deployment = await screen.findByTestId("monitor-deployment");
    const label = await within(deployment).findByText("Node memory");
    // The chip shows "…" until the payload lands.
    await waitFor(() => expect(label.nextElementSibling?.textContent).toBe(text));
  });

  describe("the tabs", () => {
    test("/monitor is the Status tab and /monitor/usage the Usage tab, and a click on a tab goes to its path", async () => {
      renderPage();
      expect(await screen.findByRole("tab", { name: "Status" })).toHaveAttribute("aria-selected", "true");
      expect(screen.getByRole("tab", { name: "Usage" })).toHaveAttribute("aria-selected", "false");
      expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", "monitor-tab-status");
      expect(screen.getByRole("tablist", { name: "Monitor" })).toBeInTheDocument();

      fireEvent.click(screen.getByRole("tab", { name: "Usage" }));
      expect(screen.getByTestId("where").textContent).toBe("/monitor/usage");
      expect(screen.getByRole("tab", { name: "Usage" })).toHaveAttribute("aria-selected", "true");
      expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", "monitor-tab-usage");
      expect(await screen.findByRole("heading", { name: "Activity" })).toBeInTheDocument();
      expect(screen.queryByRole("heading", { name: "Deployment" })).not.toBeInTheDocument();

      fireEvent.click(screen.getByRole("tab", { name: "Status" }));
      expect(screen.getByTestId("where").textContent).toBe("/monitor");
      expect(await screen.findByRole("heading", { name: "Deployment" })).toBeInTheDocument();
    });

    test("the arrow keys move between the tabs, as API Settings' do", async () => {
      renderPage("/monitor/usage");
      const usage = await screen.findByRole("tab", { name: "Usage" });
      expect(usage).toHaveAttribute("tabIndex", "0");
      expect(screen.getByRole("tab", { name: "Status" })).toHaveAttribute("tabIndex", "-1");
      fireEvent.keyDown(usage, { key: "ArrowRight" });
      expect(screen.getByTestId("where").textContent).toBe("/monitor");
      expect(screen.getByRole("tab", { name: "Status" })).toHaveFocus();
      fireEvent.keyDown(screen.getByRole("tab", { name: "Status" }), { key: "ArrowLeft" });
      expect(screen.getByTestId("where").textContent).toBe("/monitor/usage");
      expect(screen.getByRole("tab", { name: "Usage" })).toHaveFocus();
    });

    test("a path that names no tab opens Status", async () => {
      renderPage("/monitor/nope");
      expect(await screen.findByRole("tab", { name: "Status" })).toHaveAttribute("aria-selected", "true");
      expect(screen.getByTestId("where").textContent).toBe("/monitor");
    });

    test("only the shown tab's routes poll, and showing a tab reads its routes at once", async () => {
      jest.useFakeTimers();
      try {
        renderPage();
        expect(await screen.findByText("1482")).toBeInTheDocument();
        const status = [fetchMonitor, fetchMonitorErrors, fetchMonitorStorage, fetchMonitorOpenFiles] as jest.Mock[];
        const usage = [fetchMonitorUsage, fetchMonitorLlm] as jest.Mock[];
        const calls = (fetchers: jest.Mock[]) => fetchers.map((each) => each.mock.calls.length);
        expect(calls(status)).toEqual([1, 1, 1, 1]);
        expect(calls(usage)).toEqual([0, 0]);
        // The monitor's and the errors' routes again 5 seconds later.
        await act(async () => {
          jest.advanceTimersByTime(5000);
        });
        expect(calls(status)).toEqual([2, 2, 1, 1]);

        fireEvent.click(screen.getByRole("tab", { name: "Usage" }));
        expect(await screen.findByTestId("monitor-usage-measures")).toBeInTheDocument();
        expect(calls(usage)).toEqual([1, 1]);
        const shown = calls(status);
        await act(async () => {
          jest.advanceTimersByTime(60_000);
        });
        // A minute later: the Usage routes read again, the Status routes not at all.
        expect(calls(usage)).toEqual([2, 2]);
        expect(calls(status)).toEqual(shown);
      } finally {
        jest.useRealTimers();
      }
    });

    test("opened on Usage, the page asks no route of the Status tab", async () => {
      renderPage("/monitor/usage");
      expect(await screen.findByTestId("monitor-usage-measures")).toBeInTheDocument();
      await waitFor(() => expect(fetchMonitorLlm).toHaveBeenCalledTimes(1));
      expect(fetchMonitorUsage).toHaveBeenCalledTimes(1);
      for (const fetcher of [fetchMonitor, fetchMonitorErrors, fetchMonitorStorage, fetchMonitorOpenFiles]) {
        expect(fetcher).not.toHaveBeenCalled();
      }
    });

    test("the toolbar speaks for the tab shown", async () => {
      (fetchMonitorUsage as jest.Mock).mockRejectedValue(new Error("backend down"));
      renderPage("/monitor/usage");
      expect(await screen.findByRole("status")).toHaveTextContent(/Could not reach the backend/);
      // The Status tab's route answered nothing yet, as it was never asked.
      expect(fetchMonitor).not.toHaveBeenCalled();
    });
  });

  describe("Usage", () => {
    test("the tiles give the last 24 hours, node runs of both languages as one, whichever window is shown", async () => {
      renderPage("/monitor/usage");
      const tiles = within(await screen.findByTestId("monitor-usage"));
      const shown = async () => {
        expect(await tiles.findByText("42")).toBeInTheDocument();
        expect(tiles.getByText("12 accounts · 30 guests")).toBeInTheDocument();
        // 5 node runs, 4 of Python and 1 of JavaScript, 5.1 s in all; one failed.
        expect(tiles.getByText("5")).toBeInTheDocument();
        expect(tiles.getByText("average 1.0 s · 1 failed")).toBeInTheDocument();
        expect(tiles.getByText("average 15.0 s")).toBeInTheDocument();
        expect(tiles.getByText("average n/a")).toBeInTheDocument();
        expect(tiles.getByText("average 45 ms")).toBeInTheDocument();
        expect(tiles.getAllByText(/24 hours$/).map((label) => label.textContent)).toEqual([
          "Sessions seen, 24 hours", "Node runs, 24 hours", "Agent turns, 24 hours", "Run All runs, 24 hours",
          "Requests, 24 hours",
        ]);
      };
      await shown();
      fireEvent.click(screen.getByRole("button", { name: "90 days" }));
      await shown();
    });

    test("the By measure table gives each measure's work over the 7 days, shown first, then the window chosen",
      async () => {
        renderPage("/monitor/usage");
        const table = await screen.findByTestId("monitor-usage-measures");
        const row = (key: string) => table.querySelector(`tr[data-measure="${key}"]`) as HTMLElement;
        await waitFor(() => expect(within(row("node.python")).getByText("1.2K")).toBeInTheDocument());
        expect(within(table).getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual([
          "Measure", "Count", "Failed", "Average", "95th percentile",
        ]);
        expect([...table.querySelectorAll("tbody tr")].map((each) => each.querySelector("td")?.textContent)).toEqual([
          "Python node runs", "JavaScript node runs", "Run All runs", "Agent turns", "Requests",
        ]);
        const python = row("node.python");
        expect(within(python).getByText("4")).toBeInTheDocument();
        expect(within(python).getByText("1.2 s")).toBeInTheDocument();
        expect(within(python).getByText("4.1 s")).toBeInTheDocument();
        // The exact numbers are the cells' Curio tooltips, never a title.
        expect(getByTooltip(python, "1,204 runs")).toBeInTheDocument();
        expect(getByTooltip(python, "4 of 1,204 runs failed")).toBeInTheDocument();
        expect(getByTooltip(python, "1,248 ms")).toBeInTheDocument();
        expect(getByTooltip(python, "4,100 ms")).toBeInTheDocument();
        expect(table.querySelector("[title]")).toBeNull();
        // A measure that counted nothing reads 0, and n/a for its times.
        expect(within(row("turn")).getAllByText("0")).toHaveLength(2);
        expect(within(row("turn")).getAllByText("n/a")).toHaveLength(2);
        expect(within(row("run")).getByText("4.5 s")).toBeInTheDocument();
        expect(getByTooltip(row("request"), "200 requests")).toBeInTheDocument();

        fireEvent.click(screen.getByRole("button", { name: "24 hours" }));
        expect(within(row("node.python")).getByText("2.4 s")).toBeInTheDocument();
        expect(within(row("turn")).getByText("15.0 s")).toBeInTheDocument();
        expect(getByTooltip(row("turn"), "2 turns")).toBeInTheDocument();
      });

    test("each chart draws a line per measure that counted something, the times on a log scale", async () => {
      renderPage("/monitor/usage");
      const count = await screen.findByLabelText("Count by measure, last 7 days");
      expect(within(count).getByText("Python node runs: 1204 over 168 points")).toBeInTheDocument();
      expect(within(count).getByText("Run All runs: 2 over 168 points")).toBeInTheDocument();
      expect(within(count).getByText("Requests: 200 over 168 points")).toBeInTheDocument();
      expect(within(count).queryByText(/Agent turns|JavaScript node runs/)).not.toBeInTheDocument();
      expect([count.getAttribute("data-log"), count.getAttribute("data-durations")]).toEqual(["true", "false"]);

      // Each step's average: 1,250 ms then 1,200 ms of Python runs, in the 168 hours.
      const average = chartNamed("Average time by measure, last 7 days");
      expect(within(average).getByText("Python node runs: 2450 over 168 points")).toBeInTheDocument();
      expect(within(average).getByText("Requests: 45 over 168 points")).toBeInTheDocument();
      expect([average.getAttribute("data-log"), average.getAttribute("data-durations")]).toEqual(["true", "true"]);
      const p95 = chartNamed("95th percentile time by measure, last 7 days");
      expect(within(p95).getByText("Python node runs: 6480 over 168 points")).toBeInTheDocument();
      expect(within(p95).getByText("Run All runs: 7000 over 168 points")).toBeInTheDocument();

      const sessions = chartNamed("Sessions seen, accounts and guests, last 7 days");
      expect(within(sessions).getByText("Accounts: 45 over 168 points")).toBeInTheDocument();
      expect(within(sessions).getByText("Guests: 11 over 168 points")).toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: "24 hours" }));
      const day = chartNamed("Count by measure, last 24 hours");
      expect(within(day).getByText("Agent turns: 2 over 288 points")).toBeInTheDocument();
      expect(within(day).getByText("JavaScript node runs: 1 over 288 points")).toBeInTheDocument();
    });

    test("the charts of 24 hours and 7 days mark each deploy with its version, those of 90 days none", async () => {
      renderPage("/monitor/usage");
      await screen.findByLabelText("Count by measure, last 7 days");
      const week = [
        "Sessions seen, accounts and guests, last 7 days", "Count by measure, last 7 days",
        "Average time by measure, last 7 days", "95th percentile time by measure, last 7 days",
        "Average response time by model, last 7 days",
      ];
      for (const label of week) {
        expect(chartNamed(label)).toHaveAttribute("data-marks", "0.16.110,0.16.114");
      }
      fireEvent.click(screen.getByRole("button", { name: "24 hours" }));
      expect(chartNamed("Count by measure, last 24 hours")).toHaveAttribute("data-marks", "0.16.114");
      expect(chartNamed("Average response time by model, last 24 hours")).toHaveAttribute("data-marks", "0.16.114");
      fireEvent.click(screen.getByRole("button", { name: "90 days" }));
      expect(chartNamed("Count by measure, last 90 days")).toHaveAttribute("data-marks", "");
      expect(chartNamed("Sessions seen, accounts and guests, last 90 days")).toHaveAttribute("data-marks", "");
      expect(chartNamed("Average response time by model, last 90 days")).toHaveAttribute("data-marks", "");
    });

    test("a window with nothing counted and no sessions sample says so, and draws no chart of them", async () => {
      const empty = {
        ...usagePayload,
        views: Object.fromEntries(
          Object.entries(usagePayload.views).map(([name, view]) => [
            name, { ...view, rows: [], sessions: [], measures: view.measures.map((each) => work(each.key)) },
          ])
        ),
      };
      (fetchMonitorUsage as jest.Mock).mockResolvedValue(empty);
      (fetchMonitorLlm as jest.Mock).mockResolvedValue(noLlm);
      renderPage("/monitor/usage");
      expect(await screen.findAllByText("Nothing counted in the last 7 days.")).toHaveLength(3);
      expect(screen.getByText(/^No sample in the last 7 days/)).toBeInTheDocument();
      expect(screen.queryByTestId("lines-chart")).not.toBeInTheDocument();
    });

    test("the table says what each measure counts, and that the days are kept across restarts", async () => {
      renderPage("/monitor/usage");
      expect(await screen.findByTestId("monitor-usage-kept")).toHaveTextContent(
        /^The last 90 days are kept across restarts\. A node run is a node's code run by Play or by a run on the server/
      );
    });
  });

  describe("LLM performance", () => {
    test("the table names each model and its performance over the 7 days, shown first", async () => {
      renderPage("/monitor/usage");
      const table = await screen.findByTestId("monitor-llm-models");
      const gemma = (await within(table).findByText("gemma4")).closest("tr") as HTMLElement;
      expect(within(gemma).getByText("1.2K")).toBeInTheDocument();
      expect(within(gemma).getByText("4")).toBeInTheDocument();
      expect(within(gemma).getByText("1.2 s")).toBeInTheDocument();
      expect(within(gemma).getByText("2.9 s")).toBeInTheDocument();
      expect(within(gemma).getByText("290 ms")).toBeInTheDocument();
      expect(within(gemma).getByText("38.5")).toBeInTheDocument();
      // The exact numbers are the cells' Curio tooltips, never a title.
      expect(getByTooltip(gemma, "1,209 requests")).toBeInTheDocument();
      expect(getByTooltip(gemma, "4 of 1,209 requests failed")).toBeInTheDocument();
      expect(getByTooltip(gemma, "1,248 ms")).toBeInTheDocument();
      expect(getByTooltip(gemma, "2,940 ms")).toBeInTheDocument();
      expect(gemma.querySelector("[title]")).toBeNull();

      // What no request gave reads n/a: qwen3's requests were not streamed,
      // and its provider reported no output tokens.
      const other = within(table).getByText("qwen3").closest("tr") as HTMLElement;
      expect(within(other).getByText("3.5 s")).toBeInTheDocument();
      expect(within(other).getByText("4.7 s")).toBeInTheDocument();
      expect(within(other).getAllByText("n/a")).toHaveLength(2);

      // Its columns, and nothing of where a model ran.
      expect(within(table).getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual([
        "Model", "Requests", "Failed", "Average", "95th percentile", "First token", "Tokens per second",
      ]);
      const section = screen.getByTestId("monitor-llm-performance");
      expect(within(section).queryByText(/endpoint|own key|\(curio\)/i)).not.toBeInTheDocument();
    });

    test("the tab's switch shows the 24 hours or the 90 days in the chart and the table", async () => {
      renderPage("/monitor/usage");
      // The section's own chart: the tab's charts of its activity draw beside it.
      const section = await screen.findByTestId("monitor-llm-performance");
      const week = await within(section).findByTestId("lines-chart");
      expect(screen.getByRole("button", { name: "7 days" })).toHaveAttribute("aria-pressed", "true");
      expect(week).toHaveAttribute("aria-label", "Average response time by model, last 7 days");
      expect(week).toHaveAttribute("data-durations", "true");
      // Each line's average response time in every hour, an idle one adding nothing.
      expect(within(week).getByText("gemma4: 3350 over 168 points")).toBeInTheDocument();
      expect(within(week).getByText("qwen3: 3500 over 168 points")).toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: "24 hours" }));
      expect(screen.getByRole("button", { name: "24 hours" })).toHaveAttribute("aria-pressed", "true");
      expect(screen.getByRole("button", { name: "7 days" })).toHaveAttribute("aria-pressed", "false");
      const day = within(section).getByTestId("lines-chart");
      expect(day).toHaveAttribute("aria-label", "Average response time by model, last 24 hours");
      expect(within(day).getByText("gemma4: 2100 over 288 points")).toBeInTheDocument();
      const gemmaDay = within(screen.getByTestId("monitor-llm-models")).getByText("gemma4").closest("tr") as HTMLElement;
      expect(within(gemmaDay).getByText("9")).toBeInTheDocument();
      expect(within(gemmaDay).getByText("1.0 s")).toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: "90 days" }));
      const quarter = within(section).getByTestId("lines-chart");
      expect(quarter).toHaveAttribute("aria-label", "Average response time by model, last 90 days");
      expect(within(quarter).getByText("gemma4: 3483 over 90 points")).toBeInTheDocument();
      const gemmaQuarter = within(screen.getByTestId("monitor-llm-models")).getByText("gemma4")
        .closest("tr") as HTMLElement;
      expect(within(gemmaQuarter).getByText("1.7K")).toBeInTheDocument();
    });

    test("the tiles give the last 24 hours, whichever window the switch shows", async () => {
      renderPage("/monitor/usage");
      const section = await screen.findByTestId("monitor-llm-performance");
      const tiles = async () => {
        expect(await within(section).findByText("11")).toBeInTheDocument();
        expect(within(section).getByText("1 failed · 1.2K in 7 days")).toBeInTheDocument();
        expect(within(section).getByText("1.5 s")).toBeInTheDocument();
        expect(within(section).getByText("95th percentile 4.1 s")).toBeInTheDocument();
        expect(within(section).getByText("41.2")).toBeInTheDocument();
        expect(within(section).getByText("first token in 310 ms")).toBeInTheDocument();
      };
      await tiles();
      // The tab's switch, which the section follows.
      fireEvent.click(screen.getByRole("button", { name: "90 days" }));
      await tiles();
    });

    test("an instance no model answered says so in the window shown, and draws no chart", async () => {
      (fetchMonitorLlm as jest.Mock).mockResolvedValue(noLlm);
      renderPage("/monitor/usage");
      const section = await screen.findByTestId("monitor-llm-performance");
      expect(await within(section).findAllByText("No LLM requests in the last 7 days.")).toHaveLength(2);
      expect(within(section).queryByTestId("lines-chart")).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "90 days" }));
      expect(within(section).getAllByText("No LLM requests in the last 90 days.")).toHaveLength(2);
      expect(within(section).queryByTestId("lines-chart")).not.toBeInTheDocument();
    });

    test("the table says its models are this Curio's own, the last 90 days, kept across restarts", async () => {
      renderPage("/monitor/usage");
      expect(await screen.findByTestId("monitor-llm-kept")).toHaveTextContent(
        "This Curio's own models, the last 90 days, kept across restarts. A request on a key a user set for " +
          "their own is not counted."
      );
      expect(screen.queryByText(/since the backend started/i)).not.toBeInTheDocument();
    });
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
      // In the bar, not in a band of its own under it.
      expect(screen.getByTestId("global-header")).toContainElement(screen.getByTestId("section-tabs"));
    });
  });
});
