/**
 * Turn the monitor's payloads into something a person can hand over.
 *
 * The point of the monitor page is that someone hitting a problem can share
 * what they are seeing without an operator in the loop. That means two
 * formats: markdown sized for a GitHub issue, and JSON for anything else.
 *
 * Both are built from payloads the page already has. Nothing here calls the
 * backend, so the bundle is exactly what was on screen when the button was
 * pressed, not a second sample taken a moment later.
 */
import type {
  MonitorErrorsPayload,
  MonitorLlmPayload,
  MonitorLlmStats,
  MonitorLlmView,
  MonitorOpenFilesCounts,
  MonitorOpenFilesPayload,
  MonitorPayload,
  MonitorStoragePayload,
  MonitorUsageMeasure,
  MonitorUsagePayload,
  MonitorUsageStats,
  MonitorUsageView,
} from "../api/monitorApi";
import { MEASURES } from "../pages/monitor/usageSeries";

/** An issue comment nobody wants to scroll past. Older entries are summarised. */
export const MAX_BUNDLED_ERRORS = 20;

export interface DiagnosticsInput {
  monitor: MonitorPayload | null;
  storage: MonitorStoragePayload | null;
  errors: MonitorErrorsPayload | null;
  llm?: MonitorLlmPayload | null;
  openFiles?: MonitorOpenFilesPayload | null;
  usage?: MonitorUsagePayload | null;
}

// One locale, so a count reads the same in every browser and in a test.
const COMPACT = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
const EXACT = new Intl.NumberFormat("en-US");
const ONE_DECIMAL = new Intl.NumberFormat("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

/** A count as a tile or a table cell shows it: 950, 1.2K, 3.4M. */
export function formatCount(count: number | null | undefined): string {
  return count == null ? "n/a" : COMPACT.format(count);
}

/** A count in full: 1,234,567. */
export function formatExactCount(count: number | null | undefined): string {
  return count == null ? "n/a" : EXACT.format(count);
}

/**
 * A duration in milliseconds: two significant digits under a millisecond
 * ("0.43 ms"), whole milliseconds under a second ("850 ms"), seconds with one
 * decimal above ("1.2 s"). The monitor's charts write their axis and tooltip
 * the same way (`MonitorCharts.durationText`).
 */
export function formatMs(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms)) return "n/a";
  if (ms < 1) return `${Number(ms.toPrecision(2))} ms`;
  const whole = Math.round(ms);
  return whole < 1000 ? `${whole} ms` : `${(ms / 1000).toFixed(1)} s`;
}

/** A rate with one decimal: 41.2, 1,234.5. */
export function formatRate(rate: number | null | undefined): string {
  return rate == null || !Number.isFinite(rate) ? "n/a" : ONE_DECIMAL.format(rate);
}

/** One model's stats over a window, in words, every count in full. */
function llmStats(stats: MonitorLlmStats | undefined): string {
  if (!stats || stats.requests === 0) return "no requests";
  const parts = [
    `${formatExactCount(stats.requests)} requests`,
    `${formatExactCount(stats.failed)} failed`,
    `average ${formatMs(stats.averageMs)}`,
    `95th percentile ${formatMs(stats.p95Ms)}`,
  ];
  if (stats.firstTokenMs != null) parts.push(`first token ${formatMs(stats.firstTokenMs)}`);
  if (stats.tokensPerSecond != null) parts.push(`${formatRate(stats.tokensPerSecond)} tokens per second`);
  return parts.join(", ");
}

function modelStats(view: MonitorLlmView, model: string): MonitorLlmStats | undefined {
  return view.models.find((entry) => entry.model === model);
}

/** One measure's work over a window, in words, every count in full. */
function usageStats(stats: MonitorUsageStats | undefined, noun: string): string {
  if (!stats || stats.count === 0) return "none";
  return [
    `${formatExactCount(stats.count)} ${noun}`,
    `${formatExactCount(stats.failed)} failed`,
    `average ${formatMs(stats.averageMs)}`,
    `95th percentile ${formatMs(stats.p95Ms)}`,
  ].join(", ");
}

