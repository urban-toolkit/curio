/**
 * The monitor's lines over time (pages/monitor/MonitorCharts.tsx,
 * `linesOverTimeSpec`): time on x, a value on y, a line per value of a series
 * field, and its options: a log y axis, series drawn dashed, as a limit is,
 * a dot on each point, values that are durations, whose axis and tooltip
 * Vega writes as `formatMs` does, and marks, the deploys, each a thin dashed
 * rule across the plot (monitorChartDays.test.ts draws them). Its tooltip is
 * the Curio one (tooltip/vegaTooltip.test.tsx).
 */
jest.mock("vega", () => ({}), { virtual: true });
jest.mock("vega-lite", () => ({}), { virtual: true });

import { CATEGORICAL } from "../../pages/monitor/chartColors";
import {
  DURATION_TEXT_FIELD,
  durationText,
  linesOverTimeSpec,
  powersOfTen,
} from "../../pages/monitor/MonitorCharts";

const ROWS = [
  { t: 1000, server: "backend", value: 3 },
  { t: 2000, server: "backend", value: 4 },
  { t: 1000, server: "limit", value: 1024 },
];
const BASE = { rows: ROWS, timeField: "t", valueField: "value", seriesField: "server", valueTitle: "open files" };

test("time on x, the value on y and a line per series, in the palette's colours", () => {
  const spec: any = linesOverTimeSpec(BASE);
  expect(spec.data.values).toBe(ROWS);
  expect(spec.mark).toEqual({ type: "line", strokeWidth: 2, strokeCap: "round", strokeJoin: "round" });
  expect(spec.encoding.x).toMatchObject({ field: "t", type: "temporal" });
  expect(spec.encoding.x.scale).toBeUndefined();
  expect(spec.encoding.y).toMatchObject({ field: "value", type: "quantitative", title: "open files" });
  expect(spec.encoding.y.scale).toBeUndefined();
  expect(spec.encoding.color).toMatchObject({
    field: "server",
    scale: { domain: ["backend", "limit"], range: CATEGORICAL.slice(0, 2) },
  });
  expect(spec.encoding.strokeDash).toBeUndefined();
  expect(spec.encoding.tooltip.map((entry: any) => [entry.field, entry.title])).toEqual([
    ["server", "series"],
    ["t", "time"],
    ["value", "open files"],
  ]);
});

test("a log y axis, and the series it names drawn dashed", () => {
  const spec: any = linesOverTimeSpec({ ...BASE, logY: true, dashed: ["limit"] });
  expect(spec.encoding.y.scale).toEqual({ type: "log" });
  // Ticked at each power of ten the values span, from 3 to 1024, and as many
  // ticks, as Vega thins the values down to the count.
  expect(spec.encoding.y.axis.values).toEqual([1, 10, 100, 1000, 10000]);
  expect(spec.encoding.y.axis.tickCount).toBe(5);
  const linear: any = linesOverTimeSpec(BASE);
  expect(linear.encoding.y.axis.values).toBeUndefined();
  // With no legend of its own, which Vega-Lite merges into the colour's.
  expect(spec.encoding.strokeDash).toEqual({
    field: "server",
    type: "nominal",
    scale: { domain: ["backend", "limit"], range: [[1, 0], [6, 4]] },
  });
});

test("a log axis's ticks are the powers of ten around its positive values", () => {
  expect(powersOfTen([212, 96, 65536])).toEqual([10, 100, 1000, 10000, 100000]);
  expect(powersOfTen([1000, 1024])).toEqual([1000, 10000]);
  expect(powersOfTen([100])).toEqual([100]);
  expect(powersOfTen([0, -3])).toEqual([]);
  expect(powersOfTen([])).toEqual([]);
});

test("a dot on each point when asked, so a line of one point shows", () => {
  const spec: any = linesOverTimeSpec({ ...BASE, points: true });
  expect(spec.mark).toEqual({
    type: "line", strokeWidth: 2, strokeCap: "round", strokeJoin: "round", point: { filled: true, size: 64 },
  });
});

