/**
 * The LLM tokens section's lines: one per model and endpoint, with its label
 * and its colour, and each line's tokens in every hour of the charts' window.
 *
 * Pure, so the charts and the table read the same lines and colours, and a
 * test reads them without Vega.
 *
 * COLOUR. The monitor's categorical palette (`chartColors.ts`). Lines take its
 * colours in the order of their labels, so a model keeps its colour while the
 * others' tokens change. Past its eight, the models with the most tokens keep
 * a line of their own and the rest share one, `OTHER_LINE`. The table beside
 * the charts names every model and its numbers.
 */
import type { MonitorLlmCounts, MonitorLlmModel, MonitorLlmPayload } from "../../api/monitorApi";
import { CATEGORICAL } from "./chartColors";

const LINE_COLORS = CATEGORICAL;

/** The line the models past the palette share. */
export const OTHER_LINE = "Other models";

const HOUR_MS = 3_600_000;

export type TokenMeasure = "inputTokens" | "outputTokens";

export interface TokenLine {
  label: string;
  color: string;
}

/** One hour of one line, as the charts draw it: a row of `LinesOverTime`. */
export type TokenPoint = {
  t: number;
  line: string;
  tokens: number;
};

/** A model and its endpoint, as one key. */
export function modelKey(model: string, curio: boolean): string {
  return `${curio ? "curio" : "own"}:${model}`;
}

export function lineLabel(model: string, curio: boolean): string {
  return `${model} (${curio ? "Curio" : "own key"})`;
}

export function endpointLabel(curio: boolean): string {
  return curio ? "Curio's endpoint" : "Own key";
}

function byText(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

/**
 * Each model's line in the charts, by its `modelKey`: every model with a
 * request in the charts' hours. A model folded into `OTHER_LINE` maps to it.
 */
export function tokenLines(payload: MonitorLlmPayload): Map<string, TokenLine> {
  const seen = new Map<string, { label: string; tokens: number }>();
  for (const row of payload.hourly) {
    const key = modelKey(row.model, row.curio);
    const entry = seen.get(key) ?? { label: lineLabel(row.model, row.curio), tokens: 0 };
    entry.tokens += row.inputTokens + row.outputTokens;
    seen.set(key, entry);
  }
  let own = [...seen.entries()];
  const folded = own.length > LINE_COLORS.length;
  if (folded) {
    own = own.sort((a, b) => b[1].tokens - a[1].tokens).slice(0, LINE_COLORS.length - 1);
  }
  own.sort((a, b) => byText(a[1].label, b[1].label));
  const lines = new Map<string, TokenLine>();
  own.forEach(([key, entry], index) => lines.set(key, { label: entry.label, color: LINE_COLORS[index] }));
  if (folded) {
    const other = { label: OTHER_LINE, color: LINE_COLORS[LINE_COLORS.length - 1] };
    for (const key of seen.keys()) {
      if (!lines.has(key)) lines.set(key, other);
    }
  }
  return lines;
}

/** The charts' colour scale: each line's label and colour, in the palette's order. */
export function lineColors(lines: Map<string, TokenLine>): { domain: string[]; range: string[] } {
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
 * One point per line and per hour, from `hourlyFrom` to `hourlyTo`: an hour
 * with no request is 0, so a line never bridges idle hours.
 */
export function tokensPerHour(
  payload: MonitorLlmPayload,
  measure: TokenMeasure,
  lines: Map<string, TokenLine> = tokenLines(payload)
): TokenPoint[] {
  const from = Date.parse(payload.hourlyFrom);
  const to = Date.parse(payload.hourlyTo);
  if (Number.isNaN(from) || Number.isNaN(to)) return [];
  const tokens = new Map<string, number>();
  for (const row of payload.hourly) {
    const line = lines.get(modelKey(row.model, row.curio));
    const t = Date.parse(row.hour);
    if (!line || Number.isNaN(t)) continue;
    const cell = `${line.label}\n${t}`;
    tokens.set(cell, (tokens.get(cell) ?? 0) + row[measure]);
  }
  const points: TokenPoint[] = [];
  for (const label of lineColors(lines).domain) {
    for (let t = from; t <= to; t += HOUR_MS) {
      points.push({ t, line: label, tokens: tokens.get(`${label}\n${t}`) ?? 0 });
    }
  }
  return points;
}

/** The models' counts in one window, added up. */
export function sumOf(
  models: MonitorLlmModel[],
  window: "last24h" | "last7d" | "kept"
): MonitorLlmCounts {
  const sum: MonitorLlmCounts = { inputTokens: 0, outputTokens: 0, requests: 0 };
  for (const entry of models) {
    sum.inputTokens += entry[window].inputTokens;
    sum.outputTokens += entry[window].outputTokens;
    sum.requests += entry[window].requests;
  }
  return sum;
}
