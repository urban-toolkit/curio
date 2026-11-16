/**
 * The monitor of a backend that runs as several processes (`curio.py start
 * --backend-processes N`). The home process merges every process's part, and
 * each payload's `backendProcesses` says which processes answered. A process
 * that did not answer is named in one line over the sections, and with several
 * processes the Open files card says that its backend line is the busiest
 * process. A backend of one process sends no `backendProcesses`, and neither
 * line shows.
 *
 * The charts are mocked: vega does not render under jsdom.
 */
import React from "react";
import { render, screen } from "@testing-library/react";

jest.mock("../../pages/monitor/MonitorCharts", () => ({
  DurationHistogram: () => <div data-testid="duration-chart" />,
  StoreSizeHistogram: () => <div data-testid="store-chart" />,
  LinesOverTime: () => <div data-testid="lines-chart" />,
}));

jest.mock("../../api/monitorApi", () => ({
  fetchMonitor: jest.fn(),
  fetchMonitorStorage: jest.fn(),
  fetchMonitorErrors: jest.fn(),
  fetchMonitorLlm: jest.fn(),
  fetchMonitorOpenFiles: jest.fn(),
  postClientError: jest.fn(),
}));

import type { MonitorOpenFilesPayload } from "../../api/monitorApi";
import {
  fetchMonitor,
  fetchMonitorErrors,
  fetchMonitorLlm,
  fetchMonitorOpenFiles,
  fetchMonitorStorage,
} from "../../api/monitorApi";
import MonitorContent from "../../pages/monitor/MonitorContent";
import { OpenFilesSection } from "../../pages/monitor/OpenFilesSection";

const monitorPayload = {
  generatedAt: "2026-11-06T15:20:07Z",
  uptimeSeconds: 48213,
  deployment: {
    version: "0.17.286", isolation: "fork", isolationActive: "fork",
    memoryLimit: "cgroup", memoryLimitReason: null,
    execUserConfigured: true, authEnabled: true, projectsEnabled: true,
    guestLoginAllowed: true, factoryPublishAllowed: true, saveNodeOutputDefault: false,
    llmProviderConfigured: true, searchToolConfigured: false,
    bucketMounts: "none", bucketMountsProblem: null, env: "prod",
    platform: "Linux-7.0-x86_64", pythonVersion: "3.12.1",
  },
  hardware: {
    cpu: { model: "AMD EPYC", arch: "x86_64", logicalCores: 64,
           physicalCores: 32, maxFrequencyMhz: 3200, usagePercent: 12.5 },
    memory: { totalBytes: 17179869184, availableBytes: 8589934592,
              usedPercent: 50, swapTotalBytes: 0, swapUsedBytes: 0 },
    load: { avg1m: 1.5, avg5m: 1.2, avg15m: 0.9, perCore: 0.02 },
    processes: { backendRssBytes: 104857600, sandboxRssBytes: 209715200 },
  },
  execution: {
    backend: {
      total: 1482, ok: 1391, error: 91, python: 1402, javascript: 80,
      inFlight: 2, distinctNodeTypes: 17, lastExecutionAt: "2026-11-06T15:19:57Z",
      durations: { windowSize: 200, count: 200, p50Ms: 412, p90Ms: 3180,
                   p99Ms: 21400, maxMs: 58200, buckets: [] },
    },
    sandbox: {
      reachable: true, isolation: "fork", isolationActive: "fork",
      zygoteRunning: true, parallelism: 2, slotsInUse: 1, memoryLimitMb: 4096,
      cpuSecondsLimit: 300, wallTimeoutSeconds: 300, total: 1482,
      isolated: 1482, inProcess: 0, childDeaths: {},
    },
  },
  accounts: {
    total: 14, registered: 13, guest: 1, createdLast24h: 2,
    sessions: { active: 3, seenLast5m: 2, seenLast1h: 5 },
    signIn: { windowMinutes: 60, success: 6, failure: 11, distinctSources: 4 },
  },
  content: {
    projects: { total: 41, createdLast24h: 3, openedLast24h: 9, storesWithProjects: 11 },
    datasets: { total: 128, imported: 74, computed: 54, stores: 12,
                totalBytes: 2469606195, largestBytes: 671088640, medianBytes: 4194304 },
    execCacheEntries: 302,
  },
};

const storagePayload = {
  computedAt: "2026-11-06T15:19:40Z", ageSeconds: 27, ttlSeconds: 60, walkMs: 412, truncated: false,
  userStores: { count: 14, totalBytes: 2469606195, largestBytes: 671088640, medianBytes: 8388608, buckets: [] },
  breakdown: [{ area: "users", bytes: 2469606195, files: 3812 }],
  disk: { totalBytes: 494384795648, freeBytes: 120034512896 },
};

