/**
 * The open files chart's lines: each server's open files at each hourly
 * sample, and the limit, dashed. One limit line when the two servers' limits
 * are the same in every sample, else one per server.
 *
 * Pure, so the chart and a test read the same lines without Vega.
 *
 * COLOUR. The servers take the monitor's palette in its order
 * (`chartColors.ts`), as the LLM token lines do: the backend its first
 * colour, the sandbox its second. A server's own limit is dashed in its
 * colour; a limit both share is dashed in the axes' grey.
 */
import type { MonitorOpenFilesPayload, MonitorOpenFilesSample } from "../../api/monitorApi";
import { CATEGORICAL, LIMIT_INK } from "./chartColors";

export const SERVERS = ["backend", "sandbox"] as const;
export type OpenFilesServer = (typeof SERVERS)[number];

/** Each server's line, and its colour. */
export const SERVER_LINES: Record<OpenFilesServer, { label: string; color: string }> = {
  backend: { label: "Backend", color: CATEGORICAL[0] },
  sandbox: { label: "Sandbox", color: CATEGORICAL[1] },
};

/** The line of a limit both servers share. */
export const SHARED_LIMIT_LINE = "Limit";

/** The line of one server's own limit. */
export function limitLine(server: OpenFilesServer): string {
  return `${SERVER_LINES[server].label} limit`;
}

/** One point of one line, as the chart draws it: a row of `LinesOverTime`. */
export type OpenFilesPoint = {
  t: number;
  line: string;
  files: number;
};

export interface OpenFilesLines {
  points: OpenFilesPoint[];
  /** The lines drawn, in the legend's order, with their colours. */
  colors: { domain: string[]; range: string[] };
  /** The limit lines, drawn dashed. */
  dashed: string[];
  /** Whether a sample counted a server's open files: else nothing to draw. */
  counted: boolean;
}

/** Whether the two servers' limits differ in a sample that has both. */
export function limitsDiffer(samples: MonitorOpenFilesSample[]): boolean {
  return samples.some((sample) => {
    const backend = sample.backend?.limit;
    const sandbox = sample.sandbox?.limit;
    return backend != null && sandbox != null && backend !== sandbox;
  });
}

/**
 * The chart's lines from every sample kept: a point per server and sample
 * that counted, and a point of the limit's line per sample that knew it.
 */
export function openFilesLines(payload: MonitorOpenFilesPayload): OpenFilesLines {
  const shared = !limitsDiffer(payload.samples);
  const points: OpenFilesPoint[] = [];
  const add = (t: number, line: string, files: number | null | undefined) => {
    if (files != null) points.push({ t, line, files });
  };
  for (const sample of payload.samples) {
    const t = Date.parse(sample.at);
    if (Number.isNaN(t)) continue;
    for (const server of SERVERS) add(t, SERVER_LINES[server].label, sample[server]?.open);
    if (shared) {
      add(t, SHARED_LIMIT_LINE, sample.backend?.limit ?? sample.sandbox?.limit);
    } else {
      for (const server of SERVERS) add(t, limitLine(server), sample[server]?.limit);
    }
  }

  const drawn = new Set(points.map((point) => point.line));
  if (!SERVERS.some((server) => drawn.has(SERVER_LINES[server].label))) {
    return { points: [], colors: { domain: [], range: [] }, dashed: [], counted: false };
  }
  const limits: [string, string][] = shared
    ? [[SHARED_LIMIT_LINE, LIMIT_INK]]
    : SERVERS.map((server): [string, string] => [limitLine(server), SERVER_LINES[server].color]);
  const lines = [
    ...SERVERS.map((server): [string, string] => [SERVER_LINES[server].label, SERVER_LINES[server].color]),
    ...limits,
  ].filter(([label]) => drawn.has(label));
  return {
    points,
    colors: { domain: lines.map(([label]) => label), range: lines.map(([, color]) => color) },
    dashed: limits.map(([label]) => label).filter((label) => drawn.has(label)),
    counted: true,
  };
}
