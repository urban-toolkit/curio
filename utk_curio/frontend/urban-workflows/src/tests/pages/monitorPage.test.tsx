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
  // What a line chart was handed: its name, each line's values added up over
  // its points (a point with no value adds nothing), and whether its values
  // are durations.
  LinesOverTime: ({ label, rows, colors, valueField, durations }: any) => (
    <div data-testid="lines-chart" aria-label={label} data-durations={String(Boolean(durations))}>
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
  postClientError: jest.fn(),
}));

import {
  fetchMonitor,
  fetchMonitorErrors,
  fetchMonitorLlm,
  fetchMonitorOpenFiles,
  fetchMonitorStorage,
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
    (fetchMonitorLlm as jest.Mock).mockResolvedValue(llmPayload);
    (fetchMonitorOpenFiles as jest.Mock).mockResolvedValue(noOpenFiles);
  });

  test("renders every section", async () => {
    renderPage();
    for (const heading of [
      "Deployment", "Hardware", "Execution", "LLM performance", "Accounts and content",
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

  describe("LLM performance", () => {
    test("the table names each model and its performance over the 7 days, shown first", async () => {
      renderPage();
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

    test("the switch shows the 24 hours or the 90 days in the chart and the table", async () => {
      renderPage();
      const week = await screen.findByTestId("lines-chart");
      expect(screen.getByRole("button", { name: "7 days" })).toHaveAttribute("aria-pressed", "true");
      expect(week).toHaveAttribute("aria-label", "Average response time by model, last 7 days");
      expect(week).toHaveAttribute("data-durations", "true");
      // Each line's average response time in every hour, an idle one adding nothing.
      expect(within(week).getByText("gemma4: 3350 over 168 points")).toBeInTheDocument();
      expect(within(week).getByText("qwen3: 3500 over 168 points")).toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: "24 hours" }));
      expect(screen.getByRole("button", { name: "24 hours" })).toHaveAttribute("aria-pressed", "true");
      expect(screen.getByRole("button", { name: "7 days" })).toHaveAttribute("aria-pressed", "false");
      const day = screen.getByTestId("lines-chart");
      expect(day).toHaveAttribute("aria-label", "Average response time by model, last 24 hours");
      expect(within(day).getByText("gemma4: 2100 over 288 points")).toBeInTheDocument();
      const gemmaDay = within(screen.getByTestId("monitor-llm-models")).getByText("gemma4").closest("tr") as HTMLElement;
      expect(within(gemmaDay).getByText("9")).toBeInTheDocument();
      expect(within(gemmaDay).getByText("1.0 s")).toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: "90 days" }));
      const quarter = screen.getByTestId("lines-chart");
      expect(quarter).toHaveAttribute("aria-label", "Average response time by model, last 90 days");
      expect(within(quarter).getByText("gemma4: 3483 over 90 points")).toBeInTheDocument();
      const gemmaQuarter = within(screen.getByTestId("monitor-llm-models")).getByText("gemma4")
        .closest("tr") as HTMLElement;
      expect(within(gemmaQuarter).getByText("1.7K")).toBeInTheDocument();
    });

    test("the tiles give the last 24 hours, whichever window the switch shows", async () => {
      renderPage();
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
      fireEvent.click(within(section).getByRole("button", { name: "90 days" }));
      await tiles();
    });

    test("an instance no model answered says so in the window shown, and draws no chart", async () => {
      (fetchMonitorLlm as jest.Mock).mockResolvedValue(noLlm);
      renderPage();
      expect(await screen.findAllByText("No LLM requests in the last 7 days.")).toHaveLength(2);
      expect(screen.queryByTestId("lines-chart")).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "90 days" }));
      expect(screen.getAllByText("No LLM requests in the last 90 days.")).toHaveLength(2);
      expect(screen.queryByTestId("lines-chart")).not.toBeInTheDocument();
    });

    test("the table says its models are this Curio's own, the last 90 days, kept across restarts", async () => {
      renderPage();
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
