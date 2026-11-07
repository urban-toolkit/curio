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
  formatOpenFiles,
  toJson,
  toMarkdown,
} from "../../utils/diagnosticsBundle";
import type {
  MonitorErrorsPayload,
  MonitorLlmPayload,
  MonitorOpenFilesPayload,
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

function llm(): MonitorLlmPayload {
  return {
    computedAt: "2026-09-22T14:03:11Z",
    startedAt: "2026-09-21T08:40:00Z",
    maxDays: 90,
    ageSeconds: 4,
    ttlSeconds: 60,
    hourlyFrom: "2026-09-15T15:00:00Z",
    hourlyTo: "2026-09-22T14:00:00Z",
    hourly: [],
    models: [
      {
        model: "gemma4",
        curio: true,
        last24h: { inputTokens: 18200, outputTokens: 2100, requests: 9 },
        last7d: { inputTokens: 1234567, outputTokens: 98000, requests: 410 },
        kept: { inputTokens: 2469606, outputTokens: 120000, requests: 530 },
      },
      {
        model: "gpt`5",
        curio: false,
        last24h: { inputTokens: 640, outputTokens: 210, requests: 2 },
        last7d: { inputTokens: 640, outputTokens: 210, requests: 2 },
        kept: { inputTokens: 640, outputTokens: 210, requests: 2 },
      },
    ],
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

  test("lists each model's tokens, where it ran, in full", () => {
    const md = toMarkdown({ ...bundle, llm: llm() });
    expect(md).toContain("### LLM tokens");
    expect(md).toContain("_Since 2026-09-21T08:40:00Z, at most 90 days._");
    expect(md).toContain(
      "- `gemma4` (Curio's endpoint): 24 hours 18,200 in · 2,100 out, 9 requests; " +
        "7 days 1,234,567 in · 98,000 out, 410 requests; all kept 2,469,606 in · 120,000 out, 530 requests"
    );
    // A backtick in a typed name cannot end its code span.
    expect(md).toContain("- `gpt'5` (own key): 24 hours 640 in · 210 out, 2 requests");
    // Before the errors, as on the page.
    expect(md.indexOf("### LLM tokens")).toBeLessThan(md.indexOf("### Recent errors"));
  });

  test("says when no model answered, and leaves the section out with no payload", () => {
    expect(toMarkdown({ ...bundle, llm: { ...llm(), models: [] } })).toContain(
      "_No LLM requests since the backend started._"
    );
    expect(toMarkdown(bundle)).not.toContain("LLM tokens");
    expect(toMarkdown({ ...bundle, llm: null })).not.toContain("LLM tokens");
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

  test("keeps the LLM tokens' payload too, and says null without one", () => {
    const parsed = JSON.parse(toJson({ monitor: null, storage: null, errors: null, llm: llm() }));
    expect(parsed.llm.models.map((entry: { model: string }) => entry.model)).toEqual(["gemma4", "gpt`5"]);
    expect(JSON.parse(toJson({ monitor: null, storage: null, errors: null })).llm).toBeNull();
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
