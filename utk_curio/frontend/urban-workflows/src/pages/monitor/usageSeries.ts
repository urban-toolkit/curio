/**
 * The Usage tab's switch, charts, table and tiles, read from
 * `GET /api/monitor/usage`: the windows its switch shows, which the LLM
 * performance section follows too; each measure's line and colour; each
 * line's point at every step of a window; the sessions' lines; the deploys'
 * marks; and the numbers of the last 24 hours.
 *
 * Pure, so the charts, the table and the tiles read the same numbers, and a
 * test reads them without Vega.
 *
 * COLOUR. The monitor's categorical palette (`chartColors.ts`). A measure's
 * colour is its place among `MEASURES`, so it keeps its colour in every chart
 * and window, and the sessions' two lines take two colours no measure has.
 *
 * IDLE STEPS. A step in which a measure counted nothing has no time and no
 * count: its point is null, which breaks the line there, so a line never
 * bridges idle time. A step no sessions sample covers is null too. A point
 * with no neighbour on either side shows only as a dot (`hasLonePoint`).
 */
import type {
  MonitorDeploy,
  MonitorUsageMeasure,
  MonitorUsagePayload,
  MonitorUsageStats,
  MonitorUsageView,
  MonitorWindow,
} from "../../api/monitorApi";
import { CATEGORICAL } from "./chartColors";
import type { TimeMark } from "./MonitorCharts";

/** One window of the switch: its key, its button's label, and how the charts name and time it. */
export interface WindowOption {
  key: MonitorWindow;
  label: string;
  /** What a chart and an empty table call the window: "last 24 hours". */
  span: string;
  /** How a chart's tooltip writes a step's time, in d3-time-format. */
  timeFormat: string;
}

/** The switch's windows, in its order: 5-minute, hourly and daily steps. */
export const WINDOWS: WindowOption[] = [
  { key: "24h", label: "24 hours", span: "last 24 hours", timeFormat: "%b %-d, %H:%M" },
  { key: "7d", label: "7 days", span: "last 7 days", timeFormat: "%b %-d, %H:00" },
  { key: "90d", label: "90 days", span: "last 90 days", timeFormat: "%b %-d" },
];

/** The window the tab shows first. */
export const FIRST_WINDOW: MonitorWindow = "7d";

/**
 * The windows whose charts mark the deploys. Over 90 days of daily steps, a
 * deployment that deploys several times a day would bury the lines.
 */
export const MARKED_WINDOWS: readonly MonitorWindow[] = ["24h", "7d"];

/** One measure as the tab shows it: its label, the noun of its count, and its colour. */
export interface MeasureLine {
  key: MonitorUsageMeasure;
  label: string;
  /** What its count counts: "1,234 runs". */
  noun: string;
  color: string;
}

/** The measures, in the page's order, each in its colour. */
export const MEASURES: MeasureLine[] = [
  { key: "node.python", label: "Python node runs", noun: "runs", color: CATEGORICAL[0] },
  { key: "node.javascript", label: "JavaScript node runs", noun: "runs", color: CATEGORICAL[1] },
  { key: "run", label: "Run All runs", noun: "runs", color: CATEGORICAL[2] },
  { key: "turn", label: "Agent turns", noun: "turns", color: CATEGORICAL[3] },
  { key: "request", label: "Requests", noun: "requests", color: CATEGORICAL[4] },
];

/** The sessions chart's two lines: sign-ins of accounts, and of guests. */
export const SESSION_LINES = {
  accounts: { label: "Accounts", color: CATEGORICAL[5] },
  guests: { label: "Guests", color: CATEGORICAL[6] },
} as const;

/** A measure's line, by its key. */
export function measureLine(key: string): MeasureLine | undefined {
  return MEASURES.find((each) => each.key === key);
}

/** One step of one line, as a chart draws it: a row of `LinesOverTime`. */
export type UsagePoint = {
  t: number;
  line: string;
  /** The step's time in milliseconds, or its count; null where there is none. */
  value: number | null;
};

/** What a measure's chart reads of each step. */
export type UsageField = "averageMs" | "p95Ms" | "count";

/** The window's span: the start of its first step to the start of its current one. */
export function windowSpan(view: { from: string; to: string }): [number, number] | undefined {
  const from = Date.parse(view.from);
  const to = Date.parse(view.to);
  return Number.isNaN(from) || Number.isNaN(to) ? undefined : [from, to];
}

/**
 * A chart's time axis over a window: the start of its first step to the end
 * of its current one, now, so a deploy within the current step has its place.
 */
export function chartSpan(view: { from: string; to: string; stepSeconds: number }): [number, number] | undefined {
  const span = windowSpan(view);
  return span && view.stepSeconds > 0 ? [span[0], span[1] + view.stepSeconds * 1000] : span;
}

/** The measures that counted something in *view*, in the page's order: the lines its charts draw. */
export function measureLines(view: MonitorUsageView): MeasureLine[] {
  const counted = new Set(view.rows.filter((row) => row.count > 0).map((row) => row.key));
  return MEASURES.filter((each) => counted.has(each.key));
}