const errorsPayload = {
  generatedAt: "2026-11-06T15:20:07Z", serverWindow: 200, clientWindow: 50, sandboxWindow: 50,
  droppedClient: 0, errors: [],
};

const llmPayload = {
  computedAt: "2026-11-06T15:20:07Z", startedAt: "2026-11-06T08:40:00Z", maxDays: 90,
  ageSeconds: 0, ttlSeconds: 60, hourlyFrom: "2026-10-30T16:00:00Z", hourlyTo: "2026-11-06T15:00:00Z",
  hourly: [], models: [],
};

const openFilesPayload = {
  computedAt: "2026-11-06T16:25:00Z", startedAt: "2026-11-06T15:20:00Z", maxDays: 90,
  intervalSeconds: 3600, warnAbovePercent: 80, clearBelowPercent: 70,
  samples: [
    { at: "2026-11-06T15:25:07Z", backend: { open: 5000, limit: 65536 }, sandbox: { open: 96, limit: 65536 } },
    { at: "2026-11-06T16:20:07Z", backend: { open: 900, limit: 1024 }, sandbox: { open: 101, limit: 65536 } },
  ],
};

/** What a payload of a start of *count* processes says, *missing* those that did not answer. */
function processes(count: number, missing: number[] = []) {
  const answered = Array.from({ length: count }, (_, number) => number).filter((number) => !missing.includes(number));
  return { backendProcesses: { count, answered, missing } };
}

/** Every payload as a start of the processes *each* says. */
function serve(each: {
  monitor?: object; errors?: object; llm?: object; openFiles?: object;
}) {
  (fetchMonitor as jest.Mock).mockResolvedValue({ ...monitorPayload, ...each.monitor });
  (fetchMonitorStorage as jest.Mock).mockResolvedValue(storagePayload);
  (fetchMonitorErrors as jest.Mock).mockResolvedValue({ ...errorsPayload, ...each.errors });
  (fetchMonitorLlm as jest.Mock).mockResolvedValue({ ...llmPayload, ...each.llm });
  (fetchMonitorOpenFiles as jest.Mock).mockResolvedValue({ ...openFilesPayload, ...each.openFiles });
}

describe("the monitor of several backend processes", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test("names a process that did not answer in one line, and says nothing once every process answered", async () => {
    serve({ monitor: processes(3, [2]), errors: processes(3), llm: processes(3), openFiles: processes(3) });
    const first = render(<MonitorContent />);
    expect(
      await screen.findByText("Backend process 2 did not answer; its numbers are left out.")
    ).toBeInTheDocument();
    // The other processes' numbers are on the page all the same.
    expect(screen.getByText("1482")).toBeInTheDocument();
    first.unmount();

    serve({ monitor: processes(3), errors: processes(3), llm: processes(3), openFiles: processes(3) });
    const second = render(<MonitorContent />);
    expect(await screen.findByText("1482")).toBeInTheDocument();
    expect(screen.queryByText(/did not answer/)).not.toBeInTheDocument();
    second.unmount();

    // A backend of one process.
    serve({});
    render(<MonitorContent />);
    expect(await screen.findByText("1482")).toBeInTheDocument();
    expect(screen.queryByText(/did not answer/)).not.toBeInTheDocument();
  });

  test("names every process any payload left out, once each and in order", async () => {
    serve({
      monitor: processes(8, [5]),
      errors: processes(8),
      llm: processes(8, [2, 5]),
      openFiles: processes(8, [7]),
    });
    render(<MonitorContent />);
    expect(
      await screen.findByText("Backend processes 2, 5 and 7 did not answer; their numbers are left out.")
    ).toBeInTheDocument();
  });

  test("with several processes the Open files card says its backend line is the busiest process", () => {
    const eight = { ...openFilesPayload, ...processes(8) } as unknown as MonitorOpenFilesPayload;
    const several = render(<OpenFilesSection payload={eight} />);
    expect(screen.getByTestId("monitor-open-files-processes")).toHaveTextContent(
      "The backend runs as 8 processes: its line is the busiest one in each hour, against that process's own limit."
    );
    several.unmount();

    render(<OpenFilesSection payload={openFilesPayload as unknown as MonitorOpenFilesPayload} />);
    expect(screen.queryByTestId("monitor-open-files-processes")).not.toBeInTheDocument();
  });
});
