/**
 * The LLM tokens section's lines (pages/monitor/llmSeries.ts): one per model
 * and endpoint, coloured in the palette's order by label, folded into one past
 * the palette's eight, and an hour with no request drawn as 0, so a line never
 * bridges idle hours.
 */
import type { MonitorLlmHour, MonitorLlmModel, MonitorLlmPayload } from "../../api/monitorApi";
import { CATEGORICAL } from "../../pages/monitor/chartColors";
import {
  OTHER_LINE,
  endpointLabel,
  lineColors,
  modelKey,
  sumOf,
  tokenLines,
  tokensPerHour,
} from "../../pages/monitor/llmSeries";

const FROM = "2026-10-30T16:00:00Z";
const TO = "2026-11-06T15:00:00Z";

function hour(model: string, curio: boolean, at: string, inputTokens: number, outputTokens = 0): MonitorLlmHour {
  return { hour: at, model, curio, inputTokens, outputTokens, requests: 1 };
}

function payload(hourly: MonitorLlmHour[]): MonitorLlmPayload {
  return {
    computedAt: "2026-11-06T15:20:07Z",
    startedAt: "2026-11-01T00:00:00Z",
    maxDays: 90,
    ageSeconds: 0,
    ttlSeconds: 60,
    hourlyFrom: FROM,
    hourlyTo: TO,
    hourly,
    models: [],
  };
}

test("each model and endpoint is a line, coloured in the palette's order by its label", () => {
  const lines = tokenLines(
    payload([
      hour("gpt-5", false, "2026-11-06T14:00:00Z", 5),
      hour("gemma4", true, "2026-11-06T14:00:00Z", 900),
      hour("gemma4", false, "2026-11-06T13:00:00Z", 7),
    ])
  );
  expect([...lines.entries()]).toEqual([
    [modelKey("gemma4", true), { label: "gemma4 (Curio)", color: CATEGORICAL[0] }],
    [modelKey("gemma4", false), { label: "gemma4 (own key)", color: CATEGORICAL[1] }],
    [modelKey("gpt-5", false), { label: "gpt-5 (own key)", color: CATEGORICAL[2] }],
  ]);
  expect([endpointLabel(true), endpointLabel(false)]).toEqual(["Curio's endpoint", "Own key"]);
});

test("a line keeps its colour while the models' tokens change", () => {
  const at = "2026-11-06T14:00:00Z";
  const before = tokenLines(payload([hour("a", true, at, 1), hour("b", true, at, 100)]));
  const after = tokenLines(payload([hour("a", true, at, 1000), hour("b", true, at, 1)]));
  expect(after.get(modelKey("a", true))).toEqual(before.get(modelKey("a", true)));
  expect(after.get(modelKey("b", true))).toEqual(before.get(modelKey("b", true)));
});

test("past eight models, the seven with the most tokens keep a line and the rest share one", () => {
  const at = "2026-11-06T14:00:00Z";
  // m9 has the most tokens and m0 the fewest.
  const lines = tokenLines(payload(Array.from({ length: 10 }, (_, i) => hour(`m${i}`, false, at, (i + 1) * 10))));
  const own = ["m3", "m4", "m5", "m6", "m7", "m8", "m9"];
  own.forEach((name, index) => {
    expect(lines.get(modelKey(name, false))).toEqual({ label: `${name} (own key)`, color: CATEGORICAL[index] });
  });
  for (const name of ["m0", "m1", "m2"]) {
    expect(lines.get(modelKey(name, false))).toEqual({ label: OTHER_LINE, color: CATEGORICAL[7] });
  }
  expect(lineColors(lines)).toEqual({
    domain: [...own.map((name) => `${name} (own key)`), OTHER_LINE],
    range: CATEGORICAL,
  });
});

test("every line has a point for every hour of the 7 days, 0 where no request was", () => {
  const tokens = payload([
    hour("gemma4", true, "2026-11-06T14:00:00Z", 900, 40),
    hour("gemma4", true, "2026-11-06T12:00:00Z", 100, 4),
    hour("gpt-5", false, FROM, 5, 1),
  ]);
  const input = tokensPerHour(tokens, "inputTokens");
  expect(input).toHaveLength(2 * 168);

  const gemma = input.filter((point) => point.line === "gemma4 (Curio)");
  expect(gemma).toHaveLength(168);
  expect([gemma[0].t, gemma[167].t]).toEqual([Date.parse(FROM), Date.parse(TO)]);
  expect(gemma.filter((point) => point.tokens > 0).map((point) => [new Date(point.t).toISOString(), point.tokens]))
    .toEqual([
      ["2026-11-06T12:00:00.000Z", 100],
      ["2026-11-06T14:00:00.000Z", 900],
    ]);
  expect(
    tokensPerHour(tokens, "outputTokens").filter((point) => point.line === "gpt-5 (own key)" && point.tokens > 0)
  ).toEqual([{ t: Date.parse(FROM), line: "gpt-5 (own key)", tokens: 1 }]);
});

test("the folded models' tokens are one line's", () => {
  const at = "2026-11-06T14:00:00Z";
  const tokens = payload(Array.from({ length: 10 }, (_, i) => hour(`m${i}`, false, at, (i + 1) * 10)));
  const other = tokensPerHour(tokens, "inputTokens").filter((point) => point.line === OTHER_LINE);
  expect(other).toHaveLength(168);
  expect(other.find((point) => point.t === Date.parse(at))?.tokens).toBe(10 + 20 + 30);
});

test("sumOf adds a window's counts up", () => {
  const counts = (n: number) => ({ inputTokens: n, outputTokens: 2 * n, requests: 3 * n });
  const models: MonitorLlmModel[] = [
    { model: "a", curio: true, last24h: counts(1), last7d: counts(10), kept: counts(100) },
    { model: "b", curio: false, last24h: counts(2), last7d: counts(20), kept: counts(200) },
  ];
  expect(sumOf(models, "last24h")).toEqual(counts(3));
  expect(sumOf(models, "kept")).toEqual(counts(300));
  expect(sumOf([], "last7d")).toEqual(counts(0));
});