function measureStats(view: MonitorUsageView, key: MonitorUsageMeasure): MonitorUsageStats | undefined {
  return view.measures.find((entry) => entry.key === key);
}

/** A server's part of an open-files sample: "backend 212 of 65,536". */
export function formatOpenFiles(server: string, counts: MonitorOpenFilesCounts | null): string {
  if (!counts) return `${server} not answering`;
  if (counts.open == null) return `${server} not counted`;
  const open = formatExactCount(counts.open);
  return counts.limit == null ? `${server} ${open}` : `${server} ${open} of ${formatExactCount(counts.limit)}`;
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return "unknown";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value < 10 && unit > 0 ? value.toFixed(1) : Math.round(value)} ${units[unit]}`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "unknown";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}h`;
  return `${(seconds / 86400).toFixed(1)}d`;
}

export function toMarkdown({ monitor, storage, errors, llm, openFiles, usage }: DiagnosticsInput): string {
  const lines: string[] = ["## Curio diagnostics", ""];

  if (monitor) {
    const d = monitor.deployment;
    const b = monitor.execution.backend;
    const s = monitor.execution.sandbox;

    lines.push(
      `- version \`${d.version}\` · env \`${d.env}\``,
      `- isolation \`${d.isolation}\` (active: \`${d.isolationActive}\`)`,
      `- platform \`${d.platform}\` · python \`${d.pythonVersion}\``,
      `- uptime ${formatDuration(monitor.uptimeSeconds)} · captured ${monitor.generatedAt}`,
      "",
      "### Hardware",
      `- cpu ${monitor.hardware.cpu.model} (${monitor.hardware.cpu.arch}) · ${monitor.hardware.cpu.logicalCores ?? "?"} logical cores`,
      `- memory ${formatBytes(monitor.hardware.memory.totalBytes)} total, ${formatBytes(monitor.hardware.memory.availableBytes)} available (${monitor.hardware.memory.usedPercent ?? "?"}% used)`,
      `- load ${monitor.hardware.load.avg1m ?? "n/a"} / ${monitor.hardware.load.avg5m ?? "n/a"} / ${monitor.hardware.load.avg15m ?? "n/a"} (${monitor.hardware.load.perCore ?? "n/a"} per core)`,
      `- rss backend ${formatBytes(monitor.hardware.processes.backendRssBytes)} · sandbox ${formatBytes(monitor.hardware.processes.sandboxRssBytes)}`,
      "",
      "### Execution",
      `- ${b.total} runs since launch, ${b.error} failed, ${b.inFlight} in flight`,
      `- durations p50 ${b.durations.p50Ms ?? "n/a"}ms · p90 ${b.durations.p90Ms ?? "n/a"}ms · p99 ${b.durations.p99Ms ?? "n/a"}ms`
    );

    if (s.reachable) {
      const deaths = Object.entries(s.childDeaths ?? {})
        .filter(([, n]) => n > 0)
        .map(([reason, n]) => `${reason} ${n}`)
        .join(" · ");
      lines.push(
        `- sandbox: ${s.slotsInUse ?? 0}/${s.parallelism ?? "?"} slots, memory ${s.memoryLimitMb ?? "?"}MB, timeout ${s.wallTimeoutSeconds ?? "?"}s`,
        `- child deaths: ${deaths || "none"}`
      );
    } else {
      lines.push("- sandbox: **unreachable**");
    }

    lines.push(
      "",
      "### Instance",
      `- accounts ${monitor.accounts.total} (${monitor.accounts.guest} guest) · active sessions ${monitor.accounts.sessions.active}`,
      `- projects ${monitor.content.projects.total} · datasets ${monitor.content.datasets.total}`
    );
  } else {
    lines.push("_The monitor payload was unavailable when this was captured._");
  }

  if (storage) {
    lines.push(
      `- storage ${formatBytes(storage.userStores.totalBytes)} across ${storage.userStores.count} stores · disk free ${formatBytes(storage.disk.freeBytes)}`
    );
  }

  if (usage) {
    const { "24h": day, "7d": week, "90d": quarter } = usage.views;
    const sessions = usage.sessionsLast24h;
    lines.push(
      "",
      "### Usage",
      `_The last ${usage.maxDays} days, kept across restarts._`,
      "",
      sessions
        ? `- sessions seen in the last 24 hours: ${formatExactCount(sessions.accounts)} accounts, ` +
            `${formatExactCount(sessions.guests)} guests`
        : "- sessions seen in the last 24 hours: unknown"
    );
    for (const measure of MEASURES) {
      lines.push(
        `- ${measure.label}: 24 hours ${usageStats(measureStats(day, measure.key), measure.noun)}; 7 days ${usageStats(
          measureStats(week, measure.key),
          measure.noun
        )}; 90 days ${usageStats(measureStats(quarter, measure.key), measure.noun)}`
      );
    }
    const deployed = quarter.deploys[quarter.deploys.length - 1];
    if (deployed) lines.push(`- last deploy: \`${deployed.version}\`, ${deployed.at}`);
  }

  if (llm) {
    const { "24h": day, "7d": week, "90d": quarter } = llm.views;
    lines.push(
      "",
      "### LLM performance",
      `_This Curio's own models, the last ${llm.maxDays} days, kept across restarts._`,
      ""
    );
    // The 90 days hold every model the shorter windows do.
    if (quarter.models.length === 0) {
      lines.push(`_No LLM requests in the last ${llm.maxDays} days._`);
    }
    for (const entry of quarter.models) {
      // A backtick in a model's name would end the code span early.
      const model = entry.model.replace(/`/g, "'");
      lines.push(
        `- \`${model}\`: 24 hours ${llmStats(modelStats(day, entry.model))}; 7 days ${llmStats(
          modelStats(week, entry.model)
        )}; 90 days ${llmStats(entry)}`
      );
    }
  }

  const lastOpenFiles = openFiles?.samples[openFiles.samples.length - 1];
  if (lastOpenFiles) {
    lines.push(
      "",
      "### Open files",
      `- ${formatOpenFiles("backend", lastOpenFiles.backend)} · ${formatOpenFiles("sandbox", lastOpenFiles.sandbox)}, sampled ${lastOpenFiles.at}`
    );
  }

  const list = errors?.errors ?? [];
  lines.push("", `### Recent errors (${list.length})`, "");
  if (list.length === 0) {
    lines.push("_None since launch._");
  } else {
    for (const entry of list.slice(0, MAX_BUNDLED_ERRORS)) {
      const repeat = entry.count > 1 ? ` (x${entry.count})` : "";
      lines.push(`**${entry.at} · ${entry.source}${repeat}**: ${entry.summary}`);
      if (entry.detail) {
        lines.push("```", entry.detail.trimEnd(), "```");
      }
      lines.push("");
    }
    if (list.length > MAX_BUNDLED_ERRORS) {
      lines.push(
        `_${list.length - MAX_BUNDLED_ERRORS} older ${
          list.length - MAX_BUNDLED_ERRORS === 1 ? "entry" : "entries"
        } omitted; download the JSON bundle for all of them._`
      );
    }
  }

  return lines.join("\n");
}

export function toJson(input: DiagnosticsInput): string {
  return JSON.stringify(
    {
      capturedAt: new Date().toISOString(),
      monitor: input.monitor,
      storage: input.storage,
      errors: input.errors,
      llm: input.llm ?? null,
      openFiles: input.openFiles ?? null,
      usage: input.usage ?? null,
    },
    null,
    2
  );
}

export function bundleFilename(now: Date = new Date()): string {
  return `curio-diagnostics-${now.toISOString().slice(0, 19).replace(/[:]/g, "")}.json`;
}

/**
 * Copy text, falling back to a hidden textarea.
 *
 * `navigator.clipboard` is undefined on a non-secure origin, which is exactly
 * how a deployment reached over plain HTTP looks. The fallback is what keeps
 * the button working there.
 */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* fall through to the legacy path */
  }
  try {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(area);
    return ok;
  } catch {
    return false;
  }
}

export function downloadJson(input: DiagnosticsInput): void {
  const blob = new Blob([toJson(input)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = bundleFilename();
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
