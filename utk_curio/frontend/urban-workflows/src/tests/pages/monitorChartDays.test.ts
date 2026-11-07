/**
 * @jest-environment node
 */
/**
 * The monitor's lines over time (pages/monitor/MonitorCharts.tsx,
 * `linesOverTimeSpec`) name each time label's day as well as its hour once the
 * chart spans more than a day: the Open files chart over several days, and the
 * LLM tokens' charts over their 7 days. Within a day the labels stay Vega's own.
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

import { linesOverTimeSpec } from "../../pages/monitor/MonitorCharts";

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

/** The time axis's labels of the chart of *rows*, over *timeDomain* when given. */
async function timeLabels(rows: Record<string, unknown>[], timeDomain?: [number, number]): Promise<string[]> {
  const spec = linesOverTimeSpec({
    rows, timeField: "t", valueField: "files", seriesField: "line", valueTitle: "files", timeDomain,
  });
  const view = new vega.View(vega.parse(lite.compile({ ...spec, width: 600, height: 160 }).spec), {
    renderer: "none",
  });
  await view.runAsync();
  const labels = axisLabels(view.scenegraph().root, "x");
  view.finalize();
  return labels;
}

test("over two days, each time label names its day as well as its hour", async () => {
  const labels = await timeLabels(hourly("2026-11-05T09:00:00Z", 49));
  expect(labels.length).toBeGreaterThan(2);
  expect(labels.filter((label) => !DAY_AND_HOUR.test(label))).toEqual([]);
});

test("the LLM tokens' 7 days name each label's day, whatever hours their rows hold", async () => {
  const from = Date.parse("2026-10-30T16:00:00Z");
  const labels = await timeLabels(hourly("2026-11-06T12:00:00Z", 3), [from, from + 167 * HOUR]);
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
