/**
 * @jest-environment node
 */
/**
 * The monitor's lines over time (pages/monitor/MonitorCharts.tsx,
 * `linesOverTimeSpec`) name each time label's day as well as its hour once the
 * chart spans more than a day: the Open files chart over several days, and the
 * LLM performance chart over its 7 days. Within a day the labels stay Vega's
 * own. A chart of durations, the LLM performance one, labels its value axis
 * with two significant digits under a millisecond, in milliseconds under a
 * second and in seconds above, a step with no value among its rows. A chart's
 * marks, the deploys, are rules across its plot at their
 * times on the lines' time scale, each with its label for the tooltip.
 *
 * Each spec is compiled with the vega-lite the app bundles and run by vega
 * without a renderer, and its labels are read off the scene graph. It runs in
 * Node's environment: vega-lite's build reads `structuredClone`, which jsdom's
 * window does not have.
 */

// vega's and vega-lite's package entries are ES modules, which Jest does not
// load: their UMD builds are the same libraries as CommonJS.
jest.mock("vega", () => require(require("path").resolve(__dirname, "../../../node_modules/vega/build/vega.js")), {
  virtual: true,
});
jest.mock(
  "vega-lite",
  () => require(require("path").resolve(__dirname, "../../../node_modules/vega-lite/build/vega-lite.min.js")),
  { virtual: true }
);

import { DURATION_TEXT_FIELD, linesOverTimeSpec } from "../../pages/monitor/MonitorCharts";
import { formatMs } from "../../utils/diagnosticsBundle";

const vega = require("vega");
const lite = require("vega-lite");

const HOUR = 3_600_000;
/** A label that names its day and its hour: "Nov 5, 09:00". */
const DAY_AND_HOUR = /^[A-Z][a-z]{2} \d{1,2}, \d{2}:\d{2}$/;

/** A row an hour for *hours* hours from *start*, as the charts' rows are. */
function hourly(start: string, hours: number) {
  const first = Date.parse(start);
  return Array.from({ length: hours }, (_, hour) => ({ t: first + hour * HOUR, line: "Backend", files: 200 + hour }));
}

/** The labels Vega drew on the axis of *scale*, in the scene graph under *node*. */
function axisLabels(node: any, scale: string, onAxis = false, found: string[] = []): string[] {
  if (node?.marktype) {
    if (onAxis && node.role === "axis-label") found.push(...node.items.map((label: any) => label.text));
    for (const item of node.items ?? []) {
      const axis = node.role === "axis" && item.datum?.scale === scale && item.datum?.labels === true;
      axisLabels(item, scale, onAxis || axis, found);
    }
  } else {
    for (const mark of node?.items ?? []) axisLabels(mark, scale, onAxis, found);
  }
  return found;
}

/** The labels of the axis of *scale* in the chart of *spec*, as Vega draws it. */
async function drawnLabels(spec: Record<string, unknown>, scale: string): Promise<string[]> {
  const view = new vega.View(vega.parse(lite.compile({ ...spec, width: 600, height: 160 }).spec), {
    renderer: "none",
  });
  await view.runAsync();
  const labels = axisLabels(view.scenegraph().root, scale);
  view.finalize();
  return labels;
}

/**
 * Each point's value and the duration text its tooltip shows, in the drawn
 * chart of *spec*: read off the first of its datasets that holds the text.
 */
async function tooltipTexts(spec: Record<string, unknown>): Promise<unknown[][]> {
  const compiled = lite.compile({ ...spec, width: 600, height: 160 }).spec;
  const view = new vega.View(vega.parse(compiled), { renderer: "none" });
  await view.runAsync();
  const held = (compiled.data ?? [])
    .map((data: { name: string }) => view.data(data.name))
    .find((values: any[]) => values?.length > 0 && DURATION_TEXT_FIELD in values[0]);
  view.finalize();
  return (held ?? []).map((datum: any) => [datum.averageMs, datum[DURATION_TEXT_FIELD]]);
}

/** The time axis's labels of the chart of *rows*, over *timeDomain* when given. */
async function timeLabels(rows: Record<string, unknown>[], timeDomain?: [number, number]): Promise<string[]> {
  const spec = linesOverTimeSpec({
    rows, timeField: "t", valueField: "files", seriesField: "line", valueTitle: "files", timeDomain,
  });
  return drawnLabels(spec, "x");
}

test("over two days, each time label names its day as well as its hour", async () => {
  const labels = await timeLabels(hourly("2026-11-05T09:00:00Z", 49));
  expect(labels.length).toBeGreaterThan(2);
  expect(labels.filter((label) => !DAY_AND_HOUR.test(label))).toEqual([]);
});

test("the LLM performance chart's 7 days name each label's day, whatever hours their rows hold", async () => {
  const from = Date.parse("2026-10-30T16:00:00Z");
  const labels = await timeLabels(hourly("2026-11-06T12:00:00Z", 3), [from, from + 167 * HOUR]);
  expect(labels.length).toBeGreaterThan(2);
  expect(labels.filter((label) => !DAY_AND_HOUR.test(label))).toEqual([]);
});

