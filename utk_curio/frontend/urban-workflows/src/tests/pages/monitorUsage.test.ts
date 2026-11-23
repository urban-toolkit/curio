/**
 * The Usage tab's switch, lines, marks and tiles (pages/monitor/usageSeries.ts):
 * 24 hours, 7 days and 90 days, 7 days first, the deploys marked on the first
 * two; one line per measure that counted something, each in its own colour in
 * every window, and the sessions' two lines; a point at every step of the
 * window, null where nothing was counted or sampled, so a line never bridges
 * idle time, with a dot on each point when one stands alone; and the last 24
 * hours' numbers, node runs of both languages as one.
 */
import type { MonitorUsagePayload, MonitorUsageRow, MonitorUsageStats, MonitorUsageView } from "../../api/monitorApi";
import { CATEGORICAL } from "../../pages/monitor/chartColors";
import {
  FIRST_WINDOW,
  MARKED_WINDOWS,
  MEASURES,
  SESSION_LINES,
  WINDOWS,
  averageOf,
  chartSpan,
  combined,
  deployMarks,
  hasLonePoint,
  lastDay,
  lineColors,
  measureLine,
  measureLines,
  measurePoints,
  pointValue,
  sessionPoints,
  windowSpan,
  type UsagePoint,
} from "../../pages/monitor/usageSeries";

const DAY = { from: "2026-11-05T15:25:00Z", to: "2026-11-06T15:20:00Z", stepSeconds: 300 };
const WEEK = { from: "2026-10-30T16:00:00Z", to: "2026-11-06T15:00:00Z", stepSeconds: 3600 };
const QUARTER = { from: "2026-08-09T00:00:00Z", to: "2026-11-06T00:00:00Z", stepSeconds: 86400 };

function row(key: string, at: string, count: number, ms: number, p95Ms: number | null = null): MonitorUsageRow {
  return { at, key: key as MonitorUsageRow["key"], count, failed: 0, ms, p95Ms };
}

function stats(key: string, count: number, failed: number, ms: number): MonitorUsageStats {
  return {
    key: key as MonitorUsageStats["key"], count, failed, ms,
    averageMs: count > 0 ? Math.round(ms / count) : null, p95Ms: null,
  };
}

function view(rows: MonitorUsageRow[], window = WEEK, extra: Partial<MonitorUsageView> = {}): MonitorUsageView {
  return { ...window, rows, measures: [], sessions: [], deploys: [], ...extra };
}

function point(t: number, line: string, value: number | null): UsagePoint {
  return { t, line, value };
}

test("the switch offers 24 hours, 7 days and 90 days, and shows 7 days first", () => {
  expect(WINDOWS.map((each) => [each.key, each.label, each.span])).toEqual([
    ["24h", "24 hours", "last 24 hours"],
    ["7d", "7 days", "last 7 days"],
    ["90d", "90 days", "last 90 days"],
  ]);
  expect(FIRST_WINDOW).toBe("7d");
});

test("the deploys are marked on 24 hours and 7 days, not on 90 days of daily steps", () => {
  expect(MARKED_WINDOWS).toEqual(["24h", "7d"]);
});

test("each measure has its label, the noun of its count and a colour of its own, in the page's order", () => {
  expect(MEASURES.map((each) => [each.key, each.label, each.noun, each.color])).toEqual([
    ["node.python", "Python node runs", "runs", CATEGORICAL[0]],
    ["node.javascript", "JavaScript node runs", "runs", CATEGORICAL[1]],
    ["run", "Run All runs", "runs", CATEGORICAL[2]],
    ["turn", "Agent turns", "turns", CATEGORICAL[3]],
    ["request", "Requests", "requests", CATEGORICAL[4]],
  ]);
  // The sessions' lines take colours no measure has.
  expect([SESSION_LINES.accounts, SESSION_LINES.guests]).toEqual([
    { label: "Accounts", color: CATEGORICAL[5] },
    { label: "Guests", color: CATEGORICAL[6] },
  ]);
  expect(measureLine("turn")?.label).toBe("Agent turns");
  expect(measureLine("nope")).toBeUndefined();
});