test("durations read as milliseconds under a second and as seconds above, on the axis and in the tooltip", () => {
  const spec: any = linesOverTimeSpec({ ...BASE, valueTitle: "average response time", durations: true });
  expect(spec.encoding.y.axis.labelExpr).toBe(durationText("datum.value"));
  expect(spec.encoding.y.axis.format).toBeUndefined();
  // The tooltip shows each point's duration as the axis writes it, and
  // nothing for a step with no value.
  expect(spec.transform).toEqual([
    { calculate: `isValid(datum["value"]) ? ${durationText('datum["value"]')} : ''`, as: DURATION_TEXT_FIELD },
  ]);
  expect(spec.encoding.tooltip[2]).toEqual({ field: DURATION_TEXT_FIELD, type: "nominal", title: "average response time" });
  expect(spec.data.values).toBe(ROWS);

  const counts: any = linesOverTimeSpec(BASE);
  expect(counts.transform).toBeUndefined();
  expect(counts.encoding.y.axis.labelExpr).toBeUndefined();
  expect(counts.encoding.y.axis.format).toBe("~s");
  expect(counts.encoding.tooltip[2]).toEqual({ field: "value", type: "quantitative", title: "open files", format: "," });
});

test("marks within the time axis are a layer of thin dashed rules over the lines, each with its tooltip", () => {
  const marks = [
    { t: 500, label: "0.17.399" },
    { t: 1500, label: "0.17.400" },
    { t: 9000, label: "0.17.401" },
  ];
  const spec: any = linesOverTimeSpec({
    ...BASE, timeDomain: [1000, 5000], timeFormat: "%H:00", marks, markTitle: "version", durations: true,
  });
  expect(spec.mark).toBeUndefined();
  expect(spec.data).toBeUndefined();
  expect(spec.layer).toHaveLength(2);
  const [lines, rules] = spec.layer;
  // The lines as a chart without marks draws them.
  const alone: any = linesOverTimeSpec({ ...BASE, timeDomain: [1000, 5000], timeFormat: "%H:00", durations: true });
  expect(lines).toEqual({ data: alone.data, transform: alone.transform, mark: alone.mark, encoding: alone.encoding });
  expect(lines.data.values).toBe(ROWS);
  expect(spec.config).toEqual(alone.config);

  // Only the mark within the axis's span, on the lines' time axis.
  expect(rules.data.values).toEqual([{ t: 1500, label: "0.17.400" }]);
  expect(rules.mark).toEqual({ type: "rule", color: "#6B6B76", strokeWidth: 1, strokeDash: [4, 4] });
  expect(rules.encoding.x).toEqual({ ...lines.encoding.x, field: "t" });
  // No colour, so no legend of its own.
  expect(Object.keys(rules.encoding)).toEqual(["x", "tooltip"]);
  expect(rules.encoding.tooltip).toEqual([
    { field: "label", type: "nominal", title: "version" },
    { field: "t", type: "temporal", title: "time", format: "%H:00" },
  ]);
});

test("with no mark within the time axis, the chart is the lines alone", () => {
  const plain: any = linesOverTimeSpec(BASE);
  // The rows span 1000 to 2000.
  expect(linesOverTimeSpec({ ...BASE, marks: [{ t: 99999, label: "0.17.401" }] })).toEqual(plain);
  expect(linesOverTimeSpec({ ...BASE, marks: [] })).toEqual(plain);
  expect(plain.layer).toBeUndefined();
  // Within the rows' span, with no domain given, a mark is drawn.
  const marked: any = linesOverTimeSpec({ ...BASE, marks: [{ t: 2000, label: "0.17.401" }] });
  expect(marked.layer[1].data.values).toEqual([{ t: 2000, label: "0.17.401" }]);
});

test("the colours, the span and the tooltip's words it is given", () => {
  const colors = { domain: ["limit", "backend"], range: ["#6250d6", "#2a78d6"] };
  const spec: any = linesOverTimeSpec({
    ...BASE, colors, timeDomain: [0, 5000], seriesTitle: "server", timeFormat: "%H:00",
  });
  expect(spec.encoding.color.scale).toEqual(colors);
  expect(spec.encoding.x.scale).toEqual({ domain: [0, 5000] });
  expect(spec.encoding.tooltip.slice(0, 2)).toEqual([
    { field: "server", type: "nominal", title: "server" },
    { field: "t", type: "temporal", title: "time", format: "%H:00" },
  ]);
});