test("a chart of durations labels its values in milliseconds under a second and in seconds above", async () => {
  // From 150 to 1,200 ms, an hour with no request among them.
  const rows: Record<string, unknown>[] = hourly("2026-11-05T09:00:00Z", 6).map((row, index) => ({
    t: row.t, line: "gemma4", averageMs: index === 3 ? null : 150 + 210 * index,
  }));
  const spec = linesOverTimeSpec({
    rows, timeField: "t", valueField: "averageMs", seriesField: "line", valueTitle: "average response time",
    durations: true,
  });
  const labels = await drawnLabels(spec, "y");
  expect(labels.length).toBeGreaterThan(2);
  expect(labels.filter((label) => !/^(\d+ ms|\d+\.\d s)$/.test(label))).toEqual([]);
  expect(labels.some((label) => /^[1-9]\d* ms$/.test(label))).toBe(true);
  expect(labels.some((label) => /^\d+\.\d s$/.test(label))).toBe(true);
});

test("a chart of durations under a millisecond labels its log axis with two significant digits", async () => {
  // Requests from a tenth of a millisecond to 10 ms: the axis's decades are 0.1, 1 and 10 ms.
  const values = [0.1, 0.45, 2, 10];
  const rows: Record<string, unknown>[] = hourly("2026-11-05T09:00:00Z", values.length).map((row, index) => ({
    t: row.t, line: "Requests", averageMs: values[index],
  }));
  const spec = linesOverTimeSpec({
    rows, timeField: "t", valueField: "averageMs", seriesField: "line", valueTitle: "average time",
    durations: true, logY: true,
  });
  expect([...(await drawnLabels(spec, "y"))].sort()).toEqual(["0.1 ms", "1 ms", "10 ms"]);
});

test("a chart of durations writes each point's tooltip as formatMs does, nothing for a step with no value", async () => {
  const values = [0, 0.05, 0.4321, 0.996, 4.6, 49.6, 850, 999, 999.4, 999.6, 1000, 1049, 1050, 1234, 12345, 600000, null];
  const first = Date.parse("2026-11-05T09:00:00Z");
  const rows: Record<string, unknown>[] = values.map((averageMs, index) => ({
    t: first + index * HOUR, line: "gemma4", averageMs,
  }));
  const spec = linesOverTimeSpec({
    rows, timeField: "t", valueField: "averageMs", seriesField: "line", valueTitle: "average response time",
    durations: true,
  });
  expect(await tooltipTexts(spec)).toEqual(values.map((value) => [value, value == null ? "" : formatMs(value)]));
});

/** The items of every mark of *marktype* with the role of a chart's own mark (not an axis's) under *node*. */
function markItems(node: any, marktype: string, found: any[] = []): any[] {
  if (node?.marktype) {
    if (node.marktype === marktype && node.role === "mark") found.push(...node.items);
    for (const item of node.items ?? []) markItems(item, marktype, found);
  } else {
    for (const mark of node?.items ?? []) markItems(mark, marktype, found);
  }
  return found;
}

test("a chart's marks are rules across its plot at their times, each with its label for the tooltip", async () => {
  const from = Date.parse("2026-10-30T16:00:00Z");
  const marks = [
    { t: from + 30 * HOUR, label: "0.17.399" },
    { t: from + 100 * HOUR, label: "0.17.400" },
  ];
  const spec = linesOverTimeSpec({
    rows: hourly("2026-11-01T00:00:00Z", 5), timeField: "t", valueField: "files", seriesField: "line",
    valueTitle: "files", timeDomain: [from, from + 168 * HOUR], marks, markTitle: "version",
  });
  const view = new vega.View(vega.parse(lite.compile({ ...spec, width: 600, height: 160 }).spec), {
    renderer: "none",
  });
  await view.runAsync();
  const rules = markItems(view.scenegraph().root, "rule");
  const x = view.scale("x");
  const at = marks.map((mark) => x(mark.t));
  view.finalize();

  expect(rules.map((item) => item.tooltip?.version)).toEqual(["0.17.399", "0.17.400"]);
  // On the lines' own time scale, at each mark's time, inside the plot.
  rules.forEach((item, index) => {
    expect(item.x).toBeCloseTo(at[index], 6);
    expect(item.x).toBeGreaterThan(0);
    expect(item.x).toBeLessThan(600);
  });
  // From the plot's top to its bottom.
  expect(rules.map((item) => [item.y, item.y2])).toEqual([[0, 160], [0, 160]]);
  // Still a week's labels, each naming its day.
  const labels = await drawnLabels(spec, "x");
  expect(labels.length).toBeGreaterThan(2);
  expect(labels.filter((label) => !DAY_AND_HOUR.test(label))).toEqual([]);
});

test("within a day, the time labels stay Vega's own, the hour alone", async () => {
  const labels = await timeLabels(hourly("2026-11-05T09:00:00Z", 20));
  expect(labels.length).toBeGreaterThan(2);
  expect(labels.filter((label) => DAY_AND_HOUR.test(label))).toEqual([]);
  // Such as "09 AM", in whatever time zone the test runs.
  expect(labels.some((label) => /^\d{2} [AP]M$/.test(label))).toBe(true);
});