test("a chart draws the measures that counted something, each keeping its colour whatever the others counted", () => {
  const at = "2026-11-06T14:00:00Z";
  const some = measureLines(view([row("request", at, 900, 9000), row("turn", at, 2, 3000)]));
  expect(some.map((each) => [each.label, each.color])).toEqual([
    ["Agent turns", CATEGORICAL[3]],
    ["Requests", CATEGORICAL[4]],
  ]);
  expect(lineColors(some)).toEqual({ domain: ["Agent turns", "Requests"], range: [CATEGORICAL[3], CATEGORICAL[4]] });
  const all = measureLines(view(MEASURES.map((each) => row(each.key, at, 1, 10))));
  expect(lineColors(all).range).toEqual(CATEGORICAL.slice(0, 5));
  expect(measureLines(view([]))).toEqual([]);
});

test("every line has a point at every step of the window: its average, 95th percentile or count, null where none", () => {
  const week = view([
    row("node.python", "2026-11-06T14:00:00Z", 4, 3000, 1900),
    row("node.python", "2026-11-06T12:00:00Z", 2, 2401, 2300),
    row("request", WEEK.from, 1, 40, 48),
  ]);
  const averages = measurePoints(week, "averageMs");
  expect(averages).toHaveLength(2 * 168);
  const python = averages.filter((each) => each.line === "Python node runs");
  expect(python).toHaveLength(168);
  expect([python[0].t, python[167].t]).toEqual([Date.parse(WEEK.from), Date.parse(WEEK.to)]);
  // Rounded to the millisecond.
  expect(python.filter((each) => each.value !== null).map((each) => [new Date(each.t).toISOString(), each.value]))
    .toEqual([
      ["2026-11-06T12:00:00.000Z", 1201],
      ["2026-11-06T14:00:00.000Z", 750],
    ]);
  // An idle hour has no time, not one of 0.
  expect(python.filter((each) => each.value === 0)).toEqual([]);
  expect(averages.filter((each) => each.line === "Requests" && each.value !== null)).toEqual([
    point(Date.parse(WEEK.from), "Requests", 40),
  ]);

  const p95 = measurePoints(week, "p95Ms").filter((each) => each.value !== null);
  expect(p95.map((each) => [each.line, each.value])).toEqual([
    ["Python node runs", 2300], ["Python node runs", 1900], ["Requests", 48],
  ]);
  const counts = measurePoints(week, "count").filter((each) => each.value !== null);
  expect(counts.map((each) => [each.line, each.value])).toEqual([
    ["Python node runs", 2], ["Python node runs", 4], ["Requests", 1],
  ]);

  // Five-minute steps over 24 hours, and days over 90.
  expect(measurePoints(view([row("turn", DAY.to, 3, 1000)], DAY), "count")).toHaveLength(288);
  const days = measurePoints(view([row("turn", "2026-10-01T00:00:00Z", 3, 1000)], QUARTER), "averageMs");
  expect(days).toHaveLength(90);
  expect(days.filter((each) => each.value !== null)).toEqual([point(Date.parse("2026-10-01T00:00:00Z"), "Agent turns", 333)]);
});

test("an average of a fraction of a millisecond keeps its value, and one from 10 ms up is whole", () => {
  // As the route gives its times: three significant digits under 10 ms.
  expect([averageOf(2.345, 7), averageOf(4.567, 1), averageOf(45.67, 1), averageOf(1000, 3)]).toEqual([
    0.335, 4.57, 46, 333,
  ]);
  const at = "2026-11-06T14:00:00Z";
  const week = view([row("request", at, 7, 2.345, 0.95), row("turn", at, 3, 1000)]);
  const averages = measurePoints(week, "averageMs").filter((each) => each.value !== null);
  // A request's average is a point on the log axis, not a 0 the axis leaves out.
  expect(averages.map((each) => [each.line, each.value])).toEqual([["Agent turns", 333], ["Requests", 0.335]]);
  expect(measurePoints(week, "p95Ms").filter((each) => each.line === "Requests" && each.value !== null))
    .toEqual([point(Date.parse(at), "Requests", 0.95)]);
  expect(combined([stats("request", 7, 0, 2.345)], ["request"])).toEqual({ count: 7, failed: 0, averageMs: 0.335 });
});