/** A chart's colour scale: each line's label and colour, in the lines' order. */
export function lineColors(lines: { label: string; color: string }[]): { domain: string[]; range: string[] } {
  return { domain: lines.map((each) => each.label), range: lines.map((each) => each.color) };
}

/** The steps of a window, each its start in epoch milliseconds; none when the window is not one. */
function steps(view: MonitorUsageView): number[] {
  const span = windowSpan(view);
  const step = view.stepSeconds * 1000;
  if (!span || !(step > 0)) return [];
  const out: number[] = [];
  for (let t = span[0]; t <= span[1]; t += step) out.push(t);
  return out;
}

/**
 * One point per line of *lines* and per step of the window, line after line:
 * the step's average time, 95th percentile time or count (*field*), null
 * where the measure counted nothing.
 */
export function measurePoints(
  view: MonitorUsageView,
  field: UsageField,
  lines: MeasureLine[] = measureLines(view)
): UsagePoint[] {
  const values = new Map<string, number | null>();
  for (const row of view.rows) {
    const t = Date.parse(row.at);
    if (Number.isNaN(t) || row.count <= 0) continue;
    const value =
      field === "count" ? row.count : field === "averageMs" ? Math.round(row.ms / row.count) : row.p95Ms;
    values.set(`${row.key}\n${t}`, value);
  }
  const times = steps(view);
  const points: UsagePoint[] = [];
  for (const line of lines) {
    for (const t of times) {
      points.push({ t, line: line.label, value: values.get(`${line.key}\n${t}`) ?? null });
    }
  }
  return points;
}

/**
 * The sessions chart's points: per step of the window, the sign-ins of
 * accounts and of guests its sample saw, line after line; null where no
 * sample covers the step.
 */
export function sessionPoints(view: MonitorUsageView): UsagePoint[] {
  const sampled = new Map<number, { accounts: number; guests: number }>();
  for (const each of view.sessions) {
    const t = Date.parse(each.at);
    if (!Number.isNaN(t)) sampled.set(t, each);
  }
  const times = steps(view);
  const points: UsagePoint[] = [];
  for (const key of ["accounts", "guests"] as const) {
    for (const t of times) {
      const seen = sampled.get(t);
      points.push({ t, line: SESSION_LINES[key].label, value: seen ? seen[key] : null });
    }
  }
  return points;
}

/** The deploys as a chart's marks: each at the time it started, named by its version. */
export function deployMarks(deploys: MonitorDeploy[] | undefined): TimeMark[] {
  const marks: TimeMark[] = [];
  for (const deploy of deploys ?? []) {
    const t = Date.parse(deploy.at);
    if (!Number.isNaN(t)) marks.push({ t, label: deploy.version });
  }
  return marks;
}

/**
 * Whether a line has a point with no neighbour on either side, which a line
 * alone does not draw: the chart then dots every point. The points are a
 * line's steps in order, line after line, as `measurePoints` gives them;
 * *value* reads a point's value.
 */
export function hasLonePoint<P extends { line: string }>(points: P[], value: (point: P) => number | null): boolean {
  return points.some((point, index) => {
    if (value(point) == null) return false;
    const joined = (other: P | undefined) => other?.line === point.line && value(other) != null;
    return !joined(points[index - 1]) && !joined(points[index + 1]);
  });
}

/** A usage point's value. */
export function pointValue(point: UsagePoint): number | null {
  return point.value;
}

/** Several measures' numbers as one: their counts, failures and times added up. */
export interface CombinedStats {
  count: number;
  failed: number;
  averageMs: number | null;
}

/** The numbers of the measures *keys* in *stats* added up: counts, failures, and the average of every one. */
export function combined(stats: MonitorUsageStats[], keys: MonitorUsageMeasure[]): CombinedStats {
  let count = 0;
  let failed = 0;
  let ms = 0;
  for (const each of stats) {
    if (!keys.includes(each.key)) continue;
    count += each.count;
    failed += each.failed;
    ms += each.ms;
  }
  return { count, failed, averageMs: count > 0 ? Math.round(ms / count) : null };
}

/** The tiles' numbers: the last 24 hours of each measure the tiles name, and the sessions seen. */
export interface LastDay {
  sessions: { accounts: number; guests: number } | null;
  nodes: CombinedStats;
  turns: CombinedStats;
  runs: CombinedStats;
  requests: CombinedStats;
}

/** What the tiles show: the last 24 hours, node runs of both languages as one. */
export function lastDay(payload: MonitorUsagePayload): LastDay {
  const stats = payload.views["24h"].measures;
  return {
    sessions: payload.sessionsLast24h,
    nodes: combined(stats, ["node.python", "node.javascript"]),
    turns: combined(stats, ["turn"]),
    runs: combined(stats, ["run"]),
    requests: combined(stats, ["request"]),
  };
}
