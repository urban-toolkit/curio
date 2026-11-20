/**
 * The shareable bundle. This is the output a user pastes into an issue, so its
 * contents are the feature, not an implementation detail.
 */
import {
  MAX_BUNDLED_ERRORS,
  bundleFilename,
  formatBytes,
  formatCount,
  formatDuration,
  formatExactCount,
  formatMs,
  formatOpenFiles,
  formatRate,
  toJson,
  toMarkdown,
} from "../../utils/diagnosticsBundle";
import type {
  MonitorErrorsPayload,
  MonitorLlmPayload,
  MonitorOpenFilesPayload,
  MonitorPayload,
  MonitorStoragePayload,
  MonitorUsagePayload,
  MonitorUsageStats,
} from "../../api/monitorApi";

function monitor(): MonitorPayload {
  return {
    generatedAt: "2026-09-22T14:03:11Z",
    uptimeSeconds: 48213,
    deployment: {
      version: "0.16.114",
      isolation: "fork",
      isolationActive: "fork",
      memoryLimit: "cgroup",
      memoryLimitReason: null,
      execUserConfigured: true,
      authEnabled: true,
      projectsEnabled: true,
      guestLoginAllowed: true,
      factoryPublishAllowed: true,
      saveNodeOutputDefault: false,
      llmProviderConfigured: true,
      searchToolConfigured: false,
      bucketMounts: "none",
      bucketMountsProblem: null,
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

const NO_REQUESTS = {
  requests: 0, failed: 0, averageMs: null, p95Ms: null, firstTokenMs: null, tokensPerSecond: null,
};

function llm(): MonitorLlmPayload {
  const stats = (requests: number, averageMs: number) => ({
    requests, failed: 1, averageMs, p95Ms: 2380, firstTokenMs: 310, tokensPerSecond: 41.2,
  });
  const gemma = (requests: number, averageMs: number) => ({ model: "gemma4", ...stats(requests, averageMs) });
  // A model whose requests were not streamed, and whose provider reported no output tokens.
  const backticked = {
    model: "qwen`3", requests: 2, failed: 0, averageMs: 850, p95Ms: 975, firstTokenMs: null, tokensPerSecond: null,
  };
  return {
    computedAt: "2026-09-22T14:03:11Z",
    maxDays: 90,
    ageSeconds: 4,
    ttlSeconds: 60,
    views: {
      "24h": { from: "2026-09-21T14:05:00Z", to: "2026-09-22T14:00:00Z", stepSeconds: 300, rows: [],
               models: [gemma(9, 1033)], all: stats(9, 1033) },
      "7d": { from: "2026-09-15T15:00:00Z", to: "2026-09-22T14:00:00Z", stepSeconds: 3600, rows: [],
              models: [gemma(1209, 1248), backticked], all: stats(1211, 1250) },
      "90d": { from: "2026-06-25T00:00:00Z", to: "2026-09-22T00:00:00Z", stepSeconds: 86400, rows: [],
               models: [gemma(1709, 1235), backticked], all: stats(1711, 1237) },
    },
  };
}

function usage(): MonitorUsagePayload {
  const work = (key: string, count = 0, failed = 0, averageMs: number | null = null,
                p95Ms: number | null = null): MonitorUsageStats => ({
    key: key as MonitorUsageStats["key"], count, failed, ms: averageMs == null ? 0 : averageMs * count, averageMs, p95Ms,
  });
  const measures = (python: MonitorUsageStats) => [
    python, work("node.javascript"), work("run", 2, 1, 4500, 7000), work("turn"), work("request", 1234, 0, 45, 120),
  ];
  const view = (from: string, to: string, stepSeconds: number, python: MonitorUsageStats) => ({
    from, to, stepSeconds, rows: [], sessions: [], measures: measures(python),
    deploys: [
      { at: "2026-09-18T10:00:00Z", version: "0.16.110" },
      { at: "2026-09-22T09:30:12Z", version: "0.16.114" },
    ],
  });
  return {
    computedAt: "2026-09-22T14:03:11Z",
    maxDays: 90,
    ageSeconds: 3,
    ttlSeconds: 60,
    measures: ["node.python", "node.javascript", "run", "turn", "request"],
    sessionsLast24h: { accounts: 12, guests: 30 },
    views: {
      "24h": view("2026-09-21T14:05:00Z", "2026-09-22T14:00:00Z", 300, work("node.python", 4, 1, 1200, 2380)),
      "7d": view("2026-09-15T15:00:00Z", "2026-09-22T14:00:00Z", 3600, work("node.python", 1204, 4, 1248, 4100)),
      "90d": view("2026-06-25T00:00:00Z", "2026-09-22T00:00:00Z", 86400, work("node.python", 1700, 3, 1235, 4000)),
    },
  };
}

function openFiles(): MonitorOpenFilesPayload {
  return {
    computedAt: "2026-09-22T14:03:11Z",
    startedAt: "2026-09-22T12:03:00Z",
    maxDays: 90,
    intervalSeconds: 3600,
    warnAbovePercent: 80,
    clearBelowPercent: 70,
    samples: [
      { at: "2026-09-22T12:03:05Z", backend: { open: 212, limit: 65536 }, sandbox: { open: 96, limit: 65536 } },
      { at: "2026-09-22T13:03:05Z", backend: { open: 230, limit: 65536 }, sandbox: null },
    ],
  };
}

describe("formatCount and formatExactCount", () => {
  test.each([
    [950, "950", "950"],
    [18200, "18.2K", "18,200"],
    [98000, "98K", "98,000"],
    [1234567, "1.2M", "1,234,567"],
  ])("format %s", (count, compact, exact) => {
    expect([formatCount(count), formatExactCount(count)]).toEqual([compact, exact]);
  });

  test("a missing count is stated, not rendered as zero", () => {
    expect([formatCount(null), formatExactCount(undefined)]).toEqual(["n/a", "n/a"]);
  });
});

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

describe("formatMs and formatRate", () => {
  test.each([
    [0, "0 ms"],
    [12.4, "12 ms"],
    [850, "850 ms"],
    [999.4, "999 ms"],
    [999.6, "1.0 s"],
    [1000, "1.0 s"],
    [1234, "1.2 s"],
    [61500, "61.5 s"],
  ])("a duration of %s ms reads as %s", (input, expected) => {
    expect(formatMs(input)).toBe(expected);
  });

  test("a rate keeps one decimal", () => {
    expect([formatRate(41.2), formatRate(8), formatRate(1234.56)]).toEqual(["41.2", "8.0", "1,234.6"]);
  });

  test("a missing time or rate is stated, not rendered as zero", () => {
    expect([formatMs(null), formatMs(undefined), formatRate(null), formatRate(undefined)]).toEqual([
      "n/a", "n/a", "n/a", "n/a",
    ]);
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

  test("lists each model's performance in each window, every count in full", () => {
    const md = toMarkdown({ ...bundle, llm: llm() });
    expect(md).toContain("### LLM performance");
    expect(md).toContain("_This Curio's own models, the last 90 days, kept across restarts._");
    expect(md).toContain(
      "- `gemma4`: 24 hours 9 requests, 1 failed, average 1.0 s, 95th percentile 2.4 s, first token 310 ms, " +
        "41.2 tokens per second; 7 days 1,209 requests, 1 failed, average 1.2 s, 95th percentile 2.4 s, " +
        "first token 310 ms, 41.2 tokens per second; 90 days 1,709 requests, 1 failed, average 1.2 s, " +
        "95th percentile 2.4 s, first token 310 ms, 41.2 tokens per second"
    );
    // A window a model had no request in says so, and what no request gave is
    // left out. A backtick in a name cannot end its code span.
    expect(md).toContain(
      "- `qwen'3`: 24 hours no requests; 7 days 2 requests, 0 failed, average 850 ms, 95th percentile 975 ms; " +
        "90 days 2 requests, 0 failed, average 850 ms, 95th percentile 975 ms"
    );
    // Nothing says where a model ran.
    expect(md.slice(md.indexOf("### LLM performance"), md.indexOf("### Recent errors"))).not.toMatch(
      /endpoint|own key/i
    );
    // Before the errors, as on the page.
    expect(md.indexOf("### LLM performance")).toBeLessThan(md.indexOf("### Recent errors"));
  });

  test("says when no model answered, and leaves the section out with no payload", () => {
    const none = llm();
    for (const view of Object.values(none.views)) {
      view.models = [];
      view.all = NO_REQUESTS;
    }
    expect(toMarkdown({ ...bundle, llm: none })).toContain("_No LLM requests in the last 90 days._");
    expect(toMarkdown(bundle)).not.toContain("LLM performance");
    expect(toMarkdown({ ...bundle, llm: null })).not.toContain("LLM performance");
  });

  test("lists each measure's work in each window, the sessions and the last deploy, every count in full", () => {
    const md = toMarkdown({ ...bundle, usage: usage(), llm: llm() });
    expect(md).toContain("### Usage");
    expect(md).toContain("_The last 90 days, kept across restarts._");
    expect(md).toContain("- sessions seen in the last 24 hours: 12 accounts, 30 guests");
    expect(md).toContain(
      "- Python node runs: 24 hours 4 runs, 1 failed, average 1.2 s, 95th percentile 2.4 s; 7 days 1,204 runs, " +
        "4 failed, average 1.2 s, 95th percentile 4.1 s; 90 days 1,700 runs, 3 failed, average 1.2 s, " +
        "95th percentile 4.0 s"
    );
    // A measure that counted nothing says so.
    expect(md).toContain("- JavaScript node runs: 24 hours none; 7 days none; 90 days none");
    expect(md).toContain(
      "- Requests: 24 hours 1,234 requests, 0 failed, average 45 ms, 95th percentile 120 ms; 7 days 1,234 requests"
    );
    expect(md).toContain("- Agent turns: 24 hours none");
    expect(md).toContain("- Run All runs: 24 hours 2 runs, 1 failed, average 4.5 s, 95th percentile 7.0 s");
    expect(md).toContain("- last deploy: `0.16.114`, 2026-09-22T09:30:12Z");
    // As the tab shows them: the usage, then the LLM performance, before the errors.
    expect(md.indexOf("### Usage")).toBeLessThan(md.indexOf("### LLM performance"));
    expect(md.indexOf("### LLM performance")).toBeLessThan(md.indexOf("### Recent errors"));
  });

  test("says when the sessions could not be counted, and leaves the usage out with no payload", () => {
    expect(toMarkdown({ ...bundle, usage: { ...usage(), sessionsLast24h: null } })).toContain(
      "- sessions seen in the last 24 hours: unknown"
    );
    expect(toMarkdown(bundle)).not.toContain("### Usage");
    expect(toMarkdown({ ...bundle, usage: null })).not.toContain("### Usage");
  });

  test("gives both servers' open files and limits from the last sample", () => {
    const md = toMarkdown({ ...bundle, openFiles: openFiles() });
    expect(md).toContain("### Open files");
    expect(md).toContain(
      "- backend 230 of 65,536 · sandbox not answering, sampled 2026-09-22T13:03:05Z"
    );
    expect(md.indexOf("### Open files")).toBeLessThan(md.indexOf("### Recent errors"));
  });

  test("leaves the open files out before the first sample, and with no payload", () => {
    expect(toMarkdown({ ...bundle, openFiles: { ...openFiles(), samples: [] } })).not.toContain("Open files");
    expect(toMarkdown({ ...bundle, openFiles: null })).not.toContain("Open files");
    expect(toMarkdown(bundle)).not.toContain("Open files");
  });
});

describe("formatOpenFiles", () => {
  test.each([
    [{ open: 212, limit: 65536 }, "backend 212 of 65,536"],
    [{ open: 212, limit: null }, "backend 212"],
    [{ open: null, limit: 1024 }, "backend not counted"],
    [null, "backend not answering"],
  ])("writes %j", (counts, text) => {
    expect(formatOpenFiles("backend", counts)).toBe(text);
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

  test("keeps the LLM performance payload too, and says null without one", () => {
    const parsed = JSON.parse(toJson({ monitor: null, storage: null, errors: null, llm: llm() }));
    expect(parsed.llm).toEqual(llm());
    expect(parsed.llm.views["90d"].models.map((entry: { model: string }) => entry.model)).toEqual(["gemma4", "qwen`3"]);
    expect(JSON.parse(toJson({ monitor: null, storage: null, errors: null })).llm).toBeNull();
  });

  test("keeps the usage payload too, and says null without one", () => {
    const parsed = JSON.parse(toJson({ monitor: null, storage: null, errors: null, usage: usage() }));
    expect(parsed.usage).toEqual(usage());
    expect(JSON.parse(toJson({ monitor: null, storage: null, errors: null })).usage).toBeNull();
  });

  test("keeps every open-files sample, and says null without them", () => {
    const parsed = JSON.parse(toJson({ monitor: null, storage: null, errors: null, openFiles: openFiles() }));
    expect(parsed.openFiles.samples).toEqual(openFiles().samples);
    expect(JSON.parse(toJson({ monitor: null, storage: null, errors: null })).openFiles).toBeNull();
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
