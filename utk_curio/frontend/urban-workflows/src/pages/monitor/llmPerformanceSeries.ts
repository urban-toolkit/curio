/**
 * The LLM performance section's chart: one line per model with its colour,
 * and each line's average response time at every step of the window the
 * Usage tab's switch shows (`usageSeries.ts`).
 *
 * Pure, so the chart and the table read the same lines and colours, and a
 * test reads them without Vega.
 *
 * COLOUR. The monitor's categorical palette (`chartColors.ts`). Lines take its
 * colours in the order of their models' names, so a model keeps its colour
 * while the others' requests change. Past its eight, the models with the most
 * requests in the window keep a line of their own and the rest share one,
 * `OTHER_LINE`, whose average is their requests' together. The table beside
 * the chart names every model and its numbers.
 *
 * IDLE STEPS. A step in which a line had no request has no average: its point
 * is null, which breaks the line there, so a line never bridges idle time. A
 * point with no neighbour on either side shows only as a dot (`hasLonePoint`).
 */
import type { MonitorLlmView } from "../../api/monitorApi";
import { CATEGORICAL } from "./chartColors";
import { windowSpan } from "./usageSeries";

const LINE_COLORS = CATEGORICAL;

/** The line the models past the palette share. */
export const OTHER_LINE = "Other models";

export interface ModelLine {
  label: string;
  color: string;
}

/** One step of one line, as the chart draws it: a row of `LinesOverTime`. */
export type ResponsePoint = {
  t: number;
  line: string;
  /** The average response time of the step's requests, in milliseconds; null with none. */
  averageMs: number | null;
};

function byText(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

/**
 * Each model's line in the chart, by its name: every model with a request in
 * the window. A model folded into `OTHER_LINE` maps to it.
 */
export function modelLines(view: MonitorLlmView): Map<string, ModelLine> {
  const requests = new Map<string, number>();
  for (const row of view.rows) {
    requests.set(row.model, (requests.get(row.model) ?? 0) + row.requests);
  }
  let own = [...requests.entries()];
  const folded = own.length > LINE_COLORS.length;
  if (folded) {
    own = own.sort((a, b) => b[1] - a[1] || byText(a[0], b[0])).slice(0, LINE_COLORS.length - 1);
  }
  own.sort((a, b) => byText(a[0], b[0]));
  const lines = new Map<string, ModelLine>();
  own.forEach(([model], index) => lines.set(model, { label: model, color: LINE_COLORS[index] }));
  if (folded) {
    const other = { label: OTHER_LINE, color: LINE_COLORS[LINE_COLORS.length - 1] };
    for (const model of requests.keys()) {
      if (!lines.has(model)) lines.set(model, other);
    }
  }
  return lines;
}

/** The chart's colour scale: each line's label and colour, in the palette's order. */
export function lineColors(lines: Map<string, ModelLine>): { domain: string[]; range: string[] } {
  const colors = new Map<string, string>();
  for (const line of lines.values()) {
    if (!colors.has(line.label)) colors.set(line.label, line.color);
  }
  const ordered = [...colors.entries()].sort(
    (a, b) => LINE_COLORS.indexOf(a[1]) - LINE_COLORS.indexOf(b[1])
  );
  return { domain: ordered.map(([label]) => label), range: ordered.map(([, color]) => color) };
}

/**
 * One point per line and per step, from the window's `from` to its `to`,
 * one every `stepSeconds`: the average time of the line's requests in that
 * step, in whole milliseconds, or null where it had none.
 */
export function responseTimes(
  view: MonitorLlmView,
  lines: Map<string, ModelLine> = modelLines(view)
): ResponsePoint[] {
  const span = windowSpan(view);
  const step = view.stepSeconds * 1000;
  if (!span || !(step > 0)) return [];
  const sums = new Map<string, { requests: number; ms: number }>();
  for (const row of view.rows) {
    const line = lines.get(row.model);
    const t = Date.parse(row.at);
    if (!line || Number.isNaN(t)) continue;
    const cell = `${line.label}\n${t}`;
    const sum = sums.get(cell) ?? { requests: 0, ms: 0 };
    sum.requests += row.requests;
    sum.ms += row.ms;
    sums.set(cell, sum);
  }
  const points: ResponsePoint[] = [];
  for (const label of lineColors(lines).domain) {
    for (let t = span[0]; t <= span[1]; t += step) {
      const sum = sums.get(`${label}\n${t}`);
      points.push({ t, line: label, averageMs: sum && sum.requests > 0 ? Math.round(sum.ms / sum.requests) : null });
    }
  }
  return points;
}

/**
 * Whether a line has a point with no neighbour on either side, which a line
 * alone does not draw: the chart then dots every point. The points are a
 * line's steps in order, line after line, as `responseTimes` gives them.
 */
export function hasLonePoint(points: ResponsePoint[]): boolean {
  return points.some((point, index) => {
    if (point.averageMs == null) return false;
    const before = points[index - 1];
    const after = points[index + 1];
    const joined = (other: ResponsePoint | undefined) => other?.line === point.line && other.averageMs != null;
    return !joined(before) && !joined(after);
  });
}