test("the sessions chart has the accounts and the guests at every step, null where no sample covers it", () => {
  const week = view([], WEEK, {
    sessions: [
      { at: "2026-11-06T13:00:00Z", accounts: 3, guests: 0 },
      { at: WEEK.from, accounts: 1, guests: 8 },
    ],
  });
  const points = sessionPoints(week);
  expect(points).toHaveLength(2 * 168);
  const sampled = points.filter((each) => each.value !== null);
  expect(sampled.map((each) => [each.line, new Date(each.t).toISOString(), each.value])).toEqual([
    ["Accounts", "2026-10-30T16:00:00.000Z", 1],
    ["Accounts", "2026-11-06T13:00:00.000Z", 3],
    ["Guests", "2026-10-30T16:00:00.000Z", 8],
    ["Guests", "2026-11-06T13:00:00.000Z", 0],
  ]);
  // A sample that saw nobody is 0, a step with no sample nothing.
  expect(points.filter((each) => each.value === 0)).toHaveLength(1);
});

test("the deploys are marks at the time each started, named by its version", () => {
  expect(deployMarks([
    { at: "2026-11-05T09:20:07Z", version: "0.17.399" },
    { at: "not a time", version: "0.17.400" },
    { at: "2026-11-06T15:10:07Z", version: "0.17.401" },
  ])).toEqual([
    { t: Date.parse("2026-11-05T09:20:07Z"), label: "0.17.399" },
    { t: Date.parse("2026-11-06T15:10:07Z"), label: "0.17.401" },
  ]);
  expect(deployMarks(undefined)).toEqual([]);
});

test("a point with no neighbour on either side is alone, and the chart then dots every point", () => {
  const [a, b, c] = [0, 1, 2];
  expect(hasLonePoint([point(a, "x", null), point(b, "x", 5), point(c, "x", null)], pointValue)).toBe(true);
  expect(hasLonePoint([point(a, "x", 5), point(b, "x", 6), point(c, "x", null)], pointValue)).toBe(false);
  // The next line's first point is no neighbour.
  expect(hasLonePoint([point(a, "x", null), point(b, "x", 5), point(a, "y", 6), point(b, "y", 7)], pointValue))
    .toBe(true);
  // A count of 0 is a point.
  expect(hasLonePoint([point(a, "x", 0), point(b, "x", 5)], pointValue)).toBe(false);
  expect(hasLonePoint([], pointValue)).toBe(false);
});

test("a chart's time axis runs from the window's first step to the end of its current one", () => {
  expect(windowSpan(WEEK)).toEqual([Date.parse(WEEK.from), Date.parse(WEEK.to)]);
  expect(chartSpan(WEEK)).toEqual([Date.parse(WEEK.from), Date.parse(WEEK.to) + 3_600_000]);
  expect(chartSpan(DAY)).toEqual([Date.parse(DAY.from), Date.parse(DAY.to) + 300_000]);
  expect(chartSpan({ ...WEEK, from: "not a time" })).toBeUndefined();
  expect(measurePoints(view([row("turn", WEEK.to, 1, 100)], { ...WEEK, to: "not a time" }), "count")).toEqual([]);
});

test("the tiles read the last 24 hours, node runs of both languages as one", () => {
  const day = view([], DAY, {
    measures: [
      stats("node.python", 4, 1, 4800),
      stats("node.javascript", 1, 0, 300),
      stats("run", 0, 0, 0),
      stats("turn", 2, 0, 30000),
      stats("request", 200, 3, 9000),
    ],
  });
  const payload = {
    computedAt: "2026-11-06T15:20:07Z", maxDays: 90, ageSeconds: 0, ttlSeconds: 60,
    measures: MEASURES.map((each) => each.key),
    sessionsLast24h: { accounts: 12, guests: 30 },
    views: { "24h": day, "7d": view([], WEEK), "90d": view([], QUARTER) },
  } as MonitorUsagePayload;
  expect(lastDay(payload)).toEqual({
    sessions: { accounts: 12, guests: 30 },
    // 5,100 ms over 5 runs.
    nodes: { count: 5, failed: 1, averageMs: 1020 },
    turns: { count: 2, failed: 0, averageMs: 15000 },
    runs: { count: 0, failed: 0, averageMs: null },
    requests: { count: 200, failed: 3, averageMs: 45 },
  });
  expect(lastDay({ ...payload, sessionsLast24h: null }).sessions).toBeNull();
  expect(combined([], ["turn"])).toEqual({ count: 0, failed: 0, averageMs: null });
});
