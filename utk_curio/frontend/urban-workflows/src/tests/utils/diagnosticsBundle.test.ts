/**
 * The shareable bundle. This is the output a user pastes into an issue, so its
 * contents are the feature, not an implementation detail.
 */
import {
  MAX_BUNDLED_ERRORS,
  bundleFilename,
  formatBytes,
  formatDuration,
  toJson,
  toMarkdown,
} from "../../utils/diagnosticsBundle";
import type {
  MonitorErrorsPayload,
  MonitorPayload,
  MonitorStoragePayload,
} from "../../api/monitorApi";

function monitor(): MonitorPayload {
  return {
    generatedAt: "2026-09-22T14:03:11Z",
    uptimeSeconds: 48213,
    deployment: {
      version: "0.16.114",
      isolation: "fork",
      isolationActive: "fork",
      execUserConfigured: true,
      authEnabled: true,
      projectsEnabled: true,
      guestLoginAllowed: true,
      collabEnabled: false,
      sharedInstallsAllowed: false,
      factoryPublishAllowed: true,
      saveNodeOutputDefault: false,
      llmProviderConfigured: true,
      searchToolConfigured: false,
      env: "prod",
      platform: "macOS-27.0-arm64",
      pythonVersion: "3.12.1",
    },
    hardware: {
      cpu: {
        model: "Apple M1",
        arch: "arm64",
        logicalCores: 8,
        physicalCores: 8,
        maxFrequencyMhz: 3200,
        usagePercent: 12.5,
      },
      memory: {
        totalBytes: 17179869184,
        availableBytes: 8589934592,
        usedPercent: 50,
        swapTotalBytes: 0,
        swapUsedBytes: 0,
      },
      load: { avg1m: 1.5, avg5m: 1.2, avg15m: 0.9, perCore: 0.19 },
      processes: { backendRssBytes: 104857600, sandboxRssBytes: 209715200 },
    },
    execution: {
      backend: {
        total: 1482,
        ok: 1391,
        error: 91,
        python: 1402,
        javascript: 80,
        inFlight: 2,
        distinctNodeTypes: 17,
        lastExecutionAt: "2026-09-22T14:02:57Z",
        durations: {
          windowSize: 200,
          count: 200,
          p50Ms: 412,
          p90Ms: 3180,
          p99Ms: 21400,
          maxMs: 58200,
          buckets: [],
        },
      },
      sandbox: {
        reachable: true,
        isolation: "fork",
        isolationActive: "fork",
        zygoteRunning: true,
        parallelism: 2,
        slotsInUse: 1,
        memoryLimitMb: 4096,
        cpuSecondsLimit: 300,
        wallTimeoutSeconds: 300,
        total: 1482,
        isolated: 1482,
        inProcess: 0,
        childDeaths: { oom: 7, timeout: 4 },
      },
    },
    accounts: {
      total: 14,
      registered: 13,
      guest: 1,
      createdLast24h: 2,
      sessions: { active: 3, seenLast5m: 2, seenLast1h: 5 },
      signIn: { windowMinutes: 60, success: 6, failure: 11, distinctSources: 4 },
    },
    content: {
      projects: {
        total: 41,
        createdLast24h: 3,
        openedLast24h: 9,
        storesWithProjects: 11,
      },
      datasets: {
        total: 128,
        imported: 74,
        computed: 54,
        stores: 12,
        totalBytes: 2469606195,
        largestBytes: 671088640,
        medianBytes: 4194304,
      },
      execCacheEntries: 302,
    },
  };
}

function errorsPayload(count: number): MonitorErrorsPayload {
  return {
    generatedAt: "2026-09-22T14:03:11Z",
    serverWindow: 200,
    clientWindow: 50,
    sandboxWindow: 50,
    droppedClient: 0,
    errors: Array.from({ length: count }, (_, i) => ({
      at: `2026-09-22T14:0${i % 10}:00Z`,
      source: "node" as const,
      summary: `KeyError: 'column-${i}'`,
      detail: `Traceback ${i}`,
      context: {},
      count: 1,
    })),
  };
}

