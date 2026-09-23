/**
 * Turn the three monitor payloads into something a person can hand over.
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
  MonitorPayload,
  MonitorStoragePayload,
} from "../api/monitorApi";

/** An issue comment nobody wants to scroll past. Older entries are summarised. */
export const MAX_BUNDLED_ERRORS = 20;

export interface DiagnosticsInput {
  monitor: MonitorPayload | null;
  storage: MonitorStoragePayload | null;
  errors: MonitorErrorsPayload | null;
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

export function toMarkdown({ monitor, storage, errors }: DiagnosticsInput): string {
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

  const list = errors?.errors ?? [];
  lines.push("", `### Recent errors (${list.length})`, "");
  if (list.length === 0) {
    lines.push("_None since launch._");
  } else {
    for (const entry of list.slice(0, MAX_BUNDLED_ERRORS)) {
      const repeat = entry.count > 1 ? ` (x${entry.count})` : "";
      lines.push(`**${entry.at} · ${entry.source}${repeat}** — ${entry.summary}`);
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
