/**
 * The monitor's lines over time (pages/monitor/MonitorCharts.tsx,
 * `linesOverTimeSpec`): time on x, a value on y, a line per value of a series
 * field, and its options: a log y axis, series drawn dashed, as a limit is,
 * and a dot on each point. Its tooltip is the Curio one
 * (tooltip/vegaTooltip.test.tsx).
 */
jest.mock("vega", () => ({}), { virtual: true });
jest.mock("vega-lite", () => ({}), { virtual: true });

import { CATEGORICAL } from "../../pages/monitor/chartColors";
import { linesOverTimeSpec } from "../../pages/monitor/MonitorCharts";

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
  expect(spec.encoding.strokeDash).toMatchObject({
    field: "server",
    legend: null,
    scale: { domain: ["backend", "limit"], range: [[1, 0], [6, 4]] },
  });
});

test("a dot on each point when asked, so a line of one point shows", () => {
  const spec: any = linesOverTimeSpec({ ...BASE, points: true });
  expect(spec.mark).toEqual({
    type: "line", strokeWidth: 2, strokeCap: "round", strokeJoin: "round", point: { filled: true, size: 64 },
  });
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