const storage: MonitorStoragePayload = {
  computedAt: "2026-09-22T14:02:40Z",
  ageSeconds: 31,
  ttlSeconds: 60,
  walkMs: 412,
  truncated: false,
  userStores: {
    count: 14,
    totalBytes: 2469606195,
    largestBytes: 671088640,
    medianBytes: 8388608,
    buckets: [],
  },
  breakdown: [],
  disk: { totalBytes: 494384795648, freeBytes: 120034512896 },
};

describe("formatBytes", () => {
  test.each([
    [0, "0 B"],
    [512, "512 B"],
    [2048, "2.0 KB"],
    [1073741824, "1.0 GB"],
  ])("formats %s", (input, expected) => {
    expect(formatBytes(input)).toBe(expected);
  });

  test("null is stated, not rendered as zero", () => {
    // A missing counter and an empty disk are different facts.
    expect(formatBytes(null)).toBe("unknown");
  });
});

describe("formatDuration", () => {
  test.each([
    [30, "30s"],
    [600, "10m"],
    [7200, "2.0h"],
    [172800, "2.0d"],
  ])("formats %s", (input, expected) => {
    expect(formatDuration(input)).toBe(expected);
  });
});

describe("toMarkdown", () => {
  const bundle = {
    monitor: monitor(),
    storage,
    errors: errorsPayload(3),
  };

  test("carries the facts a maintainer asks for first", () => {
    const md = toMarkdown(bundle);
    expect(md).toContain("0.16.114");
    expect(md).toContain("isolation `fork`");
    expect(md).toContain("1482 runs since launch, 91 failed");
    expect(md).toContain("Apple M1");
    expect(md).toContain("8 logical cores");
    expect(md).toContain("oom 7");
  });

  test("includes the error summaries and their tracebacks", () => {
    const md = toMarkdown(bundle);
    expect(md).toContain("KeyError: 'column-0'");
    expect(md).toContain("Traceback 0");
  });

  test("caps the error list and says how many it left out", () => {
    // An issue comment nobody will scroll through is not a shareable bundle.
    const md = toMarkdown({ ...bundle, errors: errorsPayload(30) });
    expect(md).toContain("KeyError: 'column-0'");
    expect(md).not.toContain("KeyError: 'column-25'");
    expect(md).toContain("10 older entries omitted");
  });

  test("an instance with no errors says so rather than showing an empty heading", () => {
    const md = toMarkdown({ ...bundle, errors: errorsPayload(0) });
    expect(md).toContain("Recent errors (0)");
    expect(md).toContain("None since launch");
  });

  test("a missing payload degrades instead of throwing", () => {
    // The button must work while a poll is still in flight or has failed.
    expect(() =>
      toMarkdown({ monitor: null, storage: null, errors: null })
    ).not.toThrow();
    expect(toMarkdown({ monitor: null, storage: null, errors: null })).toContain(
      "unavailable"
    );
  });

  test("an unreachable sandbox is stated plainly", () => {
    const m = monitor();
    m.execution.sandbox.reachable = false;
    const md = toMarkdown({ ...bundle, monitor: m });
    expect(md).toContain("sandbox: **unreachable**");
  });
});

describe("toJson", () => {
  test("round-trips and keeps all three payloads", () => {
    const parsed = JSON.parse(
      toJson({ monitor: monitor(), storage, errors: errorsPayload(2) })
    );
    expect(parsed.monitor.deployment.version).toBe("0.16.114");
    expect(parsed.storage.userStores.count).toBe(14);
    expect(parsed.errors.errors).toHaveLength(2);
    expect(typeof parsed.capturedAt).toBe("string");
  });

  test("the JSON bundle is NOT capped the way the markdown is", () => {
    // The markdown cap exists for readability; the file is the complete record.
    const parsed = JSON.parse(
      toJson({ monitor: null, storage: null, errors: errorsPayload(40) })
    );
    expect(parsed.errors.errors.length).toBe(40);
    expect(parsed.errors.errors.length).toBeGreaterThan(MAX_BUNDLED_ERRORS);
  });
});

describe("bundleFilename", () => {
  test("is filesystem safe", () => {
    const name = bundleFilename(new Date("2026-09-22T14:03:11Z"));
    expect(name).toBe("curio-diagnostics-2026-09-22T140311.json");
    expect(name).not.toContain(":");
  });
});
