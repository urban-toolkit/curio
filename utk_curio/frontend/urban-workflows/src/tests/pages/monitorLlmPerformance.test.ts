/**
 * The LLM performance section's switch and lines
 * (pages/monitor/llmPerformanceSeries.ts): 24 hours, 7 days and 90 days, 7
 * days first; one line per model, coloured in the palette's order by its
 * name, folded into one past the palette's eight; and a point at every step
 * of the window, its average response time, null where no request was, so a
 * line never bridges idle time, with a dot on each point when one stands alone.
 */
import type { MonitorLlmRow, MonitorLlmStats, MonitorLlmView } from "../../api/monitorApi";
import { CATEGORICAL } from "../../pages/monitor/chartColors";
import {
  FIRST_WINDOW,
  LLM_WINDOWS,
  OTHER_LINE,
  hasLonePoint,
  lineColors,
  modelLines,
  responseTimes,
  windowSpan,
  type ResponsePoint,
} from "../../pages/monitor/llmPerformanceSeries";

const NONE: MonitorLlmStats = {
  requests: 0, failed: 0, averageMs: null, p95Ms: null, firstTokenMs: null, tokensPerSecond: null,
};
const DAY = { from: "2026-11-05T15:25:00Z", to: "2026-11-06T15:20:00Z", stepSeconds: 300 };
const WEEK = { from: "2026-10-30T16:00:00Z", to: "2026-11-06T15:00:00Z", stepSeconds: 3600 };
const QUARTER = { from: "2026-08-09T00:00:00Z", to: "2026-11-06T00:00:00Z", stepSeconds: 86400 };

function row(model: string, at: string, requests: number, ms: number): MonitorLlmRow {
  return { at, model, requests, failed: 0, ms };
}

function view(rows: MonitorLlmRow[], window = WEEK): MonitorLlmView {
  return { ...window, rows, models: [], all: NONE };
}

function point(t: number, line: string, averageMs: number | null): ResponsePoint {
  return { t, line, averageMs };
}

test("the switch offers 24 hours, 7 days and 90 days, and shows 7 days first", () => {
  expect(LLM_WINDOWS.map((each) => [each.key, each.label, each.span])).toEqual([
    ["24h", "24 hours", "last 24 hours"],
    ["7d", "7 days", "last 7 days"],
    ["90d", "90 days", "last 90 days"],
  ]);
  expect(FIRST_WINDOW).toBe("7d");
});

test("each model is a line, named as it is and coloured in the palette's order by its name", () => {
  const lines = modelLines(
    view([
      row("qwen3", "2026-11-06T14:00:00Z", 5, 5000),
      row("gemma4", "2026-11-06T14:00:00Z", 900, 900000),
      row("deepseek-chat", "2026-11-06T13:00:00Z", 7, 7000),
    ])
  );
  expect([...lines.entries()]).toEqual([
    ["deepseek-chat", { label: "deepseek-chat", color: CATEGORICAL[0] }],
    ["gemma4", { label: "gemma4", color: CATEGORICAL[1] }],
    ["qwen3", { label: "qwen3", color: CATEGORICAL[2] }],
  ]);
});

test("a line keeps its colour while the models' requests change", () => {
  const at = "2026-11-06T14:00:00Z";
  const before = modelLines(view([row("a", at, 1, 100), row("b", at, 100, 10000)]));
  const after = modelLines(view([row("a", at, 1000, 100000), row("b", at, 1, 100)]));
  expect(after.get("a")).toEqual(before.get("a"));
  expect(after.get("b")).toEqual(before.get("b"));
});

test("past eight models, the seven with the most requests keep a line and the rest share one", () => {
  const at = "2026-11-06T14:00:00Z";
  // m9 has the most requests and m0 the fewest.
  const lines = modelLines(view(Array.from({ length: 10 }, (_, i) => row(`m${i}`, at, (i + 1) * 10, 1000))));
  const own = ["m3", "m4", "m5", "m6", "m7", "m8", "m9"];
  own.forEach((name, index) => {
    expect(lines.get(name)).toEqual({ label: name, color: CATEGORICAL[index] });
  });
  for (const name of ["m0", "m1", "m2"]) {
    expect(lines.get(name)).toEqual({ label: OTHER_LINE, color: CATEGORICAL[7] });
  }
  expect(lineColors(lines)).toEqual({ domain: [...own, OTHER_LINE], range: CATEGORICAL });
});

test("every line has a point at every step of the window, null where no request was", () => {
  const week = view([
    row("gemma4", "2026-11-06T14:00:00Z", 4, 3000),
    row("gemma4", "2026-11-06T12:00:00Z", 2, 2400),
    row("qwen3", WEEK.from, 1, 4000),
  ]);
  const points = responseTimes(week);
  expect(points).toHaveLength(2 * 168);

  const gemma = points.filter((each) => each.line === "gemma4");
  expect(gemma).toHaveLength(168);
  expect([gemma[0].t, gemma[167].t]).toEqual([Date.parse(WEEK.from), Date.parse(WEEK.to)]);
  expect(gemma.filter((each) => each.averageMs !== null).map((each) => [new Date(each.t).toISOString(), each.averageMs]))
    .toEqual([
      ["2026-11-06T12:00:00.000Z", 1200],
      ["2026-11-06T14:00:00.000Z", 750],
    ]);
  // An idle hour has no average, not one of 0.
  expect(gemma.filter((each) => each.averageMs === 0)).toEqual([]);
  expect(points.filter((each) => each.line === "qwen3" && each.averageMs !== null)).toEqual([
    point(Date.parse(WEEK.from), "qwen3", 4000),
  ]);

  // Five-minute steps over 24 hours, and days over 90.
  expect(responseTimes(view([row("gemma4", DAY.to, 3, 1000)], DAY))).toHaveLength(288);
  const days = responseTimes(view([row("gemma4", "2026-10-01T00:00:00Z", 3, 1000)], QUARTER));
  expect(days).toHaveLength(90);
  expect(days.filter((each) => each.averageMs !== null)).toEqual([
    point(Date.parse("2026-10-01T00:00:00Z"), "gemma4", 333),
  ]);
});

test("the folded models' line averages their requests together", () => {
  const at = "2026-11-06T14:00:00Z";
  const rows = Array.from({ length: 10 }, (_, i) => row(`m${i}`, at, (i + 1) * 10, (i + 1) * 10 * (i + 1)));
  const other = responseTimes(view(rows)).filter((each) => each.line === OTHER_LINE);
  expect(other).toHaveLength(168);
  // m0, m1 and m2: 10, 20 and 30 requests of 10, 40 and 90 ms in all.
  expect(other.find((each) => each.t === Date.parse(at))?.averageMs).toBe(Math.round((10 + 40 + 90) / 60));
});

test("a point with no neighbour on either side is alone, and the chart then dots every point", () => {
  const [a, b, c] = [0, 1, 2];
  expect(hasLonePoint([point(a, "x", null), point(b, "x", 5), point(c, "x", null)])).toBe(true);
  expect(hasLonePoint([point(a, "x", 5), point(b, "x", 6), point(c, "x", null)])).toBe(false);
  // The next line's first point is no neighbour.
  expect(hasLonePoint([point(a, "x", null), point(b, "x", 5), point(a, "y", 6), point(b, "y", 7)])).toBe(true);
  expect(hasLonePoint([point(a, "x", null), point(b, "x", null)])).toBe(false);
  expect(hasLonePoint([])).toBe(false);
});

test("the window's span is the start of its first step to the start of its current one", () => {
  expect(windowSpan(view([]))).toEqual([Date.parse(WEEK.from), Date.parse(WEEK.to)]);
  expect(windowSpan(view([], { ...WEEK, from: "not a time" }))).toBeUndefined();
  expect(responseTimes(view([row("gemma4", WEEK.to, 1, 100)], { ...WEEK, to: "not a time" }))).toEqual([]);
});
